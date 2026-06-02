"""Lamp chat — LLM calls and response parsing (stdlib only)."""

import json
import re
import urllib.error
import urllib.request

from workshop import call_llm

LAMP_SYSTEM = """You are Lamp, a helpful AI assistant running privately on this family's home device.
You are friendly, concise, and practical. You help with everyday tasks: homework,
meal planning, writing messages, answering questions, brainstorming ideas.

If someone describes a problem that would be better solved by a persistent app
(reminders, trackers, lists, tools), offer to build one. When you do, include a
JSON block at the end of your message:

```json
{"app_idea": true, "description": "what the app would do"}
```

The user never sees this JSON. The interface will show a "Build this" button.
If the user says they do not want to build an app, acknowledge that and continue
the conversation normally. Do not include app_idea JSON again unless they ask for it.

Keep responses short (2-4 sentences) unless the user asks for detail.
Do not mention that you are running on a Pi or local device unless asked.

When the user is saving something to Memory and a prior note might conflict, ask in plain
language (one short question) instead of sounding like a system error.

When the user links chat threads, you may see messages tagged [From chat "…"] from another
thread. Treat them as part of this conversation. Recall facts they stated there (names,
passwords used for tests, preferences) when they ask — this is their private home assistant,
not a shared cloud service.

If they tell you a test password or code in chat, remember it and answer when they ask
later, including after threads are linked."""


def parse_chat_response(text: str) -> dict:
    """Return {reply, app_idea} with JSON stripped from visible text."""
    display = text
    app_idea = None

    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            data = json.loads(block)
            if data.get("app_idea"):
                app_idea = {
                    "app_idea": True,
                    "description": data.get("description") or "",
                }
                display = text[: text.find("```")].strip()
        except json.JSONDecodeError:
            pass

    if app_idea is None:
        for anchor in ('"app_idea"',):
            pos = text.rfind(anchor)
            if pos == -1:
                continue
            start = text.rfind("{", 0, pos)
            if start == -1:
                continue
            depth, end = 0, -1
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                try:
                    data = json.loads(text[start:end])
                    if data.get("app_idea"):
                        app_idea = {
                            "app_idea": True,
                            "description": data.get("description") or "",
                        }
                        display = (text[:start] + text[end:]).strip()
                except json.JSONDecodeError:
                    pass

    # Remove only app_idea metadata blocks, not arbitrary JSON/code examples.
    display = re.sub(
        r"```(?:json)?\s*\{[^`]*\"app_idea\"[^`]*\}\s*```",
        "",
        display,
        flags=re.S,
    ).strip()
    if not display:
        raw = (text or "").strip()
        if raw and not app_idea:
            display = raw
        elif raw and app_idea:
            display = re.sub(
                r"```(?:json)?\s*\{[^`]*\"app_idea\"[^`]*\}\s*```",
                "",
                raw,
                flags=re.S,
            ).strip() or (
                "I can build this if you want, or we can just keep talking."
            )
        else:
            display = (
                "I can build this if you want, or we can just keep talking."
                if app_idea
                else "Tell me a bit more and I can help."
            )
    return {"reply": display, "app_idea": app_idea}


LINKED_CONTEXT_NOTE = (
    "\n\n[Linked chats: this thread shares context with other chats on this home device. "
    "The message history may include lines tagged [From chat \"…\"] from those threads. "
    "Use all of it — when the user asks about something said in a linked chat, answer from "
    "that history.]"
)


MODEL_HANDOFF_NOTE = (
    "\n\n[The language model serving this chat was just changed. "
    "Continue the conversation using the full message history below. "
    "Do not mention the model switch unless the user asks.]"
)


def mind_contradiction_assistant_message(existing_content: str) -> str:
    """Natural-language prompt when a new memory may contradict an older one."""
    existing = (existing_content or "").strip()
    if len(existing) > 200:
        existing = existing[:197] + "…"
    return (
        f'Just checking — you previously noted: "{existing}". '
        "Is this an update, or something different?"
    )


def mind_contradiction_from_confirmation(confirmation: dict) -> str | None:
    """
    Return a chat-ready assistant message when confirmation needs contradiction resolution.
    Works with normalized or raw MemoMind capture payloads.
    """
    if not confirmation:
        return None
    gate = confirmation.get("gate") or {}
    conflict = confirmation.get("conflict") or {}
    contradictions = confirmation.get("contradictions") or []
    conflict_type = gate.get("conflict_type") or conflict.get("type") or conflict.get("kind")
    if gate.get("has_contradiction") or conflict_type == "contradiction" or contradictions:
        first = contradictions[0] if contradictions else conflict
        existing = (first or {}).get("existing_content") or conflict.get("existing_content")
        if existing:
            return mind_contradiction_assistant_message(existing)
    return None


def stream_chat(cfg: dict, messages: list, write_sse, system: str = None):
    """
    Stream tokens via write_sse(dict). Falls back to single response if streaming fails.
    write_sse receives dicts like {t: token, text: ...} or {t: done, reply, app_idea}.
    """
    sys_prompt = system if system is not None else LAMP_SYSTEM
    url = cfg["endpoint"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 900,
        "stream": True,
        "messages": [{"role": "system", "content": sys_prompt}] + messages,
    }).encode()

    full = []
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = (
                    chunk.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content")
                )
                if delta:
                    full.append(delta)
                    write_sse({"t": "token", "text": delta})
        text = "".join(full)
        parsed = parse_chat_response(text)
        write_sse({
            "t": "done",
            "reply": parsed["reply"],
            "app_idea": parsed["app_idea"],
            "raw": text,
        })
        return parsed
    except Exception:
        text = call_llm(cfg, messages, max_tokens=900, system=sys_prompt)
        parsed = parse_chat_response(text)
        write_sse({"t": "token", "text": parsed["reply"]})
        write_sse({
            "t": "done",
            "reply": parsed["reply"],
            "app_idea": parsed["app_idea"],
            "raw": text,
        })
        return parsed
