"""
MemoMind integration for Lamp — stdlib HTTP bridge to the MemoMind Python modules.

MemoMind source is resolved from (first match):
  MEMOMIND_PATH env, vendor/memomind/, or ../memomind/ next to this repo.
Install optional deps: pip install -r requirements-memomind.txt
"""

from __future__ import annotations

import cgi
import io
import json
import logging
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("lamp.memomind")

LAMP_DIR = Path(__file__).resolve().parent
WORKSHOP_DIR = Path.home() / ".workshop"
APP_SLUG = "memomind"

_import_error: str | None = None
_mm = None  # namespace after successful import
_local = threading.local()
_reminder_thread_started = False


def _memomind_roots() -> list[Path]:
    env = os.environ.get("MEMOMIND_PATH", "").strip()
    roots = []
    if env:
        roots.append(Path(env).expanduser())
    roots.append(LAMP_DIR / "vendor" / "memomind")
    roots.append(LAMP_DIR.parent / "memomind")
    return roots


def find_memomind_root() -> Path | None:
    for root in _memomind_roots():
        if (root / "memomind_db.py").is_file():
            return root.resolve()
    return None


def _try_import():
    global _import_error, _mm
    if _mm is not None:
        return
    root = find_memomind_root()
    if not root:
        _import_error = (
            "MemoMind not found. Clone https://github.com/thebreadcat/memomind "
            "to ../memomind or vendor/memomind, or set MEMOMIND_PATH."
        )
        return
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import memomind_api as api
        import memomind_brain as brain
        import memomind_capture as capture
        import memomind_db as mdb
        import memomind_images as images
        import memomind_search as search
        import memomind_tasks_events as te
        import memomind_voice as voice
        from memomind_config import load_config as mm_load_config
        from memomind_models import NoModelFoundError, configure_model
        from memomind_persona import COLD_START, ERROR, IMAGES
        from memomind_scheduler import build_reminder_message

        class _NS:
            pass

        ns = _NS()
        ns.api = api
        ns.brain = brain
        ns.capture = capture
        ns.db = mdb
        ns.images = images
        ns.search = search
        ns.te = te
        ns.voice = voice
        ns.mm_load_config = mm_load_config
        ns.NoModelFoundError = NoModelFoundError
        ns.configure_model = configure_model
        ns.COLD_START = COLD_START
        ns.ERROR = ERROR
        ns.IMAGES = IMAGES
        ns.build_reminder_message = build_reminder_message
        ns.root = root
        _mm = ns
        _import_error = None
    except Exception as e:
        _import_error = f"MemoMind import failed: {e}"


def available() -> bool:
    _try_import()
    return _mm is not None


def status_message() -> str:
    _try_import()
    return _import_error or "ok"


def user_db_path(user_name: str) -> Path:
    p = WORKSHOP_DIR / "users" / user_name / "memomind.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def shared_db_path() -> Path:
    p = WORKSHOP_DIR / "shared" / "memomind.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _shared_key() -> str | None:
    cfg_path = WORKSHOP_DIR / "config.json"
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if data.get("memomind_shared_key"):
                return data["memomind_shared_key"]
        except (json.JSONDecodeError, OSError):
            pass
    _try_import()
    if _mm:
        return _mm.mm_load_config().get("shared_key")
    return None


def ensure_user(user_name: str):
    _try_import()
    if not _mm:
        raise RuntimeError(_import_error or "MemoMind unavailable")
    if getattr(_local, "user", None) == user_name:
        return
    _mm.api.init(
        db_path=str(user_db_path(user_name)),
        user_id=user_name,
        shared_db_path=str(shared_db_path()),
        shared_key=_shared_key(),
        integrated_mode=True,
    )
    _local.user = user_name


def serve_html(handler) -> bool:
    _try_import()
    if not _mm:
        handler.js({"error": status_message(), "code": "MEMOMIND_UNAVAILABLE"}, 503)
        return True
    html_path = _mm.root / "memomind.html"
    if not html_path.is_file():
        handler.js({"error": "memomind.html not found"}, 500)
        return True
    text = html_path.read_text(encoding="utf-8")
    text = text.replace("const API = '';", "const API = '/api/memomind';", 1)
    b = text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(b)))
    handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
    handler.end_headers()
    handler.wfile.write(b)
    return True


