-- InsightForge control-plane schema.
-- "core" holds metadata about datasets; "data" holds the actual loaded tables.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS data;

CREATE TABLE IF NOT EXISTS core.datasets (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    source_kind     TEXT NOT NULL,                 -- upload | manual | paste
    source_name     TEXT NOT NULL DEFAULT '',
    table_name      TEXT NOT NULL UNIQUE,          -- physical table inside schema "data"
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|etl|profiling|indexing|ready|error
    row_count       INTEGER NOT NULL DEFAULT 0,
    column_count    INTEGER NOT NULL DEFAULT 0,
    quality_score   REAL NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.dataset_columns (
    id              BIGSERIAL PRIMARY KEY,
    dataset_id      TEXT NOT NULL REFERENCES core.datasets(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    name            TEXT NOT NULL,                 -- cleaned, snake_case
    original_name   TEXT NOT NULL,
    pg_type         TEXT NOT NULL,                 -- physical Postgres type
    semantic_type   TEXT NOT NULL,                 -- numeric|integer|datetime|boolean|categorical|text|identifier
    null_count      INTEGER NOT NULL DEFAULT 0,
    distinct_count  INTEGER NOT NULL DEFAULT 0,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (dataset_id, name)
);

CREATE TABLE IF NOT EXISTS core.etl_runs (
    id              BIGSERIAL PRIMARY KEY,
    dataset_id      TEXT NOT NULL REFERENCES core.datasets(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,                 -- running|success|error
    rows_in         INTEGER NOT NULL DEFAULT 0,
    rows_out        INTEGER NOT NULL DEFAULT 0,
    steps           JSONB NOT NULL DEFAULT '[]'::jsonb,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS core.rag_chunks (
    id              BIGSERIAL PRIMARY KEY,
    dataset_id      TEXT NOT NULL REFERENCES core.datasets(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,                 -- overview|schema|column|rows|insight
    ref             TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rag_chunks_dataset_idx ON core.rag_chunks (dataset_id);
CREATE INDEX IF NOT EXISTS rag_chunks_fts_idx
    ON core.rag_chunks USING GIN (to_tsvector('english', content));

CREATE TABLE IF NOT EXISTS core.conversations (
    id              TEXT PRIMARY KEY,
    dataset_id      TEXT REFERENCES core.datasets(id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT 'New conversation',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES core.conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                 -- user|assistant
    content         TEXT NOT NULL,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- sql, tables, charts, citations
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_conversation_idx ON core.messages (conversation_id, id);
