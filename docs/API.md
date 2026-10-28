# API reference

All bodies are JSON. Errors: `{"error": "<safe message>"}` with a matching status code.
`U` = user token, `D` = device token (`Authorization: Bearer <token>`).

| Method & path | Auth | Purpose |
|---|---|---|
| GET `/api/health` | – | liveness |
| GET `/api/status` | – | version, provider (name/model/ai), search status, registration_open, permission labels |
| POST `/api/auth/register` | – | `{username, password}` — first account, or if registration is enabled |
| POST `/api/auth/login` | – | `{username, password}` → `{token}` |
| GET `/api/me` | U | current user |
| GET / PUT `/api/settings` | U | memory switches, permissions, voice, timezone, name |
| POST `/api/chat` | U | `{message, conversation_id?}` → `{conversation_id, reply, error, tool_events, pending_actions, provider}` |
| GET / DELETE `/api/conversations` | U | list / clear all history |
| GET `/api/conversations/{id}/messages` | U | messages |
| DELETE `/api/conversations/{id}` | U | delete one |
| POST `/api/conversations/{id}/summarize` | U | save an AI summary to memory |
| GET `/api/memories[?q=]` · POST · DELETE | U | list/search · add `{content, kind}` · clear all |
| PUT / DELETE `/api/memories/{id}` | U | edit / delete |
| GET `/api/actions` | U | pending confirmations |
| POST `/api/actions/{id}/confirm` · `/deny` | U | approve or deny (the only way an action requiring confirmation can run) |
| GET `/api/tools` | U | tool catalog with availability and input schemas |
| GET / POST `/api/tasks` | U | list device tasks / send a device tool directly `{tool, args}` |
| GET `/api/tasks/{id}` | U | task status/result |
| GET `/api/devices` | U | devices with online status |
| POST `/api/devices/pairing-code` | U | new single-use code |
| POST `/api/devices/{id}/approve` · `/revoke` | U | owner decisions |
| POST `/api/devices/pair` | – | `{code, name, platform}` → `{device_id, device_secret}` (pending) |
| POST `/api/devices/token` | – | `{device_id, device_secret}` → device token (approved devices only) |
| POST `/api/device/heartbeat` | D | `{capabilities}` |
| GET `/api/device/tasks/next` | D | claim next task (204 if none) |
| POST `/api/device/tasks/{id}/result` | D | `{ok, data, error?}` |
| GET `/api/audit` | U | automation history (redacted) |

## Tools
See `shared/tool_catalog.json` (generated from code) for every tool's target, permission,
confirmation rule and JSON schema.

## Provider configuration
| Variable | Meaning |
|---|---|
| `JARVIS_LLM_PROVIDER` | `local-rules` (no AI), `none`, `anthropic`, `openai-compatible` |
| `JARVIS_LLM_MODEL` | required for real providers; taken from your provider's current docs |
| `JARVIS_LLM_API_KEY` | provider key (optional for local Ollama) |
| `JARVIS_LLM_BASE_URL` | for `openai-compatible`, e.g. `https://api.openai.com/v1`, `https://api.groq.com/openai/v1`, `https://openrouter.ai/api/v1`, `http://localhost:11434/v1` |
| `JARVIS_LLM_TIMEOUT_S`, `JARVIS_LLM_MAX_RETRIES`, `JARVIS_LLM_MAX_TOKENS` | resilience and length |
| `JARVIS_SEARCH_PROVIDER` / `JARVIS_SEARCH_API_KEY` | `brave` or `tavily` |

Switching providers is a config change and restart — no code changes. Model names change over
time, so none is hardcoded.