def _json(handler, data, code=200):
    handler.js(data, code)


def _err(handler, message: str, code: str = "ERROR", status: int = 400):
    _json(handler, {"error": message, "code": code}, status)


def _body_json(handler) -> dict:
    """Lamp/Workshop body() may already return a dict — do not json.loads twice."""
    raw = handler.body()
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _qs_int(qs: dict, key: str, default: int) -> int:
    v = qs.get(key, [str(default)])[0]
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_multipart(handler) -> cgi.FieldStorage:
    env = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": handler.headers.get("Content-Type", ""),
        "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
    }
    return cgi.FieldStorage(fp=handler.rfile, environ=env, keep_blank_values=True)


def _validate_shared_key(handler) -> bool:
    key = handler.headers.get("X-MemoMind-Key")
    expected = _shared_key()
    if not expected or key != expected:
        _err(
            handler,
            "I couldn't reach the family brain — check your connection",
            "SHARED_KEY_INVALID",
            403,
        )
        return False
    return True


def handle(handler, method: str, full_path: str, user: dict) -> bool:
    """Handle /api/memomind/* and /memomind-app. Returns True if handled."""
    parsed = urlparse(full_path)
    path = parsed.path
    qs = parse_qs(parsed.query)

    if path in ("/memomind-app", "/memomind-app/"):
        if method != "GET":
            handler.js({"error": "method not allowed"}, 405)
            return True
        return serve_html(handler)

    if not path.startswith("/api/memomind"):
        return False

    sub = path[len("/api/memomind") :] or "/"
    if sub != "/" and not sub.startswith("/"):
        sub = "/" + sub

    _try_import()
    if not _mm:
        _err(handler, status_message(), "MEMOMIND_UNAVAILABLE", 503)
        return True

    try:
        ensure_user(user["name"])
    except RuntimeError as e:
        _err(handler, str(e), "MEMOMIND_UNAVAILABLE", 503)
        return True

    try:
        if not _dispatch(handler, method, sub, qs, user):
            _err(handler, "not found", "NOT_FOUND", 404)
        return True
    except _mm.NoModelFoundError:
        _err(handler, _mm.ERROR["no_model"], "NO_MODEL", 503)
        return True
    except Exception as e:
        log.exception("MemoMind error on %s %s", method, sub)
        if "locked" in str(e).lower():
            _err(handler, _mm.ERROR["db_error"], "DB_LOCKED", 503)
        else:
            _err(handler, str(e), "INTERNAL_ERROR", 500)
        return True


