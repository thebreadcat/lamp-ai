#!/usr/bin/env python3
"""
Lamp WiFi captive portal — runs during first-boot on the Pi setup AP.
Stdlib only. Requires nmcli on Raspberry Pi OS (NetworkManager).

Usage (as root during setup):
    python3 setup/captive-portal.py
    python3 setup/captive-portal.py --dev   # local test, no WiFi changes
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SETUP_SSID = os.environ.get("LAMP_SETUP_SSID", "Lamp-Setup")
SETUP_PASS = os.environ.get("LAMP_SETUP_PASS", "lamplight")
SETUP_IP = "10.42.0.1"
LAMP_URL = os.environ.get("LAMP_URL", "http://lamp.local:7700")
PORT = int(os.environ.get("LAMP_PORTAL_PORT", "80"))


class Config:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.wifi_done = self.state_dir / "wifi-configured"

    def ensure(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)


CFG = Config(Path("/var/lib/lamp"))


def run(cmd: list, timeout=30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


def scan_wifi() -> list:
    """Return [{ssid, signal, secured}, ...] via nmcli."""
    code, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if code != 0:
        return []
    nets = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = parts[1] if len(parts) > 1 else "0"
        sec = parts[2] if len(parts) > 2 else ""
        nets.append({
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "secured": bool(sec and sec != "--"),
        })
    return sorted(nets, key=lambda x: -x["signal"])


def connect_wifi(ssid: str, password: str, dev: bool) -> tuple[bool, str]:
    if dev:
        CFG.ensure()
        CFG.wifi_done.write_text(
            json.dumps({"ssid": ssid, "dev": True}), encoding="utf-8"
        )
        return True, "Dev mode: saved (no system changes)"
    code, out = run(
        ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
        timeout=60,
    )
    if code != 0:
        code2, out2 = run(
            ["nmcli", "dev", "wifi", "connect", ssid], timeout=60
        )
        if code2 != 0:
            return False, out or out2 or "Connection failed"
    CFG.ensure()
    CFG.wifi_done.write_text(json.dumps({"ssid": ssid}), encoding="utf-8")
    return True, "Connected"


def wifi_qr_string() -> str:
    esc = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(":", "\\:")
    if SETUP_PASS:
        return f"WIFI:T:WPA;S:{esc(SETUP_SSID)};P:{esc(SETUP_PASS)};;"
    return f"WIFI:T:nopass;S:{esc(SETUP_SSID)};;"


def lamp_qr_string() -> str:
    return LAMP_URL


def build_setup_html(setup_ssid: str, password_hint: str) -> str:
    html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lamp Setup</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a1a;color:#f5f5f4;padding:24px 20px 40px;line-height:1.5}}
h1{{color:#d97706;font-size:26px;margin-bottom:8px}}
p{{color:#a8a29e;margin-bottom:20px;font-size:15px}}
.card{{background:#262626;border:1px solid #3a3a3a;border-radius:14px;padding:20px;margin-bottom:16px}}
label{{display:block;font-size:13px;color:#a8a29e;margin-bottom:6px}}
input,select{{width:100%;padding:14px;border-radius:10px;border:1px solid #3a3a3a;background:#1a1a1a;color:#f5f5f4;font-size:16px;margin-bottom:12px}}
button{{width:100%;padding:16px;background:#d97706;color:#fff;border:none;border-radius:12px;font-size:17px;font-weight:700;cursor:pointer}}
button:disabled{{background:#3a3a3a}}
.err{{color:#ef4444;font-size:14px;margin-top:8px;display:none}}
.ok{{color:#86efac;font-size:14px;margin-top:8px;display:none}}
.step{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#d97706;margin-bottom:12px}}
.qr-wrap{{text-align:center;padding:12px 0}}
.qr-wrap img{{max-width:200px;border-radius:8px}}
.net{{padding:12px;border:1px solid #3a3a3a;border-radius:10px;margin-bottom:8px;cursor:pointer}}
.net:hover{{border-color:#d97706}}
.net.sel{{border-color:#d97706;background:#3d2a14}}
.net strong{{display:block}}
.net span{{font-size:12px;color:#a8a29e}}
</style></head><body>
<h1>🪔 Lamp Setup</h1>
<p id="subtitle">Connect your phone to <strong>__SETUP_SSID__</strong>, then join your home WiFi below.</p>

<div class="card" id="step1">
  <div class="step">Step 1 — Join this device</div>
  <div class="qr-wrap"><img src="/qr/wifi" alt="WiFi QR"></div>
  <p style="font-size:14px;text-align:center">Network: <strong>__SETUP_SSID__</strong>
  __PASSWORD_HINT__</p>
</div>

<div class="card" id="step2">
  <div class="step">Step 2 — Home WiFi</div>
  <div id="net-list"></div>
  <label>Or type network name</label>
  <input id="ssid" placeholder="WiFi name (SSID)" autocomplete="off">
  <label>Password</label>
  <input id="pass" type="password" placeholder="WiFi password" autocomplete="off">
  <button id="btn" onclick="connect()">Connect Lamp to WiFi</button>
  <p class="err" id="err"></p>
  <p class="ok" id="ok"></p>
</div>
<script>
let selected=null;
async function loadNets(){
  const r=await fetch('/api/scan');const d=await r.json();
  const el=document.getElementById('net-list');
  if(!d.networks||!d.networks.length){el.innerHTML='<p style="color:#a8a29e;font-size:14px">Scanning… refresh page.</p>';return;}
  el.innerHTML=d.networks.slice(0,12).map(n=>`
    <div class="net" data-ssid="${n.ssid.replace(/"/g,'')}" onclick="pick(this)">
      <strong>${n.ssid}</strong><span>${n.signal}% · ${n.secured?'Secured':'Open'}</span>
    </div>`).join('');
}
function pick(el){
  document.querySelectorAll('.net').forEach(n=>n.classList.remove('sel'));
  el.classList.add('sel');
  selected=el.dataset.ssid;
  document.getElementById('ssid').value=selected;
}
async function connect(){
  const ssid=document.getElementById('ssid').value.trim()||selected;
  const pass=document.getElementById('pass').value;
  const err=document.getElementById('err'),ok=document.getElementById('ok'),btn=document.getElementById('btn');
  err.style.display=ok.style.display='none';
  if(!ssid){err.textContent='Pick or enter a network';err.style.display='block';return;}
  btn.disabled=true;btn.textContent='Connecting…';
  const r=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ssid,password:pass})});
  const d=await r.json();
  if(d.ok){ok.textContent=d.message||'Connected! Lamp will finish setup…';ok.style.display='block';
    setTimeout(()=>location.href='/done',2000);}
  else{err.textContent=d.error||'Failed';err.style.display='block';btn.disabled=false;btn.textContent='Connect Lamp to WiFi';}
}
loadNets();
</script>
</body></html>"""
    return html.replace("__SETUP_SSID__", setup_ssid).replace(
        "__PASSWORD_HINT__", password_hint
    )


