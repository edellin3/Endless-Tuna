from fastapi import Depends,Query
from . import db as storage
from .search import paper_rows,conference_results,paginate,decorate_rows,parse_query


def register_search(app,collection):
    @app.get('/api/search/conferences')
    def conferences(q:str='',year:int|None=None,conference:str|None=None,organization:str|None=None,country:str|None=None,pdf:str|None=None,review:str|None=None,page:int=Query(1,ge=1,le=100000),page_size:int=Query(12,ge=1,le=100),c=Depends(collection)):
        with storage.connect(c) as con:
            rows=conference_results(con,q,year,conference,organization,country,pdf,review)
        result=paginate(rows,page,page_size,q)
        result['matching_papers']=len({pid for row in rows for pid in row['matching_paper_ids']})
        return result

    @app.get('/api/search/papers')
    def papers(q:str='',edition:str|None=None,year:int|None=None,conference:str|None=None,organization:str|None=None,country:str|None=None,pdf:str|None=None,review:str|None=None,page:int=Query(1,ge=1,le=100000),page_size:int=Query(25,ge=1,le=100),c=Depends(collection)):
        with storage.connect(c) as con:
            rows=paper_rows(con,q,edition,year,conference,organization,pdf,review,country=country,include_evidence=False)
            result=paginate(rows,page,page_size,q)
            decorate_rows(con,result['items'],parse_query(q))
            return result