def _dispatch(handler, method: str, path: str, qs: dict, user: dict) -> bool:
    mm = _mm
    m = re.match(r"^/entries/([^/]+)/related$", path)
    if method == "GET" and m:
        related = mm.brain.get_related_entries(m.group(1))
        _json(handler, {"related": related})
        return True

    m = re.match(r"^/entries/([^/]+)/pin$", path)
    if method == "POST" and m:
        entry = mm.db.pin_entry(m.group(1))
        if not entry:
            _err(handler, "Entry not found", "NOT_FOUND", 404)
            return True
        _json(handler, entry)
        return True

    m = re.match(r"^/entries/([^/]+)/share$", path)
    if method == "POST" and m:
        try:
            _json(handler, mm.api.push_to_shared(m.group(1), author=user["name"]))
        except ValueError as e:
            _err(handler, str(e), "SHARE_ERROR", 400)
        except Exception:
            _err(
                handler,
                "I couldn't reach the family brain — check your connection",
                "SHARED_UNREACHABLE",
                502,
            )
        return True

    m = re.match(r"^/entries/([^/]+)$", path)
    if m:
        eid = m.group(1)
        if method == "GET":
            entry = mm.db.get_entry(eid)
            if not entry:
                _err(handler, "Entry not found", "NOT_FOUND", 404)
                return True
            entry["entities"] = mm.db.get_entities_for_entry(eid)
            _json(handler, entry)
            return True
        if method == "PUT":
            data = _body_json(handler)
            allowed = ("content", "type", "scope", "thread_id", "pinned")
            entry = mm.db.update_entry(eid, **{k: data[k] for k in data if k in allowed})
            if not entry:
                _err(handler, "Entry not found", "NOT_FOUND", 404)
                return True
            _json(handler, entry)
            return True
        if method == "DELETE":
            if not mm.db.soft_delete_entry(eid):
                _err(handler, "Entry not found", "NOT_FOUND", 404)
                return True
            _json(handler, {"deleted": True})
            return True

    m = re.match(r"^/threads/([^/]+)/summary$", path)
    if method == "GET" and m:
        tid = m.group(1)
        thread = mm.db.get_thread(tid)
        if not thread:
            _err(handler, "Thread not found", "NOT_FOUND", 404)
            return True
        entries = mm.db.get_thread_entries(tid)
        if not thread.get("summary") and entries:
            mm.brain.refresh_thread_summaries()
            thread = mm.db.get_thread(tid)
        _json(handler, {"summary": thread.get("summary", ""), "entry_count": len(entries)})
        return True

    m = re.match(r"^/threads/([^/]+)/close$", path)
    if method == "POST" and m:
        thread = mm.db.update_thread(m.group(1), status="done")
        if not thread:
            _err(handler, "Thread not found", "NOT_FOUND", 404)
            return True
        _json(handler, thread)
        return True

    m = re.match(r"^/threads/([^/]+)$", path)
    if m:
        tid = m.group(1)
        if method == "GET":
            thread = mm.db.get_thread(tid)
            if not thread:
                _err(handler, "Thread not found", "NOT_FOUND", 404)
                return True
            thread["entries"] = mm.db.get_thread_entries(tid)
            _json(handler, thread)
            return True
        if method == "PUT":
            data = _body_json(handler)
            allowed = ("title", "summary", "status")
            thread = mm.db.update_thread(tid, **{k: data[k] for k in data if k in allowed})
            if not thread:
                _err(handler, "Thread not found", "NOT_FOUND", 404)
                return True
            _json(handler, thread)
            return True

    m = re.match(r"^/facts/([^/]+)$", path)
    if method == "GET" and m:
        fact = mm.db.get_fact_by_topic(m.group(1))
        if not fact:
            _err(handler, "Fact not found", "NOT_FOUND", 404)
            return True
        _json(handler, fact)
        return True

    m = re.match(r"^/images/([^/]+)/(full|thumb|micro)$", path)
    if method == "GET" and m:
        size = m.group(2)
        fp = mm.images.get_image_path(m.group(1), size)
        if not fp.exists():
            _err(handler, "not found", "NOT_FOUND", 404)
            return True
        b = fp.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "image/webp")
        handler.send_header("Content-Length", str(len(b)))
        handler.end_headers()
        handler.wfile.write(b)
        return True

    m = re.match(r"^/tasks/([^/]+)/status$", path)
    if method == "POST" and m:
        from memomind_persona import TASKS

        data = _body_json(handler)
        status = data.get("status")
        if not status:
            _err(handler, "status required", "INVALID_REQUEST")
            return True
        completed_at = mm.db.now_iso() if status == "done" else None
        task = mm.db.update_task(m.group(1), status=status, completed_at=completed_at)
        msg = TASKS["completed"] if status == "done" else TASKS["saved"]
        _json(handler, {"task": task, "persona_message": msg})
        return True

    m = re.match(r"^/tasks/([^/]+)/complete$", path)
    if method == "POST" and m:
        from memomind_persona import TASKS

        task = mm.db.update_task(m.group(1), status="done", completed_at=mm.db.now_iso())
        if not task:
            _err(handler, "Task not found", "NOT_FOUND", 404)
            return True
        _json(handler, {"task": task, "persona_message": TASKS["completed"]})
        return True

    m = re.match(r"^/tasks/([^/]+)$", path)
    if m:
        tid = m.group(1)
        if method == "GET":
            task = mm.db.get_task(tid)
            if not task:
                _err(handler, "Task not found", "NOT_FOUND", 404)
                return True
            task["reminders"] = mm.db.list_reminders_for_parent(tid)
            _json(handler, task)
            return True
        if method == "PUT":
            data = _body_json(handler)
            allowed = (
                "title", "notes", "status", "priority", "due_date", "recurrence", "thread_id",
            )
            task = mm.db.update_task(tid, **{k: data[k] for k in data if k in allowed})
            if not task:
                _err(handler, "Task not found", "NOT_FOUND", 404)
                return True
            _json(handler, task)
            return True
        if method == "DELETE":
            if not mm.db.soft_delete_task(tid):
                _err(handler, "Task not found", "NOT_FOUND", 404)
                return True
            _json(handler, {"deleted": True})
            return True

    m = re.match(r"^/events/([^/]+)$", path)
    if m:
        eid = m.group(1)
        if method == "GET":
            event = mm.db.get_event(eid)
            if not event:
                _err(handler, "Event not found", "NOT_FOUND", 404)
                return True
            event["reminders"] = mm.db.list_reminders_for_parent(eid)
            _json(handler, event)
            return True
        if method == "PUT":
            data = _body_json(handler)
            allowed = (
                "title", "notes", "event_date", "end_date", "location", "all_day", "recurrence",
            )
            event = mm.db.update_event(eid, **{k: data[k] for k in data if k in allowed})
            if not event:
                _err(handler, "Event not found", "NOT_FOUND", 404)
                return True
            _json(handler, event)
            return True
        if method == "DELETE":
            if not mm.db.soft_delete_event(eid):
                _err(handler, "Event not found", "NOT_FOUND", 404)
                return True
            _json(handler, {"deleted": True})
            return True

    m = re.match(r"^/reminders/([^/]+)$", path)
    if m:
        rid = m.group(1)
        if method == "GET":
            _json(handler, {"reminders": mm.db.list_reminders_for_parent(rid)})
            return True
        if method == "PUT":
            data = _body_json(handler)
            allowed = ("offset_minutes", "label", "method", "fire_at")
            reminder = mm.db.update_reminder(rid, **{k: data[k] for k in data if k in allowed})
            if not reminder:
                _err(handler, "Reminder not found", "NOT_FOUND", 404)
                return True
            _json(handler, reminder)
            return True
        if method == "DELETE":
            if not mm.db.delete_reminder(rid):
                _err(handler, "Reminder not found", "NOT_FOUND", 404)
                return True
            _json(handler, {"deleted": True})
            return True

    # ── Simple routes ─────────────────────────────────────────────────────────
    if path == "/health" and method == "GET":
        _json(handler, {"status": "ok", "service": "memomind", "integrated": True})
        return True

    if path == "/status" and method == "GET":
        _json(handler, mm.api.get_status())
        return True

    if path == "/session" and method == "GET":
        _json(handler, mm.api.get_session_info())
        return True

    if path == "/entries" and method == "GET":
        limit = _qs_int(qs, "limit", 50)
        scope = qs.get("scope", [None])[0]
        entries = [mm.db.enrich_entry(e) for e in mm.db.list_entries(limit=limit, scope=scope)]
        _json(handler, {"entries": entries})
        return True

    if path == "/capture" and method == "POST":
        data = _body_json(handler)
        raw = (data.get("input") or "").strip()
        if not raw:
            _err(handler, mm.ERROR["too_vague"], "EMPTY_INPUT")
            return True
        result = mm.capture.build_confirmation(raw, input_type=data.get("type", "text"))
        _json(handler, result)
        return True

    if path == "/capture/confirm" and method == "POST":
        data = _body_json(handler)
        conf_id = data.get("confirmation_id")
        content = (data.get("approved_content") or "").strip()
        if not conf_id or not content:
            _err(handler, "confirmation_id and approved_content required", "INVALID_REQUEST")
            return True
        try:
            result = mm.capture.confirm_capture(
                conf_id,
                content,
                thread_id=data.get("thread_id"),
                scope=data.get("scope", "personal"),
                update_entry_id=data.get("update_entry_id"),
                save_as=data.get("save_as"),
                task_data=data.get("task"),
                event_data=data.get("event"),
                reminders=data.get("reminders"),
            )
            _json(handler, result)
        except ValueError as e:
            _err(handler, str(e), "NOT_FOUND", 404)
        return True

    if path == "/capture/discard" and method == "POST":
        data = _body_json(handler)
        conf_id = data.get("confirmation_id")
        if not conf_id:
            _err(handler, "confirmation_id required", "INVALID_REQUEST")
            return True
        _json(handler, mm.capture.discard_capture(conf_id))
        return True

    if path == "/search" and method == "POST":
        data = _body_json(handler)
        query = (data.get("query") or "").strip()
        scope = data.get("scope", "personal")
        limit = data.get("limit", 100)
        stream = data.get("stream") or qs.get("stream", ["0"])[0] in ("1", "true", "yes")
        if stream:
            handler._start_sse()
            try:
                for event in mm.search.search_stream(query, scope=scope, limit=limit):
                    handler.wfile.write(
                        f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n".encode()
                    )
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return True
        try:
            _json(handler, mm.search.search(query, scope=scope, limit=limit))
        except mm.NoModelFoundError:
            candidates = mm.search.prefilter(query, scope=scope, limit=limit)
            _json(handler, {
                "answer": (
                    mm.COLD_START["no_data"]
                    if mm.db.count_entries() == 0
                    else "I don't have anything on that yet."
                ),
                "confidence": "none",
                "sourced_from": "your records",
                "chunks_processed": 0,
                "total_entries_searched": len(candidates),
                "supporting": [],
                "also_found": [],
                "contradictions": [],
            })
        return True

    if path == "/threads" and method == "GET":
        status_filter = qs.get("status", [None])[0]
        _json(handler, {"threads": mm.db.list_threads(status=status_filter)})
        return True

    if path == "/threads" and method == "POST":
        data = _body_json(handler)
        title = (data.get("title") or "").strip()
        if not title:
            _err(handler, "title required", "INVALID_REQUEST")
            return True
        thread = mm.db.create_thread(title, data.get("summary"))
        _json(handler, thread, 201)
        return True

    if path == "/facts" and method == "GET":
        _json(handler, {"facts": mm.db.list_facts()})
        return True

    if path == "/facts/refresh" and method == "POST":
        mm.brain.refresh_fact_summaries()
        _json(handler, {"refreshed": True, "facts": mm.db.list_facts()})
        return True

    if path == "/voice/transcribe" and method == "POST":
        ct = handler.headers.get("Content-Type", "")
        if ct.startswith("multipart/"):
            fs = _parse_multipart(handler)
            if "audio" in fs:
                f = fs["audio"]
                audio_data = f.file.read() if hasattr(f, "file") else f.value
                filename = getattr(f, "filename", None) or "audio.webm"
            else:
                _err(handler, "audio file required", "INVALID_REQUEST")
                return True
        else:
            n = int(handler.headers.get("Content-Length", 0))
            audio_data = handler.rfile.read(n) if n else b""
            filename = handler.headers.get("X-Audio-Filename", "audio.webm")
        _json(handler, mm.voice.transcribe_audio(audio_data, filename))
        return True

    if path == "/onboarding/status" and method == "GET":
        complete = mm.db.get_meta("onboarding_complete", "false") == "true"
        _json(handler, {
            "onboarding_complete": complete,
            "user_name": mm.db.get_meta("user_name"),
        })
        return True

    if path == "/onboarding/complete" and method == "POST":
        from memomind_config import save_config

        data = _body_json(handler)
        name = (data.get("name") or "").strip()
        if name:
            mm.db.set_meta("user_name", name)
            save_config({"user_name": name})
        mm.db.set_meta("onboarding_complete", "true")
        _json(handler, {"onboarding_complete": True})
        return True

    if path == "/lamp/config" and method == "GET":
        _json(handler, mm.api.LAMP_APP_CONFIG)
        return True

    if path == "/lamp/context" and method == "GET":
        topic = qs.get("topic", [None])[0]
        _json(handler, {"facts": mm.api.get_facts(topic=topic)})
        return True

    if path == "/model" and method == "POST":
        data = _body_json(handler)
        provider = data.get("provider")
        model = data.get("model")
        if not provider:
            _err(handler, "provider is required", "INVALID_REQUEST")
            return True
        try:
            _json(handler, mm.api.set_model(provider, model))
        except ValueError as e:
            _err(handler, str(e), "MODEL_ERROR", 400)
        return True

    if path == "/brain/consolidate" and method == "POST":
        mm.brain.consolidate()
        _json(handler, {"consolidated": True})
        return True

    if path == "/images/upload" and method == "POST":
        fs = _parse_multipart(handler)
        if "image" not in fs:
            _err(handler, "image file required", "INVALID_REQUEST")
            return True
        f = fs["image"]
        caption_hint = fs.getfirst("caption", "") if hasattr(fs, "getfirst") else ""
        suffix = Path(getattr(f, "filename", None) or "upload.jpg").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            if hasattr(f, "file"):
                tmp.write(f.file.read())
            else:
                tmp.write(f.value if isinstance(f.value, bytes) else f.value.encode())
            tmp_path = tmp.name
        entry = mm.db.create_entry(
            content=caption_hint or getattr(f, "filename", None) or "Image",
            entry_type="image",
            staged=False,
        )
        try:
            processed = mm.images.process_image(tmp_path, entry["id"])
            content = processed.get("caption") or processed.get("text") or caption_hint or "Image"
            if processed.get("text"):
                content = f"{content}\n{processed['text']}".strip()
            mm.db.update_entry(entry["id"], content=content)
            mm.db.create_image_record(entry["id"], processed)
            stats = mm.images.get_storage_stats()
            _json(handler, {
                "entry_id": entry["id"],
                "stored": True,
                "persona_message": (
                    mm.IMAGES["extracted"] if processed.get("text") else mm.IMAGES["saved"]
                ),
                "storage": stats,
            }, 201)
        except Exception as e:
            mm.db.soft_delete_entry(entry["id"])
            _err(handler, str(e), "IMAGE_ERROR", 400)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return True

    if path == "/storage/stats" and method == "GET":
        _json(handler, mm.images.get_storage_stats())
        return True

    if path == "/tasks" and method == "GET":
        status = qs.get("status", [None])[0]
        filter_name = qs.get("filter", [None])[0]
        sort = qs.get("sort", ["priority"])[0]
        tasks = mm.db.list_tasks(status=status, filter_name=filter_name, sort=sort)
        for t in tasks:
            t["reminders"] = mm.db.list_reminders_for_parent(t["id"])
        _json(handler, {"tasks": tasks})
        return True

    if path == "/tasks" and method == "POST":
        data = _body_json(handler)
        title = (data.get("title") or "").strip()
        if not title:
            _err(handler, "title required", "INVALID_REQUEST")
            return True
        result = mm.te.create_task_from_confirmation(
            title=title,
            notes=data.get("notes"),
            priority=data.get("priority", "medium"),
            due_date=data.get("due_date"),
            recurrence=data.get("recurrence"),
            reminders=data.get("reminders"),
            thread_id=data.get("thread_id"),
        )
        _json(handler, result, 201)
        return True

    if path == "/events" and method == "GET":
        upcoming = qs.get("upcoming", ["1"])[0] != "0"
        events = mm.db.list_events(upcoming_only=upcoming)
        past = mm.db.list_events_past() if qs.get("include_past") else []
        for ev in events + past:
            ev["reminders"] = mm.db.list_reminders_for_parent(ev["id"])
        _json(handler, {"events": events, "past": past})
        return True

    if path == "/events/upcoming" and method == "GET":
        limit = _qs_int(qs, "limit", 10)
        events = mm.db.list_events(upcoming_only=True, limit=limit)
        for ev in events:
            ev["reminders"] = mm.db.list_reminders_for_parent(ev["id"])
        _json(handler, {"events": events})
        return True

    if path == "/events" and method == "POST":
        data = _body_json(handler)
        title = (data.get("title") or "").strip()
        event_date = data.get("event_date")
        if not title or not event_date:
            _err(handler, "title and event_date required", "INVALID_REQUEST")
            return True
        result = mm.te.create_event_from_confirmation(
            title=title,
            event_date=event_date,
            end_date=data.get("end_date"),
            location=data.get("location"),
            all_day=data.get("all_day", False),
            notes=data.get("notes"),
            recurrence=data.get("recurrence"),
            reminders=data.get("reminders"),
            thread_id=data.get("thread_id"),
        )
        _json(handler, result, 201)
        return True

    if path == "/reminders" and method == "POST":
        data = _body_json(handler)
        parent_id = data.get("parent_id")
        parent_type = data.get("parent_type")
        offset = data.get("offset_minutes")
        fire_at = data.get("fire_at")
        if not all([parent_id, parent_type, offset is not None]):
            _err(handler, "parent_id, parent_type, offset_minutes required", "INVALID_REQUEST")
            return True
        if not fire_at:
            parent = (
                mm.db.get_task(parent_id)
                if parent_type == "task"
                else mm.db.get_event(parent_id)
            )
            due = parent.get("due_date") or parent.get("event_date") if parent else mm.db.now_iso()
            fire_at = mm.te.compute_fire_at(due, int(offset))
        reminder = mm.db.create_reminder(
            parent_id,
            parent_type,
            int(offset),
            fire_at,
            label=data.get("label"),
            method=data.get("method", "notification"),
        )
        _json(handler, reminder, 201)
        return True

    if path == "/reminders/due" and method == "GET":
        minutes = _qs_int(qs, "minutes", 60)
        _json(handler, {"reminders": mm.db.get_reminders_due_soon(minutes)})
        return True

    if path == "/events/stream" and method == "GET":
        import memomind_scheduler as sched
        import queue as queue_mod

        def generate():
            q = sched.sse_subscribe()
            try:
                yield b"event: connected\ndata: {}\n\n"
                while True:
                    try:
                        payload = q.get(timeout=30)
                        yield f"event: reminder\ndata: {json.dumps(payload)}\n\n".encode()
                    except queue_mod.Empty:
                        yield b": keepalive\n\n"
            finally:
                sched.sse_unsubscribe(q)

        handler._start_sse()
        try:
            for chunk in generate():
                handler.wfile.write(chunk)
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    if path == "/shared/push" and method == "POST":
        if not _validate_shared_key(handler):
            return True
        data = _body_json(handler)
        _json(handler, mm.api.receive_shared_entry(data), 201)
        return True

    if path == "/shared/receive" and method == "POST":
        if not _validate_shared_key(handler):
            return True
        data = _body_json(handler)
        _json(handler, mm.api.receive_shared_entry(data), 201)
        return True

    if path in ("/shared/search",) and method in ("GET", "POST"):
        if not _validate_shared_key(handler):
            return True
        if method == "POST":
            data = _body_json(handler)
            query = data.get("query", "")
        else:
            query = qs.get("q", [""])[0]
        _json(handler, mm.search.search(query, scope="shared"))
        return True

    if path == "/shared/entries" and method == "GET":
        if not _validate_shared_key(handler):
            return True
        _json(handler, {"entries": mm.db.list_entries(scope="shared")})
        return True

    return False


