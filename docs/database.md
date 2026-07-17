# Database

Mentat stores core data in SQLite. By default the database lives at `data/mentat.db` and fresh installs create the required schema automatically when Mentat starts.

## Location And Lifecycle

```env
DATABASE_PATH=data/mentat.db
```

Relative `DATABASE_PATH` values are resolved from the project root. The database is runtime state, not source code: do not commit personal `data/mentat.db` files.

## Core Tables

### `memories`

Primary memory records created by capture, link ingestion, voice capture, chat saves, and related commands.

Schema, as initialized by `mentat/core/database.py`:

```sql
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    command_type TEXT NOT NULL,
    tags TEXT,
    metadata TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, content, command_type)
);
```

Important columns:

- `id` — durable memory id used by top-level `view`, `delete`, and other agent-friendly commands.
- `user_id` — separates memories by user/profile.
- `content` — saved note, link URL/comment, transcript, or generated memory text.
- `command_type` — classification such as `idea`, `task`, `link`, `reflection`, `voice_conversation`, or `ai_response`.
- `tags` — serialized tags used by search and display.
- `metadata` — JSON metadata for entities, todos, links, summaries, and command-specific details.
- `timestamp` — creation time used by temporal queries and recent/latest views.

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_command_type ON memories(command_type);
CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp);
```

### `memories_fts`

FTS5 search index over memory content, tags, and user id:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, tags, user_id);
```

This table supports keyword search. Mentat rebuilds or refreshes entries from `memories` when needed. If search results look stale after manual database edits, avoid editing the FTS table directly; rebuild through Mentat's maintenance/search paths or recreate from `memories`.

### `mem_embeddings`

Stores serialized semantic embeddings for memory ids:

```sql
CREATE TABLE IF NOT EXISTS mem_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    embedding TEXT NOT NULL
);
```

Embeddings are generated locally by sentence-transformers by default. They are used for semantic search and hybrid chat retrieval.

### `chat_sessions`

Tracks enhanced chat sessions, created by `mentat/chat/session_store.py`:

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_key TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    summary TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`session_key` is generated from `user_id`, channel, and thread id. `summary` stores compact session context when old messages are summarized.

### `chat_messages`

Stores enhanced chat message history:

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_key) REFERENCES chat_sessions(session_key)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
ON chat_messages(session_key, created_at);
```

## Search Data Flow

- Keyword search reads `memories_fts` and joins back to `memories` for full records.
- Semantic search reads `mem_embeddings` and compares stored embedding vectors.
- Hybrid search merges keyword and semantic candidates, then ranks and truncates results.
- Temporal queries filter `memories.timestamp` before or alongside normal retrieval.

## Migrations And Schema Changes

Mentat currently initializes tables with `CREATE TABLE IF NOT EXISTS` and adds indexes on startup. When changing schema:

1. Keep fresh-install creation in sync with existing-database migration behavior.
2. Preserve existing `id` values; they are user-visible durable references.
3. Update this document when adding tables, indexes, metadata fields, or search behavior.
4. Add tests for both fresh databases and upgraded existing databases when practical.

## Backup And Restore

For a simple local backup, copy the SQLite database and markdown export directory while Mentat is not actively writing:

```bash
cp data/mentat.db data/mentat.db.backup
cp -R data/markdown data/markdown.backup
```

For a safer live SQLite backup, use SQLite's backup command:

```bash
sqlite3 data/mentat.db ".backup data/mentat.db.backup"
```

Restoring is the reverse: stop Mentat, replace `data/mentat.db` with the backup, then start Mentat again.
