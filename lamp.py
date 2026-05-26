#!/usr/bin/env python3
"""
Lamp — home AI assistant (wraps Workshop + Tortoise).
Zero dependencies beyond Python 3.10+ stdlib.
"""

import argparse
import json
import os
import re
import shutil
import socket
import sys
import urllib.request
from http import cookies
from pathlib import Path
from urllib.parse import parse_qs, urlparse

LAMP_DIR = Path(__file__).resolve().parent
WORKSHOP_ROOT = LAMP_DIR / "vendor" / "workshop"
if WORKSHOP_ROOT.is_dir():
    sys.path.insert(0, str(WORKSHOP_ROOT))

import workshop_db as db  # noqa: E402
import ticker  # noqa: E402
import lamp_db as ldb  # noqa: E402
import lamp_chat  # noqa: E402
import lamp_admin  # noqa: E402
import lamp_models  # noqa: E402
import lamp_voice  # noqa: E402
from workshop import (  # noqa: E402
    Handler as WorkshopHandler,
    ThreadedHTTPServer,
    VERSION as WORKSHOP_VERSION,
    apps_dir,
    app_meta,
    list_apps,
    load_config,
    set_app_display_meta,
    save_config,
    tortoise_version,
    tortoise_script,
    TORTOISE_INSTALL_HINT,
    DEFAULT_PORT,
)

VERSION = lamp_admin.LAMP_VERSION
LAMP_HTML = LAMP_DIR / "lamp.html"
SESSION_COOKIE = "lamp_session"

_tortoise_sibling = LAMP_DIR.parent / "tortoise" / "tortoise.py"
if _tortoise_sibling.is_file() and not os.environ.get("TORTOISE_PATH"):
    os.environ.setdefault("TORTOISE_PATH", str(_tortoise_sibling))

AUTH_PUBLIC_GET = {
    "/",
    "/manifest.json",
    "/sw.js",
    "/lamp-icons.js",
    "/favicon.svg",
    "/icon-192.png",
    "/icon-512.png",
    "/favicon.ico",
}
AUTH_PUBLIC_GET_PREFIX = ("/api/auth/", "/assets/")
AUTH_PUBLIC_POST = {"/api/auth/login", "/api/auth/setup"}


