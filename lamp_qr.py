"""QR codes for Lamp — PNG via qrencode when available, else SVG (Nayuki qrcodegen, MIT)."""

from __future__ import annotations

import socket
import subprocess

import lamp_qrcodegen as qrcodegen


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def phone_connect_url(
    request_host: str,
    port: int,
    *,
    scheme: str = "http",
    server_bind_host: str = "127.0.0.1",
) -> str:
    """Best URL for phones on the same Wi‑Fi (LAN IP when opened from localhost)."""
    host = (request_host or "").split(":")[0].strip().lower()
    bind = (server_bind_host or "").strip().lower()
    listening_lan = bind in ("", "0.0.0.0", "::")

    if host in ("localhost", "127.0.0.1", "::1") and listening_lan:
        ip = _lan_ip()
        if ip:
            return f"{scheme}://{ip}:{port}"

    if host and host not in ("localhost", "127.0.0.1", "::1"):
        if ":" in (request_host or ""):
            return f"{scheme}://{request_host}"
        return f"{scheme}://{host}:{port}"

    return f"{scheme}://localhost:{port}"


def make_qr_png(data: str) -> bytes | None:
    try:
        r = subprocess.run(
            ["qrencode", "-o", "-", "-s", "8", "-m", "2", data],
            capture_output=True,
            timeout=15,
            check=True,
        )
        return r.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def make_qr_svg(data: str, *, scale: int = 8, border: int = 4) -> str:
    qr = qrcodegen.QrCode.encode_text(data, qrcodegen.QrCode.Ecc.MEDIUM)
    size = qr.get_size()
    dim = (size + border * 2) * scale
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
        f'viewBox="0 0 {dim} {dim}" role="img" aria-label="QR code">',
        f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>',
    ]
    for y in range(size):
        for x in range(size):
            if qr.get_module(x, y):
                px = (x + border) * scale
                py = (y + border) * scale
                parts.append(
                    f'<rect x="{px}" y="{py}" width="{scale}" height="{scale}" fill="#1c1917"/>'
                )
    parts.append("</svg>")
    return "".join(parts)


def print_terminal_qr(url: str) -> bool:
    """Print a scannable QR in the terminal (requires qrencode). Returns True if printed."""
    try:
        subprocess.run(
            ["qrencode", "-t", "ANSIUTF8", "-m", "2", url],
            check=True,
            timeout=15,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False
