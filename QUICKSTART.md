# Lamp — Quickstart (Mac / Linux / Windows)

Run Lamp on your own computer in a few minutes. Everything stays local — no cloud account required.

## Easy install (one command)

**Mac or Linux** — installs Python (if needed), downloads Lamp + Workshop + Tortoise (no Git required), installs Ollama, pulls a RAM-sized model, writes `~/.workshop/config.json`, and starts the server:

```bash
curl -fsSL https://raw.githubusercontent.com/thebreadcat/lamp-ai/main/setup/install.sh | bash
```

**Windows** — download [setup/install.bat](setup/install.bat) and double-click, or in PowerShell:

```powershell
irm https://raw.githubusercontent.com/thebreadcat/lamp-ai/main/setup/install.ps1 | iex
```

When it finishes, open **https://localhost:7700** on this computer. On a phone or tablet on the same Wi‑Fi, **scan the QR code** in the terminal or on the login screen. Accept the browser’s security warning once (self-signed certificate), then create your admin name and PIN. **HTTPS is included automatically** so the microphone works on phones — no extra setup.

Optional environment variables:

| Variable | Effect |
|----------|--------|
| `LAMP_INSTALL_DIR` | Install location (default `~/lamp`) |
| `LAMP_HOST=127.0.0.1` | Localhost only (no phone/tablet access) |
| `LAMP_NO_TLS=1` | HTTP only — microphone on phones will not work |
| `LAMP_SKIP_OLLAMA=1` | Skip Ollama install and model pull |
| `LAMP_START=0` | Setup only; start manually with `python3 lamp.py` |

Manual setup (Git, submodules, Tortoise) is below if you prefer the developer path.

---

## What you need

