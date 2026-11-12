"""Explicit fictional-data acceptance harness; never used by the production worker."""
import argparse
import io
import json
import time
import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from endless_tuna import db
from endless_tuna.pipeline_store import index_pages
from endless_tuna.enrichment import enrich_paper,insert_assertion,AssertionInput
from endless_tuna.enrichment_api import review_assertion,AssertionReview
from endless_tuna.collection import CollectionError


def fixture_pdf():
    writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 40 740 Td (DEMO DATA - FICTIONAL ACCEPTANCE FIXTURE) Tj 0 -24 Td (Mira Chen: Tidal Research Institute) Tj 0 -24 Td (Alex Rivera: Northstar Lab) Tj 0 -24 Td (Tidal Research Institute, Country: Canada.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);return output.getvalue()


def prepare():
    for c in ('demo','real'):db.initialize(c)
    path=db.DATA/'demo-pdfs'/'harbor-0.pdf';raw=fixture_pdf();path.write_bytes(raw)
    from endless_tuna.collection import parse_pdf_pages
    with db.connect() as con:
        con.execute("UPDATE downloads SET source_url='https://fixtures.example/accepted/demo.pdf' WHERE id='harbor-0-pdf'")
        index_pages(con,'harbor-0','harbor-0-pdf',parse_pdf_pages(raw))
    enrich_paper('demo','harbor-0',False)
    with db.connect() as con:
        aff=con.execute("SELECT id FROM author_assertions WHERE author_id='a1' AND kind='affiliation' AND paper_id='harbor-0'").fetchone()['id']
        review_assertion(con,aff,AssertionReview(action='confirm',note='Fictional fixture assertion verification.'))
        loc,_=insert_assertion(con,'a1',AssertionInput(kind='organization_country',value='Canada',organization='Tidal Research Institute',paper_id='harbor-0',source_url='https://fixtures.example/accepted/demo.pdf',excerpt='Tidal Research Institute, Country: Canada.',page=1))
        review_assertion(con,loc,AssertionReview(action='confirm',note='Fictional fixture country verification.'))


    # Durable fictional preview for the link-first browser workflow. It is never
    # installed by application startup or the production worker.
    records=[{'title':'Fictional CoRL fixture '+str(n),'source_url':f'https://proceedings.mlr.press/v270/fixture{n}.html','authors':[],'detail_pending':True,'year':2024} for n in (1,2)]
    with db.connect('real') as con:
        con.execute('INSERT INTO intake_previews VALUES(?,?,?,?,?,?,?,?)',('fixture-corl-preview','https://proceedings.mlr.press/v270/','pmlr-volume','Fictional CoRL browser fixture',2024,json.dumps(records),2,time.time()))
        wacv_records=[{'title':'Fictional WACV paper '+str(n),'source_url':f'https://wacv.thecvf.com/virtual/2026/poster/{n}',
                       'authors':[{'name':'Fixture WACV Researcher'}],'year':2026,'pdf_url':f'https://fixtures.example/wacv-paper-{n}.pdf'} for n in (10,20)]
        con.execute('INSERT INTO intake_previews VALUES(?,?,?,?,?,?,?,?)',('fixture-wacv-preview','https://wacv.thecvf.com/virtual/2026/papers.html','wacv-2026-program','Fictional WACV browser fixture',2026,json.dumps(wacv_records),2,time.time()))


def worker():
    from endless_tuna import worker as production
    def blocked(*args,**kwargs):raise AssertionError('Acceptance harness forbids all live HTTP transport.')
    httpx.HTTPTransport.handle_request=blocked
    raw=fixture_pdf()
    def fetch(url,**kwargs):
        if url.startswith('https://proceedings.mlr.press/v270/fixture'):
            n=url.rsplit('fixture',1)[1].split('.')[0]
            return ('<meta name="citation_title" content="Fictional CoRL fixture '+n+'"><meta name="citation_author" content="Fixture Researcher"><meta name="citation_pdf_url" content="https://fixtures.example/corl'+n+'.pdf"><div id="abstract">Fictional abstract.</div>').encode(),url
        if 'export.arxiv.org/' in url:return b'<feed xmlns="http://www.w3.org/2005/Atom"/>',url
        if url=='https://fixtures.example/failing-inventory.json':
            if not (db.DATA/'fixture-source-enabled').exists():raise CollectionError('Mocked official source returned HTTP 503; retry this fixture job.')
            return json.dumps({'papers':[{'title':'Fictional robotics recovery','source_url':'https://fixtures.example/papers/recovered','authors':[{'name':'Fixture Researcher'}],'pdf_url':'https://fixtures.example/recovered.pdf'}]}).encode(),url
        if url.endswith('/resume-later.pdf'):
            while (db.DATA/'fixture-block-transfer').exists():
                with db.connect() as con:running=con.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone()
                if not running:raise CollectionError('Mocked transfer interrupted after cancellation.')
                time.sleep(.1)
        if url.startswith('https://fixtures.example/') and url.endswith('.pdf'):return raw,url
        raise CollectionError('Acceptance fixture does not support this source URL; no real HTTP was attempted.')
    production.fetch_bytes=fetch
    for c in ('demo','real'):db.initialize(c)
    while True:
        production.tick('demo')
        production.tick('real')
        time.sleep(.1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','worker']);args=parser.parse_args()
    prepare() if args.mode=='prepare' else worker()
