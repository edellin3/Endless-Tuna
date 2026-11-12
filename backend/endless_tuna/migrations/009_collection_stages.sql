ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'collect';
CREATE TABLE intake_previews(id TEXT PRIMARY KEY, source_url TEXT NOT NULL, adapter TEXT NOT NULL, name TEXT NOT NULL, year INTEGER, records TEXT NOT NULL, official_count INTEGER, created REAL NOT NULL);
CREATE INDEX intake_expiry ON intake_previews(created);
