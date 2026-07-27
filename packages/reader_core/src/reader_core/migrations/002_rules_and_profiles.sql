CREATE TABLE reader_rule_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 200),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    scope TEXT NOT NULL CHECK (scope IN ('system', 'global', 'language', 'voice_engine', 'document')),
    source_sha256 TEXT,
    version INTEGER NOT NULL CHECK (version > 0),
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_import_metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE reader_speech_rules (
    id TEXT PRIMARY KEY,
    rule_set_id TEXT NOT NULL REFERENCES reader_rule_sets(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 200),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    stage TEXT NOT NULL CHECK (stage IN ('cleanup', 'pronunciation', 'markup')),
    rule_type TEXT NOT NULL CHECK (rule_type IN ('literal_replace', 'regex_replace', 'skip', 'spell', 'pause', 'phoneme')),
    pattern TEXT NOT NULL CHECK (length(pattern) > 0 AND length(pattern) <= 2048),
    replacement TEXT NOT NULL DEFAULT '' CHECK (length(replacement) <= 4096),
    case_sensitive INTEGER NOT NULL CHECK (case_sensitive IN (0, 1)),
    whole_word INTEGER NOT NULL CHECK (whole_word IN (0, 1)),
    language_filter TEXT,
    engine_filter TEXT,
    voice_filter TEXT,
    document_filter TEXT,
    priority INTEGER NOT NULL CHECK (priority BETWEEN -100000 AND 100000),
    regex_timeout_ms INTEGER NOT NULL CHECK (regex_timeout_ms BETWEEN 1 AND 1000),
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_import_metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE reader_rule_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    rules_version INTEGER NOT NULL CHECK (rules_version > 0),
    updated_at TEXT NOT NULL
);

INSERT INTO reader_rule_state(singleton_id, rules_version, updated_at)
VALUES (1, 1, '1970-01-01T00:00:00+00:00');

CREATE TABLE reader_rule_imports (
    id TEXT PRIMARY KEY,
    target_rule_set_id TEXT NOT NULL REFERENCES reader_rule_sets(id) ON DELETE CASCADE,
    source_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    report_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(target_rule_set_id, source_sha256)
);

CREATE TABLE reader_voice_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0 AND length(name) <= 200),
    voice_id TEXT NOT NULL,
    language_hint TEXT,
    rate REAL NOT NULL DEFAULT 1.0,
    volume REAL NOT NULL DEFAULT 1.0,
    pitch REAL NOT NULL DEFAULT 0.0,
    sentence_pause_ms INTEGER NOT NULL DEFAULT 120 CHECK (sentence_pause_ms >= 0),
    comma_pause_ms INTEGER NOT NULL DEFAULT 60 CHECK (comma_pause_ms >= 0),
    rule_set_ids_json TEXT NOT NULL DEFAULT '[]',
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_reader_rule_sets_scope ON reader_rule_sets(scope, enabled, created_at, id);
CREATE INDEX idx_reader_speech_rules_order ON reader_speech_rules(rule_set_id, stage, priority, created_at, id);
CREATE INDEX idx_reader_rule_imports_source ON reader_rule_imports(target_rule_set_id, source_sha256);
