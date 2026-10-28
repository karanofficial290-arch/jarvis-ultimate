# Architecture

## Components

| | Tech | Role |
|---|---|---|
| Backend | Python, Starlette, Pydantic, Uvicorn, SQLite (FTS5) | Auth, conversations, memory, tool framework, AI providers, search, device registry & task queue, serves the web console |
| Web console | Vanilla JS + Canvas, Web Speech API | Fastest way to use Jarvis anywhere; all 10 screens |
| Windows app | Python, PySide6, pyttsx3, SpeechRecognition, keyring, PyInstaller | Chat/voice UI + device agent that executes allowlisted actions |
| Android app | Kotlin, Jetpack Compose, OkHttp, kotlinx.serialization, Room, EncryptedSharedPreferences | Chat/voice UI + device agent for phone intents |

## Request flow (chat)
1. Client `POST /api/chat` with a user token.
2. Backend stores the message, builds the system prompt (time, language rules, honesty and
   security rules, relevant approved memories), loads the last 24 messages.
3. Provider is called with only the tools the user has *permitted* and that have a paired device.
4. For each tool call: validate → permission → confirmation? → run (server) or enqueue (device)
   and wait up to `JARVIS_DEVICE_WAIT_S` for the device result → audit → feed the result back.
5. Up to 5 tool rounds, then a final answer. Response includes tool events and pending approvals.

## Device flow
`pairing-code (owner)` → `pair (device, pending)` → `approve (owner)` → `token (device)` →
loop: `heartbeat` / `GET tasks/next` (claims one) → execute locally → `POST result`.
Tasks expire after 5 minutes. Devices are "online" if seen in the last 45 s.

## Key trade-offs
- **Starlette instead of FastAPI.** FastAPI could not be installed in the build environment, and
  FastAPI is a layer over Starlette + Pydantic. Using them directly kept every line tested. Porting
  to FastAPI later is mechanical (routes → decorators; the Pydantic bodies already exist).
- **Polling instead of WebSockets/push.** Works through NAT and firewalls with no open ports and no
  extra service (no FCM account). Cost: up to ~2 s latency and a request every 1.5–2 s while a
  device is active.
- **SQLite instead of PostgreSQL.** One personal user ⇒ SQLite is simpler and needs no server. The
  schema uses portable types; for Postgres replace `AUTOINCREMENT` with identity columns and the
  FTS5 table with a `tsvector` index, and add a driver (`psycopg`). Not done because no driver was
  installable to test it.
- **Local command mode.** A deterministic matcher keeps the full pipeline usable and testable
  without any API key, and is always labelled "no AI" in the UIs.
- **Browser/OS speech engines.** No paid speech service and no model downloads; quality and privacy
  depend on the platform (documented). Whisper/Vosk could be added behind the same interfaces.
- **Phone tasks only while the app is open.** Android blocks background apps from launching other
  apps; a foreground service would add a permanent notification and battery cost.

## Data model
`users`, `user_settings` (JSON: permissions, memory switches, voice, timezone), `conversations`,
`messages` (incl. tool calls/results), `memories` + `memories_fts`, `devices`, `pairing_codes`,
`pending_actions`, `device_tasks`, `audit_log`. See `backend/jarvis/migrations/001_init.sql`.

## Adding a tool
1. Define a Pydantic args model and a `Tool(...)` entry in `backend/jarvis/tools/catalog.py`
   (target, permission, confirmation, timeout, handler for server tools).
2. For device tools, implement it in `desktop/jarvis_desktop/local_tools.py` or
   `android/.../device/AndroidTools.kt` and add it to the device's capabilities.
3. `python -m jarvis.tools.export` to refresh `shared/tool_catalog.json`; add tests.
