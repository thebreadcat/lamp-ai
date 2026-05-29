#!/usr/bin/env bash
# Self-signed TLS cert for Lamp on your home LAN (microphone / PWA over HTTPS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAN_IP=""
if [[ -n "${1:-}" ]]; then
  LAN_IP="$1"
else
  LAN_IP="$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except OSError:
    pass
" 2>/dev/null || true)"
fi

ARGS=()
[[ -n "$LAN_IP" ]] && ARGS+=(--lan "$LAN_IP")
python3 "$ROOT/lamp_tls.py" "${ARGS[@]}"

echo ""
echo "Start Lamp (HTTPS is automatic when listening on the network):"
echo "  python3 lamp.py --host 0.0.0.0"
echo ""
if [[ -n "$LAN_IP" ]]; then
  echo "On your phone (accept the security warning once):"
  echo "  https://${LAN_IP}:7700"
fi
echo "  https://lamp.local:7700  (Pi / mDNS)"
