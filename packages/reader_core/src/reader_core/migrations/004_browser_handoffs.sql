CREATE TABLE reader_desktop_open_requests (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_reader_desktop_open_document
    ON reader_desktop_open_requests(document_id);
CREATE INDEX idx_reader_desktop_open_order
    ON reader_desktop_open_requests(created_at, id);
