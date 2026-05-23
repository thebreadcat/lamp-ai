#!/bin/bash
# Run on your Mac (or on the Pi before first-boot) to catch missing deps early.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

ok() { echo "  ✓ $*"; }
bad() { echo "  ✗ $*"; fail=1; }

echo "Lamp preflight ($ROOT)"
echo ""

for f in lamp.py lamp_db.py lamp_chat.py lamp_admin.py lamp_models.py; do
  if python3 -m py_compile "$f" 2>/dev/null; then
    ok "$f compiles"
  else
    bad "$f does not compile"
  fi
done

if python3 -m py_compile setup/captive-portal.py 2>/dev/null; then
  ok "setup/captive-portal.py compiles"
else
  bad "setup/captive-portal.py does not compile"
fi

if bash -n setup/first-boot.sh 2>/dev/null; then
  ok "setup/first-boot.sh syntax"
else
  bad "setup/first-boot.sh syntax error"
fi

if [[ -f vendor/workshop/workshop.py ]]; then
  ok "Workshop vendor present"
else
  bad "Missing vendor/workshop/workshop.py — run: git submodule update --init"
fi

if [[ -f vendor/workshop/vendor/tortoise/tortoise.py ]]; then
  ok "Tortoise present"
else
  bad "Missing vendor/workshop/vendor/tortoise/tortoise.py"
  echo "      git clone --depth 1 https://github.com/thebreadcat/tortoise.git vendor/workshop/vendor/tortoise"
fi

if grep -E '^\s+install_ollama\b' setup/first-boot.sh >/dev/null; then
  ok "first-boot calls install_ollama in run_install"
else
  bad "first-boot must call install_ollama before pull_model in run_install()"
fi

echo ""
if [[ $fail -eq 0 ]]; then
  echo "Preflight passed. Safe to rsync/clone this tree to the Pi."
  exit 0
fi
echo "Preflight failed. Fix items above before Pi provision."
exit 1
