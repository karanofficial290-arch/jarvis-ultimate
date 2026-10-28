# Status: what exists, what was verified, what is missing

Build environment used: Linux, Python 3.13, Chromium (headless), JDK 21, Gradle 8.14.
Package registries (PyPI, Maven, Google Maven) were **blocked**, so nothing could be installed.

## Verification legend

- ✅ **Verified** — implemented and exercised by automated tests or a real run in the build environment.
- 🟡 **Written, not run** — complete source, syntax-checked, but never compiled/executed here.
- ❌ **Not implemented**.

## Test results (last run)

```
python -m pytest -q backend/tests desktop/tests tests
88 passed
```

| Suite | Tests | Covers |
|---|---|---|
| backend/tests | 68 | providers (Anthropic + OpenAI-compatible request/response shapes, retries, invalid key, timeouts, bad JSON), config, local command mode incl. Hindi/Hinglish greetings, auth, tokens (tampered/expired/`alg=none`/wrong kind), rate limiting, memory CRUD/search/isolation, sensitive-data refusal, DB failure ⇒ nothing reported saved, permissions, confirmation flow, unknown/invalid tool rejection, prompt-injection containment, bounded tool loop, pairing/approval/revocation, task queue, expiry, cross-device isolation, security headers |
| desktop/tests | 19 | allowlist enforcement, path traversal & symlink escape, no-overwrite notes/organise, URL schemes, agent state machine (pending/revoked/offline), task timeout, TTS (Hindi voice selection, interruption), STT failure handling, missing voice packages, credential file permissions |
| tests/test_e2e.py | 1 | real HTTP server + real desktop agent: CLI pairing → pending → owner approval → "open notepad on my computer" via chat → document read → path escape blocked → organise denied until permitted → confirmation → files moved → revoke cuts agent off → audit trail |

The web console was additionally driven in headless Chromium (login, greeting, time tool,
memory approval, every screen, mobile width) with zero console errors.

## Feature checklist

### Backend & AI
- ✅ Starlette + Pydantic API (FastAPI not installable here; see ARCHITECTURE for the trade-off)
- ✅ Provider abstraction; switch by config only; model never hardcoded
- ✅ Anthropic Messages API provider — 🟡 *not called live (no API key in the build environment)*
- ✅ OpenAI-compatible provider (OpenAI/Groq/OpenRouter/Ollama…) — 🟡 *not called live*
- ✅ Local command mode (no AI) with English/Hinglish/Hindi greetings
- ✅ Timeouts, retries with backoff, honest error messages
- ✅ Tool loop with max rounds; tool failures reported, never faked
- ✅ Hindi / Hinglish / English replies — instructed in the system prompt; quality depends on the chosen model
- ✅ Web search via Brave or Tavily with source URLs — 🟡 *APIs not called live*
- ✅ Conversation summaries saved to memory (needs an AI provider)
- ❌ Document upload from the web console/phone (documents are read on the PC from approved folders)

### Memory
- ✅ Save / search (SQLite FTS5) / edit / delete / clear; per-user isolation
- ✅ Approval before the assistant saves a memory (default on)
- ✅ Disable memory; clear conversation history; temporary context vs saved memory
- ✅ Refuses passwords, OTPs, card numbers (Luhn), CVV, Aadhaar, PAN, API keys, UPI PIN

### Security
- ✅ scrypt password hashing, HS256 JWTs, device secrets hashed at rest
- ✅ Device pairing: single-use 10-minute code → device *pending* → owner approval → token
- ✅ Revocation takes effect on the next request
- ✅ Permissions the model cannot change; confirmations only via the user's authenticated request
- ✅ Untrusted-content marking for web/document results
- ✅ Rate limits, CSP and security headers, safe error responses, redacted audit log
- 🟡 TLS — expected from a reverse proxy/Tailscale in front; not set up here

### Web console (10 screens)
- ✅ Startup (real checks), dashboard, voice, chat, device control, connected devices, memory, AI provider, privacy, history
- ✅ States idle/listening/processing/speaking driven by real events
- 🟡 Browser speech recognition/synthesis — code paths written; headless Chromium has no microphone, so not exercised
- ✅ Optional wake word (tab must be open & visible) — 🟡 not exercised (needs a mic)

### Windows desktop
- ✅ Device agent: outbound polling, token refresh, pending/revoked/offline handling, task timeouts
- ✅ Allowlisted actions: open app, open URL, create note, list folder, read document (txt/md/csv/…; PDF/DOCX with optional packages), organise folder (confirmation required, no overwrite, no delete)
- ✅ No arbitrary command execution, no delete/install/admin actions exist at all
- ✅ Credential storage via Windows Credential Manager (keyring) or a user-only file
- 🟡 PySide6 GUI (`desktop/jarvis_desktop/ui/main_window.py`) — not run (PySide6 unavailable)
- 🟡 Voice: pyttsx3 SAPI TTS, SpeechRecognition push-to-talk — logic tested with fakes; real audio not run
- 🟡 PyInstaller spec — not built (needs Windows)
- ❌ Windows executable — **not built**
- ❌ Wake word on desktop

### Android
- 🟡 Complete Kotlin/Compose project: startup, login, dashboard, voice, chat, devices, memory, AI provider, privacy, history
- 🟡 SpeechRecognizer push-to-talk (Hindi/English), TextToSpeech with interruption and rate
- 🟡 Intent tools: open app/URL/camera/settings, notes & reminders (Room + Clock app), battery, SMS draft, dial prep
- 🟡 EncryptedSharedPreferences for tokens/device secret; HTTPS-only network config
- 🟡 One JVM unit test (API contract against a real backend response)
- ❌ APK — **not built** (no Android SDK / Maven access). Kotlin sources passed a syntax-only parse with the Kotlin 2.0.21 compiler; full compilation has not happened, so expect to fix small compile issues on first build.
- ❌ Wake word / background listening (see ANDROID.md for why)
- ❌ Executing phone tasks while the app is in the background

### Cross-device
- ✅ Shared history, memories and settings (all live on the backend)
- ✅ Device status (online = heartbeat within 45 s)
- ✅ Phone → PC tasks and results; results flow back into the chat
- ❌ Push notifications (devices poll instead)

### Data
- ✅ SQLite with forward-only migrations (`backend/jarvis/migrations`)
- ❌ PostgreSQL — schema is portable, but no driver was available to implement/test it

## What you need to provide
1. An LLM: an Anthropic or OpenAI-compatible API key, **or** a local Ollama install (free).
2. Optional: a Brave Search or Tavily API key for web search.
3. A way to reach the backend over HTTPS from your phone (Tailscale recommended, free for personal use).
4. Android Studio (for the APK) and a Windows PC with Python 3.11+ (for the desktop app / .exe).
