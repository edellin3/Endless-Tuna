# Local lab setup

Supported targets: Ubuntu 22.04/24.04 and macOS with Python **3.11–3.13**, SQLite FTS5, Node **22.12+ within 22.x or 24.x**, and npm. Python 3.12 and Node 24 are the reference versions (`.python-version`, `.nvmrc`). This checkout was exercised on Ubuntu with Python 3.12 and Node 24; the CI matrix covers the listed Python/Node versions, but has not yet run on GitHub. macOS has not been exercised here.

## Prerequisites

On Ubuntu 24.04:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

Ubuntu 22.04's default Python 3.10 is too old. Install an approved Python 3.11–3.13 distribution first and use its executable below. On macOS, use an approved Python 3.12 installation; with Homebrew already installed:

```bash
brew install python@3.12 node@24
export PATH="$(brew --prefix node@24)/bin:$PATH"
```

The versioned [Python](https://formulae.brew.sh/formula/python@3.12) and [Node](https://formulae.brew.sh/formula/node@24) formulae provide the reference interpreters; Node's versioned formula is keg-only, hence the PATH line.

On Ubuntu, install Node 24 using your lab's supported package/version manager. With nvm already installed, from the repository root:

```bash
cd endless-tuna
nvm install
nvm use
cd ..
```

Check `python3.12 --version`, `node --version`, and `npm --version`. Replace `python3.12` below with `python3` only if it is a supported version. Virtual environments are intentionally recreated rather than copied between machines; see [Python's venv documentation](https://docs.python.org/3.12/library/venv.html).

## First installation

Run from the repository root, the directory containing `start.sh`:

```bash
python3.12 -m venv endless-tuna/.venv
endless-tuna/.venv/bin/python -m pip install -r endless-tuna/backend/requirements.lock
cd endless-tuna/frontend
npm ci
npm run build
cd ../..
```

Optional server configuration: copy `.env.example` to `endless-tuna/.env` **only if that file does not already exist**, and edit it locally. No credentials are needed to start. The older root application and its `.env` are separate and are never loaded by endless tuna.

```bash
test -e endless-tuna/.env || cp .env.example endless-tuna/.env
./start.sh
```

Open **http://127.0.0.1:5173**. The supervisor launches the API on 8000, Vite on 5173, and one separate worker servicing both isolated collections. API readiness precedes the other processes. Ctrl-C or SIGTERM stops all three; a failed child stops its siblings. Shutdown waits up to 120 seconds for a bounded worker batch; if forced, lease recovery resumes persisted checkpoints on restart. No browser opens automatically and startup performs no model request. Existing queued collection jobs can resume external collection access.

For daily use without the Vite process, `./start.sh --built` serves the production frontend from the API at **http://127.0.0.1:8000** and launches the worker. Rebuild after frontend changes. `TUNA_API_PORT`/`TUNA_UI_PORT` can be set in `endless-tuna/.env` or process environment; all native listeners remain on `127.0.0.1`. Stop an older separately launched instance if its port is occupied.

## Database migrations and isolated modes

From the repository root:

```bash
cd endless-tuna/backend
../.venv/bin/python -m endless_tuna.migrate --status
../.venv/bin/python -m endless_tuna.migrate
```

Status does not create databases. Apply initializes both collections and runs unapplied ordered SQL migrations transactionally; API/worker startup also applies migrations under a SQLite write lock. New demo gets fictional seed records/PDFs; new real stays empty. `--collection real` limits the command. Demo reset in Settings never clears real records. Existing real collections are preserved. Set `TUNA_DATA_DIR` to a **new empty directory** for an independently empty installation; do not delete an existing collection to simulate a fresh start.

Before upgrades, stop services and [back up](backup-and-restore.md), install locked dependencies, build, inspect/apply migrations, then start. There is no automated downgrade: restore matching code and data together.

## Optional Docker Compose

Requires Docker Engine/Desktop and Compose **2.24+** (optional env-file support). From the repository root:

```bash
docker compose -f endless-tuna/compose.yaml up --build
```

Open **http://127.0.0.1:8000**. The image builds the frontend; the app serves it and a separate worker waits for app health. The container binds internally on all interfaces, but the only host port is explicitly loopback. [Compose health-based dependency ordering](https://docs.docker.com/compose/how-tos/startup-order/) is used. Ctrl-C shuts down both services; `docker compose -f endless-tuna/compose.yaml down` removes containers while retaining volumes. Do not add `-v` unless intentionally deleting data.

Named volumes hold database/export state (`endless-tuna_database`) and separate demo/real PDFs (`endless-tuna_demo-pdfs`, `endless-tuna_real-pdfs`). They are shared by app and worker; they are separate from native `var/` data. Optional `endless-tuna/.env` is read only at runtime, excluded from the image. Compose forces `TUNA_DATA_DIR=/data`. `TUNA_API_PORT=8041 docker compose -f endless-tuna/compose.yaml up` selects a different loopback host port if 8000 is occupied; internal app port remains 8000. No Docker socket mount, remote host port or external database is required. Docker build/pull and first installation need package-network access.

To inspect/apply container migrations with services stopped:

```bash
docker compose -f endless-tuna/compose.yaml run --rm --no-deps app python -m endless_tuna.migrate --status
docker compose -f endless-tuna/compose.yaml run --rm --no-deps app python -m endless_tuna.migrate
```
