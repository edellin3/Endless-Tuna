"""Explicit real NeurIPS smoke collection, hard-capped at 10 papers; no model calls."""
import argparse
import json
import time
from . import config
from . import db as storage
from .main import NewConference, add_conference
from .pipeline_api import queue
from .pipeline_store import coverage
from .worker import tick


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,choices=range(1,11),default=10)
    args=parser.parse_args()
    for collection in ('demo','real'):storage.initialize(collection)
    source='https://papers.nips.cc/paper_files/paper/2024'
    with storage.connect('real') as con:
        existing=con.execute("SELECT e.id FROM editions e JOIN series s ON s.id=e.series_id WHERE e.source_url=? AND s.name='NeurIPS 2024 smoke collection'",(source,)).fetchone()
    if existing:
        eid=existing['id']
        with storage.connect('real') as con:
            track=con.execute('SELECT id FROM tracks WHERE edition_id=?',(eid,)).fetchone()['id']
            jid=queue(con,eid,track,args.limit)
    else:
        created=add_conference(NewConference(name='NeurIPS 2024 smoke collection',year=2024,track='Main Conference',source_url=source,paper_limit=args.limit),c='real')
        eid,jid=created['id'],created['job_id']
    tick('real',jid)
    with storage.connect('real') as con:
        job=dict(con.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        results=[dict(r) for r in con.execute('SELECT jp.paper_id,p.title,jp.status,jp.stage,jp.error FROM job_papers jp JOIN papers p ON p.id=jp.paper_id WHERE job_id=? ORDER BY ordinal',(jid,))]
        indexed_pages=con.execute('SELECT COUNT(*) FROM fulltext_fts WHERE paper_id IN (SELECT paper_id FROM paper_editions WHERE edition_id=?)',(eid,)).fetchone()[0]
        report={'indexed_pages':indexed_pages,'run_at':time.time(),'source':source,'edition_id':eid,'job_id':jid,'limit':args.limit,'status':job['status'],'message':job['message'],'coverage':coverage(con,eid),'papers':results}
    path=storage.DATA/'neurips-smoke-result.json';path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    print('Saved failure/success evidence to '+str(path))


if __name__=='__main__':main()
