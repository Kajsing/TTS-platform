CREATE TABLE reader_documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    source_type TEXT NOT NULL,
    source_name TEXT,
    source_uri TEXT,
    source_sha256 TEXT,
    language_hint TEXT,
    state TEXT NOT NULL CHECK (state IN ('inbox', 'active', 'finished', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    deleted_at TEXT,
    content_revision INTEGER NOT NULL CHECK (content_revision > 0),
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    total_sections INTEGER NOT NULL CHECK (total_sections >= 0),
    total_blocks INTEGER NOT NULL CHECK (total_blocks >= 0),
    total_characters INTEGER NOT NULL CHECK (total_characters >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE reader_sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    parent_section_id TEXT REFERENCES reader_sections(id) ON DELETE SET NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    level INTEGER NOT NULL CHECK (level > 0),
    heading TEXT,
    first_block_ordinal INTEGER NOT NULL CHECK (first_block_ordinal >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (document_id, ordinal)
);

CREATE TABLE reader_blocks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    section_id TEXT REFERENCES reader_sections(id) ON DELETE SET NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    character_count INTEGER NOT NULL CHECK (character_count >= 0),
    content_sha256 TEXT NOT NULL,
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (document_id, ordinal)
);

CREATE TABLE reader_playback_positions (
    document_id TEXT PRIMARY KEY REFERENCES reader_documents(id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES reader_blocks(id) ON DELETE CASCADE,
    block_ordinal INTEGER NOT NULL CHECK (block_ordinal >= 0),
    character_offset INTEGER NOT NULL CHECK (character_offset >= 0),
    content_revision INTEGER NOT NULL CHECK (content_revision > 0),
    segment_index INTEGER,
    voice_profile_id TEXT,
    pipeline_version INTEGER NOT NULL CHECK (pipeline_version > 0),
    rules_version INTEGER NOT NULL CHECK (rules_version > 0),
    updated_at TEXT NOT NULL,
    completed INTEGER NOT NULL CHECK (completed IN (0, 1)),
    row_version INTEGER NOT NULL CHECK (row_version > 0)
);

CREATE TABLE reader_bookmarks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES reader_blocks(id) ON DELETE CASCADE,
    block_ordinal INTEGER NOT NULL CHECK (block_ordinal >= 0),
    character_offset INTEGER NOT NULL CHECK (character_offset >= 0),
    content_revision INTEGER NOT NULL CHECK (content_revision > 0),
    segment_index INTEGER,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL CHECK (row_version > 0)
);

CREATE TABLE reader_queue_items (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'playing', 'completed', 'skipped')),
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL CHECK (row_version > 0),
    UNIQUE (ordinal)
);

CREATE TABLE reader_document_edits (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reader_documents(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    base_content_revision INTEGER NOT NULL CHECK (base_content_revision > 0),
    result_content_revision INTEGER NOT NULL CHECK (result_content_revision > base_content_revision),
    block_id TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
    original_text TEXT NOT NULL,
    replacement_text TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('replace', 'append')),
    created_at TEXT NOT NULL,
    applied INTEGER NOT NULL CHECK (applied IN (0, 1)),
    undone_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (document_id, sequence)
);

CREATE INDEX idx_reader_documents_list
    ON reader_documents(state, updated_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_reader_documents_all_list
    ON reader_documents(updated_at DESC, id DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_reader_blocks_order ON reader_blocks(document_id, ordinal);
CREATE INDEX idx_reader_bookmarks_order ON reader_bookmarks(document_id, block_ordinal, character_offset);
CREATE INDEX idx_reader_edits_history ON reader_document_edits(document_id, sequence);
CREATE UNIQUE INDEX idx_reader_queue_single_playing
    ON reader_queue_items(status) WHERE status = 'playing';
