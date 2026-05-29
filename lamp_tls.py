#!/usr/bin/env python3
"""Self-signed TLS for Lamp on the home LAN (microphone on phones). Uses openssl when available."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


def lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def default_paths() -> tuple[Path, Path]:
    d = Path.home() / ".workshop"
    return d / "lamp-cert.pem", d / "lamp-key.pem"


def find_openssl() -> str | None:
    import shutil

    exe = shutil.which("openssl")
    if exe:
        return exe
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\usr\bin\openssl.exe",
            r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
            r"C:\Program Files\OpenSSL-Win64\bin\openssl",
        ):
            if os.path.isfile(candidate):
                return candidate
    return None


def ensure_openssl() -> str:
    exe = find_openssl()
    if exe:
        return exe
    if sys.platform == "win32":
        raise RuntimeError(
            "OpenSSL not found. Install Git for Windows (includes openssl) or OpenSSL, then re-run install."
        )
    raise RuntimeError(
        "OpenSSL not found. Install it (macOS/Linux usually include it; try: sudo apt install openssl)."
    )


def generate_cert(
    cert: Path,
    key: Path,
    *,
    lan: str | None = None,
    cn: str = "lamp.local",
    days: int = 825,
) -> None:
    openssl = ensure_openssl()
    cert.parent.mkdir(parents=True, exist_ok=True)
    ip = (lan or lan_ip() or "").strip()
    san = f"DNS:{cn},DNS:localhost,IP:127.0.0.1"
    if ip:
        san += f",IP:{ip}"
    cmd = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-days",
        str(days),
        "-subj",
        f"/CN={cn}",
        "-addext",
        f"subjectAltName={san}",
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass


def ensure_tls_cert(*, lan: str | None = None, force: bool = False) -> tuple[Path, Path]:
    """Create ~/.workshop/lamp-cert.pem + lamp-key.pem if missing."""
    cert, key = default_paths()
    if cert.is_file() and key.is_file() and not force:
        return cert, key
    generate_cert(cert, key, lan=lan)
    if not cert.is_file() or not key.is_file():
        raise RuntimeError(f"TLS cert generation failed ({cert})")
    return cert, key


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Generate Lamp self-signed TLS certificate")
    ap.add_argument("--force", action="store_true", help="Regenerate even if cert exists")
    ap.add_argument("--lan", default="", help="LAN IP for certificate SAN")
    args = ap.parse_args()
    try:
        cert, key = ensure_tls_cert(lan=args.lan or None, force=args.force)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"  [lamp] TLS error: {e}", file=sys.stderr)
        return 1
    print(f"  [lamp] TLS certificate: {cert}")
    print(f"  [lamp] TLS private key:  {key}")
    ip = args.lan or lan_ip()
    if ip:
        print(f"  [lamp] Phone URL: https://{ip}:7700")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
