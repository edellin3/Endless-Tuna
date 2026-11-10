import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from . import config  # consistent .env loading for API, worker and migration CLI

DATA = Path(os.getenv('TUNA_DATA_DIR', Path(__file__).resolve().parents[2] / 'var')).expanduser().resolve()

def collection_path(collection):
    if collection not in ('demo', 'real'):
        raise ValueError('Unknown collection')
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA / f'{collection}.sqlite3'

@contextmanager
def connect(collection='demo'):
    db = sqlite3.connect(collection_path(collection), timeout=30)
    db.row_factory = sqlite3.Row
    def pdf_exists(value):
        try:
            root=(DATA/f'{collection}-pdfs').resolve();path=(root/(value or '')).resolve()
            return int(bool(value) and path.is_relative_to(root) and path.is_file())
        except (OSError,ValueError):return 0
    db.create_function('pdf_exists',1,pdf_exists)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize(collection):
    with connect(collection) as db:
        # Serialize initialization across the API and separate worker processes.
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS migrations(version TEXT PRIMARY KEY)')
        files=sorted((Path(__file__).parent / 'migrations').glob('*.sql'))
        applied={r[0] for r in db.execute('SELECT version FROM migrations')}
        if applied-{f.name for f in files}:
            raise ValueError('Database is newer than this checkout. Restore matching application code; downgrades are not supported.')
        for file in files:
            if db.execute('SELECT 1 FROM migrations WHERE version=?', (file.name,)).fetchone():
                continue
            statement = ''
            for char in file.read_text():
                statement += char
                if char == ';' and sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            if statement.strip():
                db.execute(statement)
            db.execute('INSERT INTO migrations VALUES(?)', (file.name,))
        if collection == 'demo' and not db.execute('SELECT 1 FROM series').fetchone():
            seed(db)

def seed(db):
    conferences = [ ('harbor', 'Harbor Robotics Forum', 2025, 'Robotics, with a human perspective.', 'complete'), ('summit', 'Summit Learning Symposium', 2025, 'New ideas at the intersection of learning and the physical world.', 'partial'), ('field', 'Field Intelligence Workshop', 2024, 'Practical intelligence beyond the lab.', 'complete') ]
    titles = [ ['Learning to navigate together', 'Soft grippers for delicate ocean sampling', 'A benchmark for collaborative robotics'], ['Teaching robots through human demonstration', 'Reliable representations for changing environments', 'Small models, thoughtful decisions'], ['Robotics for coastal ecosystem monitoring', 'Mapping uncertainty in field observations', 'Low-power sensors for remote habitats'] ]
    abstracts = ['We explore robotics and shared navigation through a fictional fleet of coastal research robots. Our study considers safe coordination and learning from limited demonstrations.', 'This fictional study investigates adaptive sensing, robust learning, and environmental observation in changing conditions.', 'A fictional benchmark with transparent evaluation, reproducible methods, and an emphasis on practical deployment.']
    for i, (slug,name,year,desc,status) in enumerate(conferences):
        db.execute('INSERT INTO series VALUES(?,?)',(slug,name))
        db.execute('INSERT INTO editions(id,series_id,year,description,status,source_url) VALUES(?,?,?,?,?,?)',(slug,slug,year,desc,status,'https://example.org/'+slug))
        db.execute('INSERT INTO tracks VALUES(?,?,?)',(slug+'-main',slug,'Main research track'))
        db.execute('INSERT INTO sources VALUES(?,?,?,?)',(slug+'-source',slug,'https://example.org/'+slug,'Fictional accepted-paper listing'))
        for j,title in enumerate(titles[i]):
            pid=f'{slug}-{j}'
            db.execute('INSERT INTO papers(id,edition_id,track_id,title,abstract,review_status) VALUES(?,?,?,?,?,?)',(pid,slug,slug+'-main',title,abstracts[j], 'uncertain' if j==1 else 'confirmed'))
            db.execute('INSERT INTO paper_editions VALUES(?,?,?,?,?,?)',(pid,slug,slug+'-main','https://example.org/'+slug,'https://example.org/'+slug,0))
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(pid+'-ev',pid,slug+'-source','accepted paper',f'Demo listing: “{title}” — accepted in the main research track.'))
            db.execute('INSERT INTO downloads(id,paper_id,status,path,source_url,error) VALUES(?,?,?,?,?,?)',(pid+'-pdf',pid,'available' if j==0 else 'missing', pid+'.pdf' if j==0 else None, None,None))
            if j==0:
                write_demo_pdf(pid, title)
    for aid,name,org in [('a1','Mira Chen','Tidal Research Institute'),('a2','Alex Rivera','Northstar Lab'),('a3','Sam Okafor','Tidal Research Institute'),('a4','Alex Rivera','Open Coast Collective')]:
        db.execute('INSERT INTO authors VALUES(?,?,?)',(aid,name,'Fictional researcher in the isolated demo collection.'))
        db.execute('INSERT OR IGNORE INTO organizations VALUES(?,?)',(org,org))
    for i,slug in enumerate(['harbor','summit','field']):
        for j in range(3):
            for pos,aid in enumerate([['a1','a2'],['a3','a1'],['a4','a3']][j],1):
                db.execute('INSERT INTO authorship VALUES(?,?,?)',(f'{slug}-{j}',aid,pos))
                org='Tidal Research Institute' if aid in ('a1','a3') else ('Northstar Lab' if aid=='a2' else 'Open Coast Collective')
                db.execute('INSERT INTO affiliations VALUES(?,?,?)',(f'{slug}-{j}',aid,org))

def write_demo_pdf(pid,title):
    folder=DATA/'demo-pdfs'; folder.mkdir(exist_ok=True)
    content=f'BT /F1 18 Tf 50 750 Td (DEMO DATA - FICTIONAL PAPER) Tj 0 -35 Td /F1 12 Tf ({title}) Tj 0 -30 Td (Illustrative PDF. No real research claims.) Tj ET'.encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream']
    pdf=b'%PDF-1.4\n'; offsets=[0]
    for n,obj in enumerate(objects,1):
        offsets.append(len(pdf)); pdf+=f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(pdf); pdf+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    (folder/(pid+'.pdf')).write_bytes(pdf)
