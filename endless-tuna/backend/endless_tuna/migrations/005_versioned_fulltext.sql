DROP TABLE fulltext_fts;
CREATE VIRTUAL TABLE fulltext_fts USING fts5(paper_id UNINDEXED,page UNINDEXED,text,download_id UNINDEXED,version UNINDEXED);
INSERT INTO fulltext_fts(paper_id,page,text,download_id,version) SELECT pg.paper_id,pg.page,pg.text,pg.download_id,d.version FROM pdf_pages pg JOIN downloads d ON d.id=pg.download_id WHERE trim(pg.text)!='';
