# Backup and restore

Back up SQLite **and** its matching PDF folders together. Exports alone are not a backup: assertions, review history, memberships, jobs and settings live in SQLite. Configuration credentials are not inside the database and should be backed up separately using the lab's secret store. Do not add backups, PDFs or `.env` to Git.

## Native installation

1. Stop `start.sh` with Ctrl-C and wait for shutdown. Stop any independently launched worker/API too. Do not copy a live WAL database as a lone `.sqlite3` file.
2. Identify `TUNA_DATA_DIR` (default `endless-tuna/var`). The examples below assume the default; substitute an absolute directory for a custom location.
3. From the repository root, create a private archive outside the repository:

```bash
umask 077
mkdir -p "$HOME/endless-tuna-backups"
tar -czf "$HOME/endless-tuna-backups/endless-tuna-data-$(date +%Y%m%d-%H%M%S).tgz" -C endless-tuna/var .
```

The stopped-directory snapshot includes both collection DBs and any WAL/SHM companions, demo/real PDFs, app settings and temporary export artifacts. Keep a record of the matching Git commit/app version and dependency locks. Protect storage permissions and follow the lab's retention policy for third-party documents.

Restore a **trusted** backup into a new empty directory, leaving current data intact:

```bash
mkdir -m 700 /tmp/endless-tuna-restored
tar -xzf "$HOME/endless-tuna-backups/<backup-file>.tgz" -C /tmp/endless-tuna-restored
```

Choose an enduring lab directory instead of `/tmp` for actual use. Verify SQLite integrity before starting (adjust the path):

```bash
endless-tuna/.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
for file in Path('/tmp/endless-tuna-restored').glob('*.sqlite3'):
    with sqlite3.connect(file) as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', file.name
        assert not con.execute('PRAGMA foreign_key_check').fetchall(), file.name
    print(file.name, 'integrity ok')
PY
```

Set `TUNA_DATA_DIR` to that absolute restored directory in this application's `.env`, inspect migrations with matching code, then `./start.sh`. Check demo and real counts, open a known paper/PDF, inspect review history and job status. Interrupted running jobs may wait up to 120 seconds for expired leases; resume/retry from Collection jobs. Restore matching older code/data together for rollback; no down-migration is provided. Do not run old code on a newer schema.

## Docker volumes

Stop both services first:

```bash
docker compose -f endless-tuna/compose.yaml stop
mkdir -p "$HOME/endless-tuna-backups"
docker compose -f endless-tuna/compose.yaml run --rm --no-deps --user 0 \
  -v "$HOME/endless-tuna-backups:/backup" app \
  sh -c 'umask 077; tar -czf /backup/endless-tuna-container-data.tgz -C /data .'
```

That command mounts all three shared volumes and snapshots the combined `/data` tree. It does not start the app or worker. Avoid overwriting an earlier backup file unintentionally; rename it between runs. To restore, use **new** volumes under another Compose project name, ensure no services are running against them, and extract the trusted archive:

```bash
docker compose -p endless-tuna-restored -f endless-tuna/compose.yaml run --rm --no-deps --user 0 \
  -v "$HOME/endless-tuna-backups:/backup:ro" app \
  sh -c 'tar -xzf /backup/endless-tuna-container-data.tgz -C /data; chown -R 10001:10001 /data'
```

Run integrity checks/migration status in a one-off restored app container before `up`. This second project still uses host port 8000; stop the original app first. Named volumes persist across `down`; `down -v` destroys them. Native and container storage are separate unless explicitly migrated using a stopped snapshot.
