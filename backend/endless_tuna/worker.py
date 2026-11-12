"""Staged collection worker with atomic claiming, leases, and per-paper checkpoints."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import signal
import threading
import time
import uuid
from urllib.parse import urlsplit
from . import config
from . import db as storage
from .collection import CollectionError, Metadata, fetch_bytes, parse_pdf, parse_pdf_pages, public_url
from .adapters import adapter_for, Inventory
from .network import number
from .resolution import resolve, Candidate
from .pipeline_store import upsert_paper, hydrate_paper, save_download, save_candidate, coverage, stable
from .adapters import canonical_url


class LostLease(Exception):pass
class WorkerStopping(Exception):pass
class PDFSourceDenied(CollectionError):pass


def owned(con,jid,token):
    con.execute('BEGIN IMMEDIATE')
    if not con.execute("SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND status='running'",(jid,token)).fetchone():raise LostLease()
    con.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()+120,jid))


def heartbeat(collection,jid,token,stop):
    while not stop.wait(15):
        with storage.connect(collection) as con:
            result=con.execute("UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='running'",(time.time()+120,jid,token))
            if not result.rowcount:return


def paper_stage(collection,jid,token,pid,stage,metadata=None):
    with storage.connect(collection) as con:
        owned(con,jid,token)
        con.execute('UPDATE job_papers SET stage=?,updated=? WHERE job_id=? AND paper_id=?',(stage,time.time(),jid,pid))
        con.execute('UPDATE jobs SET stage=?,updated=? WHERE id=?',(stage,time.time(),jid))
        if metadata:con.execute('UPDATE job_papers SET metadata=? WHERE job_id=? AND paper_id=?',(metadata.model_dump_json(),jid,pid))


def process_paper(collection,job,token,item,adapter):
    jid,pid=job['id'],item['paper_id']
    def fetch(url, **kwargs):
        if job['kind'] in ('pdfs','automatic'):
            with storage.connect(collection) as con:owned(con,jid,token)
        return fetch_bytes(url, **kwargs)
    try:
        record=Metadata.model_validate_json(item['metadata'])
        paper_stage(collection,jid,token,pid,'resolve')
        if record.detail_pending:
            try:record=adapter.hydrate(record,fetch)
            except CollectionError:
                if job['kind'] not in ('pdfs','automatic'):raise
                # The saved title remains usable for alternate-copy discovery.
                # Missing author evidence prevents automatic acceptance.
                record=record.model_copy(update={'detail_pending':False})
            with storage.connect(collection) as con:
                owned(con,jid,token)
                hydrate_paper(con,pid,record)
                con.execute('UPDATE job_papers SET metadata=? WHERE job_id=? AND paper_id=?',(record.model_dump_json(),jid,pid))
        with storage.connect(collection) as con:
            accepted=con.execute("SELECT * FROM pdf_candidates WHERE paper_id=? AND status='confirmed' ORDER BY reviewed DESC LIMIT 1",(pid,)).fetchone()
        if accepted:
            selected=Candidate(accepted['url'],accepted['title'],json.loads(accepted['authors']),accepted['version'])
            candidates,error=[],None
        else:
            selected,candidates,error=resolve(record,collection,fetch,wide=job["kind"] in ("pdfs","automatic"))
        with storage.connect(collection) as con:
            owned(con,jid,token)
            for candidate in candidates:save_candidate(con,pid,candidate,error or 'Candidate requires review')
        if not selected:
            with storage.connect(collection) as con:
                owned(con,jid,token)
                con.execute("UPDATE job_papers SET status=?,stage='resolve',error=?,updated=? WHERE job_id=? AND paper_id=?",('review' if candidates else 'missing',error,time.time(),jid,pid))
            return
        paper_stage(collection,jid,token,pid,'download')
        with storage.connect(collection) as con:
            previous=con.execute("SELECT * FROM downloads WHERE paper_id=? AND source_url=? AND status='available'",(pid,selected.url)).fetchone()
        if previous and previous['parse_status'] in ('indexed','ocr_required') and previous['path'] and (storage.DATA/f'{collection}-pdfs'/previous['path']).is_file():
            pass  # durable content hash and page text already exist; no duplicate transfer
        else:
            if job['kind'] in ('pdfs','automatic'):
                excluded=[];download_errors=[]
                for attempt in range(4):
                    try:
                        raw,final=fetch(selected.url)
                        parsed_pages=parse_pdf_pages(raw)
                        break
                    except CollectionError as download_error:
                        download_errors.append(str(download_error));excluded.append(selected.url)
                        selected,candidates,error=resolve(record.model_copy(update={'pdf_url':None}),collection,fetch,wide=True,excluded_urls=excluded)
                        if not selected:break
                else:
                    selected=None;error='Several copies were inaccessible. Retry or supply another free PDF URL.'
                if not selected:
                    with storage.connect(collection) as con:
                        owned(con,jid,token)
                        for candidate in candidates:save_candidate(con,pid,candidate,error or 'Possible alternate copy; review required.')
                        con.execute("UPDATE job_papers SET status=?,error=?,updated=? WHERE job_id=? AND paper_id=?",('review' if candidates else 'missing',' '.join(download_errors)+' '+(error or ''),time.time(),jid,pid))
                    return
            else:
                try:
                    raw,final=fetch(selected.url)
                    paper_stage(collection,jid,token,pid,'extract')
                    parsed_pages=parse_pdf_pages(raw)
                except CollectionError as direct_error:
                    # A broken proceedings link can still resolve to a distinct arXiv version.
                    if selected.version!='proceedings' and not selected.version.startswith('openreview:'):raise
                    fallback=record.model_copy(update={'pdf_url':None})
                    selected,candidates,error=resolve(fallback,collection,fetch,wide=job["kind"] in ("pdfs","automatic"))
                    with storage.connect(collection) as con:
                        owned(con,jid,token)
                        for candidate in candidates:save_candidate(con,pid,candidate,error or 'Proceedings PDF unavailable; fallback requires review')
                    if not selected:
                        with storage.connect(collection) as con:
                            owned(con,jid,token)
                            con.execute('UPDATE job_papers SET status=?,error=?,updated=? WHERE job_id=? AND paper_id=?',('review' if candidates else 'missing',str(direct_error)+' '+(error or 'No alternate PDF resolved.'),time.time(),jid,pid))
                        return
                    raw,final=fetch(selected.url)
                    parsed_pages=parse_pdf_pages(raw)
            paper_stage(collection,jid,token,pid,'extract')
            with storage.connect(collection) as con:
                owned(con,jid,token)
                save_download(con,collection,pid,selected,raw,final,parsed_pages)
        from .enrichment import enrich_paper
        try:enrich_paper(collection,pid,use_las=False)
        except Exception:pass  # enrichment failures cannot invalidate collection or indexed text
        with storage.connect(collection) as con:
            owned(con,jid,token)
            con.execute("UPDATE job_papers SET stage='ready',status='done',error=NULL,updated=? WHERE job_id=? AND paper_id=?",(time.time(),jid,pid))
    except LostLease:raise
    except Exception as error:
        # Isolate all paper failures, including parser/adapter defects, while preserving safe evidence.
        message=str(error) if isinstance(error,CollectionError) else 'Paper processing failed ('+type(error).__name__+'). Retry or inspect the source.'
        with storage.connect(collection) as con:
            owned(con,jid,token)
            con.execute("UPDATE job_papers SET status='failed',error=?,updated=? WHERE job_id=? AND paper_id=?",(message,time.time(),jid,pid))
    finally:
        with storage.connect(collection) as con:
            current=con.execute("SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND status='running'",(jid,token)).fetchone()
            if current:
                completed=con.execute("SELECT COUNT(*) FROM job_papers WHERE job_id=? AND status!='pending'",(jid,)).fetchone()[0]
                total=con.execute('SELECT COUNT(*) FROM job_papers WHERE job_id=?',(jid,)).fetchone()[0]
                con.execute('UPDATE jobs SET cursor=?,progress=?,updated=? WHERE id=? AND lease_token=?',(completed,10+int(85*completed/max(1,total)),time.time(),jid,token))


def tick(collection,job_id=None,shutdown=None):
    now=time.time()
    with storage.connect(collection) as con:
        con.execute('BEGIN IMMEDIATE')
        where="(status='queued' OR (status='running' AND lease_until < ?))"
        args=[now]
        if job_id:where+=' AND id=?';args.append(job_id)
        found=con.execute('SELECT * FROM jobs WHERE '+where+' ORDER BY updated LIMIT 1',args).fetchone()
        if not found:return False
        job=dict(found);jid=job['id'];token=str(uuid.uuid4())
        con.execute("UPDATE jobs SET status='running',attempts=attempts+1,lease_until=?,lease_token=?,updated=?,message='Collecting official inventory' WHERE id=?",(now+120,token,now,jid))
        con.execute("UPDATE editions SET status='collecting' WHERE id=?",(job['edition_id'],))
        edition=dict(con.execute('SELECT * FROM editions WHERE id=?',(job['edition_id'],)).fetchone())
        track=job['track_id'] or con.execute('SELECT id FROM tracks WHERE edition_id=? ORDER BY id LIMIT 1',(edition['id'],)).fetchone()['id']
    stop=threading.Event();thread=threading.Thread(target=heartbeat,args=(collection,jid,token,stop),daemon=True);thread.start()
    try:
        adapter=adapter_for(edition['source_url'],edition['adapter'])
        with storage.connect(collection) as con:saved=con.execute('SELECT records FROM job_payloads WHERE job_id=?',(jid,)).fetchone()
        if saved:
            payload=json.loads(saved['records'])
            if isinstance(payload,list):payload={'records':payload,'official_count':None,'url':edition['source_url']}
            inventory=Inventory([Metadata.model_validate(r) for r in payload['records']],payload['official_count'],payload['url'])
        else:
            inventory=adapter.inventory(edition['source_url'],fetch_bytes)
            if job['paper_limit'] is not None:inventory.records=inventory.records[:job['paper_limit']]
            payload={'records':[r.model_dump() for r in inventory.records],'official_count':inventory.official_count,'url':inventory.url}
            with storage.connect(collection) as con:
                owned(con,jid,token)
                con.execute('INSERT INTO job_payloads VALUES(?,?)',(jid,json.dumps(payload)))
        with storage.connect(collection) as con:
            owned(con,jid,token)
            for index,record in enumerate(inventory.records):
                if record.year is not None and record.year!=edition['year']:raise CollectionError('Official inventory or CSV year does not match this edition.')
                paper_track=track
                if record.track and record.track!=con.execute('SELECT name FROM tracks WHERE id=?',(track,)).fetchone()['name']:
                    if not getattr(adapter,'multi_track',False):raise CollectionError('CSV track does not match this edition. Import workshops into a separate track/edition.')
                    paper_track=stable(edition['id']+':track:'+record.track)
                    con.execute('INSERT OR IGNORE INTO tracks VALUES(?,?,?)',(paper_track,edition['id'],record.track))
                pid=upsert_paper(con,edition['id'],paper_track,record,inventory.url)
                con.execute('INSERT OR IGNORE INTO job_papers VALUES(?,?,?,?,?,?,?,?)',(jid,pid,index,record.model_dump_json(),'resolve','pending',None,time.time()))
            total=con.execute('SELECT COUNT(DISTINCT paper_id) FROM paper_editions WHERE edition_id=?',(edition['id'],)).fetchone()[0]
            complete=inventory.official_count is not None and len({canonical_url(r.source_url) for r in inventory.records})==inventory.official_count and total==inventory.official_count
            if job['kind']=='automatic' and edition['inventory_complete'] and edition['official_count']==inventory.official_count and total==inventory.official_count:complete=True
            if inventory.records and job["kind"] != "pdfs":
                con.execute('UPDATE editions SET official_count=COALESCE(?,official_count),inventory_complete=?,inventory_retrieved=? WHERE id=?',(inventory.official_count,int(complete),time.time(),edition['id']))
            else:
                complete=bool(edition['inventory_complete'])  # candidate-only downloads do not recollect or invalidate inventory
            con.execute("UPDATE jobs SET official_count=?,stage='resolve',progress=10,message='Inventory persisted; resolving paper sources' WHERE id=?",(inventory.official_count,jid))
            items=[dict(r) for r in con.execute("SELECT * FROM job_papers WHERE job_id=? AND status='pending' ORDER BY ordinal",(jid,))]
        if job['kind']=='inventory':
            with storage.connect(collection) as con:
                owned(con,jid,token)
                con.execute("UPDATE job_papers SET status='done',stage='inventory',updated=? WHERE job_id=?",(time.time(),jid))
                con.execute("UPDATE jobs SET status='complete',stage='inventory',cursor=?,progress=100,lease_until=NULL,lease_token=NULL,updated=?,message=? WHERE id=?",(len(inventory.records),time.time(),f'{len(inventory.records)} paper titles saved. Ready to find free PDFs.',jid))
                con.execute("UPDATE editions SET status='list_ready',description='Paper list ready. Find free PDFs to continue.' WHERE id=?",(edition['id'],))
            return True
        concurrency=int(number('TUNA_DOWNLOAD_CONCURRENCY',2,1,4))
        # Bound the number of in-flight futures as well as worker threads.
        denied=0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for offset in range(0,len(items),concurrency):
                if shutdown is not None and shutdown.is_set():raise WorkerStopping()
                with storage.connect(collection) as con:owned(con,jid,token)
                futures=[executor.submit(process_paper,collection,job,token,item,adapter) for item in items[offset:offset+concurrency]]
                for future in futures:future.result()
                if getattr(adapter,'stop_on_repeated_pdf_denial',False):
                    with storage.connect(collection) as con:
                        for item in items[offset:offset+concurrency]:
                            outcome=con.execute('SELECT status,error,metadata FROM job_papers WHERE job_id=? AND paper_id=?',(jid,item['paper_id'])).fetchone()
                            metadata=Metadata.model_validate_json(outcome['metadata'])
                            blocked=outcome['status']!='done' and 'HTTP 403' in (outcome['error'] or '') and urlsplit(metadata.pdf_url or '').hostname=='openreview.net'
                            denied=denied+1 if blocked else 0
                    if denied>=2:raise PDFSourceDenied('Official inventory is stored and searchable. OpenReview denied consecutive PDF requests (HTTP 403); remaining downloads are paused. Check network/source access, then Retry. Completed papers and inventory are preserved.')
        with storage.connect(collection) as con:
            owned(con,jid,token)
            incomplete=con.execute("SELECT COUNT(*) FROM job_papers WHERE job_id=? AND status!='done'",(jid,)).fetchone()[0]
            total=con.execute('SELECT COUNT(*) FROM job_papers WHERE job_id=?',(jid,)).fetchone()[0]
            state='partial' if incomplete else 'complete'
            con.execute("UPDATE jobs SET status=?,stage='ready',progress=100,lease_until=NULL,lease_token=NULL,updated=?,message=? WHERE id=?",(state,time.time(),f'{total} inventory records processed; {incomplete} papers need retry, review, or a PDF. Inventory completeness is reported separately.',jid))
            con.execute("UPDATE editions SET status=? WHERE id=?",('partial' if incomplete or not complete else 'complete',edition['id']))
            if job['kind']=='automatic':
                available=coverage(con,edition['id'])['pdfs']
                con.execute('UPDATE jobs SET message=? WHERE id=?',(f'{total} papers checked. {available} PDFs available; {incomplete} need attention.',jid))
                con.execute('UPDATE editions SET description=? WHERE id=?',('Papers and available free PDFs collected.',edition['id']))
    except WorkerStopping:
        # All submitted futures have finished; retain per-paper checkpoints and release ownership.
        try:
            with storage.connect(collection) as con:
                owned(con,jid,token)
                con.execute("UPDATE jobs SET status='queued',lease_until=NULL,lease_token=NULL,updated=?,message='Worker stopped; queued to resume from saved checkpoints.' WHERE id=?",(time.time(),jid))
        except LostLease:pass
    except LostLease:pass
    except Exception as error:
        message=str(error) if isinstance(error,CollectionError) else 'Inventory processing failed ('+type(error).__name__+'). Retry or inspect the source.'
        try:
            with storage.connect(collection) as con:
                owned(con,jid,token)
                status='partial' if isinstance(error,PDFSourceDenied) else 'failed'
                con.execute("UPDATE jobs SET status=?,lease_until=NULL,lease_token=NULL,message=?,updated=? WHERE id=?",(status,message,time.time(),jid))
                con.execute("UPDATE editions SET status=? WHERE id=?",(status,edition['id']))
        except LostLease:pass
    finally:stop.set();thread.join(timeout=2)
    return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--job');parser.add_argument('--collection',choices=['demo','real'],default=None);args=parser.parse_args()
    shutdown=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:shutdown.set())
    for c in ('demo','real'):storage.initialize(c)
    while not shutdown.is_set():
        for c in ([args.collection] if args.collection else ['demo','real']):
            if shutdown.is_set():break
            tick(c,args.job,shutdown)
        if args.once:break
        shutdown.wait(1)


if __name__=='__main__':main()
