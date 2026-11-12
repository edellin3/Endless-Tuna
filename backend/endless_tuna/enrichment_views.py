from urllib.parse import urlencode
from .enrichment import component,assertions


def review_status(claims):
    active=[a for a in claims if a['status'] not in ('rejected','superseded')]
    if active and all(a['status']=='verified' for a in active):return 'verified'
    if any(a['status']=='needs_review' for a in active) or not active:return 'needs_review'
    return 'extracted'


def summary(con,aid):
    ids=component(con,aid);claims=assertions(con,ids,False);marks=','.join('?' for _ in ids)
    active=[a for a in claims if a['status'] not in ('rejected','superseded')]
    orgs=sorted({a['organization'] for a in active if a['kind'] in ('affiliation','current_affiliation') and a['organization']})
    verified_affiliations={(a['author_id'],a['organization_id'],a['paper_id']) for a in active if a['kind']=='affiliation' and a['status']=='verified'}
    countries=sorted({a['value'] for a in active if a['kind']=='organization_country' and a['status']=='verified' and (a['author_id'],a['organization_id'],a['paper_id']) in verified_affiliations})
    return {'member_ids':ids,'paper_count':con.execute(f'SELECT COUNT(DISTINCT paper_id) FROM authorship WHERE author_id IN ({marks})',ids).fetchone()[0],
        'organizations':orgs,'verified_countries':countries,'review_status':review_status(claims),'assertion_count':len(active)}


def directory(con,q='',organization='',country='',review=''):
    output=[];seen=set()
    for author in con.execute('SELECT * FROM authors ORDER BY name,id'):
        if author['id'] in seen:continue
        info=summary(con,author['id']);seen.update(info['member_ids'])
        aliases=[dict(r) for r in con.execute('SELECT id,name FROM authors WHERE id IN ('+','.join('?' for _ in info['member_ids'])+')',info['member_ids'])]
        if q and not any(q.casefold() in a['name'].casefold() for a in aliases):continue
        if organization and organization not in info['organizations']:continue
        if country and country not in info['verified_countries']:continue
        if review and review!=info['review_status']:continue
        output.append({**dict(author),**info,'aliases':aliases})
    return output


def detail(con,aid):
    row=con.execute('SELECT * FROM authors WHERE id=?',(aid,)).fetchone()
    if not row:return None
    info=summary(con,aid);ids=info['member_ids'];marks=','.join('?' for _ in ids)
    claims=assertions(con,ids)
    return {**dict(row),**info,'assertions':claims,'members':[dict(r) for r in con.execute(f'SELECT id,name FROM authors WHERE id IN ({marks}) ORDER BY name,id',ids)],
        'paper_time_affiliations':[a for a in claims if a['kind']=='affiliation' and a['status'] not in ('rejected','superseded')],
        'verified_current_affiliations':[a for a in claims if a['kind']=='current_affiliation' and a['status']=='verified'],
        'verified_profiles':[a for a in claims if a['kind']=='scholar_profile' and a['status']=='verified'],
        'scholar_search_url':'https://scholar.google.com/citations?'+urlencode({'view_op':'search_authors','mauthors':row['name']}),
        'scholar_lookup_status':'manual_verification_required',
        'nationality':None,'residence':None,'unsupported_fields_status':'Nationality and residence are not inferred from affiliation or organization location.',
        'legacy_affiliations':[dict(r) for r in con.execute(f'SELECT DISTINCT o.name,p.title,p.id paper_id,e.year FROM affiliations f JOIN organizations o ON o.id=f.organization_id JOIN papers p ON p.id=f.paper_id JOIN editions e ON e.id=p.edition_id WHERE f.author_id IN ({marks})',ids)]}
