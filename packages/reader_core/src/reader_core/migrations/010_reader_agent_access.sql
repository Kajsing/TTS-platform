CREATE TABLE reader_agent_grants (
    id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL REFERENCES reader_folders(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    credential_hash TEXT NOT NULL UNIQUE CHECK (length(credential_hash) = 64),
    operations_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

-- Enabling Privacy lock permanently revokes existing agent grants. Removing
-- the lock later must not silently revive an old credential.
CREATE TRIGGER revoke_agents_on_folder_privacy
AFTER INSERT ON reader_folder_privacy
BEGIN
    UPDATE reader_agent_grants SET revoked_at = NEW.updated_at
    WHERE folder_id = NEW.folder_id AND revoked_at IS NULL;
END;

CREATE TABLE reader_agent_chapters (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    story_key TEXT NOT NULL,
    chapter_key TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    order_label TEXT,
    order_index INTEGER,
    order_warning TEXT,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    edit_id TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    result_row_version INTEGER NOT NULL,
    result_content_revision INTEGER NOT NULL,
    UNIQUE(document_id, story_key, chapter_key)
);

-- Receipts deliberately outlive Undo/history trimming and soft deletion.
-- A retry is a delivery acknowledgement, not a command to restore removed text.
CREATE TABLE reader_agent_chapter_retries (
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    retry_key TEXT NOT NULL,
    chapter_id TEXT NOT NULL REFERENCES reader_agent_chapters(id) ON DELETE CASCADE,
    PRIMARY KEY(document_id, retry_key)
);

CREATE INDEX idx_reader_agent_chapters_document
ON reader_agent_chapters(document_id, imported_at, id);
