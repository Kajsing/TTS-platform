-- Creation retry identities survive grant renewal and ordinary article edits.
-- Soft deletion keeps the identity; scope is checked again before any replay.
CREATE TABLE reader_agent_creations (
    folder_id TEXT NOT NULL REFERENCES reader_folders(id) ON DELETE CASCADE,
    retry_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    PRIMARY KEY (folder_id, retry_key)
);
