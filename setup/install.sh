#!/usr/bin/env bash
# Lamp one-command installer (macOS / Linux).
#   curl -fsSL https://raw.githubusercontent.com/thebreadcat/lamp-ai/main/setup/install.sh | bash
# Or from a clone:
#   ./setup/install.sh
#
# Optional env:
#   LAMP_INSTALL_DIR=~/lamp     where to install (default ~/lamp)
#   LAMP_SKIP_OLLAMA=1            skip Ollama install / model pull
#   LAMP_SKIP_PULL=1              skip ollama pull (still writes config if missing)
#   LAMP_START=0                  setup only; do not start lamp.py
#   LAMP_NO_TLS=1                 skip HTTPS (voice on phones will not work)
#   LAMP_GITHUB=thebreadcat/lamp-ai
#   LAMP_BRANCH=main
set -euo pipefail

LAMP_GITHUB="${LAMP_GITHUB:-thebreadcat/lamp-ai}"
LAMP_BRANCH="${LAMP_BRANCH:-main}"
LAMP_REPO="${LAMP_REPO:-https://github.com/${LAMP_GITHUB}.git}"
WORKSHOP_GITHUB="${WORKSHOP_GITHUB:-thebreadcat/workshop}"
TORTOISE_GITHUB="${TORTOISE_GITHUB:-thebreadcat/tortoise}"
INSTALL_DIR="${LAMP_INSTALL_DIR:-$HOME/lamp}"
PORT="${LAMP_PORT:-7700}"
HOST="${LAMP_HOST:-0.0.0.0}"
LOCAL_SOURCE=0

log() { echo "  [lamp] $*"; }
warn() { echo "  [lamp] warning: $*" >&2; }
die() { echo "  [lamp] error: $*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── Detect running from a local clone vs curl | bash ─────────────────────────
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ "${BASH_SOURCE[0]}" == *install.sh ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  LAMP_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
  if [[ -f "$LAMP_SRC/lamp.py" ]]; then
    INSTALL_DIR="${LAMP_INSTALL_DIR:-$LAMP_SRC}"
    LOCAL_SOURCE=1
    log "Using local source: $INSTALL_DIR"
  fi
fi

detect_ram_gb() {
  local ram_mb=8192
  if [[ "$(uname -s)" == "Darwin" ]]; then
    ram_mb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1024 / 1024 ))
  elif [[ -f /proc/meminfo ]]; then
    ram_mb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
  fi
  echo $(( (ram_mb + 512) / 1024 ))
}

pick_model() {
  local gb="$1"
  if [[ "$gb" -ge 16 ]]; then
    echo "qwen2.5:7b"
  elif [[ "$gb" -ge 8 ]]; then
    echo "qwen2.5:3b"
  elif [[ "$gb" -ge 4 ]]; then
    echo "qwen2.5:3b"
  else
    echo "qwen2.5:1.5b"
  fi
}

ensure_python() {
  if have python3; then
    if python3 -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      log "Python $(python3 --version 2>&1 | awk '{print $2}')"
      return
    fi
    die "Python 3.10+ required (found $(python3 --version 2>&1))"
  fi
  log "Python 3 not found — trying to install…"
  if [[ "$(uname -s)" == "Darwin" ]] && have brew; then
    brew install python@3.12
    return
  fi
  if have apt-get; then
    sudo apt-get update -qq
    sudo apt-get install -y python3 python3-venv curl unzip ca-certificates
    return
  fi
  die "Install Python 3.10+ from https://www.python.org/downloads/ then re-run this script."
}

download_zip() {
  local repo="$1" dest="$2"
  local url="https://github.com/${repo}/archive/refs/heads/${LAMP_BRANCH}.zip"
  local tmp zip root
  tmp="$(mktemp -d)"
  zip="$tmp/repo.zip"
  log "Downloading ${repo}…"
  curl -fsSL "$url" -o "$zip"
  unzip -q "$zip" -d "$tmp"
  root="$(find "$tmp" -maxdepth 1 -type d ! -path "$tmp" | head -1)"
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  mv "$root" "$dest"
  rm -rf "$tmp"
}

