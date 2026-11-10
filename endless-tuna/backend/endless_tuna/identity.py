"""Reversible identity edges; original author IDs/authorship/assertions never move."""
import json
import time
import uuid
from .enrichment import component,norm,EnrichmentError
from .network import validate_url
from .collection import CollectionError


def corroboration(con,left,right,excerpt=''):
    left_ids=component(con,left);right_ids=component(con,right)
    if set(left_ids)&set(right_ids):return False,'These authors are already linked.'
    def rows(ids):
        placeholders=','.join('?' for _ in ids)
        claims=[dict(r) for r in con.execute(f"SELECT * FROM author_assertions WHERE author_id IN ({placeholders}) AND status='verified'",ids)]
        papers={r['id']:r['title'] for r in con.execute(f'SELECT p.id,p.title FROM papers p JOIN authorship au ON au.paper_id=p.id WHERE au.author_id IN ({placeholders})',ids)}
        return claims,papers
    lc,lp=rows(left_ids);rc,rp=rows(right_ids)
    if lp.keys()&rp.keys():return False,'Distinct ordered authors on the same paper cannot be merged by this workflow.'
    lo={a['value'] for a in lc if a['kind']=='orcid'};ro={a['value'] for a in rc if a['kind']=='orcid'}
    if len(lo)>1 or len(ro)>1:return False,'Multiple conflicting verified ORCIDs within an identity require correction first.'
    if lo and ro and lo.isdisjoint(ro):return False,'Conflicting verified ORCID identifiers require correction first.'
    if lo&ro:return True,'Matching verified ORCID assertions corroborate an identity proposal; analyst confirmation is still required.'
    orgs=lambda claims:{a['organization_id'] for a in claims if a['kind'] in ('affiliation','current_affiliation')}
    evidence=norm(excerpt)
    if orgs(lc)&orgs(rc) and any(norm(t) in evidence for t in lp.values()) and any(norm(t) in evidence for t in rp.values()):
        names=[r['name'] for r in con.execute('SELECT name FROM authors WHERE id IN (?,?)',(left,right))]
        if all(norm(name) in evidence for name in names):return True,'Verified affiliation overlap plus a supplied publication-list excerpt corroborate the proposed identity.'
    return False,'Insufficient identity evidence. A name match alone cannot be confirmed; use verified ORCID or verified affiliations plus corroborating publication evidence.'


def propose(con,left,right,source_url,excerpt,assertion_ids=None):
    if left==right:raise EnrichmentError('Select two distinct author identities.')
    if con.execute('SELECT COUNT(*) FROM authors WHERE id IN (?,?)',(left,right)).fetchone()[0]!=2:raise EnrichmentError('Both author identities must exist.')
    try:validate_url(source_url,resolve=False)
    except CollectionError as error:raise EnrichmentError(str(error)) from None
    for aid in assertion_ids or []:
        if not con.execute('SELECT 1 FROM author_assertions WHERE id=? AND author_id IN (?,?)',(aid,left,right)).fetchone():raise EnrichmentError('Referenced assertion does not belong to either proposed author.')
    pair=sorted((left,right))
    existing=con.execute("SELECT id FROM identity_proposals WHERE left_author_id=? AND right_author_id=? AND status='pending'",pair).fetchone()
    if existing:return existing['id']
    eligible,reason=corroboration(con,left,right,excerpt)
    ident=str(uuid.uuid4())
    con.execute('INSERT INTO identity_proposals VALUES(?,?,?,?,?,?,?,?,?)',(ident,*pair,source_url,excerpt,json.dumps(assertion_ids or []),reason,'pending',time.time()))
    return ident


def review_identity(con,pid,action,note):
    row=con.execute('SELECT * FROM identity_proposals WHERE id=?',(pid,)).fetchone()
    if not row:raise EnrichmentError('Identity proposal not found.')
    if action=='undo':
        if row['status']!='confirmed':raise EnrichmentError('Only a confirmed merge can be undone.')
        con.execute('UPDATE identity_links SET active=0 WHERE proposal_id=?',(pid,))
        con.execute("UPDATE identity_proposals SET status='undone' WHERE id=?",(pid,))
        outcome='Merge undone. Original assertions, ordered authorship, and all paper associations remain intact.'
    else:
        if row['status']!='pending':raise EnrichmentError('Proposal has already been reviewed.')
        if action=='confirm':
            eligible,reason=corroboration(con,row['left_author_id'],row['right_author_id'],row['excerpt'])
            if not eligible:raise EnrichmentError(reason)
            con.execute('INSERT INTO identity_links VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),pid,row['left_author_id'],row['right_author_id'],1,time.time()))
            status='confirmed';outcome='Identity link confirmed. Original author records were preserved.'
        else:status='rejected';outcome='Identity proposal rejected. Author records remain separate.'
        con.execute('UPDATE identity_proposals SET status=? WHERE id=?',(status,pid))
    con.execute('INSERT INTO identity_history VALUES(?,?,?,?,?)',(str(uuid.uuid4()),pid,action,note,time.time()))
    return outcome


def supported_proposals(con):
    rows=con.execute("SELECT * FROM author_assertions WHERE kind='orcid' AND status='verified' ORDER BY value,author_id").fetchall();created=[]
    # Bounded; no quadratic name matching or automatic merge.
    by_id={}
    for row in rows:
        for prior in by_id.get(row['value'],[])[:20]:
            if prior['author_id']==row['author_id']:continue
            if con.execute("SELECT 1 FROM identity_proposals WHERE ((left_author_id=? AND right_author_id=?) OR (left_author_id=? AND right_author_id=?)) AND status IN ('pending','rejected','confirmed','undone')",(prior['author_id'],row['author_id'],row['author_id'],prior['author_id'])).fetchone():continue
            eligible,_=corroboration(con,prior['author_id'],row['author_id'])
            if not eligible:continue
            pid=propose(con,prior['author_id'],row['author_id'],prior['source_url'],prior['excerpt'],[prior['id'],row['id']]);created.append(pid)
        by_id.setdefault(row['value'],[]).append(row)
        if len(created)>=100:break
    return created
