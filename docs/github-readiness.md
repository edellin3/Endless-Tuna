# GitHub preparation

Canonical source repository: [edellin3/Endless-Tuna](https://github.com/edellin3/Endless-Tuna). Its project files live directly at the repository root. Existing destination history is retained; no parent expert-on-call history is imported.

Publish this project as a standalone repository with this folder’s contents at the repository root. Push only to an explicitly authorized destination. Publishing source does not deploy the running application or transfer local collections. No public license has been selected.

Original application code is under `backend/endless_tuna`, `frontend/src`, migrations and scripts. Tiny fictional/minimal test fixtures are separate from collected documents. Local `var/`, custom PDF folders, exports, credentials and backups are not source code and must remain outside Git. The older Flask files live outside this project folder. Publish only this folder's contents as endless tuna, preserving the separate application in its parent workspace. The parent Git remote still belongs to expert-on-call; this local reorganization does not change it or push code.

Prepared files include the dependency constraints and exact `backend/requirements.lock`, npm `package-lock.json`, version hints, `start.sh`/supervisor, Dockerfile/Compose/.dockerignore, `.env.example`, `.gitignore`, architecture/analyst/operations docs, tests and `.github/workflows/endless-tuna.yml`. CI runs offline backend tests/compile checks on Python 3.11–3.13 and frontend TypeScript/build on Node 22/24. No credentials, live source requests or model calls are used by application tests. Dependency/action installation still requires registry/GitHub access. The workflow's GitHub execution is unverified until a repository owner runs it there.

From the project root:

```bash
python3 scripts/check_publication.py
git diff --check
git status --short
```

The scanner inspects tracked index bytes plus tracked/unignored working files and prints only filenames/rules/counts. It flags common credentials, private keys, literal key assignments, credential URLs and runtime/document artifacts. Four URL-rejection test files intentionally allow invalid credential-URL fixtures; actual key/private-key rules still apply there. Ignored secrets/data are deliberately not read. This is a heuristic working-tree/index scan, not a historical Git secret audit or guarantee. Review staged file names and diffs locally without printing secret values into issue reports. Re-run after staging and before a future push.

If a credential was ever committed, removing the file or adding an ignore rule is insufficient: revoke/rotate it and perform an authorized history-removal process before publication. Use a clean source snapshot for the standalone repository so the parent application’s history and local data are not transferred. Keep the parent remote unchanged. Inspect an existing destination before updating it, preserve its work and never force-push to replace its history. No license is selected by this preparation.
