-- Schema version 4. Apply only to a new database.
-- Times are UTC ISO 8601 strings supplied by the application.

CREATE TABLE users (
    telegram_user_id INTEGER PRIMARY KEY,
    display_name TEXT,
    username TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'revoked')),
    approved_by INTEGER REFERENCES users(telegram_user_id),
    decided_at TEXT
);

CREATE TABLE access_requests (
    id INTEGER PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by INTEGER REFERENCES users(telegram_user_id)
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE project_permissions (
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    can_read INTEGER NOT NULL DEFAULT 0 CHECK (can_read IN (0, 1)),
    can_submit INTEGER NOT NULL DEFAULT 0 CHECK (can_submit IN (0, 1)),
    PRIMARY KEY (telegram_user_id, project_id)
);

CREATE TABLE destinations (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    deleted_from_group INTEGER NOT NULL DEFAULT 0 CHECK (deleted_from_group IN (0, 1)),
    UNIQUE (chat_id, topic_id)
);
CREATE UNIQUE INDEX active_topic_name_per_group
    ON destinations(chat_id, lower(trim(name)))
    WHERE active = 1 AND deleted_from_group = 0;

CREATE TABLE project_destinations (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    destination_id INTEGER NOT NULL REFERENCES destinations(id),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    PRIMARY KEY (project_id, destination_id)
);
CREATE UNIQUE INDEX one_default_destination_per_project
    ON project_destinations(project_id) WHERE is_default = 1;

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE submission_drafts (
    id INTEGER PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    source_chat_id INTEGER NOT NULL,
    source_message_ids TEXT NOT NULL,
    source_payload TEXT NOT NULL DEFAULT '{}',
    project_id INTEGER REFERENCES projects(id),
    destination_id INTEGER REFERENCES destinations(id),
    category_id INTEGER REFERENCES categories(id),
    title TEXT,
    description TEXT,
    step TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'ready', 'publishing', 'completed', 'cancelled', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_draft_per_source_message
    ON submission_drafts(source_chat_id, source_message_ids);

CREATE TABLE content_items (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    submitter_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    title TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    original_text TEXT,
    previous_version_id TEXT REFERENCES content_items(id),
    status TEXT NOT NULL DEFAULT 'published'
        CHECK (status IN ('published', 'unavailable', 'archived')),
    created_at TEXT NOT NULL,
    published_at TEXT NOT NULL
);

CREATE TABLE attachments (
    id INTEGER PRIMARY KEY,
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    media_type TEXT NOT NULL,
    filename TEXT,
    file_id TEXT NOT NULL,
    file_unique_id TEXT,
    UNIQUE (content_id, position)
);

CREATE TABLE published_messages (
    id INTEGER PRIMARY KEY,
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('summary', 'attachment', 'text')),
    UNIQUE (chat_id, message_id)
);

CREATE TABLE search_documents (
    content_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
    searchable_text TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (extraction_status IN ('pending', 'complete', 'unsupported', 'failed')),
    extraction_method TEXT
);

CREATE TABLE item_allowlists (
    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    telegram_user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
    PRIMARY KEY (content_id, telegram_user_id)
);

CREATE TABLE publication_jobs (
    id INTEGER PRIMARY KEY,
    draft_id INTEGER NOT NULL UNIQUE REFERENCES submission_drafts(id),
    reserved_content_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('ready', 'publishing', 'published', 'indexed', 'failed', 'needs_review')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    sent_message_ids TEXT NOT NULL DEFAULT '[]',
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    actor_user_id INTEGER REFERENCES users(telegram_user_id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    result TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX content_items_project_title ON content_items(project_id, title);
CREATE INDEX content_items_published_at ON content_items(published_at);
CREATE INDEX attachments_filename ON attachments(filename);
CREATE INDEX access_requests_user_status ON access_requests(telegram_user_id, status);
CREATE UNIQUE INDEX one_pending_access_request_per_user
    ON access_requests(telegram_user_id) WHERE status = 'pending';
CREATE INDEX audit_events_occurred_at ON audit_events(occurred_at);
