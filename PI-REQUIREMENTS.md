# Lamp — Raspberry Pi requirements

Minimum and recommended hardware/software for running Lamp as a **home appliance** (WiFi setup, local LLM, family phones on the LAN).

For step-by-step provisioning, see [setup/README.md](setup/README.md). For trying Lamp on a laptop first, see [QUICKSTART.md](QUICKSTART.md).

---

## Hardware

| | Minimum | Recommended |
|---|---------|-------------|
| **Board** | Raspberry Pi 4 (2 GB RAM) | Raspberry Pi 4 (4–8 GB) or **Pi 5 (4 GB+)** |
| **Storage** | 32 GB microSD (or USB SSD) | 64 GB+ SSD boot (faster, more room for models) |
| **Power** | Official Pi PSU for your model | Same — avoid underpowered USB chargers |
| **Network** | 2.4 GHz WiFi (built-in) | 5 GHz WiFi or Ethernet for initial setup |
| **Cooling** | Heatsink | Active fan / case — Ollama loads the CPU during chat & builds |

Lamp does **not** require a monitor or keyboard after first setup; you use a phone/laptop on the same WiFi.

### Not supported as a target (for now)

- Pi 3 / Zero — insufficient RAM for Ollama + Lamp + builds
- Less than **2 GB RAM** — use a desktop with [QUICKSTART.md](QUICKSTART.md) instead

---

## RAM and model size

First-boot picks an Ollama model from total RAM (`setup/first-boot.sh`):

| Device RAM | Default model | Typical use |
|--------------|---------------|-------------|
| **&lt; 3 GB** | `qwen2.5:1.5b` | Chat, light apps; slower builds |
| **3–7 GB** | `qwen2.5:3b` | Good balance on Pi 4 4 GB |
| **8 GB+** | `qwen2.5:7b` | Better replies; leave headroom for builds |

You can change the model anytime in Lamp → **Admin → Models** (shows RAM-aware suggestions and can pull models). Larger models need more RAM and disk; if the Pi swaps or OOMs, drop to a smaller model.

**Rule of thumb:** model weights ≈ **1–5 GB** on disk depending on size; keep **≥ 4 GB free** beyond the OS for apps and SQLite.

### Recommended models (Pi)