def poll_reminders():
    """Fire due MemoMind reminders into Workshop notifications (all users)."""
    _try_import()
    if not _mm:
        return
    import workshop_db as wdb

    try:
        rows = wdb.get_conn().execute("SELECT name FROM users ORDER BY name").fetchall()
    except Exception:
        return
    for row in rows:
        name = row["name"]
        try:
            ensure_user(name)
            due = _mm.db.get_due_reminders()
            for reminder in due:
                parent_type = reminder["parent_type"]
                parent = None
                if parent_type == "task":
                    parent = _mm.db.get_task(reminder["parent_id"])
                elif parent_type == "event":
                    parent = _mm.db.get_event(reminder["parent_id"])
                if not parent:
                    _mm.db.mark_reminder_fired(reminder["id"])
                    continue
                message = _mm.build_reminder_message(reminder, parent)
                title = parent.get("title") or "Reminder"
                _mm.db.mark_reminder_fired(reminder["id"])
                wdb.notif_insert(APP_SLUG, title, message)
                log.info("MemoMind reminder for %s: %s", name, message)
        except Exception as e:
            log.warning("MemoMind reminders for %s: %s", name, e)


def start_reminder_thread():
    global _reminder_thread_started
    if _reminder_thread_started:
        return
    _reminder_thread_started = True

    def loop():
        import time

        while True:
            try:
                poll_reminders()
            except Exception as e:
                log.warning("MemoMind reminder loop: %s", e)
            time.sleep(60)

    t = threading.Thread(target=loop, name="memomind-reminders", daemon=True)
    t.start()