ensure_lamp_tree() {
  if [[ -f "$INSTALL_DIR/lamp.py" ]]; then
    log "Lamp already at $INSTALL_DIR"
    return
  fi
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if have git; then
    log "Cloning Lamp (git)…"
    git clone --depth 1 --branch "$LAMP_BRANCH" "$LAMP_REPO" "$INSTALL_DIR" 2>/dev/null \
      || git clone --depth 1 "$LAMP_REPO" "$INSTALL_DIR"
    (cd "$INSTALL_DIR" && git submodule update --init --recursive 2>/dev/null || true)
  else
    log "Git not found — downloading zip archives instead…"
    download_zip "$LAMP_GITHUB" "$INSTALL_DIR"
  fi
  [[ -f "$INSTALL_DIR/lamp.py" ]] || die "Install failed — lamp.py missing in $INSTALL_DIR"
}

ensure_workshop() {
  if [[ -f "$INSTALL_DIR/vendor/workshop/workshop.py" ]]; then
    return
  fi
  log "Installing Workshop…"
  if have git && [[ -d "$INSTALL_DIR/.git" ]]; then
    (cd "$INSTALL_DIR" && git submodule update --init --recursive) || true
  fi
  if [[ -f "$INSTALL_DIR/vendor/workshop/workshop.py" ]]; then
    return
  fi
  download_zip "$WORKSHOP_GITHUB" "$INSTALL_DIR/vendor/workshop"
}

ensure_tortoise() {
  local t="$INSTALL_DIR/vendor/workshop/vendor/tortoise/tortoise.py"
  if [[ -f "$t" ]]; then
    return
  fi
  log "Installing Tortoise (app builder)…"
  mkdir -p "$INSTALL_DIR/vendor/workshop/vendor"
  if have git; then
    git clone --depth 1 "https://github.com/${TORTOISE_GITHUB}.git" \
      "$INSTALL_DIR/vendor/workshop/vendor/tortoise" 2>/dev/null && return
  fi
  download_zip "$TORTOISE_GITHUB" "$INSTALL_DIR/vendor/workshop/vendor/tortoise"
  [[ -f "$t" ]] || die "Tortoise install failed"
}

ensure_ollama() {
  if [[ "${LAMP_SKIP_OLLAMA:-}" == "1" ]]; then
    warn "Skipping Ollama (LAMP_SKIP_OLLAMA=1)"
    return
  fi
  if have ollama; then
    log "Ollama already installed"
  else
    log "Installing Ollama…"
    if [[ "$(uname -s)" == "Darwin" ]] && have brew; then
      brew install ollama 2>/dev/null || true
    fi
    if ! have ollama; then
      curl -fsSL https://ollama.com/install.sh | sh
    fi
  fi
  start_ollama
}

start_ollama() {
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    return
  fi
  if have systemctl && systemctl list-unit-files 2>/dev/null | grep -q '^ollama.service'; then
    sudo systemctl enable ollama 2>/dev/null || true
    sudo systemctl start ollama 2>/dev/null || true
    sleep 2
    return
  fi
  if have ollama; then
    log "Starting Ollama…"
    (nohup ollama serve >/dev/null 2>&1 &) || true
    sleep 3
  fi
}

wait_for_ollama() {
  local i
  for i in $(seq 1 45); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  warn "Ollama API not responding yet — you can pull a model later in Lamp Admin"
  return 1
}

pull_model() {
  local model="$1"
  [[ "${LAMP_SKIP_OLLAMA:-}" == "1" ]] && return
  [[ "${LAMP_SKIP_PULL:-}" == "1" ]] && return
  if ! have ollama; then
    warn "ollama not in PATH — skip model pull"
    return
  fi
  wait_for_ollama || true
  log "Pulling model $model (this may take several minutes)…"
  ollama pull "$model" || warn "Model pull failed — set model later in Lamp"
}

