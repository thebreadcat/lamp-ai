# Lamp website (GitHub Pages)

Static landing page for onboarding — **not** the Lamp app itself.

## Enable on GitHub

1. Push this repo to `thebreadcat/lamp-ai`
2. **Settings → Pages**
3. Source: **Deploy from a branch**
4. Branch: **main**, folder: **/docs**
5. Save — site goes live at `https://thebreadcat.github.io/lamp-ai/`

## Local preview

```bash
cd docs && python3 -m http.server 8080
# open http://localhost:8080
```

## What it covers

- One-line install commands (Mac/Linux, Windows, Pi)
- What the installer does automatically (Ollama, HTTPS, QR)
- FAQ for non-technical users

Developer docs stay in the repo root: [QUICKSTART.md](../QUICKSTART.md), [README.md](../README.md).
