#!/bin/bash
# Lamp first-boot provisioning for Raspberry Pi OS (Bookworm+).
# Run once as root: sudo ./setup/first-boot.sh
#
# Flow:
#   1. WiFi captive portal (Lamp-Setup hotspot)
#   2. Install Ollama + pull model sized to RAM
#   3. Clone Lamp to /opt/lamp, init tortoise vendor
#   4. Write ~/.workshop/config.json, enable systemd + Avahi
#
# Continue after portal: sudo ./setup/first-boot.sh --continue
set -euo pipefail

LAMP_REPO="${LAMP_REPO:-https://github.com/thebreadcat/lamp.git}"
INSTALL_DIR="${LAMP_INSTALL_DIR:-/opt/lamp}"
STATE_DIR="/var/lib/lamp"
STATE_FILE="$STATE_DIR/provision.json"
WIFI_DONE="$STATE_DIR/wifi-configured"
LAMP_USER="${LAMP_USER:-pi}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMP_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "  [lamp] $*"; }
need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run as root: sudo $0 $*"
    exit 1
  fi
}

read_stage() {
  if [[ -f "$STATE_FILE" ]]; then
    python3 -c "import json; print(json.load(open('$STATE_FILE')).get('stage',''))" 2>/dev/null || echo ""
  else
    echo ""
  fi
}

write_stage() {
  mkdir -p "$STATE_DIR"
  python3 -c "import json; json.dump({'stage':'$1'}, open('$STATE_FILE','w'), indent=2)"
}

apt_packages() {
  log "Installing system packages…"
  apt-get update -qq
  apt-get install -y -qq \
    git curl ca-certificates network-manager qrencode avahi-daemon avahi-utils \
    python3 python3-venv 2>/dev/null || true
  systemctl enable avahi-daemon 2>/dev/null || true
  systemctl start avahi-daemon 2>/dev/null || true
}

wifi_portal() {
  log "Starting WiFi setup portal…"
  write_stage "wifi"
  if ! command -v nmcli &>/dev/null; then
    echo "  nmcli not found — install NetworkManager"
    exit 1
  fi
  python3 "$SCRIPT_DIR/captive-portal.py" --state-dir "$STATE_DIR"
  if [[ ! -f "$WIFI_DONE" ]]; then
    echo "  WiFi setup was not completed."
    exit 1
  fi
  write_stage "wifi_done"
  log "Home WiFi configured."
}

install_ollama() {
  if command -v ollama &>/dev/null; then
    log "Ollama already installed."
    return
  fi
  log "Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
  systemctl enable ollama 2>/dev/null || true
  systemctl start ollama 2>/dev/null || true
  sleep 3
}

pick_model() {
  local ram_mb=2048
  if [[ -f /proc/meminfo ]]; then
    ram_mb=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 ))
  fi
  if [[ $ram_mb -ge 7000 ]]; then
    echo "qwen2.5:7b"
  elif [[ $ram_mb -ge 3000 ]]; then
    echo "qwen2.5:3b"
  else
    echo "qwen2.5:1.5b"
  fi
}

pull_model() {
  local model
  model="$(pick_model)"
  log "Pulling model $model (RAM-based choice)…"
  ollama pull "$model" || log "Warning: model pull failed — set model in Lamp admin later."
  echo "$model"
}

install_lamp_code() {
  if [[ -f "$INSTALL_DIR/lamp.py" ]]; then
    log "Lamp already at $INSTALL_DIR"
    return
  fi
  log "Installing Lamp to $INSTALL_DIR…"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [[ -f "$LAMP_SRC/lamp.py" ]]; then
    log "Using local copy from $LAMP_SRC"
    rm -rf "$INSTALL_DIR"
    cp -a "$LAMP_SRC" "$INSTALL_DIR"
  else
    git clone --depth 1 "$LAMP_REPO" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"
  git submodule update --init --recursive 2>/dev/null || true
  if [[ ! -f vendor/workshop/vendor/tortoise/tortoise.py ]]; then
    log "Cloning Tortoise…"
    git clone --depth 1 https://github.com/thebreadcat/tortoise.git \
      vendor/workshop/vendor/tortoise 2>/dev/null || true
  fi
  chown -R "$LAMP_USER:$LAMP_USER" "$INSTALL_DIR"
}

