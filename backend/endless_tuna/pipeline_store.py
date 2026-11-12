"""Canonical papers, membership evidence, and page-indexed downloads."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from . import db as storage
from .adapters import canonical_url
from .collection import CollectionError, parse_pdf_pages


def stable(value):return str(uuid.uuid5(uuid.NAMESPACE_URL,value))


def upsert_paper(con,edition,track,record,inventory_url):
    now=time.time()
    url=canonical_url(record.source_url)
    existing=con.execute('SELECT id FROM papers WHERE canonical_url=?',(url,)).fetchone()
    pid=existing['id'] if existing else stable('paper:'+url)
    if not existing:
        con.execute('INSERT INTO papers(id,edition_id,track_id,title,abstract,review_status,canonical_url) VALUES(?,?,?,?,?,?,?)',(pid,edition,track,record.title,record.abstract,'uncertain',url))
    elif record.abstract:
        con.execute("UPDATE papers SET abstract=CASE WHEN abstract='' THEN ? ELSE abstract END WHERE id=?",(record.abstract,pid))
    for namespace,value in record.identifiers.items():
        con.execute('INSERT OR IGNORE INTO paper_identifiers VALUES(?,?,?)',(pid,namespace,value))
    con.execute('INSERT INTO paper_editions VALUES(?,?,?,?,?,?) ON CONFLICT(paper_id,edition_id,track_id) DO UPDATE SET retrieved=excluded.retrieved',(pid,edition,track,url,record.inventory_url or inventory_url,now))
    # Do not overwrite reviewed authorship. Inventory authors are hydrated only on first detail fetch.
    if not con.execute('SELECT 1 FROM authorship WHERE paper_id=?',(pid,)).fetchone():
        for position,person in enumerate(record.authors,1):
            aid=stable(pid+':author:'+str(position))
            con.execute('INSERT OR IGNORE INTO authors VALUES(?,?,?)',(aid,person.name,'Identity anchored to this official paper; not merged by name.'))
            con.execute('INSERT OR IGNORE INTO authorship VALUES(?,?,?)',(pid,aid,position))
            for org in person.organizations:
                oid=stable('organization:'+org)
                con.execute('INSERT OR IGNORE INTO organizations VALUES(?,?)',(oid,org))
                con.execute('INSERT OR IGNORE INTO affiliations VALUES(?,?,?)',(pid,aid,oid))
    sid=stable(edition+':inventory:'+ (record.inventory_url or inventory_url))
    con.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?)',(sid,edition,record.inventory_url or inventory_url,'Official inventory / analyst-supplied inventory evidence'))
    con.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)',(stable(pid+sid),pid,sid,'conference membership',record.title+' — '+url))
    for warning in record.source_warnings:
        con.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)',(stable(pid+sid+warning),pid,sid,'Inventory warning — needs review',warning))
    from .enrichment import metadata_assertions
    metadata_assertions(con,pid,record)
    return pid


def hydrate_paper(con,pid,record):
    paper=con.execute('SELECT review_status FROM papers WHERE id=?',(pid,)).fetchone()
    reviewed=con.execute('SELECT 1 FROM review_history WHERE paper_id=?',(pid,)).fetchone()
    if paper['review_status']=='uncertain' and not reviewed:
        con.execute('UPDATE papers SET title=? WHERE id=?',(record.title,pid))
    con.execute("UPDATE papers SET abstract=CASE WHEN abstract='' THEN ? ELSE abstract END WHERE id=?",(record.abstract,pid))
    for namespace,value in record.identifiers.items():con.execute('INSERT OR IGNORE INTO paper_identifiers VALUES(?,?,?)',(pid,namespace,value))
    current=[dict(r) for r in con.execute('SELECT a.id,a.name FROM authorship au JOIN authors a ON a.id=au.author_id WHERE au.paper_id=? ORDER BY au.position',(pid,))]
    # Ordered citation authors are authoritative for an unreviewed inventory row.
    if record.authors and not reviewed and paper['review_status']=='uncertain' and not con.execute('SELECT 1 FROM author_assertions WHERE paper_id=?',(pid,)).fetchone() and [r['name'] for r in current]!=[a.name for a in record.authors]:
        con.execute('DELETE FROM affiliations WHERE paper_id=?',(pid,))
        con.execute('DELETE FROM authorship WHERE paper_id=?',(pid,))
        for pos,person in enumerate(record.authors,1):
            aid=stable(pid+':author:'+str(pos))
            con.execute('INSERT INTO authors VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',(aid,person.name,'Identity from ordered official paper metadata.'))
            con.execute('INSERT INTO authorship VALUES(?,?,?)',(pid,aid,pos))
        for old in current:
            con.execute('DELETE FROM authors WHERE id=? AND NOT EXISTS(SELECT 1 FROM authorship WHERE author_id=?)',(old['id'],old['id']))


def save_candidate(con,pid,candidate,reason):
    cid=stable(pid+':candidate:'+candidate.url)
    con.execute('INSERT INTO pdf_candidates(id,paper_id,url,version,title,authors,reason,status,created) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(paper_id,url) DO NOTHING',(cid,pid,candidate.url,candidate.version,candidate.title,json.dumps(candidate.authors),reason,'pending',time.time()))


def save_download(con,collection,pid,candidate,raw,final_url,pages=None):
    # Validate the PDF structure before making a file available; not an extension check.
    pages=parse_pdf_pages(raw) if pages is None else pages
    digest=hashlib.sha256(raw).hexdigest()
    folder=storage.DATA/f'{collection}-pdfs';folder.mkdir(parents=True,exist_ok=True)
    filename=digest+'.pdf';path=folder/filename
    if not path.exists():
        temp=folder/(digest+'.'+uuid.uuid4().hex+'.tmp')
        try:temp.write_bytes(raw);temp.replace(path)
        finally:temp.unlink(missing_ok=True)
    did=stable(pid+':download:'+candidate.url)
    ocr=not any(text.strip() for text in pages)
    con.execute('INSERT INTO downloads(id,paper_id,status,path,source_url,error,sha256,size_bytes,retrieved,version,final_url,parse_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,path=excluded.path,error=excluded.error,sha256=excluded.sha256,size_bytes=excluded.size_bytes,retrieved=excluded.retrieved,version=excluded.version,final_url=excluded.final_url,parse_status=excluded.parse_status',(did,pid,'available',filename,candidate.url,'Image-only/scanned PDF: OCR required' if ocr else None,digest,len(raw),time.time(),candidate.version,final_url,'ocr_required' if ocr else 'indexed'))
    index_pages(con,pid,did,pages)
    return did,ocr


def index_pages(con,pid,did,pages):
    download=con.execute('SELECT version FROM downloads WHERE id=?',(did,)).fetchone()
    version=download['version'] if download else 'unknown'
    con.execute('DELETE FROM pdf_pages WHERE download_id=?',(did,))
    con.execute('DELETE FROM fulltext_fts WHERE download_id=?',(did,))
    for page,text in enumerate(pages,1):
        con.execute('INSERT INTO pdf_pages VALUES(?,?,?,?)',(pid,did,page,text))
        if text.strip():con.execute('INSERT INTO fulltext_fts(paper_id,page,text,download_id,version) VALUES(?,?,?,?,?)',(pid,page,text,did,version))
    con.execute('UPDATE downloads SET parse_status=? WHERE id=?',('indexed' if any(t.strip() for t in pages) else 'ocr_required',did))
    official=con.execute("SELECT 1 FROM downloads WHERE paper_id=? AND version='proceedings' AND status='available' AND parse_status='indexed' AND id!=?",(pid,did)).fetchone()
    if version=='proceedings' or not official:
        con.execute('INSERT INTO pdf_text VALUES(?,?,?) ON CONFLICT(paper_id) DO UPDATE SET text=excluded.text,pages=excluded.pages',(pid,'\n'.join(pages),len(pages)))


def coverage(con,eid):
    ids='SELECT DISTINCT paper_id FROM paper_editions WHERE edition_id=?'
    count=lambda sql:con.execute(sql,(eid,)).fetchone()[0]
    total=count('SELECT COUNT(DISTINCT paper_id) FROM paper_editions WHERE edition_id=?')
    available=count(f"SELECT COUNT(DISTINCT paper_id) FROM downloads WHERE status='available' AND pdf_exists(path) AND paper_id IN ({ids})")
    row=con.execute('SELECT official_count,inventory_complete FROM editions WHERE id=?',(eid,)).fetchone()
    return {'indexed':total,'inventory_records':total,'official_count':row['official_count'],'inventory_complete':bool(row['inventory_complete']),
        'pdfs':available,'missing_pdfs':total-available,
        'ambiguous':count(f"SELECT COUNT(DISTINCT paper_id) FROM pdf_candidates WHERE status='pending' AND paper_id IN ({ids})"),
        'fulltext':count(f'SELECT COUNT(DISTINCT paper_id) FROM fulltext_fts WHERE paper_id IN ({ids})'),
        'ocr_required':count(f"SELECT COUNT(DISTINCT paper_id) FROM downloads WHERE parse_status='ocr_required' AND paper_id IN ({ids})"),
        'confirmed':count(f"SELECT COUNT(*) FROM papers WHERE review_status='confirmed' AND id IN ({ids})"),
        'failed_jobs':con.execute("SELECT COUNT(*) FROM jobs WHERE edition_id=? AND status IN ('failed','partial')",(eid,)).fetchone()[0],
        'pending_jobs':con.execute("SELECT COUNT(*) FROM jobs WHERE edition_id=? AND status IN ('queued','running','cancelled')",(eid,)).fetchone()[0]}
