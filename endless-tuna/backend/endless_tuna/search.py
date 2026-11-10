"""Safe literal FTS5 queries shared by browsing, paginated search, and exports."""
import re
from dataclasses import dataclass
from .pipeline_store import coverage

WORDS=re.compile(r'[^\W_]+',re.UNICODE)


@dataclass
class Query:
    units:list[str]
    notes:list[str]
    empty:bool=False


def parse_query(value):
    notes=[];units=[];text=(value or '').strip()
    if len(text)>500:notes.append('Only the first 500 query characters are searched.');text=text[:500]
    i=0
    while i<len(text):
        if text[i]=='"':
            end=text.find('"',i+1)
            if end<0:
                notes.append('An unclosed quote is treated as ordinary terms.')
                units.extend('"'+t+'"' for t in WORDS.findall(text[i+1:]));break
            words=WORDS.findall(text[i+1:end])
            if words:units.append('"'+' '.join(words)+'"')
            i=end+1
        else:
            end=text.find('"',i)
            if end<0:end=len(text)
            units.extend('"'+t+'"' for t in WORDS.findall(text[i:end]));i=end
    if len(units)>32:notes.append('Only the first 32 terms or phrases are searched.')
    return Query(list(dict.fromkeys(units[:32])),notes,bool(text) and not units)


def paper_rows(db,q='',edition=None,year=None,conference=None,organization=None,pdf=None,review=None,all_memberships=False,country=None,include_evidence=True):
    query=parse_query(q)
    if query.empty:return []
    sql='SELECT DISTINCT p.id,p.title,p.abstract,p.review_status,p.canonical_url,m.edition_id,m.track_id,s.name conference,e.year,t.name track,EXISTS(SELECT 1 FROM downloads d WHERE d.paper_id=p.id AND d.status="available" AND pdf_exists(d.path)) has_pdf FROM papers p JOIN paper_editions m ON m.paper_id=p.id JOIN editions e ON e.id=m.edition_id JOIN series s ON s.id=e.series_id LEFT JOIN tracks t ON t.id=m.track_id WHERE 1=1';args=[]
    # Each unit can match a different indexed field/page. A phrase stays within one field/page.
    for expr in query.units:
        sql+=' AND (p.rowid IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?) OR p.id IN (SELECT paper_id FROM fulltext_fts WHERE fulltext_fts MATCH ?) OR e.id IN (SELECT edition_id FROM edition_fts WHERE edition_fts MATCH ?))';args.extend([expr,expr,expr])
    for val,clause in [(edition,'m.edition_id=?'),(year,'e.year=?'),(conference,'e.series_id=?'),(review,'p.review_status=?')]:
        if val:sql+=' AND '+clause;args.append(val)
    if organization:
        sql+=" AND (EXISTS(SELECT 1 FROM affiliations a WHERE a.paper_id=p.id AND a.organization_id=? AND NOT EXISTS(SELECT 1 FROM author_assertions h WHERE h.paper_id=a.paper_id AND h.author_id=a.author_id AND h.kind='affiliation')) OR EXISTS(SELECT 1 FROM author_assertions a WHERE a.paper_id=p.id AND a.organization_id=? AND a.kind='affiliation' AND a.status NOT IN ('rejected','superseded')))";args.extend([organization,organization])
    if country:
        sql+=" AND EXISTS(SELECT 1 FROM author_assertions loc JOIN author_assertions aff ON aff.author_id=loc.author_id AND aff.paper_id=loc.paper_id AND aff.organization_id=loc.organization_id WHERE loc.paper_id=p.id AND loc.kind='organization_country' AND loc.status='verified' AND loc.value=? COLLATE NOCASE AND aff.kind='affiliation' AND aff.status='verified')";args.append(country)
    if pdf in ('yes','no'):
        sql+=(' AND ' if pdf=='yes' else ' AND NOT ')+'EXISTS(SELECT 1 FROM downloads d WHERE d.paper_id=p.id AND d.status="available" AND pdf_exists(d.path))'
    sql+=' ORDER BY e.year DESC,p.title COLLATE NOCASE,p.id,m.edition_id,m.track_id'
    rows=[dict(r) for r in db.execute(sql,args)]
    if not all_memberships:
        unique={}
        for row in rows:unique.setdefault(row['id'],row)
        rows=list(unique.values())
    if include_evidence:decorate_rows(db,rows,query)
    return rows


