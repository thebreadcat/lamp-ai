# Lamp — pre-release test checklist

Run from the lamp repo root:

```bash
python3 lamp.py
# Open http://localhost:7700

# Health check (no server):
python3 lamp.py --status

# Automated smoke (server must be running):
./scripts/smoke-test.sh
```

**Prerequisites:** Ollama and/or LM Studio running locally is ideal for full coverage.

## 1. First run & auth

- [ ] Visit `/` → first-run setup (name + 4-digit PIN) if no users exist
- [ ] Create admin account → lands on home
- [ ] Log out (Admin → Users → Sign out) → login screen
- [ ] Wrong PIN shakes / errors; correct PIN logs in
- [ ] Second user can be added in Admin → Users

## 2. Model setup

- [ ] Home shows banner if model not configured (admin only)
- [ ] `#/setup-model` scans and lists Ollama / LM Studio models
- [ ] Pick a detected model → Save → banner disappears
- [ ] Chat and Build work after configuration

## 3. Chat

- [ ] Chat list and open conversation show spinners while loading (no blank flash)
- [ ] **Model** chip above chat input opens model picker; switch model mid-chat → system note appears, next reply continues with full history
- [ ] **Use home default** clears per-chat model override
- [ ] **Microphone** records → Whisper transcribes into the input (requires `openai-whisper` + `ffmpeg`)
- [ ] **Speaker** (header) toggles auto-read; **Listen** on assistant bubbles reads aloud
- [ ] Admin → System shows Whisper OK when installed
- [ ] Home → **Chat with Lamp** opens chat (auto-creates first conversation if none)
- [ ] Send message → streaming reply appears
- [ ] If model suggests an app → **Build this app** → Build shows plan card (no extra interview); optional **Refine plan with AI**
- [ ] Chat shows typing indicator while Lamp responds; code blocks have **Copy**
- [ ] **New** starts another conversation; **Delete** removes current thread
- [ ] **Star** pins chat to top of list; **Rename** (pencil icon) edits title
- [ ] **Pull to refresh** on chat list (mobile) reloads conversations
- [ ] **Desktop:** sidebar list + chat panel side by side (wide layout)
- [ ] **Mobile:** chat list first; tap a chat → full-screen thread; **← Chats** returns to list
- [ ] Conversation list shows titles, star indicator, and times

## 4. Build & apps

- [ ] Home **Recent apps** and **Quick start** show spinners while loading
- [ ] **Apps** tab shows spinner before app cards appear
- [ ] Build interview proposes a plan → **Build this** runs Tortoise
- [ ] Build progress SSE steps complete → **Open app**
- [ ] App appears under **Apps** and home recent row
- [ ] **Apps** shows **Shared** and **My apps** sections when applicable
- [ ] **Clear data** on an app wipes DB keys/schedules (app files remain)
- [ ] Template on home (e.g. Grocery List) → confirm → builds without interview
- [ ] Improve / Delete on an app card

## 5. Notifications

- [ ] `#/notifications` shows spinner while loading the feed
- [ ] Create a schedule in a built app (if app supports it) or wait for ticker
- [ ] Home nav badge shows unread count
- [ ] Tap badge → `#/notifications` list (read + unread)
- [ ] Tap notification marks read; **Clear all** works
- [ ] Swipe notification left marks read (mobile)
- [ ] First home visit shows onboarding tour (skip or complete); does not repeat

## 6. Admin (admin account)

- [ ] Admin tabs show a spinner while loading (Users, Models, Storage, System); tabs dim briefly during fetch
- [ ] `#/admin/users` — list, add user, change role, reset PIN, delete user
- [ ] `#/admin/models` — Ollama + LM Studio sections list models
- [ ] **Use** switches endpoint + model; active model highlighted
- [ ] Catalog search + **Pull** downloads an Ollama model (if `ollama` CLI installed)
- [ ] Import `qwen2.5:1.5b` starts pull; Hugging Face URL (e.g. `https://huggingface.co/…`) starts `ollama pull hf.co/…`
- [ ] Recommended model chips trigger pull
- [ ] `#/admin/storage` — disk stats, per-app sizes list, backup cleanup, chat cleanup, vacuum
- [ ] `#/admin/system` — Ollama, ticker, RAM, CPU temp, uptime, IP, versions

## 7. Appearance

- [ ] Nav **Light** / **Dark** toggle switches theme immediately
- [ ] Theme persists after reload
- [ ] Admin → System → Appearance Light/Dark buttons match nav toggle
- [ ] First visit respects system preference if no saved choice

## 8. PWA / offline shell

- [ ] Browser “Add to Home Screen” (optional)
- [ ] `manifest.json` and icons load
- [ ] Service worker registers (no errors in console)

## 9. Pi setup (optional, on device)

```bash
sudo ./setup/first-boot.sh
# or --install-only if already on WiFi
```

- [ ] Captive portal: `python3 setup/captive-portal.py --dev --port 8080`
- [ ] Full provision: WiFi → Ollama → `http://lamp.local:7700`

## 10. Child account (optional)

- [ ] Admin creates user with role **Child**
- [ ] Child login: no **Build** nav, no templates, no admin
- [ ] Child can chat; no **Build this app** button in chat
- [ ] Child can open apps; **Apps** shows Open only (no Delete / Improve / Clear data)
- [ ] API rejects build start for child (`403`)

## Before you test

Restart the server after pulling changes (`Ctrl+C`, then `python3 lamp.py`). If static files like `/favicon.svg` return 401, an old process is still bound to port 7700 — stop it and start again.

## Known limitations (v0.4)

- Hugging Face import requires a recent Ollama that supports `hf.co/` pulls
- Child role: basic restrictions only (no time limits or per-app parental controls yet)
- iOS PWA: push notifications only while app is open
- `ollama search` catalog requires recent Ollama CLI
- Whisper: first transcription loads the model (slow); use `tiny` on Pi; max ~90s recording per message
- Read-aloud uses browser TTS (quality varies by device); Whisper is STT only

## Quick smoke (5 min)

1. Login → Setup model (detect) → Chat one message  
2. Build one template app → Open it  
3. Admin → Models → confirm Ollama + LM Studio lists  
4. Notifications page loads  
