import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import pytest

from fastapi.testclient import TestClient
from endless_tuna import db
from endless_tuna.main import app
from endless_tuna import worker


def test_worker_shutdown_requeues_and_resumes_persisted_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path)
    with TestClient(app) as client:
        response = client.post('/api/conferences', headers={'X-Collection': 'real'}, json={
            'name': 'Fictional shutdown fixture', 'year': 2024, 'track': 'Main',
            'source_url': 'https://example.org/inventory.json', 'adapter': 'metadata'})
        assert response.status_code == 201, response.text
    # Use a persisted inventory, so neither shutdown nor resume needs source access.
    with db.connect('real') as con:
        jid = con.execute('SELECT id FROM jobs').fetchone()[0]
        payload = {'records': [{'title': 'Fictional checkpoint', 'source_url': 'https://example.org/paper',
                               'authors': [], 'abstract': ''}], 'official_count': 1,
                   'url': 'https://example.org/inventory.json'}
        con.execute('INSERT INTO job_payloads VALUES(?,?)', (jid, json.dumps(payload)))
    stopped = threading.Event(); stopped.set()
    assert worker.tick('real', shutdown=stopped)
    with db.connect('real') as con:
        job = con.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        assert job['status'] == 'queued' and job['lease_token'] is None
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1
    def finish(collection, job, token, item, adapter):
        with db.connect(collection) as con:
            worker.owned(con, job['id'], token)
            con.execute("UPDATE job_papers SET status='done',stage='ready' WHERE job_id=?", (job['id'],))
    monkeypatch.setattr(worker, 'process_paper', finish)
    assert worker.tick('real')
    with db.connect('real') as con:
        assert con.execute('SELECT status FROM jobs').fetchone()[0] == 'complete'
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 1


def test_migration_status_does_not_create_data_and_apply_is_repeatable(tmp_path, monkeypatch):
    from endless_tuna import migrate
    monkeypatch.setattr(db, 'DATA', tmp_path / 'new')
    monkeypatch.setattr(sys, 'argv', ['migrate', '--status'])
    migrate.main()
    assert not db.DATA.exists()
    monkeypatch.setattr(sys, 'argv', ['migrate'])
    migrate.main(); migrate.main()
    with db.connect('real') as con:
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 0
    with db.connect('demo') as con:
        assert con.execute('SELECT COUNT(*) FROM papers').fetchone()[0] == 9


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_supervisor_shutdown_terminates_child_process_group():
    supervisor = load_script('tuna_start', Path(__file__).parents[2] / 'scripts/start.py')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    try:
        supervisor.stop_children([child], timeout=2)
        assert child.returncode == -signal.SIGTERM
    finally:
        if child.poll() is None: child.kill(); child.wait()


def test_older_checkout_refuses_newer_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path)
    db.initialize('real')
    with db.connect('real') as con:
        con.execute("INSERT INTO migrations VALUES('999_future.sql')")
    with pytest.raises(ValueError, match='newer than this checkout'):
        db.initialize('real')


def test_publication_scan_reports_rules_without_secret_values():
    scanner = load_script('publication', Path(__file__).parents[2] / 'scripts/check_publication.py')
    fake = b'LAS_API_KEY=' + b'opaque-credential-for-fixture'
    assert scanner.findings('config.py', fake) == ['literal secret assignment']
    assert not scanner.findings('.env.example', b'LAS_API_KEY=\nLAS_MODEL=\n')
    assert 'runtime/secret/document artifact' in scanner.findings('collected/paper.pdf', b'')
