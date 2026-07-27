CREATE TABLE reader_export_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    document_ids_json TEXT NOT NULL,
    section_ids_json TEXT NOT NULL DEFAULT '[]',
    start_cursor_json TEXT,
    end_cursor_json TEXT,
    voice_id TEXT,
    output_basename TEXT,
    overwrite_existing INTEGER NOT NULL CHECK (overwrite_existing IN (0, 1)),
    total_documents INTEGER NOT NULL CHECK (total_documents > 0),
    completed_documents INTEGER NOT NULL DEFAULT 0 CHECK (completed_documents >= 0),
    current_document_id TEXT,
    output_files_json TEXT NOT NULL DEFAULT '[]',
    error_type TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    row_version INTEGER NOT NULL CHECK (row_version > 0)
);

CREATE INDEX idx_reader_export_jobs_status
    ON reader_export_jobs(status, created_at, id);
