# GitHub preparation

The repository is prepared locally only. No remote is created, no code is pushed and no application is published by these instructions. No public license is selected; the owner must decide licensing before public release.

Original application code is under `backend/endless_tuna`, `frontend/src`, migrations and scripts. Tiny fictional/minimal test fixtures are separate from collected documents. Local `var/`, custom PDF folders, exports, credentials and backups are not source code and must remain outside Git. Root Flask files are the preserved older application, not endless tuna; review whether to include that legacy code when choosing the eventual repository's scope.

Prepared files include the dependency constraints and exact `backend/requirements.lock`, npm `package-lock.json`, version hints, `start.sh`/supervisor, Dockerfile/Compose/.dockerignore, `.env.example`, `.gitignore`, architecture/analyst/operations docs, tests and `.github/workflows/endless-tuna.yml`. CI runs offline backend tests/compile checks on Python 3.11–3.13 and frontend TypeScript/build on Node 22/24. No credentials, live source requests or model calls are used by application tests. Dependency/action installation still requires registry/GitHub access. The workflow's GitHub execution is unverified until a repository owner runs it there.

From the repository root:

```bash
python3 scripts/check_publication.py
git diff --check
git status --short
```

The scanner inspects tracked index bytes plus tracked/unignored working files and prints only filenames/rules/counts. It flags common credentials, private keys, literal key assignments, credential URLs and runtime/document artifacts. Three URL-rejection test files intentionally allow invalid credential-URL fixtures; actual key/private-key rules still apply there. Ignored secrets/data are deliberately not read. This is a heuristic working-tree/index scan, not a historical Git secret audit or guarantee. Review staged file names and diffs locally without printing secret values into issue reports. Re-run after staging and before a future push.

If a credential was ever committed, removing the file or adding an ignore rule is insufficient: revoke/rotate it and perform an authorized history-removal process before publication. Nothing in this preparation changes history, stages files, commits, creates a remote or selects a license.