Browse the full catalog at **[ollama.com/library](https://ollama.com/library)**. These are tuned for Lamp on a Pi (chat + light app building):

| RAM | First-boot default | Also good on Pi |
|-----|-------------------|-----------------|
| **&lt; 3 GB** | [`qwen2.5:1.5b`](https://ollama.com/library/qwen2.5) | [`llama3.2:1b`](https://ollama.com/library/llama3.2), [`phi3:mini`](https://ollama.com/library/phi3) |
| **3–7 GB** | [`qwen2.5:3b`](https://ollama.com/library/qwen2.5) | [`gemma2:2b`](https://ollama.com/library/gemma2), [`llama3.2:3b`](https://ollama.com/library/llama3.2) |
| **8 GB+** | [`qwen2.5:7b`](https://ollama.com/library/qwen2.5) | [`mistral:7b`](https://ollama.com/library/mistral), [`llama3.1:8b`](https://ollama.com/library/llama3.1) |

Avoid multi‑GB “desktop only” models on a 2–4 GB Pi. Reasoning-heavy models (e.g. `deepseek-r1`) are slow on Pi hardware.

---

## Using Lamp without a monitor or keyboard (headless appliance)

**Yes — that is the intended Pi setup.** After you flash the SD card and run first-boot once (SSH from another machine is fine; no HDMI required), the Pi is meant to live in a closet and be used only from phones, tablets, and laptops on your home WiFi.

| Phase | What you use | Pi needs |
|-------|----------------|----------|
| **WiFi onboarding** | Phone joins hotspot **Lamp-Setup** → captive portal picks home WiFi | Power + SD only |
| **Daily use** | Browser or “Add to Home Screen” PWA at **`http://lamp.local:7700`** | Nothing attached |
| **Admin / models** | Same URL → **Admin** (PIN) | Nothing attached |

How it works technically:

- **`lamp.service`** binds Lamp to **`0.0.0.0:7700`** so any device on the LAN can reach the UI (not just localhost).
- **Avahi** advertises **`lamp.local`** so you rarely need to remember the Pi’s IP.
- **Ollama** runs as a system service on the Pi; the browser never talks to Ollama directly — only Lamp does.
- **PIN login** per family member; optional child accounts with restricted UI.

**Tips for families**

1. On iPhone/Android: open `http://lamp.local:7700` → use the browser’s **Add to Home Screen** for an app-like icon (Lamp is a PWA).
2. If `lamp.local` does not resolve (some routers block mDNS), use **`http://<pi-ip>:7700`** from **Admin → System** on any device that already works, or your router’s DHCP list.
3. The Pi does **not** need to stay on the **Lamp-Setup** hotspot after setup — it joins your normal WiFi and stays there across reboots (`systemd` starts Lamp automatically).

You only need a monitor/keyboard if you prefer typing on the Pi itself during troubleshooting — not for normal use.

---

## Storage budget

| Component | Approximate size |
|-----------|------------------|
| Raspberry Pi OS (64-bit) | ~8–12 GB |
| Ollama + `qwen2.5:1.5b` | ~1 GB |
| Ollama + `qwen2.5:3b` | ~2 GB |
| Ollama + `qwen2.5:7b` | ~4–5 GB |
| Lamp install (`/opt/lamp`) | ~50–100 MB |
| Built apps + database | Grows with use (plan **5–20 GB** for a household) |

**Minimum SD:** 32 GB tight; **64 GB+** recommended if you build several apps or pull multiple models.

---

## Software

| Requirement | Notes |
|-------------|--------|
| **OS** | Raspberry Pi OS **64-bit** (Bookworm or newer) |
| **NetworkManager** | `nmcli` — default on Pi OS; used for WiFi captive portal |
| **Python** | 3.10+ (included on Pi OS) |
| **Ollama** | Installed automatically by `setup/first-boot.sh` |
| **Git** | Clone Lamp / Tortoise during install |
| **Avahi** | `lamp.local` mDNS (installed by first-boot) |

Optional packages (installed by first-boot when possible): `qrencode` (setup QR codes).

---

## Network

- **First boot:** Pi creates hotspot **Lamp-Setup** (password `lamplight`) for WiFi onboarding.
- **After setup:** Pi joins your home WiFi; phones/PCs reach **`http://lamp.local:7700`** (or the Pi’s IP).
- **Internet** required during first boot (Ollama install, `git clone`, model pull).
- **No inbound ports** from the internet required — LAN only.

---

## What runs on the Pi

| Service | Port | Purpose |
|---------|------|---------|
| **Lamp** | 7700 | Web UI + API (PIN auth, chat, build, admin) |
| **Ollama** | 11434 | Local LLM |
| **Captive portal** | 80 | WiFi setup only (first boot) |
| **Avahi** | mDNS | `lamp.local` hostname |

---

## Optional features on Pi

| Feature | Extra requirements | Pi notes |
|---------|-------------------|----------|
| **Voice (Whisper)** | `ffmpeg`, `pip install openai-whisper` | Use `whisper_model: "tiny"` in config; first run is slow; needs extra RAM/CPU |
| **Multiple users** | None | Same as desktop; PINs stored in local SQLite |
| **Child accounts** | None | Enforced in UI + API |
| **Building apps** | Tortoise + disk space | Slow on Pi 4; works best with smaller models and simple templates |

Voice and large-model chat are **optional** — core Lamp works without them.

---

## Performance expectations (realistic)

| Task | Pi 4 (4 GB) | Pi 5 |
|------|-------------|------|
| Login / UI | Snappy | Snappy |
| Chat (3b model) | Usable, a few sec to first token | Faster |
| Chat (7b model) | Heavier; may stutter under load | Good |
| Template build | Several minutes | Shorter |
| Whisper transcribe | 5–30+ sec per message (`tiny`) | Faster |

For development and heavy building, use [QUICKSTART.md](QUICKSTART.md) on a Mac/PC and deploy to the Pi when ready.

---

## Quick provision checklist

1. Flash **Pi OS 64-bit** to SD/SSD.
2. Copy or clone Lamp to the Pi (or let first-boot clone from GitHub).
3. Run: `sudo ./setup/first-boot.sh`
4. Join **Lamp-Setup** → configure home WiFi in the portal.
5. Wait for Ollama + model pull + install (can take **15–45 minutes** on first run).
6. Open **http://lamp.local:7700** → create admin PIN.
7. Confirm **Admin → System** shows Ollama OK and expected model.

Details and flags (`--install-only`, `--wifi-only`, etc.): [setup/README.md](setup/README.md).

---

## Related docs

- [QUICKSTART.md](QUICKSTART.md) — run on your computer first
- [setup/README.md](setup/README.md) — provisioning commands & troubleshooting
- [TESTING.md](TESTING.md) — feature checklist after install
- [README.md](README.md) — architecture and status
