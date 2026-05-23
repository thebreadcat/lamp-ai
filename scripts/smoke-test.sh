#!/bin/bash
# Quick Mac smoke test — run while lamp.py is listening on port 7700.
set -euo pipefail
BASE="${LAMP_URL:-http://127.0.0.1:7700}"

fail=0
check() {
  local name="$1" expect="$2" url="$3"
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [[ "$code" != "$expect" ]]; then
    echo "  ✗ $name — expected HTTP $expect, got $code ($url)"
    fail=1
  else
    echo "  ✓ $name ($code)"
  fi
}

echo "Lamp smoke test → $BASE"
echo ""

check "index" 200 "$BASE/"
check "manifest" 200 "$BASE/manifest.json"
check "favicon.svg" 200 "$BASE/favicon.svg"
check "icon-192" 200 "$BASE/icon-192.png"
check "sw.js" 200 "$BASE/sw.js"
check "auth check (guest)" 401 "$BASE/api/auth/check"
check "templates (no auth)" 401 "$BASE/api/templates"

echo ""
if [[ $fail -eq 0 ]]; then
  echo "Smoke test passed."
  exit 0
fi
echo "Smoke test failed — restart lamp.py if static files 401."
exit 1