class LampHandler(WorkshopHandler):
    lamp_user = None
    _lamp_body_cache = None

    def body(self):
        if self._lamp_body_cache is not None:
            return self._lamp_body_cache
        self._lamp_body_cache = super().body()
        return self._lamp_body_cache

    def _cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        jar = cookies.SimpleCookie()
        jar.load(raw)
        m = jar.get(name)
        return m.value if m else None

    def _set_session_cookie(self, token: str):
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 86400}",
        )

    def _clear_session_cookie(self):
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )

    def js(self, data, code=200, extra_headers=None):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _is_public(self, method: str, path: str) -> bool:
        if method == "GET" and path in AUTH_PUBLIC_GET:
            return True
        if method == "GET" and path.startswith(AUTH_PUBLIC_GET_PREFIX):
            return True
        if method == "POST" and path in AUTH_PUBLIC_POST:
            return True
        return False

    def _require_auth(self) -> dict | None:
        token = self._cookie(SESSION_COOKIE)
        user = ldb.session_check(token) if token else None
        if not user:
            self.js({"error": "not logged in"}, 401)
            return None
        return user

    def _require_admin(self, user: dict) -> bool:
        if user.get("role") != "admin":
            self.js({"error": "admin only"}, 403)
            return False
        return True

    def _require_builder(self, user: dict) -> bool:
        """Admin and standard users may build; child accounts may not."""
        if user.get("role") == "child":
            self.js({"error": "building is not available for child accounts"}, 403)
            return False
        return True

    def _allowed_app_slugs(self, user: dict) -> set[str]:
        """App folder names this user may use (personal + shared family apps)."""
        return {a["name"] for a in list_apps(load_config(), user["name"])}

    def _can_access_app(self, user: dict, owner: str, name: str) -> bool:
        if owner == "shared":
            return True
        return owner == user["name"]

    def _can_access_app_slug(self, user: dict, slug: str) -> bool:
        return slug in self._allowed_app_slugs(user)

    def _filter_notifs(self, notifs: list, user: dict) -> list:
        allowed = self._allowed_app_slugs(user)
        return [n for n in notifs if n.get("app") in allowed]

    def _filter_schedules(self, schedules: list, user: dict) -> list:
        allowed = self._allowed_app_slugs(user)
        return [s for s in schedules if s.get("app") in allowed]

    def _notif_access_ok(self, user: dict, nid: int) -> bool:
        row = db.notif_get(nid)
        if not row:
            return False
        return row.get("app") in self._allowed_app_slugs(user)

    def _schedule_access_ok(self, user: dict, sid: str) -> bool:
        row = db.schedule_get(sid)
        if not row:
            return False
        return row.get("app") in self._allowed_app_slugs(user)

    def _schedules_enriched(self, schedules: list) -> list:
        cfg = load_config()
        base = apps_dir(cfg)
        from ticker import _find_app_dir

        for s in schedules:
            s["app_missing"] = bool(
                s.get("app") and _find_app_dir(base, s["app"]) is None
            )
        return schedules

    def html_file(self, path: Path):
        b = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(b)

    def _serve_static(self, path: str) -> bool:
        mapping = {
            "/": LAMP_HTML,
            "/manifest.json": LAMP_DIR / "manifest.json",
            "/sw.js": LAMP_DIR / "sw.js",
            "/lamp-icons.js": LAMP_DIR / "lamp-icons.js",
            "/favicon.svg": LAMP_DIR / "assets" / "favicon.svg",
            "/icon-192.png": LAMP_DIR / "icon-192.png",
            "/icon-512.png": LAMP_DIR / "icon-512.png",
        }
        if path == "/":
            if LAMP_HTML.exists():
                self.html_file(LAMP_HTML)
                return True
            self.js({"error": "lamp.html missing"}, 500)
            return True
        fp = mapping.get(path)
        if fp and fp.is_file():
            self._send_file(fp, no_cache=path in ("/sw.js", "/lamp-icons.js"))
            return True
        if path.startswith("/assets/"):
            rel = path[len("/assets/") :].lstrip("/")
            if rel and ".." not in rel:
                fp = (LAMP_DIR / "assets" / rel).resolve()
                root = (LAMP_DIR / "assets").resolve()
                if fp.is_file() and str(fp).startswith(str(root)):
                    self._send_file(fp)
                    return True
        return False

    def _send_file(self, fp: Path, *, no_cache: bool = False):
        ct = {
            ".json": "application/json",
            ".js": "application/javascript",
            ".css": "text/css; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
            ".ttf": "font/ttf",
            ".txt": "text/plain; charset=utf-8",
        }.get(fp.suffix.lower(), "application/octet-stream")
        b = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        if no_cache:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(b)

    def _sse_write(self, data: dict):
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _auth_get(self, path: str, qs: dict):
        if path == "/api/auth/check":
            token = self._cookie(SESSION_COOKIE)
            user = ldb.session_check(token) if token else None
            if user:
                self.js({"ok": True, "user": user["name"], "role": user["role"]})
            else:
                self.js({"ok": False, "needs_setup": ldb.user_count() == 0}, 401)
            return
        if path == "/api/auth/users":
            self.js({"users": ldb.user_list_public(), "needs_setup": ldb.user_count() == 0})
            return
        self.js({"error": "not found"}, 404)

    def _auth_post(self, body: dict):
        path = urlparse(self.path).path
        if path == "/api/auth/login":
            user = ldb.user_verify((body.get("name") or "").strip(), (body.get("pin") or "").strip())
            if not user:
                self.js({"error": "invalid PIN"}, 401)
                return
            token = ldb.session_create(user["name"])
            ldb.ensure_user_apps_dir(user["name"], apps_dir(load_config()))
            self.send_response(200)
            b = json.dumps({"ok": True, "user": user["name"], "role": user["role"]}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
            self.send_header("Access-Control-Allow-Credentials", "true")
            self._set_session_cookie(token)
            self.end_headers()
            self.wfile.write(b)
            return
        if path == "/api/auth/setup":
            if ldb.user_count() > 0:
                self.js({"error": "already set up"}, 400)
                return
            try:
                user = ldb.user_create(
                    (body.get("name") or "").strip(),
                    (body.get("pin") or "").strip(),
                    role="admin",
                )
            except ValueError as e:
                self.js({"error": str(e)}, 400)
                return
            token = ldb.session_create(user["name"])
            ldb.ensure_user_apps_dir(user["name"], apps_dir(load_config()))
            self.send_response(200)
            b = json.dumps({"ok": True, "user": user["name"], "role": user["role"]}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
            self.send_header("Access-Control-Allow-Credentials", "true")
            self._set_session_cookie(token)
            self.end_headers()
            self.wfile.write(b)
            return
        if path == "/api/auth/logout":
            ldb.session_delete(self._cookie(SESSION_COOKIE))
            self.send_response(200)
            b = json.dumps({"ok": True}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self._clear_session_cookie()
            self.end_headers()
            self.wfile.write(b)
            return
        self.js({"error": "not found"}, 404)

    # ── Chat ──────────────────────────────────────────────────────────────────

    def _chat_get(self, path: str, user: dict):
        m = re.match(r"^/api/chat/conversations/([^/]+)/messages$", path)
        if m:
            cid = m.group(1)
            convo = ldb.convo_get(cid, user["name"])
            if not convo:
                self.js({"error": "not found"}, 404)
                return
            cfg = load_config()
            active = ldb.convo_chat_cfg(cfg, convo)
            self.js({
                "messages": ldb.msg_list(cid),
                "chat_model": {
                    "model": active.get("model"),
                    "endpoint": active.get("endpoint"),
                    "override": bool(convo.get("model") or convo.get("endpoint")),
                },
                "default_model": {
                    "model": cfg.get("model"),
                    "endpoint": cfg.get("endpoint"),
                },
            })
            return
        if path == "/api/chat/conversations":
            self.js({"conversations": ldb.convo_list(user["name"])})
            return
        self.js({"error": "not found"}, 404)

    def _voice_get(self, path: str):
        if path == "/api/voice/status":
            self.js(lamp_voice.voice_status(load_config()))
            return
        self.js({"error": "not found"}, 404)

    def _chat_transcribe(self, user: dict):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n) if n else b""
        mime = (self.headers.get("Content-Type") or "audio/webm").split(";")[0].strip()
        lang = (self.headers.get("X-Lamp-Language") or "en").strip()[:16] or "en"
        result = lamp_voice.transcribe_bytes(data, mime=mime, language=lang)
        if not result.get("ok"):
            self.js({"error": result.get("error", "transcription failed")}, 400)
            return
        text = lamp_voice.clean_transcript(result.get("text", ""))
        self.js({
            "ok": True,
            "text": text,
            "engine": result.get("engine", "whisper"),
        })

    def _chat_post(self, body: dict, user: dict):
        path = urlparse(self.path).path
        if path == "/api/chat/conversations":
            title = (body.get("title") or "").strip() or None
            self.js({"ok": True, **ldb.convo_create(user["name"], title)})
            return
        if path == "/api/chat/messages":
            self._chat_send_message(body, user)
            return
        self.js({"error": "not found"}, 404)

    def _chat_send_message(self, body: dict, user: dict):
        global_cfg = load_config()
        cid = (body.get("convo_id") or "").strip()
        content = (body.get("content") or "").strip()
        if not cid or not content:
            self.js({"error": "convo_id and content required"}, 400)
            return
        convo = ldb.convo_get(cid, user["name"])
        if not convo:
            self.js({"error": "not found"}, 404)
            return
        cfg = ldb.convo_chat_cfg(global_cfg, convo)
        if not cfg.get("endpoint") or not cfg.get("model"):
            self.js({"error": "not configured"}, 400)
            return

        ldb.msg_add(cid, "user", content)
        if not convo.get("title"):
            ldb.convo_touch(cid, content[:60])

        history = [
            {"role": m["role"], "content": m["content"]}
            for m in ldb.msg_list(cid)
            if m["role"] in ("user", "assistant")
        ]

        system = lamp_chat.LAMP_SYSTEM
        if ldb.convo_take_handoff(cid):
            system += lamp_chat.MODEL_HANDOFF_NOTE

        self._start_sse()
        try:
            def write_sse(ev):
                self._sse_write(ev)

            parsed = lamp_chat.stream_chat(cfg, history, write_sse, system=system)
            stored = parsed["reply"]
            if parsed.get("app_idea"):
                stored += "\n\n```json\n" + json.dumps(parsed["app_idea"]) + "\n```"
            ldb.msg_add(cid, "assistant", stored)
            ldb.convo_touch(cid)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return

    def _chat_put(self, path: str, body: dict, user: dict):
        m = re.match(r"^/api/chat/conversations/([^/]+)$", path)
        if not m:
            self.js({"error": "not found"}, 404)
            return
        cid = m.group(1)
        if body.get("use_default"):
            convo = ldb.convo_clear_model(cid, user["name"])
            if not convo:
                self.js({"error": "not found"}, 404)
                return
            cfg = load_config()
            active = ldb.convo_chat_cfg(cfg, convo)
            self.js({
                "ok": True,
                **convo,
                "chat_model": {
                    "model": active.get("model"),
                    "endpoint": active.get("endpoint"),
                    "override": False,
                },
            })
            return
        if "model" in body and "endpoint" in body:
            try:
                convo = ldb.convo_set_model(
                    cid,
                    user["name"],
                    (body.get("endpoint") or "").strip(),
                    (body.get("model") or "").strip(),
                )
            except ValueError as e:
                self.js({"error": str(e)}, 400)
                return
            if not convo:
                self.js({"error": "not found"}, 404)
                return
            cfg = load_config()
            active = ldb.convo_chat_cfg(cfg, convo)
            self.js({
                "ok": True,
                **convo,
                "chat_model": {
                    "model": active.get("model"),
                    "endpoint": active.get("endpoint"),
                    "override": True,
                },
            })
            return
        title = starred = None
        if "title" in body:
            title = (body.get("title") or "").strip() or None
        if "starred" in body:
            starred = bool(body.get("starred"))
        if title is None and starred is None:
            self.js({"error": "title or starred required"}, 400)
            return
        if not ldb.convo_update(cid, user["name"], title=title, starred=starred):
            self.js({"error": "not found"}, 404)
            return
        convo = ldb.convo_get(cid, user["name"])
        self.js({"ok": True, **convo})

    def _chat_delete(self, path: str, user: dict):
        m = re.match(r"^/api/chat/conversations/([^/]+)$", path)
        if m:
            ok = ldb.convo_delete(m.group(1), user["name"])
            self.js({"ok": ok} if ok else {"error": "not found"}, 200 if ok else 404)
            return
        self.js({"error": "not found"}, 404)

    # ── Templates ─────────────────────────────────────────────────────────────

    def _templates_get(self, path: str):
        m = re.match(r"^/api/templates/([^/]+)$", path)
        if m:
            tpl = lamp_admin.load_template(m.group(1))
            if tpl:
                self.js(tpl)
            else:
                self.js({"error": "not found"}, 404)
            return
        if path == "/api/templates":
            self.js({"templates": lamp_admin.list_templates()})
            return
        self.js({"error": "not found"}, 404)

    # ── Admin ─────────────────────────────────────────────────────────────────

    def _admin_users_list(self, cfg):
        out = []
        for u in ldb.user_list_public():
            out.append({
                **u,
                "app_count": len(list_apps(cfg, u["name"])),
                "chat_count": ldb.chat_count(u["name"]),
            })
        return out

    def _admin_get(self, path: str, user: dict, qs: dict):
        if not self._require_admin(user):
            return
        cfg = load_config()
        if path == "/api/admin/users":
            self.js({"users": self._admin_users_list(cfg)})
            return
        if path == "/api/admin/models/catalog":
            q = qs.get("q", [""])[0]
            self.js(lamp_models.catalog_search(q))
            return
        if path == "/api/admin/models":
            self.js(lamp_models.models_overview(cfg))
            return
        if path == "/api/admin/storage":
            self.js(lamp_admin.storage_breakdown(cfg))
            return
        if path == "/api/admin/system":
            self.js(lamp_admin.system_status(cfg, tortoise_version() or "?"))
            return
        if path == "/api/admin/reminders":
            from ticker import _find_app_dir
            base = apps_dir(cfg)
            schedules = db.schedule_list()
            for s in schedules:
                s["app_missing"] = bool(
                    s.get("app") and _find_app_dir(base, s["app"]) is None
                )
            self.js({"schedules": schedules})
            return
        self.js({"error": "not found"}, 404)

    def _admin_post(self, body: dict, user: dict):
        if not self._require_admin(user):
            return
        path = urlparse(self.path).path
        cfg = load_config()

        if path == "/api/admin/users":
            try:
                u = ldb.user_create(
                    (body.get("name") or "").strip(),
                    (body.get("pin") or "").strip(),
                    role=body.get("role") or "user",
                )
                ldb.ensure_user_apps_dir(u["name"], apps_dir(cfg))
                self.js({"ok": True, **u})
            except ValueError as e:
                self.js({"error": str(e)}, 400)
            return

        if path == "/api/admin/models/pull":
            model = (body.get("model") or "").strip()
            if not model:
                self.js({"error": "model required"}, 400)
                return
            self._start_sse()
            try:
                lamp_admin.ollama_pull_stream(model, self._sse_write)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if path == "/api/admin/models/switch":
            model = (body.get("model") or "").strip()
            endpoint = (body.get("endpoint") or "").strip()
            if not model:
                self.js({"error": "model required"}, 400)
                return
            if endpoint:
                cfg = lamp_models.switch_model(cfg, endpoint, model)
            else:
                cfg["model"] = model
            save_config(cfg)
            self.js({
                "ok": True,
                "model": cfg["model"],
                "endpoint": cfg.get("endpoint"),
            })
            return

        if path == "/api/admin/models/import-url":
            url = (body.get("url") or "").strip()
            name = (body.get("name") or "").strip()
            result = lamp_models.import_from_url(url, name)
            if not result.get("ok"):
                self.js(result, 400)
                return
            if result.get("action") == "pull":
                model = result.get("model")
                self.js({
                    "ok": True,
                    "action": "pull",
                    "model": model,
                    "message": f"Ready to pull {model} — call /api/admin/models/pull",
                })
            else:
                self.js(result)
            return

        if path == "/api/admin/storage/delete-app":
            owner = (body.get("owner") or "").strip()
            name = (body.get("name") or "").strip()
            if not owner or not name:
                self.js({"error": "owner and name required"}, 400)
                return
            apps = lamp_admin.list_app_storage(cfg)
            match = next(
                (a for a in apps if a["owner"] == owner and a["name"] == name),
                None,
            )
            if not match:
                self.js({"error": "not found"}, 404)
                return
            result = lamp_admin.delete_app_from_disk(cfg, owner, name)
            if not result.get("ok"):
                self.js({"error": result.get("error", "delete failed")}, 404)
                return
            self.js(result)
            return

        if path == "/api/admin/storage/cleanup":
            target = body.get("target", "backups")
            freed = 0
            if target == "backups":
                freed = lamp_admin.cleanup_backups(int(body.get("days", 30)), cfg)
            elif target == "chats":
                freed = ldb.chats_clear_older_than(
                    int(body.get("days", 90)), body.get("user")
                )
                self.js({"ok": True, "deleted_count": freed})
                return
            elif target == "orphans":
                self.js(lamp_admin.delete_orphan_apps(cfg))
                return
            elif target == "app_data" and body.get("app"):
                import workshop_db as wdb
                wdb.get_conn().execute(
                    "DELETE FROM app_data WHERE app=?", (body["app"],)
                )
                wdb.get_conn().commit()
            self.js({"ok": True, "freed_bytes": freed})
            return

        if path == "/api/admin/storage/vacuum":
            before, after = lamp_admin.vacuum_db()
            self.js({"ok": True, "size_before": before, "size_after": after})
            return

        self.js({"error": "not found"}, 404)

    def _admin_put(self, path: str, body: dict, user: dict):
        if not self._require_admin(user):
            return
        m = re.match(r"^/api/admin/users/([^/]+)$", path)
        if m:
            name = m.group(1)
            if not ldb.user_get(name):
                self.js({"error": "not found"}, 404)
                return
            ldb.user_update(name, role=body.get("role"), pin=body.get("pin"))
            self.js({"ok": True})
            return
        self.js({"error": "not found"}, 404)

    def _admin_delete(self, path: str, user: dict):
        if not self._require_admin(user):
            return
        cfg = load_config()
        m = re.match(r"^/api/admin/users/([^/]+)$", path)
        if m:
            name = m.group(1)
            if name == user["name"]:
                self.js({"error": "cannot delete yourself"}, 400)
                return
            base = apps_dir(cfg) / "users" / name
            if base.exists():
                shutil.rmtree(base)
            ldb.user_delete(name)
            self.js({"ok": True})
            return
        m = re.match(r"^/api/admin/models/([^/]+)$", path)
        if m:
            ok = lamp_admin.ollama_rm(m.group(1))
            self.js({"ok": ok} if ok else {"error": "failed"}, 200 if ok else 500)
            return
        self.js({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Lamp-Language",
        )
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p, qs = parsed.path, parse_qs(parsed.query)

        if self._serve_static(p):
            return
        if p.startswith("/api/auth/"):
            self._auth_get(p, qs)
            return

        if self._is_public("GET", p):
            return super().do_GET()

        user = self._require_auth()
        if not user:
            return
        self.lamp_user = user

        if p.startswith("/api/voice/"):
            self._voice_get(p)
            return
        if p.startswith("/api/chat/"):
            self._chat_get(p, user)
            return
        if p.startswith("/api/templates"):
            self._templates_get(p)
            return
        if p.startswith("/api/admin/"):
            self._admin_get(p, user, qs)
            return
        if p == "/api/apps":
            self.js({"apps": list_apps(load_config(), user["name"])})
            return

        if p == "/api/notifications":
            unread = qs.get("unread", ["0"])[0] in ("1", "true", "yes")
            notifs = db.notif_list(unread_only=unread)
            self.js({"notifications": self._filter_notifs(notifs, user)})
            return

        if p == "/api/schedules":
            app = qs.get("app", [None])[0]
            if app and not self._can_access_app_slug(user, app):
                self.js({"schedules": []})
                return
            schedules = self._filter_schedules(db.schedule_list(app=app), user)
            self.js({"schedules": self._schedules_enriched(schedules)})
            return

        m = re.match(r"^/api/data/([^/]+)", p)
        if m and not self._can_access_app_slug(user, m.group(1)):
            self.js({"error": "forbidden"}, 403)
            return

        m = re.match(r"^/api/print/([^/]+)/([^/]+)", p)
        if m and not self._can_access_app(user, m.group(1), m.group(2)):
            self.js({"error": "forbidden"}, 403)
            return

        m = re.match(r"^/api/app/([^/]+)/([^/]+)/", p)
        if m and not self._can_access_app(user, m.group(1), m.group(2)):
            self.js({"error": "forbidden"}, 403)
            return

        m = re.match(r"^/apps/([^/]+)/([^/]+)", p)
        if m and not self._can_access_app(user, m.group(1), m.group(2)):
            self.js({"error": "forbidden"}, 403)
            return

        return super().do_GET()

    def do_POST(self):
        self._lamp_body_cache = None
        p = urlparse(self.path).path

        if p.startswith("/api/auth/"):
            self._auth_post(self.body())
            return
        if self._is_public("POST", p):
            return super().do_POST()

        user = self._require_auth()
        if not user:
            return
        self.lamp_user = user

        if p == "/api/chat/transcribe":
            self._chat_transcribe(user)
            return
        if p.startswith("/api/chat/"):
            self._chat_post(self.body(), user)
            return
        if p.startswith("/api/admin/"):
            self._admin_post(self.body(), user)
            return

        m = re.match(r"^/api/apps/([^/]+)/([^/]+)/wipe-data$", p)
        if m:
            if user.get("role") == "child":
                self.js({"error": "not allowed for child accounts"}, 403)
                return
            owner, name = m.group(1), m.group(2)
            if owner == "shared" and user.get("role") != "admin":
                self.js({"error": "admin only for shared apps"}, 403)
                return
            if owner not in ("shared", user["name"]) and user.get("role") != "admin":
                self.js({"error": "forbidden"}, 403)
                return
            self.js({"ok": True, **lamp_admin.wipe_app_data(name)})
            return

        if p in ("/api/build/start", "/api/build/resume", "/api/build/update", "/api/agent/chat", "/api/fix"):
            if not self._require_builder(user):
                return
            b = self.body()
            if not b.get("user"):
                b["user"] = user["name"]
            return self._post_with_body(p, b)

        if p == "/api/setup" and user.get("role") != "admin":
            self.js({"error": "admin only"}, 403)
            return

        m = re.match(r"^/api/notifications/(\d+)/read$", p)
        if m:
            nid = int(m.group(1))
            if not self._notif_access_ok(user, nid):
                self.js({"error": "not found"}, 404)
                return
            ok = db.notif_mark_read(nid)
            self.js({"ok": ok} if ok else {"error": "not found"}, 200 if ok else 404)
            return

        if p == "/api/notifications/clear":
            if user.get("role") == "child":
                self.js({"error": "not allowed for child accounts"}, 403)
                return
            b = self.body()
            app = (b.get("app") or "").strip() or None
            if b.get("mark_read"):
                n = 0
                for row in self._filter_notifs(db.notif_list(unread_only=True), user):
                    if db.notif_mark_read(row["id"]):
                        n += 1
                self.js({"ok": True, "marked_read": n})
                return
            if app:
                if not self._can_access_app_slug(user, app):
                    self.js({"error": "not found"}, 404)
                    return
                n = db.notif_clear(app=app, read_only=bool(b.get("read_only")))
            else:
                n = 0
                for slug in self._allowed_app_slugs(user):
                    n += db.notif_clear(app=slug, read_only=bool(b.get("read_only")))
            self.js({"ok": True, "deleted": n})
            return

        if p == "/api/schedules":
            app = (self.body().get("app") or "").strip()
            if app and not self._can_access_app_slug(user, app):
                self.js({"error": "forbidden"}, 403)
                return
        if p == "/api/schedules/toggle":
            sid = (self.body().get("id") or "").strip()
            if sid and not self._schedule_access_ok(user, sid):
                self.js({"error": "not found"}, 404)
                return
        if p == "/api/schedules/stop-app":
            app = (self.body().get("app") or "").strip()
            if app and not self._can_access_app_slug(user, app):
                self.js({"error": "not found"}, 404)
                return

        if user.get("role") == "child" and (
            p.startswith("/api/schedules")
            or p == "/api/notifications/clear"
        ):
            self.js({"error": "not allowed for child accounts"}, 403)
            return

        return super().do_POST()

    def _post_with_body(self, path: str, body: dict):
        import io

        data = json.dumps(body).encode()
        self.rfile = io.BytesIO(data)
        self.headers["Content-Length"] = str(len(data))
        try:
            dispatch = {
                "/api/build/start": self._start_build,
                "/api/build/resume": self._resume_build,
                "/api/build/update": self._update_app,
                "/api/agent/chat": self._agent_chat,
                "/api/fix": self._fix_app,
            }
            fn = dispatch.get(path)
            if fn:
                fn(body)
            else:
                self.js({"error": "not found"}, 404)
        finally:
            pass

    def do_PUT(self):
        self._lamp_body_cache = None
        p = urlparse(self.path).path
        if self._is_public("PUT", p):
            return super().do_PUT()
        user = self._require_auth()
        if not user:
            return
        self.lamp_user = user
        if p.startswith("/api/chat/"):
            self._chat_put(p, self.body(), user)
            return
        if p.startswith("/api/admin/"):
            self._admin_put(p, self.body(), user)
            return

        m = re.match(r"^/api/data/([^/]+)", p)
        if m and not self._can_access_app_slug(user, m.group(1)):
            self.js({"error": "forbidden"}, 403)
            return

        m = re.match(r"^/api/apps/([^/]+)/([^/]+)/meta$", p)
        if m:
            if user.get("role") == "child":
                self.js({"error": "not allowed for child accounts"}, 403)
                return
            owner, name = m.group(1), m.group(2)
            if not self._can_access_app(user, owner, name):
                self.js({"error": "forbidden"}, 403)
                return
            body = self.body()
            title = (body.get("title") or "").strip()
            summary = (body.get("desc") or body.get("summary") or "").strip()
            if not title:
                self.js({"error": "title required"}, 400)
                return
            cfg = load_config()
            base = apps_dir(cfg)
            ap = (
                base / "shared" / name
                if owner == "shared"
                else base / "users" / owner / name
            )
            if not ap.is_dir():
                self.js({"error": "not found"}, 404)
                return
            if not set_app_display_meta(ap, title, summary):
                self.js({"error": "could not update app"}, 500)
                return
            scope = "shared" if owner == "shared" else "personal"
            self.js({"ok": True, **app_meta(ap, owner, scope)})
            return

        return super().do_PUT()

    def do_DELETE(self):
        p = urlparse(self.path).path
        if self._is_public("DELETE", p):
            return super().do_DELETE()
        user = self._require_auth()
        if not user:
            return
        self.lamp_user = user
        if p.startswith("/api/chat/"):
            self._chat_delete(p, user)
            return
        if p.startswith("/api/admin/"):
            self._admin_delete(p, user)
            return
        if p.startswith("/api/apps/") and user.get("role") == "child":
            self.js({"error": "not allowed for child accounts"}, 403)
            return

        m = re.match(r"^/api/notifications/(\d+)$", p)
        if m:
            nid = int(m.group(1))
            if not self._notif_access_ok(user, nid):
                self.js({"error": "not found"}, 404)
                return
            ok = db.notif_delete(nid)
            self.js({"ok": ok} if ok else {"error": "not found"}, 200 if ok else 404)
            return

        m = re.match(r"^/api/data/([^/]+)", p)
        if m and not self._can_access_app_slug(user, m.group(1)):
            self.js({"error": "forbidden"}, 403)
            return

        if p.startswith("/api/schedules/"):
            sid = p.split("/")[-1]
            if not self._schedule_access_ok(user, sid):
                self.js({"error": "not found"}, 404)
                return

        if user.get("role") == "child" and p.startswith("/api/schedules"):
            self.js({"error": "not allowed for child accounts"}, 403)
            return

        return super().do_DELETE()


def print_status(cfg) -> int:
    ts_ok = bool(tortoise_script())
    print(f"\n  Lamp {VERSION}  (Workshop {WORKSHOP_VERSION})")
    if ts_ok:
        print(f"  tortoise : v{tortoise_version()} ✓  ({tortoise_script()})")
    else:
        print("  tortoise : ✗ NOT FOUND")
    print(f"  apps dir : {apps_dir(cfg)}")
    print(f"  database : {db.DB_PATH}")
    print(f"  users    : {ldb.user_count()} account(s)")
    print(f"  templates: {len(lamp_admin.list_templates())}")
    ep = cfg.get("endpoint")
    print(f"  model    : {cfg.get('model') or '—'}")
    print(f"  endpoint : {ep or '—'}")
    if ep:
        ok = lamp_admin.system_status(cfg, tortoise_version() or "?")["ollama"]["ok"]
        print(f"  ollama   : {'OK' if ok else 'down'}")
    vs = lamp_voice.voice_status(cfg)
    wh = "OK" if vs["whisper_available"] else "not installed"
    print(f"  whisper  : {wh} (model {vs['model']}, ffmpeg {'yes' if vs['ffmpeg'] else 'no'})")
    print()
    return 0 if ts_ok else 1


def _lan_ip() -> str | None:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def server_urls(host: str, port: int, *, scheme: str = "http") -> list[tuple[str, str]]:
    """(url, hint) pairs for the startup banner."""
    host_norm = host.strip().lower()
    listening_all = host_norm in ("", "0.0.0.0", "::")
    secure = scheme == "https"
    lines: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(url: str, hint: str = "") -> None:
        if url not in seen:
            seen.add(url)
            lines.append((url, hint))

    if host_norm in ("127.0.0.1", "localhost", "::1") or listening_all:
        add(f"{scheme}://localhost:{port}", "this computer")
    elif host_norm not in ("",):
        add(f"{scheme}://{host}:{port}", "")

    ip = _lan_ip()
    if ip:
        if listening_all:
            hint = "phones/tablets" + (" — accept cert warning once" if secure else " — add --tls for microphone")
        else:
            hint = "phones/tablets — restart with --host 0.0.0.0" + (" --tls" if not secure else "")
        add(f"{scheme}://{ip}:{port}", hint)

    if listening_all:
        hn = os.uname().nodename.split(".")[0].lower()
        if hn == "lamp":
            add(f"{scheme}://lamp.local:{port}", "mDNS")
        elif hn not in ("localhost", ""):
            add(f"{scheme}://{hn}.local:{port}", "mDNS (if your OS advertises it)")

    return lines


def _default_tls_paths() -> tuple[Path, Path]:
    d = Path.home() / ".workshop"
    return d / "lamp-cert.pem", d / "lamp-key.pem"


def _localhost_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _fetch_localhost_shell(port: int) -> str | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as r:
            return r.read(120_000).decode("utf-8", errors="replace")
    except Exception:
        return None


def warn_localhost_port_conflict(port: int):
    """Another process on 127.0.0.1:port (often Lamp.app) shadows localhost for dev."""
    if not _localhost_port_in_use(port):
        return
    body = _fetch_localhost_shell(port) or ""
    ours = "nav-account" in body and "id=\"nav-account\"" in body
    stale = "theme-toggle" in body or "nav-theme" in body
    if ours:
        return
    print("\n  ⚠  Another Lamp is already listening on http://127.0.0.1:{}/".format(port))
    if stale:
        print("     That copy is an older build (no Account in the sidebar).")
    print("     localhost will NOT show this dev tree — use the LAN URL below, or quit Lamp.app")
    print("     and restart this server.\n")


def main():
    ap = argparse.ArgumentParser(prog="lamp")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--tls",
        action="store_true",
        help="Serve HTTPS (required for microphone from phones on Wi‑Fi; run setup/generate-lamp-cert.sh first)",
    )
    ap.add_argument("--tls-cert", type=Path, default=None, help="TLS certificate PEM (default: ~/.workshop/lamp-cert.pem)")
    ap.add_argument("--tls-key", type=Path, default=None, help="TLS private key PEM (default: ~/.workshop/lamp-key.pem)")
    ap.add_argument("--status", action="store_true", help="Print config health and exit")
    args = ap.parse_args()

    scheme = "https" if args.tls else "http"
    def_cert, def_key = _default_tls_paths()
    tls_cert = args.tls_cert or def_cert
    tls_key = args.tls_key or def_key
    if args.tls and (not tls_cert.is_file() or not tls_key.is_file()):
        print("\n  TLS certificate not found.")
        print("  Run:  ./setup/generate-lamp-cert.sh")
        print("  Then: python3 lamp.py --host 0.0.0.0 --tls\n")
        raise SystemExit(1)

    cfg = load_config()
    apps_dir(cfg).mkdir(parents=True, exist_ok=True)
    ldb.init_lamp_tables()

    if args.status:
        raise SystemExit(print_status(cfg))

    ticker.start_ticker_thread(lambda: apps_dir(load_config()))

    code = print_status(cfg)
    if code:
        for line in TORTOISE_INSTALL_HINT.splitlines():
            print(f"    {line}")
    print("  Open:")
    for url, hint in server_urls(args.host, args.port, scheme=scheme):
        line = f"    {url}"
        if hint:
            line += f"  — {hint}"
        print(line)
    if not args.tls and args.host.strip() not in ("127.0.0.1", "localhost", "::1"):
        print("  Note: microphone from phones needs HTTPS — use --tls (see setup/generate-lamp-cert.sh)")
    warn_localhost_port_conflict(args.port)
    print()

    server = ThreadedHTTPServer((args.host, args.port), LampHandler)
    if args.tls:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(tls_cert), str(tls_key))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
