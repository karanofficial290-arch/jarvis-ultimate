# Security & privacy

## Threat model in one paragraph
The assistant is driven by an LLM, and LLMs can be manipulated by text they read (web pages,
documents, messages). So the design never trusts the model with authority: **the model can only
*request* tools; code decides.** Separately, the phone and PC are valuable targets, so they never
listen on the network, never run arbitrary commands, and only act inside lists you control.

## Controls

| Area | Control | Where |
|---|---|---|
| Secrets | API keys and signing key only in backend env vars / `.env` (git-ignored). Apps hold no provider keys. Placeholder secret is rejected; production refuses to start without one. | `config.py`, `.env.example` |
| Accounts | scrypt password hashing; first account is the owner; registration closed afterwards unless enabled | `security.py`, `app.py` |
| Tokens | HS256 JWT with expiry and `kind` (user/device); `alg=none` and wrong kinds rejected; users re-checked per request | `security.py` |
| Devices | Single-use, 10-minute pairing code → device starts **pending** → owner approves → device secret (stored hashed) → 1-hour device token. Revocation is checked on every request. | `devices.py` |
| Authorization | Every query is scoped by `user_id`; devices can only claim/complete their own tasks; device tokens can't call user endpoints | `app.py`, tests |
| Tools | Pydantic validation (extra fields forbidden) → permission switch → confirmation → execution with timeout → audit. Unknown tools rejected. | `tools/base.py` |
| Self-escalation | No tool exists to change permissions or approve actions; approvals require the user's own authenticated HTTP call. Pending actions expire after 15 minutes and can't be approved twice. | `tools/base.py` |
| Prompt injection | Web/document/folder results are flagged `untrusted_content`; system prompt says to treat them as data. Even if the model obeys an injection, sensitive tools still stop at confirmation (tested). | `assistant.py`, `test_api_chat.py` |
| Confirmations | Required for: saving memories (default), SMS drafts, call preparation, organising files. Calls/SMS are never sent automatically on Android — the user presses Send/Call. | `tools/catalog.py` |
| PC sandbox | Allowlist of exact executable paths, folders and actions, edited only on the PC. Paths resolved with `realpath` + `commonpath` (blocks `..` and symlink escapes). Notes use exclusive create (never overwrite); organise moves only, skips conflicts. No shell, no delete, no install, no admin. | `desktop/jarvis_desktop/` |
| Network | Devices make outbound HTTPS only. Bind the backend to 127.0.0.1 and put TLS in front (Tailscale/Caddy). Android blocks cleartext except emulator loopback. | `__main__.py`, `network_security_config.xml` |
| Abuse | Token-bucket rate limits on login, pairing, chat and tasks | `security.py`, `app.py` |
| Web console | Strict CSP (no inline/eval scripts), `X-Frame-Options: DENY`, all user text rendered with `textContent` | `app.py`, `static/app.js` |
| Logging | Audit log stores redacted arguments (secrets removed, message/note bodies replaced by length). Errors returned to clients are generic. | `security.redact` |
| Memory | Refuses passwords, OTPs, card numbers, CVV, Aadhaar, PAN, API keys, UPI PIN; can be disabled; per-item delete; clear-all | `memory.py` |
| Credentials on devices | Android: EncryptedSharedPreferences (Keystore). Windows: Credential Manager via `keyring`, else user-only file. | |

## Privacy notes
- **Voice:** Chrome's web speech recognition and Android's default recognizer may send audio to
  Google. Desktop push-to-talk uses Google Web Speech via `SpeechRecognition`. Text-to-speech on
  Windows (SAPI) and Android is on-device. The microphone opens only on an explicit tap/press,
  and the UI shows "Listening" only while it is open.
- **AI provider:** conversation text and approved memories are sent to the provider you configure.
  Use Ollama for a fully local setup.
- **What is stored:** account, conversations, approved memories, settings, devices, task results and
  the audit log — all in the backend SQLite file. Back it up and protect it like any personal data.

## Known limitations
- Rate limiting and the pairing flow are single-process (fine for one personal server).
- No 2FA on the owner account yet; protect the backend behind Tailscale.
- JWT revocation for *user* tokens relies on expiry (12 h); device tokens are revocable instantly.
- The web console stores its session token in `localStorage` (mitigated by the strict CSP).
