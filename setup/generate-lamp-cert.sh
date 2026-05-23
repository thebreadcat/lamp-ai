#!/usr/bin/env bash
# Self-signed TLS cert for Lamp on your home LAN (microphone / PWA over HTTPS).
set -euo pipefail

DIR="${LAMP_TLS_DIR:-$HOME/.workshop}"
CERT="$DIR/lamp-cert.pem"
KEY="$DIR/lamp-key.pem"
CN="${LAMP_TLS_CN:-lamp.local}"
DAYS="${LAMP_TLS_DAYS:-825}"

mkdir -p "$DIR"

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

SAN="DNS:${CN},DNS:localhost,IP:127.0.0.1"
if [[ -n "$LAN_IP" ]]; then
  SAN="${SAN},IP:${LAN_IP}"
fi

echo "Writing $CERT (SAN: $SAN)"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$CERT" -days "$DAYS" \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=${SAN}"

chmod 600 "$KEY"
echo ""
echo "Start Lamp with HTTPS:"
echo "  python3 lamp.py --host 0.0.0.0 --tls"
echo ""
if [[ -n "$LAN_IP" ]]; then
  echo "On your phone (accept the security warning once):"
  echo "  https://${LAN_IP}:7700"
fi
echo "  https://${CN}:7700  (Pi / mDNS)"