write_workshop_config() {
  local model="$1"
  python3 - "$model" <<'PY'
import json, sys
from pathlib import Path
model = sys.argv[1]
cfg_dir = Path.home() / ".workshop"
cfg_path = cfg_dir / "config.json"
if cfg_path.exists():
    print(f"  [lamp] Config exists — leaving {cfg_path}")
    sys.exit(0)
cfg_dir.mkdir(parents=True, exist_ok=True)
apps = Path.home() / "workshop-apps"
apps.mkdir(parents=True, exist_ok=True)
cfg = {
    "endpoint": "http://localhost:11434/v1",
    "model": model,
    "api_key": None,
    "apps_dir": str(apps),
    "users": [],
}
cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"  [lamp] Wrote {cfg_path} (model: {model})")
PY
}

detect_lan_ip() {
  python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except OSError:
    pass
" 2>/dev/null || true
}

print_access_urls() {
  local lan phone_url scheme="https"
  [[ "${LAMP_NO_TLS:-}" == "1" ]] && scheme="http"
  lan="$(detect_lan_ip)"
  echo "  On this computer: ${scheme}://localhost:${PORT}"
  if [[ -n "$lan" ]] && [[ "$HOST" != "127.0.0.1" ]] && [[ "$HOST" != "localhost" ]]; then
    phone_url="${scheme}://${lan}:${PORT}"
    echo "  Phones/tablets (same Wi‑Fi): ${phone_url}"
    if [[ "$scheme" == "https" ]]; then
      echo "  On your phone: scan the QR, accept the security warning once, then use the mic."
    fi
    if [[ -f "$INSTALL_DIR/lamp_qr.py" ]]; then
      echo ""
      echo "  Scan on your phone:"
      (cd "$INSTALL_DIR" && python3 -c "import lamp_qr; lamp_qr.print_terminal_qr('${phone_url}')" 2>/dev/null) \
        || echo "    (QR also on the login page in your browser)"
      echo ""
    fi
  fi
}

ensure_tls() {
  [[ "${LAMP_NO_TLS:-}" == "1" ]] && return
  log "Setting up HTTPS (for microphone on phones)…"
  (cd "$INSTALL_DIR" && python3 lamp_tls.py) || die "HTTPS setup failed — install OpenSSL and re-run"
}

preflight() {
  if [[ -x "$INSTALL_DIR/setup/preflight.sh" ]]; then
    (cd "$INSTALL_DIR" && ./setup/preflight.sh) || warn "Preflight reported issues — Lamp may still run"
  fi
}

start_lamp() {
  if [[ "${LAMP_START:-1}" == "0" ]]; then
    log "Setup complete (LAMP_START=0). Start with: cd $INSTALL_DIR && python3 lamp.py --host $HOST"
    print_access_urls
    return
  fi
  if lsof -ti ":$PORT" >/dev/null 2>&1; then
    warn "Port $PORT already in use — not starting a second server"
    echo ""
    print_access_urls
    return
  fi
  echo ""
  echo "  ═══════════════════════════════════════════════════════"
  echo "  Lamp is starting."
  print_access_urls
  echo "  Create your admin name + PIN on first visit."
  echo "  Press Ctrl+C to stop the server."
  echo "  ═══════════════════════════════════════════════════════"
  echo ""
  cd "$INSTALL_DIR"
  local tls_flag=""
  [[ "${LAMP_NO_TLS:-}" == "1" ]] && tls_flag="--no-tls"
  exec python3 lamp.py --host "$HOST" --port "$PORT" $tls_flag
}

main() {
  echo ""
  echo "  Lamp installer"
  echo "  ──────────────"
  ensure_python
  ensure_lamp_tree
  ensure_workshop
  ensure_tortoise
  local ram_gb model
  ram_gb="$(detect_ram_gb)"
  model="$(pick_model "$ram_gb")"
  log "Detected ~${ram_gb} GB RAM → default model: $model"
  ensure_ollama
  pull_model "$model"
  write_workshop_config "$model"
  ensure_tls
  preflight
  start_lamp
}

main "$@"