write_workshop_config() {
  local model="$1"
  local cfg_dir
  cfg_dir="$(eval echo "~$LAMP_USER")/.workshop"
  mkdir -p "$cfg_dir"
  local apps_dir="$cfg_dir/../workshop-apps"
  cat > "$cfg_dir/config.json" <<EOF
{
  "endpoint": "http://localhost:11434/v1",
  "model": "$model",
  "api_key": null,
  "apps_dir": "$apps_dir",
  "users": []
}
EOF
  chown -R "$LAMP_USER:$LAMP_USER" "$cfg_dir"
  mkdir -p "$apps_dir"
  chown -R "$LAMP_USER:$LAMP_USER" "$(dirname "$apps_dir")"
  log "Wrote $cfg_dir/config.json"
}

setup_avahi() {
  log "Configuring mDNS (lamp.local)…"
  hostnamectl set-hostname lamp 2>/dev/null || echo "lamp" > /etc/hostname
  mkdir -p /etc/avahi/services
  cat > /etc/avahi/services/lamp.http.service <<'EOF'
<?xml version="1.0" standalone='yes'?>
<service-group>
  <name replace-wildcards="yes">Lamp on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>7700</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
EOF
  systemctl restart avahi-daemon 2>/dev/null || true
}

install_systemd() {
  log "Enabling lamp.service…"
  local svc="/etc/systemd/system/lamp.service"
  sed "s|/opt/lamp|$INSTALL_DIR|g; s|User=pi|User=$LAMP_USER|g" \
    "$SCRIPT_DIR/lamp.service" > "$svc"
  local tortoise="$INSTALL_DIR/vendor/workshop/vendor/tortoise/tortoise.py"
  if [[ -f "$tortoise" ]] && ! grep -q 'TORTOISE_PATH=' "$svc"; then
    sed -i '/^\[Service\]/a Environment=TORTOISE_PATH='"$tortoise" "$svc"
  fi
  systemctl daemon-reload
  systemctl enable lamp.service
  systemctl restart lamp.service
}

show_done() {
  write_stage "complete"
  touch "$STATE_DIR/setup-complete"
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo ""
  echo "  ═══════════════════════════════════════"
  echo "  Lamp is ready!"
  echo "  Open: http://lamp.local:7700"
  [[ -n "$ip" ]] && echo "        http://${ip}:7700"
  echo "  Create your admin account on first visit."
  echo "  ═══════════════════════════════════════"
  echo ""
}

run_install() {
  apt_packages
  install_ollama
  local model
  model="$(pull_model)"
  install_lamp_code
  write_workshop_config "$model"
  setup_avahi
  install_systemd
  show_done
}

main() {
  need_root
  mkdir -p "$STATE_DIR"
  local stage
  stage="$(read_stage)"

  case "${1:-}" in
    --continue)
      if [[ ! -f "$WIFI_DONE" ]]; then
        echo "  WiFi not configured. Run without --continue first."
        exit 1
      fi
      run_install
      ;;
    --wifi-only)
      wifi_portal
      ;;
    --install-only)
      run_install
      ;;
    --status)
      echo "  stage: $(read_stage)"
      echo "  wifi:  $([ -f "$WIFI_DONE" ] && echo yes || echo no)"
      echo "  lamp:  $([ -f "$INSTALL_DIR/lamp.py" ] && echo yes || echo no)"
      systemctl is-active lamp 2>/dev/null || true
      ;;
    *)
      if [[ -f "$STATE_DIR/setup-complete" ]] || [[ "$stage" == "complete" ]]; then
        log "Already provisioned."
        show_done
        exit 0
      fi
      if [[ ! -f "$WIFI_DONE" ]]; then
        wifi_portal
      fi
      run_install
      ;;
  esac
}

main "$@"
