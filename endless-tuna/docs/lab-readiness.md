# Local lab preparation results

Verified 2026-11-10 on Ubuntu, Python 3.12 and Node 24. The repository was prepared locally: no remote creation, staging/commit, push, public deployment or license selection was performed. The existing Option 3 dashboard, stored collections and LAS-only model path were preserved.

## Changes

- Added `start.sh` and a Python supervisor for API, Vite frontend and a separate worker, with readiness checks, loopback ports, occupied-port diagnostics, coordinated shutdown and a production-UI `--built` mode. The worker serves both isolated collections by default.
- Fixed graceful worker shutdown to finish a submitted bounded batch, preserve checkpoints and requeue remaining work without waiting for lease expiry. Forced termination still recovers through leases. Added a migration CLI with read-only status, repeatable apply and a guard against starting older code against newer schemas.
- Added a non-root multi-stage Docker image and optional Compose services with health ordering, configurable loopback host port and persistent SQLite/demo-PDF/real-PDF volumes.
- Removed the dashboard's external Google Fonts dependency; clean system sans-serif typography retains the bright design and permits fully local browser operation. Acceptance now blocks all external browser requests.
- Added constrained direct dependencies, exact Python/npm locks, supported version hints, offline CI and a redacted publication scanner. No obsolete Conference Explorer branding was found in the active application/docs/configuration.
- Finished README, analyst walkthrough, architecture/data flow, configuration, adapter guide, backup/restore, troubleshooting, limitations, publication guide and enduring AGENTS constraints.

## Verification

| Check | Outcome | Scope |
| --- | --- | --- |
| Backend suite | Passed | **116 tests**, with all production HTTP transports blocked/mocked. Includes worker shutdown/resume, migrations, FTS, provenance, identity, LAS diagnostics and export behavior. |
| Python compile and dependency consistency | Passed | compileall and pip check. One upstream Starlette/httpx TestClient deprecation warning remains; no failing test. |
| Clean frontend install/type check/build | Passed | npm ci, TypeScript and Vite production build; npm reported zero known vulnerabilities at installation time. |
| Browser analyst acceptance | Passed | All eleven requested workflow steps; fictional inventory/mocked transport, no credentials. Zero console errors, zero attempted external browser requests and zero LAS calls. Desktop/narrow, keyboard, history, evidence, review, import/retry, Excel/ZIP inspection and restart/resume exercised. |
| Accessibility | Passed within tested scope | Discovery axe scan had zero violations. A pseudo-element badge required an explicit contrast check (15.53:1). No comprehensive manual audit claimed. |
| One-command launcher | Passed | Actual API, Vite and worker launched on isolated loopback ports; built mode also exercised. Health/UI/demo loading and clean shutdown checked, listeners closed and data preserved. |
| Docker Compose | Passed | Config validation, clean locked image build, healthy app/worker, non-root writable volumes, nine demo papers/three PDFs and empty real collection. Test marker/PDFs survived rebuild and container recreation. No-LAS health passed. Isolated verification containers/volumes were removed afterwards; normal application data was untouched. |
| Backup/restore | Passed | Stopped fictional two-database/three-PDF snapshot restored to a new directory; SQLite integrity/foreign-key checks and byte hashes matched. |
| Publication hygiene | Passed within scanner scope | Tracked index and prepared unignored files checked without printing values; no findings. Runtime/secrets/build artifacts remain ignored. This is not a historical secret audit. |
| Naming | Passed | Active UI/API/package/docs use endless tuna / endless-tuna. Preserved root legacy application remains separate. |
| Real conference collection | Previously verified; not rerun here | Existing smoke report records ten official NeurIPS 2024 main papers, ten proceedings PDFs and 332 indexed pages. Observed official main count 4,034; full inventory incomplete. Previous stored-real exports inspected ten papers/PDFs separately. No fresh live collection is represented by the mocked browser checks. |
| Live LAS model discovery | Unverified | No local credentials configured; no live request attempted. |
| Live LAS inference | Unverified | No live completion initiated; tests are mocked. |
| macOS execution | Unverified | Instructions prepared; no macOS runtime available for this local verification. |
| GitHub-hosted CI/version matrix | Unverified | Workflow prepared for Python 3.11/3.12/3.13 and Node 22/24. No remote repository or GitHub run created. |

No failing final checks remain. Port 8000 was already occupied on this workstation; Compose verification used configurable loopback port 8041 and native verification used 8031/8032 plus 5187. No unrelated process was stopped.

## Evidence and remaining scope

Ignored local artifacts: `var/acceptance/acceptance.json`, `accessibility.json`, screenshots and inspected XLSX/ZIP; `var/launcher-verification.json`, `backup-verification.json`, `neurips-smoke-result.json` and `real-export-verification.json`. Reports distinguish fictional fixtures from actual stored source data. Docker build/start/recreate checks were performed through the local CLI; no runtime documents or credentials were added to source control.

Remaining product limits are explicit in [known limitations](known-limitations.md): other live adapters, OCR, automatic Scholar lookup, broader affiliation-layout extraction, large-scale performance validation and authenticated remote use are unfinished. These are not represented as implemented features. LAS discovery/inference require locally configured credentials and gateway access; the supplied URL alone verifies neither.

Use [setup](setup.md) for exact first-time/daily startup and migration commands and [GitHub preparation](github-readiness.md) for prepared files and review scope.
