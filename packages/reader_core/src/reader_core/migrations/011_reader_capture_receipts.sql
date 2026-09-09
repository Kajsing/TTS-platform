-- Receipts outlive soft deletion and Undo. Retrying delivery is not Redo.
CREATE TABLE reader_capture_receipts (
    operation_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    document_id TEXT NOT NULL,
    committed_at TEXT NOT NULL
);
