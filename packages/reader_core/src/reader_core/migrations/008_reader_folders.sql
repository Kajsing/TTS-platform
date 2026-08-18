CREATE TABLE reader_folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
    normalized_name TEXT NOT NULL UNIQUE CHECK (length(normalized_name) BETWEEN 1 AND 400),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0)
);

ALTER TABLE reader_documents
ADD COLUMN folder_id TEXT REFERENCES reader_folders(id) ON DELETE SET NULL;

CREATE INDEX idx_reader_documents_folder_list
ON reader_documents(folder_id, updated_at DESC, id DESC)
WHERE deleted_at IS NULL;
