CREATE TABLE reader_highlighter_config (
    id TEXT PRIMARY KEY CHECK (id = 'global'),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    updated_at TEXT NOT NULL
);

INSERT INTO reader_highlighter_config(id, row_version, updated_at)
VALUES ('global', 1, strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'));

CREATE TABLE reader_highlighter_terms (
    id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL DEFAULT 'global'
        REFERENCES reader_highlighter_config(id) ON DELETE CASCADE,
    term TEXT NOT NULL CHECK (length(trim(term)) BETWEEN 1 AND 200),
    normalized_term TEXT NOT NULL UNIQUE CHECK (length(normalized_term) BETWEEN 1 AND 400),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    color TEXT NOT NULL CHECK (length(color) = 7 AND substr(color, 1, 1) = '#'),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(config_id, ordinal)
);

CREATE INDEX reader_highlighter_terms_active_order
ON reader_highlighter_terms(config_id, active, ordinal);
