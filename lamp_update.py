"""Lamp self-update — git pull or zip overlay; ~/.workshop data is never touched."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

LAMP_ROOT = Path(__file__).resolve().parent
WORKSHOP_DIR = Path.home() / ".workshop"

DEFAULT_GITHUB = os.environ.get("LAMP_GITHUB", "thebreadcat/lamp-ai")
DEFAULT_BRANCH = os.environ.get("LAMP_BRANCH", "main")
WORKSHOP_GITHUB = os.environ.get("WORKSHOP_GITHUB", "thebreadcat/workshop")
TORTOISE_GITHUB = os.environ.get("TORTOISE_GITHUB", "thebreadcat/tortoise")
REMOTE_VERSION_URL = os.environ.get(
    "LAMP_VERSION_URL",
    f"https://raw.githubusercontent.com/{DEFAULT_GITHUB}/{DEFAULT_BRANCH}/VERSION",
)
UPDATE_CHECK_TTL = int(os.environ.get("LAMP_UPDATE_CHECK_TTL", str(6 * 3600)))

_cache: dict = {"at": 0.0, "data": None}


def read_local_version(root: Path | None = None) -> str:
    vf = (root or LAMP_ROOT) / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()
    return "0.0.0"


def parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for piece in re.split(r"[.\-+]", (v or "").strip()):
        m = re.match(r"(\d+)", piece)
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def version_gt(a: str, b: str) -> bool:
    return parse_version(a) > parse_version(b)


def _fetch_text(url: str, timeout: float = 12.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Lamp-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def fetch_remote_version() -> str | None:
    return _fetch_text(REMOTE_VERSION_URL)


def update_command(root: Path | None = None) -> str:
    install = (root or LAMP_ROOT).resolve()
    if sys.platform == "win32":
        return f'cd /d "{install}" && python lamp.py --update'
    return f'cd "{install}" && python3 lamp.py --update'


def get_update_status(*, force: bool = False, root: Path | None = None) -> dict:
    now = time.time()
    if (
        not force
        and _cache["data"] is not None
        and now - float(_cache["at"]) < UPDATE_CHECK_TTL
    ):
        return dict(_cache["data"])

    install = (root or LAMP_ROOT).resolve()
    current = read_local_version(install)
    latest = fetch_remote_version()
    available = bool(latest and version_gt(latest, current))
    data = {
        "current": current,
        "latest": latest,
        "available": available,
        "install_dir": str(install),
        "command": update_command(install),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "remote_url": REMOTE_VERSION_URL,
    }
    _cache["at"] = now
    _cache["data"] = data
    return data


def _log(msg: str) -> None:
    print(f"  [lamp update] {msg}")


def _have_git() -> bool:
    return shutil.which("git") is not None


def backup_workshop_data() -> Path | None:
    if not WORKSHOP_DIR.is_dir():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = WORKSHOP_DIR / "backups" / f"pre-update-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "workshop.db", "lamp-cert.pem", "lamp-key.pem"):
        src = WORKSHOP_DIR / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    _log(f"Backed up key files to {dest}")
    return dest


def _download_zip(repo: str, branch: str, dest_dir: Path) -> None:
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"
    _log(f"Downloading {repo}…")
    req = urllib.request.Request(url, headers={"User-Agent": "Lamp-Updater"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "repo.zip"
        zpath.write_bytes(data)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not roots:
            raise RuntimeError(f"Empty zip from {repo}")
        overlay_tree(roots[0], dest_dir)


def overlay_tree(src: Path, dest: Path) -> None:
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        target_dir = dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, target_dir / name)


def _git(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def update_workshop(install: Path) -> None:
    ws = install / "vendor" / "workshop" / "workshop.py"
    if ws.is_file() and (install / ".git").is_dir() and _have_git():
        _log("Updating Workshop submodule…")
        try:
            _git(["git", "submodule", "update", "--init", "--recursive"], install)
            return
        except subprocess.CalledProcessError:
            _log("Submodule update failed — refreshing Workshop from zip…")
    _log("Refreshing Workshop…")
    _download_zip(WORKSHOP_GITHUB, DEFAULT_BRANCH, install / "vendor" / "workshop")


def update_tortoise(install: Path) -> None:
    tortoise = install / "vendor" / "workshop" / "vendor" / "tortoise"
    tp = tortoise / "tortoise.py"
    if tp.is_file() and (tortoise / ".git").is_dir() and _have_git():
        _log("Updating Tortoise…")
        try:
            _git(["git", "pull", "--ff-only"], tortoise)
            return
        except subprocess.CalledProcessError:
            _log("Tortoise git pull failed — re-downloading…")
    _log("Refreshing Tortoise…")
    tortoise.parent.mkdir(parents=True, exist_ok=True)
    if tortoise.exists():
        shutil.rmtree(tortoise)
    if _have_git():
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    f"https://github.com/{TORTOISE_GITHUB}.git",
                    str(tortoise),
                ],
                check=True,
                capture_output=True,
            )
            if tp.is_file():
                return
        except subprocess.CalledProcessError:
            pass
    _download_zip(TORTOISE_GITHUB, DEFAULT_BRANCH, tortoise)
    if not tp.is_file():
        raise RuntimeError("Tortoise update failed")


def update_lamp_code(install: Path) -> None:
    if (install / ".git").is_dir() and _have_git():
        _log("Pulling latest Lamp (git)…")
        _git(["git", "fetch", "origin", DEFAULT_BRANCH], install)
        _git(["git", "pull", "--ff-only", "origin", DEFAULT_BRANCH], install)
        update_workshop(install)
        return
    _log("No git repo — downloading latest Lamp zip…")
    tmp_parent = install.parent
    staging = tmp_parent / f".lamp-update-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    _download_zip(DEFAULT_GITHUB, DEFAULT_BRANCH, staging)
    overlay_tree(staging, install)
    shutil.rmtree(staging, ignore_errors=True)
    update_workshop(install)


def port_in_use(port: int) -> bool:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def run_update(*, install: Path | None = None, port: int = 7700) -> int:
    install = (install or LAMP_ROOT).resolve()
    if not (install / "lamp.py").is_file():
        _log(f"Not a Lamp install: {install}")
        return 1
    if port_in_use(port):
        _log(f"Port {port} is in use — stop Lamp first (Ctrl+C in its terminal), then re-run:")
        _log(f"  {update_command(install)}")
        return 1

    before = read_local_version(install)
    _log(f"Current version: {before}")
    backup_workshop_data()

    try:
        update_lamp_code(install)
        update_tortoise(install)
    except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError) as e:
        _log(f"Update failed: {e}")
        _log("Your data in ~/.workshop was not modified.")
        return 1

    after = read_local_version(install)
    _cache["data"] = None
    _log(f"Update complete: {before} → {after}")
    print("")
    print("  Restart Lamp:")
    if Path("/etc/systemd/system/lamp.service").is_file():
        print("    sudo systemctl restart lamp")
    elif sys.platform == "win32":
        print(f'    cd /d "{install}" && python lamp.py --host 0.0.0.0')
    else:
        print(f'    cd "{install}" && python3 lamp.py --host 0.0.0.0')
    print("")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: python3 lamp.py --update")
        return 0
    port = 7700
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
    return run_update(port=port)


if __name__ == "__main__":
    raise SystemExit(main())
