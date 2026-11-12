CREATE INDEX authorship_author ON authorship(author_id,paper_id);
CREATE INDEX downloads_paper ON downloads(paper_id,status);
CREATE INDEX affiliations_author ON affiliations(author_id,paper_id);
CREATE INDEX review_history_paper ON review_history(paper_id,created);
CREATE INDEX evidence_paper ON evidence(paper_id);
