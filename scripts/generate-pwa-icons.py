#!/usr/bin/env python3
"""Generate icon-192.png and icon-512.png from assets/app-icon.svg (optional dev tool)."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "app-icon.svg"
OUT192 = ROOT / "icon-192.png"
OUT512 = ROOT / "icon-512.png"


def run(cmd):
    print(" ", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    if not SVG.is_file():
        print(f"Missing {SVG}")
        return 1
    for exe in ("rsvg-convert", "magick", "convert"):
        if shutil.which(exe):
            break
    else:
        print("Install rsvg-convert or ImageMagick to rasterize SVG.")
        print("Placeholder PNGs in repo are used until then.")
        return 1
    if shutil.which("rsvg-convert"):
        run(["rsvg-convert", "-w", "192", "-h", "192", "-o", str(OUT192), str(SVG)])
        run(["rsvg-convert", "-w", "512", "-h", "512", "-o", str(OUT512), str(SVG)])
    else:
        exe = "magick" if shutil.which("magick") else "convert"
        run([exe, "-background", "none", str(SVG), "-resize", "192x192", str(OUT192)])
        run([exe, "-background", "none", str(SVG), "-resize", "512x512", str(OUT512)])
    print("Wrote", OUT192.name, "and", OUT512.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