def decorate_rows(db,rows,query):
    for row in rows:
        row['authors']=[dict(r) for r in db.execute('SELECT a.id,a.name,au.position FROM authors a JOIN authorship au ON au.author_id=a.id WHERE au.paper_id=? ORDER BY au.position',(row['id'],))]
        row['matching_pages']=[];reasons=[]
        for expr in query.units:
            for field,index,label in [('title',0,'Paper title'),('abstract',1,'Abstract')]:
                match=db.execute(f"SELECT snippet(papers_fts,{index},'','','…',24) excerpt FROM papers_fts WHERE rowid=(SELECT rowid FROM papers WHERE id=?) AND papers_fts MATCH ? LIMIT 1",(row['id'],field+' : '+expr)).fetchone()
                if match:reasons.append({'kind':field,'label':label,'excerpt':match['excerpt'],'source_url':row['canonical_url']})
            match=db.execute("SELECT snippet(edition_fts,-1,'','','…',24) excerpt FROM edition_fts WHERE edition_id=? AND edition_fts MATCH ? LIMIT 1",(row['edition_id'],expr)).fetchone()
            if match:reasons.append({'kind':'conference','label':'Conference metadata','excerpt':match['excerpt'],'source_url':db.execute('SELECT source_url FROM editions WHERE id=?',(row['edition_id'],)).fetchone()[0]})
            matches=db.execute("SELECT page,download_id,version,snippet(fulltext_fts,2,'','','…',24) excerpt FROM fulltext_fts WHERE paper_id=? AND fulltext_fts MATCH ? ORDER BY download_id,CAST(page AS INTEGER) LIMIT 3",(row['id'],expr)).fetchall()
            for match in matches:
                page=dict(match)
                if not any(p['download_id']==page['download_id'] and p['page']==page['page'] for p in row['matching_pages']):row['matching_pages'].append(page)
                reasons.append({'kind':'fulltext','label':page['version']+' PDF p. '+str(page['page']),'excerpt':page['excerpt'],'source_url':db.execute('SELECT source_url FROM downloads WHERE id=?',(page['download_id'],)).fetchone()[0],'page':page['page']})
            if len(reasons)>=6:break
        row['match_reasons']=reasons[:6]
    return rows


def conference_results(db,q='',year=None,conference=None,organization=None,country=None,pdf=None,review=None,edition=None):
    query=parse_query(q)
    if query.empty:return []
    matched=paper_rows(db,q,edition,year,conference,organization,pdf,review,True,country,include_evidence=False)
    results=[]
    for source in db.execute('SELECT e.*,s.name FROM editions e JOIN series s ON s.id=e.series_id ORDER BY e.year DESC,s.name COLLATE NOCASE,e.id'):
        row=dict(source)
        if edition and row['id']!=edition or year and row['year']!=year or conference and row['series_id']!=conference:continue
        papers=list({p['id']:p for p in matched if p['edition_id']==row['id']}.values())
        metadata_match=bool(query.units) and all(db.execute('SELECT 1 FROM edition_fts WHERE edition_id=? AND edition_fts MATCH ?',(row['id'],u)).fetchone() for u in query.units)
        if (query.units or organization or country or pdf or review) and not papers and not (metadata_match and not any((organization,country,pdf,review))):continue
        decorate_rows(db,papers[:3],query)
        row['matching_count']=len(papers);row['matching_paper_ids']=[p['id'] for p in papers]
        row['coverage']=coverage(db,row['id']);row['total_count']=row['coverage']['inventory_records']
        reasons=[r for p in papers[:3] for r in p.get('match_reasons',[])]
        if reasons:row['snippet']=reasons[0]['label']+': '+reasons[0]['excerpt'];row['match_reasons']=reasons[:4]
        elif metadata_match:
            row['snippet']='Conference metadata: '+row['name']+' '+str(row['year'])+' — '+row['description']+' (no collected matching papers)';row['match_reasons']=[{'kind':'conference','label':'Conference metadata','excerpt':row['snippet'],'source_url':row['source_url']}]
        else:
            evidence=db.execute('SELECT quote FROM evidence WHERE paper_id=? LIMIT 1',(papers[0]['id'],)).fetchone() if papers else None
            row['snippet']=evidence[0] if evidence else 'Indexed metadata only. No matching paper evidence or full text is available yet.';row['match_reasons']=[]
        results.append(row)
    return results


def paginate(items,page,page_size,q):
    query=parse_query(q);total=len(items)
    return {'items':items[(page-1)*page_size:page*page_size],'total':total,'page':page,'page_size':page_size,'pages':max(1,(total+page_size-1)//page_size),
        'query':{'semantics':'All terms required across conference metadata, title, abstract and indexed PDF pages. Quoted phrases match within one field/page; punctuation separates words. Operators are literal words.','notes':query.notes,'units':query.units}}
