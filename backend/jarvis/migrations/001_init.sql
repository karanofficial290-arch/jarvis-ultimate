-- JARVIS Ultimate AI: initial schema (SQLite dialect; see docs/ARCHITECTURE.md for Postgres notes)

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE user_settings (
    user_id  INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data     TEXT NOT NULL  -- JSON
);

CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_conversations_user ON conversations(user_id, updated_at);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
    content         TEXT NOT NULL DEFAULT '',
    tool_calls      TEXT,          -- JSON list, assistant messages only
    tool_call_id    TEXT,          -- tool messages only
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('preference','project','fact','summary')),
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_memories_user ON memories(user_id);

CREATE VIRTUAL TABLE memories_fts USING fts5(content, content='memories', content_rowid='id');
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    platform     TEXT NOT NULL CHECK (platform IN ('android','desktop')),
    status       TEXT NOT NULL CHECK (status IN ('pending','approved','revoked')),
    secret_hash  TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',  -- JSON list reported by the device
    created_at   TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE pairing_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash  TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pending_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER,
    tool            TEXT NOT NULL,
    args            TEXT NOT NULL,   -- JSON, validated
    summary         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('awaiting','confirmed','denied','expired')),
    result          TEXT,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);

CREATE TABLE device_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    tool        TEXT NOT NULL,
    args        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','expired')),
    result      TEXT,
    error       TEXT,
    origin      TEXT NOT NULL DEFAULT 'assistant',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX idx_tasks_device ON device_tasks(device_id, status, id);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    actor       TEXT NOT NULL,      -- 'assistant', 'user', 'device:<id>'
    event       TEXT NOT NULL,      -- 'tool.call', 'tool.denied', 'device.paired', ...
    tool        TEXT,
    detail      TEXT,               -- redacted JSON
    status      TEXT NOT NULL,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_audit_user ON audit_log(user_id, id);
