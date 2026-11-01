-- Managed imports use a folder-local story namespace. Legacy article receipts
-- remain unchanged; only explicitly prepared M2 parts are managed here.
CREATE TABLE reader_agent_stories (
    folder_id TEXT NOT NULL REFERENCES reader_folders(id) ON DELETE CASCADE,
    story_key TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    PRIMARY KEY (folder_id, story_key)
);

CREATE TABLE reader_agent_import_plans (
    id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    story_key TEXT NOT NULL,
    retry_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    wrapper TEXT NOT NULL,
    title TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    parts_json TEXT NOT NULL,
    base_story_version INTEGER NOT NULL,
    next_index INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (folder_id, retry_key),
    FOREIGN KEY (folder_id, story_key)
        REFERENCES reader_agent_stories(folder_id, story_key) ON DELETE CASCADE
);

CREATE TABLE reader_agent_import_parts (
    folder_id TEXT NOT NULL,
    story_key TEXT NOT NULL,
    part_number INTEGER NOT NULL,
    plan_id TEXT NOT NULL REFERENCES reader_agent_import_plans(id) ON DELETE CASCADE,
    plan_part_number INTEGER NOT NULL,
    document_id TEXT NOT NULL UNIQUE REFERENCES reader_documents(id) ON DELETE CASCADE,
    last_row_version INTEGER NOT NULL,
    PRIMARY KEY (folder_id, story_key, part_number),
    UNIQUE (plan_id, plan_part_number),
    FOREIGN KEY (folder_id, story_key)
        REFERENCES reader_agent_stories(folder_id, story_key) ON DELETE CASCADE
);

CREATE TABLE reader_agent_import_assignments (
    folder_id TEXT NOT NULL,
    story_key TEXT NOT NULL,
    chapter_key TEXT NOT NULL,
    plan_id TEXT NOT NULL REFERENCES reader_agent_import_plans(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    receipt_id TEXT NOT NULL UNIQUE REFERENCES reader_agent_chapters(id) ON DELETE CASCADE,
    part_number INTEGER NOT NULL,
    PRIMARY KEY (folder_id, story_key, chapter_key),
    UNIQUE (plan_id, chapter_index),
    FOREIGN KEY (folder_id, story_key)
        REFERENCES reader_agent_stories(folder_id, story_key) ON DELETE CASCADE
);

CREATE INDEX idx_reader_agent_story_receipts
ON reader_agent_chapters(story_key, imported_at, id);

CREATE INDEX idx_reader_agent_import_plans_folder
ON reader_agent_import_plans(folder_id, story_key);
