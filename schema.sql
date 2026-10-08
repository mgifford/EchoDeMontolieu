-- Public, derived layer. Built from public/ by `python -m echo_montolieu build-db`; never committed.
-- Names are scrubbed (elected officials on the attendance list may appear); property sales appear
-- only as a count and a neutral title, with no text, places or amounts. This is the only database
-- the website, the API and the MCP server may read.
PRAGMA journal_mode = DELETE;

CREATE TABLE meetings (
    id TEXT PRIMARY KEY,               -- document_id
    date TEXT NOT NULL,                -- ISO date as read from the minutes (tentative)
    date_status TEXT,
    title TEXT,
    source_url TEXT NOT NULL,          -- the Mairie's PDF, or the Internet Archive capture
    source_sha256 TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    page_count INTEGER,
    items INTEGER NOT NULL DEFAULT 0,
    sensitive_items INTEGER NOT NULL DEFAULT 0,
    folder TEXT                        -- meetings/<folder>/ on the website
);

CREATE TABLE items (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL,
    topics TEXT NOT NULL DEFAULT '[]', -- JSON array
    vote_result TEXT,
    first_page INTEGER,
    last_page INTEGER,
    page_url TEXT,                     -- link to the first page of the original
    sensitive INTEGER NOT NULL DEFAULT 0,
    amounts TEXT NOT NULL DEFAULT '[]',-- JSON: euro figures with the sentence they come from
    body TEXT NOT NULL DEFAULT ''      -- scrubbed text; empty for sensitive items
);

CREATE TABLE summaries (
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    lang TEXT NOT NULL CHECK (lang IN ('fr', 'en', 'nl')),
    body TEXT NOT NULL,
    produced_by TEXT NOT NULL,         -- always names the AI model
    human_reviewed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (meeting_id, lang)
);

-- One searchable row per non-sensitive item and per summary.
CREATE VIRTUAL TABLE search USING fts5(
    kind UNINDEXED, ref UNINDEXED, lang UNINDEXED, title, body,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
