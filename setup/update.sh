#!/usr/bin/env bash
# Update Lamp to the latest release (same logic as: python3 lamp.py --update)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python3 lamp.py --update "$@"