def build_done_html(lamp_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lamp Ready</title>
<style>
body{{font-family:-apple-system,sans-serif;background:#1a1a1a;color:#f5f5f4;padding:32px 24px;text-align:center}}
h1{{color:#d97706;font-size:28px;margin:16px 0}}
p{{color:#a8a29e;margin:12px 0;font-size:16px}}
a{{display:inline-block;margin-top:24px;padding:16px 28px;background:#d97706;color:#fff;text-decoration:none;border-radius:12px;font-weight:700}}
img{{max-width:220px;margin:20px auto;border-radius:12px;display:block}}
</style></head><body>
<h1>🪔 Setup complete!</h1>
<p>Scan to open Lamp on your home network:</p>
<img src="/qr/lamp" alt="Open Lamp">
<p><a href="{lamp_url}">{lamp_url}</a></p>
<p style="font-size:14px">Create your admin account on first visit.</p>
</body></html>"""


def make_qr_png(data: str) -> bytes | None:
    """Generate PNG via qrencode if installed."""
    try:
        r = subprocess.run(
            ["qrencode", "-o", "-", "-s", "6", "-m", "2", data],
            capture_output=True, timeout=10, check=True,
        )
        return r.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


class PortalHandler(BaseHTTPRequestHandler):
    dev = False

    def log_message(self, *_):
        pass

    def _json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self, html: str, code=200):
        b = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html", "/hotspot-detect.html", "/generate_204", "/ncsi.txt"):
            hint = f"<br>Password: <strong>{SETUP_PASS}</strong>" if SETUP_PASS else "(open network)"
            self._html(build_setup_html(SETUP_SSID, hint))
            return
        if p == "/done":
            self._html(build_done_html(LAMP_URL))
            return
        if p == "/api/scan":
            self._json({"networks": scan_wifi()})
            return
        if p == "/qr/wifi":
            png = make_qr_png(wifi_qr_string())
            if png:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            else:
                self.send_response(404)
                self.end_headers()
            return
        if p == "/qr/lamp":
            png = make_qr_png(lamp_qr_string())
            if png:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            else:
                self.send_response(404)
                self.end_headers()
            return
        self.send_response(302)
        self.send_header("Location", "/")
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/connect":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n)) if n else {}
            ssid = (body.get("ssid") or "").strip()
            password = body.get("password") or ""
            if not ssid:
                self._json({"ok": False, "error": "SSID required"}, 400)
                return
            ok, msg = connect_wifi(ssid, password, self.dev)
            if ok:
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                self._json({"ok": True, "message": msg})
            else:
                self._json({"ok": False, "error": msg}, 400)
            return
        self._json({"error": "not found"}, 404)


def start_hotspot(dev: bool) -> bool:
    if dev:
        print("  [dev] Skipping hotspot")
        return True
    run(["nmcli", "radio", "wifi", "on"])
    run(["nmcli", "dev", "wifi", "rescan"])
    if SETUP_PASS:
        code, out = run([
            "nmcli", "dev", "wifi", "hotspot",
            "ifname", "wlan0",
            "ssid", SETUP_SSID,
            "password", SETUP_PASS,
        ])
    else:
        code, out = run([
            "nmcli", "dev", "wifi", "hotspot",
            "ifname", "wlan0",
            "ssid", SETUP_SSID,
        ])
    if code != 0:
        print(f"  Hotspot warning: {out}")
        return False
    print(f"  Hotspot active: {SETUP_SSID}")
    return True


def stop_hotspot(dev: bool):
    if dev:
        return
    run(["nmcli", "connection", "down", "Hotspot"])
    run(["nmcli", "connection", "delete", "Hotspot"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="Test UI locally, no WiFi changes")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--state-dir", type=str, default="/var/lib/lamp")
    args = ap.parse_args()

    global CFG
    CFG = Config(Path(args.state_dir))
    CFG.ensure()

    dev = args.dev
    if CFG.wifi_done.exists() and not dev:
        print("  WiFi already configured.")
        return 0

    if os.geteuid() != 0 and not dev:
        print("  Run as root for WiFi setup: sudo python3 setup/captive-portal.py")
        return 1

    start_hotspot(dev)
    PortalHandler.dev = dev
    server = HTTPServer(("0.0.0.0", args.port), PortalHandler)
    print(f"\n  Lamp setup portal: http://{SETUP_IP if not dev else 'localhost'}:{args.port}")
    print(f"  Connect phone to WiFi: {SETUP_SSID}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    stop_hotspot(dev)
    if CFG.wifi_done.exists():
        print("  WiFi configured — continue with: sudo setup/first-boot.sh --continue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
