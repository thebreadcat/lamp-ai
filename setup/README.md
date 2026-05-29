# Lamp — Raspberry Pi setup

Provision a Pi as a home Lamp device: WiFi onboarding, Ollama, mDNS, and systemd.

**Hardware & model sizing:** [PI-REQUIREMENTS.md](../PI-REQUIREMENTS.md)  
**Try on a computer first:** [QUICKSTART.md](../QUICKSTART.md)

## Desktop one-command install (Mac / Linux / Windows)

| Platform | Command |
|----------|---------|
| **macOS / Linux** | `curl -fsSL https://raw.githubusercontent.com/thebreadcat/lamp-ai/main/setup/install.sh \| bash` |
| **Windows** | Double-click `setup/install.bat`, or `irm …/setup/install.ps1 \| iex` (see [QUICKSTART.md](../QUICKSTART.md)) |

The installer:

- Uses **zip downloads** when Git is not installed (no submodules required for end users)
- Installs **Ollama** and pulls a model sized to your RAM (`qwen2.5:3b` on 8 GB, `qwen2.5:7b` on 16 GB+)
- Creates a **self-signed HTTPS certificate** and starts **`python3 lamp.py --host 0.0.0.0`** (TLS automatic on the network)
- Writes **`~/.workshop/config.json`** so you can skip in-browser model setup

From an existing clone: `./setup/install.sh` (uses the current directory instead of re-downloading).

## Requirements (short)

- Raspberry Pi 4 (2 GB+) or Pi 5 — see [PI-REQUIREMENTS.md](../PI-REQUIREMENTS.md) for RAM/model guidance
- Raspberry Pi OS (64-bit Bookworm recommended)
- NetworkManager (`nmcli`) — default on Pi OS
- Internet during first boot (for Ollama + git clone)

## Preflight (Mac or Pi, before copy)

```bash
./setup/preflight.sh
```

Checks Python sources, workshop/tortoise vendor paths, and `first-boot.sh` syntax.

## Quick provision (on the Pi)

Copy or clone Lamp onto the Pi, then:

```bash
cd /path/to/lamp
sudo ./setup/first-boot.sh
```

1. Pi creates WiFi hotspot **Lamp-Setup** (password: `lamplight`)
2. On your phone: join **Lamp-Setup**, open the captive portal (or http://10.42.0.1)
3. Scan QR / pick your home WiFi and enter password
4. Script installs Ollama, pulls a RAM-sized model, installs Lamp to `/opt/lamp`, starts services
5. Open **http://lamp.local:7700** and create the admin account

## Commands

| Command | Purpose |
|---------|---------|
| `sudo ./setup/first-boot.sh` | Full setup (WiFi portal + install) |
| `sudo ./setup/first-boot.sh --continue` | Install only (after WiFi portal finished) |
| `sudo ./setup/first-boot.sh --wifi-only` | Run captive portal only |
| `sudo ./setup/first-boot.sh --install-only` | Skip WiFi (already on network) |
| `sudo ./setup/first-boot.sh --status` | Show provision state |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LAMP_INSTALL_DIR` | `/opt/lamp` | Install path |
| `LAMP_REPO` | GitHub lamp URL | Clone source if not copying locally |
| `LAMP_USER` | `pi` | Unix user running Lamp |
| `LAMP_SETUP_SSID` | `Lamp-Setup` | Hotspot name |
| `LAMP_SETUP_PASS` | `lamplight` | Hotspot password |

## Services

- **`lamp.service`** — Lamp HTTP server on port 7700 (`0.0.0.0`)
- **`lamp-setup.service`** — Optional one-shot first boot (enable manually)
- **`avahi-daemon`** — Resolves `lamp.local`

```bash
sudo cp setup/lamp.service /etc/systemd/system/
sudo systemctl enable --now lamp
```

## Test captive portal on your Mac (dev)

No WiFi changes — UI only:

```bash
python3 setup/captive-portal.py --dev --port 8080
# Open http://localhost:8080
```

## Manual model / endpoint

After setup, admins can change the model in Lamp → **Admin → Models**, or edit `~/.workshop/config.json`.

## Troubleshooting

- **Portal does not appear** — Join `Lamp-Setup` manually; browse to http://10.42.0.1 or http://10.42.0.1:80
- **nmcli failed** — Run `sudo ./setup/first-boot.sh --install-only` on Ethernet
- **No QR images** — `apt install qrencode` (installed by first-boot)
- **lamp.local not resolving** — Use `http://<pi-ip>:7700` from Admin → System
