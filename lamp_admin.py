"""Lamp admin helpers — system, storage, Ollama (stdlib only)."""

import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import workshop_db as wdb
import ticker
import lamp_voice
from workshop import apps_dir, load_config, save_config, probe_endpoint, VERSION as WS_VERSION

LAMP_VERSION = "0.4.2"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def list_templates() -> list:
    out = []
    if not TEMPLATES_DIR.is_dir():
        return out
    for fp in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            out.append({
                "id": data.get("id", fp.stem),
                "icon": data.get("icon", "apps"),
                "title": data.get("title", fp.stem),
                "subtitle": data.get("subtitle", ""),
                "description": data.get("description", ""),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return out


def load_template(tid: str) -> dict | None:
    fp = TEMPLATES_DIR / f"{tid}.json"
    if not fp.is_file():
        for p in TEMPLATES_DIR.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("id") == tid:
                    return d
            except (json.JSONDecodeError, OSError):
                pass
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def list_app_storage(cfg) -> list:
    """Per-app folder sizes for admin storage view."""
    base = apps_dir(cfg)
    out = []
    if not base.exists():
        return out
    shared = base / "shared"
    if shared.is_dir():
        for d in sorted(shared.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                out.append({
                    "name": d.name,
                    "owner": "shared",
                    "scope": "shared",
                    "bytes": dir_size(d),
                })
    users_root = base / "users"
    if users_root.is_dir():
        for user_dir in sorted(users_root.iterdir()):
            if not user_dir.is_dir():
                continue
            for d in sorted(user_dir.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    out.append({
                        "name": d.name,
                        "owner": user_dir.name,
                        "scope": "personal",
                        "bytes": dir_size(d),
                    })
    out.sort(key=lambda x: x["bytes"], reverse=True)
    return out


def storage_breakdown(cfg) -> dict:
    base = apps_dir(cfg)
    apps_bytes = dir_size(base)
    db_bytes = wdb.DB_PATH.stat().st_size if wdb.DB_PATH.exists() else 0
    backup_bytes = 0
    if base.exists():
        for td in base.rglob(".tortoise/backups"):
            if td.is_dir():
                backup_bytes += dir_size(td)
    du = shutil.disk_usage(Path.home())
    models_bytes = 0
    endpoint = cfg.get("endpoint")
    if endpoint:
        try:
            req = urllib.request.Request(endpoint.rstrip("/") + "/models")
            if cfg.get("api_key"):
                req.add_header("Authorization", f"Bearer {cfg['api_key']}")
            with urllib.request.urlopen(req, timeout=3) as r:
                for m in json.loads(r.read()).get("data", []):
                    # Ollama may include size in bytes
                    models_bytes += m.get("size", 0) or 0
        except Exception:
            pass
    return {
        "disk": {"total": du.total, "used": du.used, "free": du.free},
        "breakdown": {
            "apps": apps_bytes,
            "database": db_bytes,
            "backups": backup_bytes,
            "models": models_bytes,
            "system": max(0, du.used - apps_bytes - db_bytes - backup_bytes),
        },
        "apps_list": list_app_storage(cfg),
    }


def cleanup_backups(days: int, cfg) -> int:
    import time as _time

    base = apps_dir(cfg)
    cutoff = _time.time() - days * 86400
    freed = 0
    if not base.exists():
        return 0
    for f in base.rglob(".tortoise/backups/*"):
        if f.is_file():
            try:
                if f.stat().st_mtime < cutoff:
                    freed += f.stat().st_size
                    f.unlink()
            except OSError:
                pass
    return freed


def wipe_app_data(app_slug: str) -> dict:
    """Clear Workshop DB rows for an app slug (folder name)."""
    conn = wdb.get_conn()
    keys = conn.execute("DELETE FROM app_data WHERE app=?", (app_slug,)).rowcount
    sched = conn.execute("DELETE FROM schedules WHERE app=?", (app_slug,)).rowcount
    conn.commit()
    return {"keys_deleted": keys, "schedules_deleted": sched}


def vacuum_db() -> tuple:
    before = wdb.DB_PATH.stat().st_size if wdb.DB_PATH.exists() else 0
    wdb.get_conn().execute("VACUUM")
    wdb.get_conn().commit()
    after = wdb.DB_PATH.stat().st_size if wdb.DB_PATH.exists() else 0
    return before, after


def system_status(cfg, tortoise_ver: str) -> dict:
    ollama_ok = False
    ep = cfg.get("endpoint")
    if ep:
        ollama_ok = probe_endpoint(ep, cfg.get("api_key")) is not None
    ts = ticker.ticker_status()
    ram = {}
    try:
        if os.path.exists("/proc/meminfo"):
            lines = Path("/proc/meminfo").read_text().splitlines()
            mem = {}
            for ln in lines:
                k, _, v = ln.partition(":")
                mem[k.strip()] = int(v.strip().split()[0])
            ram = {
                "total_mb": mem.get("MemTotal", 0) // 1024,
                "available_mb": mem.get("MemAvailable", 0) // 1024,
            }
    except (ValueError, OSError):
        pass
    temp = None
    try:
        for p in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            t = int(p.read_text().strip()) / 1000
            if temp is None or t > temp:
                temp = round(t, 1)
    except (ValueError, OSError):
        pass
    hostname = os.uname().nodename
    ip = "127.0.0.1"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    uptime_s = 0
    try:
        uptime_s = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (ValueError, OSError):
        pass
    return {
        "ollama": {"ok": ollama_ok, "endpoint": ep, "model": cfg.get("model")},
        "ticker": ts,
        "uptime_seconds": uptime_s,
        "ram": ram,
        "temp_c": temp,
        "versions": {
            "lamp": LAMP_VERSION,
            "workshop": WS_VERSION,
            "tortoise": tortoise_ver,
        },
        "network": {"hostname": hostname, "ip": ip},
        "voice": lamp_voice.voice_status(cfg),
    }


def model_recommendations() -> list:
    import lamp_models
    return lamp_models._recommendations()


def ollama_pull_stream(model: str, write_line):
    """Stream ollama pull output as SSE-friendly lines."""
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            write_line({"t": "log", "text": line.rstrip()})
        proc.wait()
        write_line({"t": "done", "ok": proc.returncode == 0})
    except FileNotFoundError:
        write_line({"t": "error", "msg": "ollama not found on PATH"})
    except Exception as e:
        write_line({"t": "error", "msg": str(e)})


def ollama_rm(model: str) -> bool:
    try:
        subprocess.run(["ollama", "rm", model], check=True, capture_output=True, timeout=120)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False
