"""Lamp auth + chat tables — same DB as Workshop (~/.workshop/workshop.db)."""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import workshop_db as wdb

SESSION_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expires(days: int = SESSION_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def pin_hash(name: str, pin: str) -> str:
    return hashlib.sha256(f"{name}{pin}".encode()).hexdigest()


def init_lamp_tables():
    wdb.init_db()
    conn = wdb.get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            name        TEXT PRIMARY KEY,
            pin_hash    TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'user',
            created_at  TEXT NOT NULL,
            last_login  TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id          TEXT PRIMARY KEY,
            user        TEXT NOT NULL,
            title       TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            convo_id    TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (convo_id) REFERENCES conversations(id)
        );
    """)
    conn.commit()
    for ddl in (
        "ALTER TABLE conversations ADD COLUMN starred INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE conversations ADD COLUMN model TEXT",
        "ALTER TABLE conversations ADD COLUMN endpoint TEXT",
        "ALTER TABLE conversations ADD COLUMN model_handoff INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError:
            pass


def user_count() -> int:
    row = wdb.get_conn().execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return row["n"] if row else 0


def user_list_public() -> list:
    rows = wdb.get_conn().execute(
        "SELECT name, role, last_login FROM users ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def user_create(name: str, pin: str, role: str = "user") -> dict:
    name = name.strip()
    if not name or len(pin) < 4:
        raise ValueError("name and 4-digit PIN required")
    ts = _now()
    try:
        wdb.get_conn().execute(
            "INSERT INTO users (name, pin_hash, role, created_at) VALUES (?,?,?,?)",
            (name, pin_hash(name, pin), role, ts),
        )
        wdb.get_conn().commit()
    except sqlite3.IntegrityError:
        raise ValueError("user already exists")
    return {"name": name, "role": role}


def user_verify(name: str, pin: str) -> dict | None:
    row = wdb.get_conn().execute(
        "SELECT name, pin_hash, role FROM users WHERE name=?", (name.strip(),)
    ).fetchone()
    if not row or row["pin_hash"] != pin_hash(name, pin):
        return None
    ts = _now()
    wdb.get_conn().execute(
        "UPDATE users SET last_login=? WHERE name=?", (ts, row["name"])
    )
    wdb.get_conn().commit()
    return {"name": row["name"], "role": row["role"]}


def session_create(user: str) -> str:
    token = secrets.token_urlsafe(32)
    ts = _now()
    wdb.get_conn().execute(
        "INSERT INTO sessions (token, user, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user, ts, _expires()),
    )
    wdb.get_conn().commit()
    return token


def session_check(token: str) -> dict | None:
    if not token:
        return None
    row = wdb.get_conn().execute(
        """SELECT s.user, u.role FROM sessions s
           JOIN users u ON u.name = s.user
           WHERE s.token=? AND s.expires_at > ?""",
        (token, _now()),
    ).fetchone()
    return {"name": row["user"], "role": row["role"]} if row else None


def session_delete(token: str):
    if token:
        wdb.get_conn().execute("DELETE FROM sessions WHERE token=?", (token,))
        wdb.get_conn().commit()


def ensure_user_apps_dir(name: str, cfg_apps_dir: Path):
    (cfg_apps_dir / "users" / name).mkdir(parents=True, exist_ok=True)


# ── conversations / messages ───────────────────────────────────────────────────

def convo_create(user: str, title: str = None) -> dict:
    cid = secrets.token_urlsafe(12)
    ts = _now()
    wdb.get_conn().execute(
        """INSERT INTO conversations (id, user, title, created_at, updated_at)
           VALUES (?,?,?,?,?)""",
        (cid, user, title, ts, ts),
    )
    wdb.get_conn().commit()
    return {
        "id": cid,
        "title": title,
        "starred": False,
        "created_at": ts,
        "updated_at": ts,
    }


def convo_list(user: str) -> list:
    rows = wdb.get_conn().execute(
        """SELECT id, title, starred, created_at, updated_at FROM conversations
           WHERE user=? ORDER BY starred DESC, updated_at DESC LIMIT 100""",
        (user,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["starred"] = bool(d.get("starred"))
        out.append(d)
    return out


def convo_get(cid: str, user: str) -> dict | None:
    row = wdb.get_conn().execute(
        """SELECT id, user, title, starred, model, endpoint, model_handoff,
                  created_at, updated_at
           FROM conversations WHERE id=? AND user=?""",
        (cid, user),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["starred"] = bool(d.get("starred"))
    d["model_handoff"] = bool(d.get("model_handoff"))
    return d


def convo_chat_cfg(global_cfg: dict, convo: dict) -> dict:
    """Endpoint/model for this chat: per-conversation override or home default."""
    cfg = dict(global_cfg)
    if convo.get("endpoint"):
        cfg["endpoint"] = convo["endpoint"]
    if convo.get("model"):
        cfg["model"] = convo["model"]
    return cfg


def convo_take_handoff(cid: str) -> bool:
    row = wdb.get_conn().execute(
        "SELECT model_handoff FROM conversations WHERE id=?", (cid,)
    ).fetchone()
    if not row or not row["model_handoff"]:
        return False
    wdb.get_conn().execute(
        "UPDATE conversations SET model_handoff=0 WHERE id=?", (cid,)
    )
    wdb.get_conn().commit()
    return True


def convo_set_model(cid: str, user: str, endpoint: str, model: str) -> dict | None:
    convo = convo_get(cid, user)
    if not convo:
        return None
    endpoint = (endpoint or "").strip()
    model = (model or "").strip()
    if not endpoint or not model:
        raise ValueError("endpoint and model required")
    changed = convo.get("endpoint") != endpoint or convo.get("model") != model
    ts = _now()
    wdb.get_conn().execute(
        """UPDATE conversations
           SET endpoint=?, model=?, model_handoff=?, updated_at=?
           WHERE id=? AND user=?""",
        (endpoint, model, 1 if changed else 0, ts, cid, user),
    )
    wdb.get_conn().commit()
    if changed:
        short = model.split("/")[-1] if "/" in model else model
        msg_add(cid, "system", f"Switched to {short} — continuing this conversation.")
    return convo_get(cid, user)


def convo_clear_model(cid: str, user: str) -> dict | None:
    convo = convo_get(cid, user)
    if not convo:
        return None
    had_override = bool(convo.get("model") or convo.get("endpoint"))
    ts = _now()
    wdb.get_conn().execute(
        """UPDATE conversations
           SET endpoint=NULL, model=NULL, model_handoff=?, updated_at=?
           WHERE id=? AND user=?""",
        (1 if had_override else 0, ts, cid, user),
    )
    wdb.get_conn().commit()
    if had_override:
        msg_add(cid, "system", "Using the home default model for this chat.")
    return convo_get(cid, user)


def convo_touch(cid: str, title: str = None):
    ts = _now()
    if title:
        wdb.get_conn().execute(
            "UPDATE conversations SET updated_at=?, title=? WHERE id=?",
            (ts, title[:60], cid),
        )
    else:
        wdb.get_conn().execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid)
        )
    wdb.get_conn().commit()


def convo_update(
    cid: str,
    user: str,
    title: str = None,
    starred: bool = None,
    model: str = None,
    endpoint: str = None,
    use_default: bool = False,
) -> bool:
    if use_default:
        return convo_clear_model(cid, user) is not None
    if model is not None and endpoint is not None:
        return convo_set_model(cid, user, endpoint, model) is not None
    if not convo_get(cid, user):
        return False
    ts = _now()
    if title is not None:
        title = title.strip()[:120] or None
        wdb.get_conn().execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user=?",
            (title, ts, cid, user),
        )
    if starred is not None:
        wdb.get_conn().execute(
            "UPDATE conversations SET starred=?, updated_at=? WHERE id=? AND user=?",
            (1 if starred else 0, ts, cid, user),
        )
    wdb.get_conn().commit()
    return True


def convo_delete(cid: str, user: str) -> bool:
    cur = wdb.get_conn().execute(
        "DELETE FROM conversations WHERE id=? AND user=?", (cid, user)
    )
    wdb.get_conn().execute("DELETE FROM messages WHERE convo_id=?", (cid,))
    wdb.get_conn().commit()
    return cur.rowcount > 0


def msg_list(cid: str) -> list:
    rows = wdb.get_conn().execute(
        """SELECT role, content, created_at FROM messages
           WHERE convo_id=? ORDER BY id""",
        (cid,),
    ).fetchall()
    return [dict(r) for r in rows]


def msg_add(cid: str, role: str, content: str) -> dict:
    ts = _now()
    wdb.get_conn().execute(
        "INSERT INTO messages (convo_id, role, content, created_at) VALUES (?,?,?,?)",
        (cid, role, content, ts),
    )
    wdb.get_conn().commit()
    return {"role": role, "content": content, "created_at": ts}


def chat_count(user: str) -> int:
    row = wdb.get_conn().execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE user=?", (user,)
    ).fetchone()
    return row["n"] if row else 0


def chats_clear_older_than(days: int, user: str = None) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = wdb.get_conn()
    if user:
        rows = conn.execute(
            "SELECT id FROM conversations WHERE user=? AND updated_at < ?",
            (user, cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM conversations WHERE updated_at < ?", (cutoff,)
        ).fetchall()
    n = 0
    for r in rows:
        conn.execute("DELETE FROM messages WHERE convo_id=?", (r["id"],))
        conn.execute("DELETE FROM conversations WHERE id=?", (r["id"],))
        n += 1
    conn.commit()
    return n


# ── admin user management ────────────────────────────────────────────────────────

def user_get(name: str) -> dict | None:
    row = wdb.get_conn().execute(
        "SELECT name, role, created_at, last_login FROM users WHERE name=?", (name,)
    ).fetchone()
    return dict(row) if row else None


def user_update(name: str, role: str = None, pin: str = None) -> bool:
    if role:
        wdb.get_conn().execute(
            "UPDATE users SET role=? WHERE name=?", (role, name)
        )
    if pin:
        wdb.get_conn().execute(
            "UPDATE users SET pin_hash=? WHERE name=?",
            (pin_hash(name, pin), name),
        )
    wdb.get_conn().commit()
    return True


def user_delete(name: str) -> bool:
    conn = wdb.get_conn()
    rows = conn.execute(
        "SELECT id FROM conversations WHERE user=?", (name,)
    ).fetchall()
    for r in rows:
        conn.execute("DELETE FROM messages WHERE convo_id=?", (r["id"],))
    conn.execute("DELETE FROM conversations WHERE user=?", (name,))
    conn.execute("DELETE FROM sessions WHERE user=?", (name,))
    cur = conn.execute("DELETE FROM users WHERE name=?", (name,))
    conn.commit()
    return cur.rowcount > 0
