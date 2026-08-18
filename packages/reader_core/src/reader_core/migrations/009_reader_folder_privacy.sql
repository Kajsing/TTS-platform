CREATE TABLE reader_folder_privacy (
    folder_id TEXT PRIMARY KEY
        REFERENCES reader_folders(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL CHECK (length(code_hash) BETWEEN 64 AND 512),
    recovery_hash TEXT NOT NULL CHECK (length(recovery_hash) BETWEEN 64 AND 512),
    updated_at TEXT NOT NULL
);
