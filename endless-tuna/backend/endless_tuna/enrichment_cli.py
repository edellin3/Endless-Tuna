"""Backfill stored paper enrichment deterministically. This CLI never invokes LAS."""
import argparse
import json
from . import config,db
from .enrichment import enrich_paper


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection',choices=['demo','real'],default='real')
    parser.add_argument('--limit',type=int,default=10)
    parser.add_argument('--paper')
    args=parser.parse_args()
    if not 1<=args.limit<=1000:parser.error('--limit must be between 1 and 1000')
    for c in ('demo','real'):db.initialize(c)
    with db.connect(args.collection) as con:
        ids=[args.paper] if args.paper else [r['id'] for r in con.execute('SELECT id FROM papers ORDER BY title LIMIT ?',(args.limit,))]
    results=[{'paper_id':pid,**enrich_paper(args.collection,pid,use_las=False)} for pid in ids]
    report={'collection':args.collection,'model_requests':0,'results':results}
    (db.DATA/'enrichment-result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'papers':len(results),'model_requests':0,'new_assertions':sum(r['assertions_added'] for r in results),'statuses':{s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})}},indent=2))


if __name__=='__main__':main()
