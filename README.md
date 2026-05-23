# Lamp

**Every home needs a Lamp.** A private, local AI assistant for the household — built on [Workshop](https://github.com/thebreadcat/workshop) and [Tortoise](https://github.com/thebreadcat/tortoise).

Plug in a Raspberry Pi, connect phones over WiFi, and chat + build custom apps without cloud accounts or subscriptions.

## Stack

```
Lamp → Workshop → Tortoise
```

| Layer | Role |
|-------|------|
| **Tortoise** | Chunk-based code generation for slow/local LLMs |
| **Workshop** | Interview + build loop, SQLite data API, ticker |
| **Lamp** | PWA hub, PIN auth, chat, admin, notifications, per-user apps |

## Documentation

| Guide | Audience |
|-------|----------|
| **[QUICKSTART.md](QUICKSTART.md)** | Run Lamp on your Mac, Linux, or PC (Ollama/LM Studio, first login, voice) |
| **[PI-REQUIREMENTS.md](PI-REQUIREMENTS.md)** | Minimum & recommended hardware for Raspberry Pi |
| **[setup/README.md](setup/README.md)** | Pi WiFi onboarding, `first-boot.sh`, systemd |
| **[TESTING.md](TESTING.md)** | Manual QA checklist |

## Requirements (summary)

- Python 3.10+
- [Workshop](https://github.com/thebreadcat/workshop) (git submodule) + [Tortoise](https://github.com/thebreadcat/tortoise)
- Ollama, LM Studio, or another OpenAI-compatible endpoint

See [QUICKSTART.md](QUICKSTART.md) for full desktop setup steps.

## Configuration

Workshop config stays at `~/.workshop/config.json` (endpoint, model, optional API key). Built apps default to `~/workshop-apps/`. Lamp adds auth tables in the same SQLite DB: `~/.workshop/workshop.db`.

## Current status (v0.4.2)

| Phase | Status |
|-------|--------|
| 1 Auth + hub | Done — PIN login, sessions, build, apps |
| 2 Chat | Done — conversations, SSE streaming, build handoff |
| 3 PWA notifications | Done — `#/notifications`, SW polling, nav badge |
| 4 Admin | Done — users, models, storage, system (`#/admin`) |
| 5 Templates | Done — 10 templates on home, one-tap build |
| 6 Pi first-boot | Done — see [setup/README.md](setup/README.md) |

### Raspberry Pi

Read **[PI-REQUIREMENTS.md](PI-REQUIREMENTS.md)** (RAM, storage, [recommended models](https://ollama.com/library), **headless use from phones/PCs**), then provision with [setup/README.md](setup/README.md):

```bash
sudo ./setup/first-boot.sh
# Join Lamp-Setup → captive portal → http://lamp.local:7700 (no monitor on the Pi after this)
```

Before testing, use [TESTING.md](TESTING.md) for a full checklist.

### Recent (v0.4.x)

- **Child accounts** — chat + open apps only; build/templates/admin hidden (server-enforced)
- **Branding** — logo on login/setup, SVG favicon, `assets/lamp-logo.svg`, `scripts/generate-pwa-icons.py`
- **Chat** — adaptive desktop/mobile layout; star, rename, delete; pull-to-refresh
- **Per-chat model** — switch Ollama/LM Studio mid-conversation; history resumes on the new model
- Home **app chips** with initials; shared apps labeled
- Font Awesome Free icons (self-hosted); onboarding tour; pull-to-refresh; notification swipe
- Apps **Shared** / **My apps**; per-app **Clear data**
- Light/dark theme; chat → build handoff; HF import; admin system stats
- Loading spinners on admin, home, apps, chat, login, and notifications while data loads
- **Voice** — [Whisper](https://github.com/openai/whisper) dictation on the server (private, no cloud); browser text-to-speech for read-aloud

### Voice (optional)

Chat can transcribe speech with **OpenAI Whisper** running on the same machine as Lamp (not a cloud API).

```bash
brew install ffmpeg          # macOS
pip install openai-whisper   # or: pip install -r requirements-voice.txt
```

Set model size in `~/.workshop/config.json` (default `tiny` for Pi; `base` or `small` on a Mac):

```json
{ "whisper_model": "tiny" }
```

In chat: tap the **microphone** to record, tap **stop** to transcribe into the message box. The **speaker** icon in the header toggles auto-read for replies (browser TTS). If Whisper is not installed, Lamp falls back to the browser’s built-in dictation where supported.

Check status: `python3 lamp.py --status` (Whisper / ffmpeg line) or Admin → System.

**Pi device testing** is tracked in local `PI-RUNBOOK.md` (gitignored) — run when hardware is ready.

Generate sharper PWA PNGs from the logo: `python3 scripts/generate-pwa-icons.py` (needs `rsvg-convert` or ImageMagick).

Mac smoke test (server running): `./scripts/smoke-test.sh`

## License

[Lamp License](LICENSE) — same terms as [Tortoise](https://github.com/thebreadcat/tortoise/blob/main/LICENSE) and [Workshop](https://github.com/thebreadcat/workshop/blob/main/LICENSE). Free to use and modify; you may not sell the software or offer paid support for the Lamp codebase itself.

UI icons use [Font Awesome Free 6](https://fontawesome.com) (self-hosted under `assets/fontawesome/`; see [assets/fontawesome/LICENSE.txt](assets/fontawesome/LICENSE.txt)).
