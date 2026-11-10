"""Apply ordered migrations or inspect status; never downgrade or reset collections."""
import argparse
import sqlite3
from pathlib import Path
from . import db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', choices=['demo', 'real', 'all'], default='all')
    parser.add_argument('--status', action='store_true', help='Inspect without creating or changing databases')
    args = parser.parse_args()
    versions = [p.name for p in sorted((Path(__file__).parent / 'migrations').glob('*.sql'))]
    for collection in (['demo', 'real'] if args.collection == 'all' else [args.collection]):
        path = db.DATA / f'{collection}.sqlite3'
        if not args.status:
            db.initialize(collection)
        applied = set()
        if path.exists():
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as con:
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='migrations'").fetchone():
                    applied = {r[0] for r in con.execute('SELECT version FROM migrations')}
        unknown = applied - set(versions)
        if unknown:
            parser.exit(1, f'{collection}: database is newer than this checkout; restore matching application code.\n')
        print(f'{collection}: {len(applied)}/{len(versions)} migrations applied')
        for version in versions:
            print(f'  {"applied" if version in applied else "pending"} {version}')


if __name__ == '__main__':
    main()
