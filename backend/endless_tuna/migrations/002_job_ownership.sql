ALTER TABLE jobs ADD COLUMN lease_token TEXT;
CREATE INDEX papers_edition ON papers(edition_id);
CREATE INDEX affiliations_organization ON affiliations(organization_id,paper_id);