| Requirement | Notes |
|-------------|--------|
| **Python 3.10+** | `python3 --version` |
| **Git** | To clone Lamp and submodules |
| **A local LLM** | [Ollama](https://ollama.com) (easiest) or [LM Studio](https://lmstudio.ai) |
| **~2 GB free disk** | More if you pull large models or build many apps |

Optional: **ffmpeg** + **openai-whisper** for voice dictation ([details below](#optional-voice-dictation)).

---

## 1. Get the code

```bash
git clone https://github.com/thebreadcat/lamp.git
cd lamp
git submodule update --init --recursive
```

Tortoise (the app builder) is not bundled in the submodule — clone it once:

```bash
git clone --depth 1 https://github.com/thebreadcat/tortoise.git vendor/workshop/vendor/tortoise
```

Or point to an existing install:

```bash
export TORTOISE_PATH=/path/to/tortoise/tortoise.py
```

Preflight check (optional):

```bash
./setup/preflight.sh
```

---

## 2. Start a local model

### Option A — Ollama (recommended)

Install from **[ollama.com](https://ollama.com)**. Browse all models at **[ollama.com/library](https://ollama.com/library)**.

```bash
ollama pull qwen2.5:3b    # good default on 8–16 GB RAM Mac/PC
ollama serve              # usually runs automatically
```

**Recommended models (desktop / laptop)**

| Your RAM | Good defaults | Stronger (if you have 16 GB+ RAM) |
|----------|---------------|-----------------------------------|
| **8 GB** | [`qwen2.5:3b`](https://ollama.com/library/qwen2.5), [`llama3.2:3b`](https://ollama.com/library/llama3.2) | [`qwen2.5:7b`](https://ollama.com/library/qwen2.5) |
| **16 GB+** | [`qwen2.5:7b`](https://ollama.com/library/qwen2.5), [`mistral:7b`](https://ollama.com/library/mistral) | [`llama3.1:8b`](https://ollama.com/library/llama3.1), [`deepseek-r1:7b`](https://ollama.com/library/deepseek-r1) |
| **Coding focus** | — | [`deepseek-coder:6.7b`](https://ollama.com/library/deepseek-coder), [`codellama:7b`](https://ollama.com/library/codellama) |

Lamp → **Admin → Models** lists popular models and can pull them for you. The in-app list matches `data/ollama-popular.json`.

### Option B — LM Studio

1. Install LM Studio and load a model.
2. Enable the **local server** (OpenAI-compatible API, default port `1234`).
3. Note the model name shown in LM Studio.

---

## 3. Run Lamp

```bash
python3 lamp.py
```

Open **http://localhost:7700** in your browser (Chrome, Safari, or Firefox).

Health check without starting the server:

```bash
python3 lamp.py --status
```

You should see Tortoise ✓ and your configured endpoint. Port **7700** must be free (`lsof -ti :7700` if something else is using it).

---

## 4. First-time setup in the browser

1. **Create admin** — pick a name and 4-digit PIN (this device’s owner).
2. **Set up model** (admin only) — home banner → **Set up**, or go to `#/setup-model`.
   - Lamp scans for Ollama / LM Studio, or enter manually:
   - Ollama: `http://localhost:11434/v1` + model name e.g. `qwen2.5:3b`
   - LM Studio: `http://localhost:1234/v1` + your loaded model id
3. **Chat** — send a message; you should get a streaming reply.
4. **Build** — try a template on the home screen or **Build something new**.

Add family members later: **Admin → Users**.

---

## 5. Verify (optional)

With the server running:

```bash
./scripts/smoke-test.sh
```

Manual checklist: [TESTING.md](TESTING.md).

---

## Updating Lamp

Admins see an **Update available** banner on the home screen when a newer version is on GitHub.

1. Stop Lamp (Ctrl+C in the terminal where it runs)
2. Run from your Lamp folder:

```bash
python3 lamp.py --update
```

Or: `./setup/update.sh`

3. Restart Lamp (`python3 lamp.py --host 0.0.0.0` or `sudo systemctl restart lamp` on a Pi)

Your chats, users, config, and apps in `~/.workshop` are **not** touched — only the Lamp program files update.

Bump the **`VERSION`** file in the repo when you ship a release so clients can detect it.

---

## Optional: voice dictation

Local speech-to-text uses [Whisper](https://github.com/openai/whisper) on the same machine (not a cloud API).

```bash
# macOS
brew install ffmpeg
pip install -r requirements-voice.txt

# Linux (Debian/Ubuntu)
sudo apt install ffmpeg
pip install -r requirements-voice.txt
```

Restart Lamp, then in chat use the **microphone** button. Check **Admin → System** or `python3 lamp.py --status` for `whisper: OK`.

Optional in `~/.workshop/config.json`:

```json
{ "whisper_model": "tiny" }
```

Use `tiny` on low-RAM machines; `base` or `small` on a desktop Mac for better accuracy.

### Voice over Wi‑Fi (phone → Mac / Pi)

Browsers **only allow the microphone on secure pages**: `https://…` or `http://localhost` on the same device. Opening `http://192.168.x.x:7700` from your phone will **not** show a permission prompt — dictation is blocked by the browser, not Lamp.

**Fix:** serve Lamp with HTTPS on your LAN:

```bash
./setup/generate-lamp-cert.sh          # writes ~/.workshop/lamp-cert.pem
python3 lamp.py --host 0.0.0.0 --tls
```

On your phone, open the **`https://`** URL from the startup banner (e.g. `https://192.168.0.160:7700`). Accept the self-signed certificate warning once, then the mic button works.

Read-aloud (text-to-speech) usually still works over plain HTTP; only **speech-to-text** needs HTTPS off-localhost.

---

## Optional: install as a PWA

In Chrome or Safari: **Add to Home Screen** / **Install app**. Lamp works offline for the shell; chat and build still need the local server and model running.

---

## Where data lives

| Data | Path |
|------|------|
| Config (model, endpoint, API key) | `~/.workshop/config.json` |
| Users, chats, app DB | `~/.workshop/workshop.db` |
| Built apps | `~/workshop-apps/` (default) |

These paths are on **your machine only** — they are not in the git repo.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Address already in use` | Another Lamp is running: `lsof -ti :7700 \| xargs kill` then restart |
| Chat says not configured | Admin → set model, or `#/setup-model` |
| Build fails / no Tortoise | Clone Tortoise (step 1) or set `TORTOISE_PATH` |
| Model errors | Confirm Ollama/LM Studio is running; test `curl http://localhost:11434/api/tags` |
| Voice: ffmpeg not found | Install ffmpeg and restart Lamp |
| Static files 401 | Restart `python3 lamp.py` after pulling updates |

---

## Next steps

- **Raspberry Pi home device** → [PI-REQUIREMENTS.md](PI-REQUIREMENTS.md) + [setup/README.md](setup/README.md)
- **Full feature checklist** → [TESTING.md](TESTING.md)
- **Project overview** → [README.md](README.md)
