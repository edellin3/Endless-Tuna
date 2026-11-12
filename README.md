# endless tuna

Source repository: [edellin3/Endless-Tuna](https://github.com/edellin3/Endless-Tuna).

A local research discovery dashboard for analysts: search indexed conference editions, explore accepted papers and PDFs, inspect author/organization evidence, review uncertain results and export stored data. Project slug: **endless-tuna**. This folder is the self-contained project root; the older Flask prototype remains separately in the parent workspace.

The Option 3 dashboard uses a bright #F6F8FC page, white rounded cards, a large pale-blue search panel, desktop left filters/two-column conference cards, narrow-screen collapsible filters/one-column cards, cobalt actions and restrained coral tuna/infinity branding. Explore, Library and Authors are primary navigation; Collection jobs and Review queue are under More. Settings is secondary. These are real React components, not a mockup image.

## Collect a conference

Paste its link in **Add conference** and click **Collect papers**. Titles and available free PDFs arrive automatically on one conference page. The default is a ten-paper quick test; choose **Entire conference** for all papers. Pause/resume and attention counts stay on that page. [Automatic collection](docs/automatic-collection.md).

## Open in VS Code

Open this folder, or open [endless-tuna.code-workspace](endless-tuna.code-workspace). All paths below are relative to this folder, not the parent `prototype` workspace.

```text
endless-tuna/
  backend/       FastAPI, SQLite migrations and backend tests
  frontend/      React, TypeScript and Vite
  docs/          Analyst and operations guides
  scripts/       Startup supervisor and publication checks
  .github/       Standalone GitHub Actions workflow
  .env.example   Server configuration template
  .venv/         Existing local Python environment (ignored)
  var/           Existing databases, PDFs and exports (ignored)
  start.sh       One-command launcher
```

## First installation

Supported: Ubuntu 22.04/24.04 or macOS; **Python 3.11–3.13 with SQLite FTS5**, **Node 22.12+ within 22.x or 24.x**, npm. Reference versions are Python 3.12 and Node 24. See [Ubuntu/macOS prerequisites](docs/setup.md), including Ubuntu 22.04's older default Python.

From the project root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
cd frontend
npm ci
npm run build
cd ..
test -e .env || cp .env.example .env
./start.sh
```

Open **http://127.0.0.1:5173**. After installation, `./start.sh` is the one-command launcher for backend, frontend and durable worker. Ctrl-C stops them together. Credentials are optional. It binds localhost and does not publish the application. `./start.sh --built` instead serves the built UI at **http://127.0.0.1:8000** with the API and worker. Stop conflicting older instances first; ports are configurable.

Optional containers: `docker compose -f compose.yaml up --build` serves the built UI/API on **127.0.0.1:8000**, with a separate worker and persistent database/demo-PDF/real-PDF volumes. See [setup, migrations and Compose](docs/setup.md).

## Working features

- Local FTS5 keyword/phrase search across conference metadata, titles, abstracts and available page text. Stable pagination, duplicate-free matching counts, evidence snippets and URL/browser-history state. Filters include year, conference, organization, verified organization country, PDF and review status.
- Real NeurIPS 2026 **official virtual-program** inventory (published tracks kept separate) and NeurIPS 2024 **main-proceedings** adapters, explicit metadata/CSV import, official PDF preference, conservative arXiv matching, reviewable candidates, manual PDF URLs and optional JSON web search. Durable jobs checkpoint Inventory → Resolve PDFs → Download → Extract text → Ready for enrichment, with per-paper failure/retry/resume.
- Ordered authors, paper-time multi-affiliations, evidence/status/history, conservative deterministic extraction and optional explicit LAS extraction. Analyst review, corroborated identity links and undo preserve original paper associations. Scholar profile links require supplied URLs and verification.
- Conference/paper/author detail, PDF viewing, coverage, review queue and Settings diagnostics. Seven-sheet relational Excel exports and size-bounded split PDF ZIPs include manifests/missing reports; export scopes are explicit.
- Isolated fictional **Demo data** (three editions, nine papers, four author identities and three illustrative PDFs) and independently empty **Real collection** on first initialization. Existing real data is preserved. Demo reset never clears real records.

Search covers the **indexed collection**, not the live web. A ten-paper sample job never establishes complete conference inventory. Unsupported conference URLs are rejected. OCR, arbitrary-site collection and automatic Scholar lookup are not implemented. See [known limitations](docs/known-limitations.md).

## LAS and network boundaries

Only the server loads `.env`; process environment takes precedence. This uses the same connection pattern intended for Scientist-on-Call while keeping the applications and configuration separate:

```dotenv
LAS_API_BASE_URL=https://llm-west.ncsu-las.net/v1
LAS_API_KEY=
LAS_MODEL=
LAS_TIMEOUT_SECONDS=90
```

Fill placeholders locally; never paste keys into chat/browser controls or VITE variables. `OPENAI_KEY` is a compatibility fallback only when LAS_API_KEY is **absent**; explicitly empty LAS_API_KEY does not fall back. All model inference passes through the centralized server-side LAS client and configured gateway. No hard-coded/substituted model or automatic fallback to another provider exists.

Settings shows credential presence only. **Check connection** explicitly discovers `/models`; select an exact returned ID, then **Test model** explicitly sends a tiny `/chat/completions` request. Opening Settings sends no completion. Discovery and inference access are verified separately. A previous 403 may reflect permissions or network access and does not prove the key is wrong. See [configuration](docs/configuration.md) and [troubleshooting](docs/troubleshooting.md).

Conference websites, arXiv and optional web search are separate collection connections. Stored records remain locally searchable without external access. New collection needs relevant source access; AI enrichment needs LAS connectivity. Local parsing, deterministic extraction and exports work without LAS.

## Documentation and checks

- [Analyst walkthrough](docs/analyst-walkthrough.md)
- [Architecture and data flow](docs/architecture.md)
- [Configuration reference](docs/configuration.md)
- [Adapter development](docs/adapter-development.md) and [collection/CSV contracts](docs/collection.md)
- [Evidence and identity](docs/enrichment.md); [search and export semantics](docs/search-and-exports.md)
- [Backup/restore](docs/backup-and-restore.md), [troubleshooting](docs/troubleshooting.md), [limitations](docs/known-limitations.md)
- [Analyst acceptance checklist](docs/acceptance.md), [lab preparation results](docs/lab-readiness.md), [GitHub preparation](docs/github-readiness.md), [enduring constraints](AGENTS.md)

```bash
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/python -m endless_tuna.migrate --status
cd ../frontend
npm run typecheck
npm run build
npm run test:acceptance
cd ..
python3 scripts/check_publication.py
git diff --check
```

Automated backend/browser tests use mocked source/model transport and fictional demo data; they do not call live external services. The prior real smoke collection recorded ten official NeurIPS 2024 main papers/PDFs from an observed 4,034-paper main inventory (incomplete). A subsequent full live 2026 run collected 9,139 listed papers across published tracks; inventory is complete for that fetched feed, but PDF downloads paused after OpenReview access denials. See the collection guide for the separate coverage figures. Live LAS discovery/inference is not claimed by those checks. [Verification reports](docs/lab-readiness.md) distinguish each category.

CI is prepared in `.github/workflows/endless-tuna.yml`; it needs no credentials or live service access for application tests. Runtime databases, PDFs, logs, exports, backups and `.env` are ignored. Collected third-party documents are separate from original code. No public license has been chosen. Source publication is separate from running or hosting the application; see [GitHub preparation](docs/github-readiness.md).

Find new sources from **Explore → Find conferences**. Search the official PMLR directory by conference name/abbreviation or known subject, filter by event year/source, and check inventory access before adding to Real collection. CoRL/ICML PMLR volumes and RSS 2025 have collectors alongside NeurIPS. A complete inventory is distinct from PDF availability; collection still defaults to ten papers. See [conference discovery](docs/discovery.md).

The default **Add conference** flow accepts a link and automatically collects titles and free PDFs. It uses Real collection and retains the ten-paper default unless you choose Entire conference. See [automatic collection](docs/automatic-collection.md) for behavior and limits; [manual staged intake](docs/link-first-collection.md) is an optional advanced workflow.

WACV 2026 is supported from its [conference homepage](https://wacv.thecvf.com/Conferences/2026): click Collect papers to save titles and find free PDFs automatically. See [WACV 2026 collection](docs/wacv-2026.md) for scope, source validation and live test results.
