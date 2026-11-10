# endless tuna

A local research discovery dashboard for analysts: search indexed conference editions, explore accepted papers and PDFs, inspect author/organization evidence, review uncertain results and export stored data. Project slug: **endless-tuna**. The active application is in `endless-tuna/`; the older root Flask prototype is preserved separately.

The Option 3 dashboard uses a bright #F6F8FC page, white rounded cards, a large pale-blue search panel, desktop left filters/two-column conference cards, narrow-screen collapsible filters/one-column cards, cobalt actions and restrained coral tuna/infinity branding. Navigation includes Explore, Library, Authors, Collection jobs and Review queue; Settings is secondary. These are real React components, not a mockup image.

## First installation

Supported: Ubuntu 22.04/24.04 or macOS; **Python 3.11–3.13 with SQLite FTS5**, **Node 22.12+ within 22.x or 24.x**, npm. Reference versions are Python 3.12 and Node 24. See [Ubuntu/macOS prerequisites](endless-tuna/docs/setup.md), including Ubuntu 22.04's older default Python.

From the repository root:

```bash
python3.12 -m venv endless-tuna/.venv
endless-tuna/.venv/bin/python -m pip install -r endless-tuna/backend/requirements.lock
cd endless-tuna/frontend
npm ci
npm run build
cd ../..
test -e endless-tuna/.env || cp .env.example endless-tuna/.env
./start.sh
```

Open **http://127.0.0.1:5173**. After installation, `./start.sh` is the one-command launcher for backend, frontend and durable worker. Ctrl-C stops them together. Credentials are optional. It binds localhost and does not publish the application. `./start.sh --built` instead serves the built UI at **http://127.0.0.1:8000** with the API and worker. Stop conflicting older instances first; ports are configurable.

Optional containers: `docker compose -f endless-tuna/compose.yaml up --build` serves the built UI/API on **127.0.0.1:8000**, with a separate worker and persistent database/demo-PDF/real-PDF volumes. See [setup, migrations and Compose](endless-tuna/docs/setup.md).

## Working features

- Local FTS5 keyword/phrase search across conference metadata, titles, abstracts and available page text. Stable pagination, duplicate-free matching counts, evidence snippets and URL/browser-history state. Filters include year, conference, organization, verified organization country, PDF and review status.
- Real NeurIPS 2024 **main-proceedings** inventory adapter, explicit metadata/CSV import, official PDF preference, conservative arXiv matching, reviewable candidates, manual PDF URLs and optional JSON web search. Durable jobs checkpoint Inventory → Resolve PDFs → Download → Extract text → Ready for enrichment, with per-paper failure/retry/resume.
- Ordered authors, paper-time multi-affiliations, evidence/status/history, conservative deterministic extraction and optional explicit LAS extraction. Analyst review, corroborated identity links and undo preserve original paper associations. Scholar profile links require supplied URLs and verification.
- Conference/paper/author detail, PDF viewing, coverage, review queue and Settings diagnostics. Seven-sheet relational Excel exports and size-bounded split PDF ZIPs include manifests/missing reports; export scopes are explicit.
- Isolated fictional **Demo data** (three editions, nine papers, four author identities and three illustrative PDFs) and independently empty **Real collection** on first initialization. Existing real data is preserved. Demo reset never clears real records.

Search covers the **indexed collection**, not the live web. A ten-paper sample job never establishes complete conference inventory. Unsupported conference URLs are rejected. OCR, arbitrary-site collection and automatic Scholar lookup are not implemented. See [known limitations](endless-tuna/docs/known-limitations.md).

## LAS and network boundaries

Only the server loads `endless-tuna/.env`; process environment takes precedence. This uses the same connection pattern intended for Scientist-on-Call while keeping the applications and configuration separate:

```dotenv
LAS_API_BASE_URL=https://llm-west.ncsu-las.net/v1
LAS_API_KEY=
LAS_MODEL=
LAS_TIMEOUT_SECONDS=90
```

Fill placeholders locally; never paste keys into chat/browser controls or VITE variables. `OPENAI_KEY` is a compatibility fallback only when LAS_API_KEY is **absent**; explicitly empty LAS_API_KEY does not fall back. All model inference passes through the centralized server-side LAS client and configured gateway. No hard-coded/substituted model or automatic fallback to another provider exists.

Settings shows credential presence only. **Check connection** explicitly discovers `/models`; select an exact returned ID, then **Test model** explicitly sends a tiny `/chat/completions` request. Opening Settings sends no completion. Discovery and inference access are verified separately. A previous 403 may reflect permissions or network access and does not prove the key is wrong. See [configuration](endless-tuna/docs/configuration.md) and [troubleshooting](endless-tuna/docs/troubleshooting.md).

Conference websites, arXiv and optional web search are separate collection connections. Stored records remain locally searchable without external access. New collection needs relevant source access; AI enrichment needs LAS connectivity. Local parsing, deterministic extraction and exports work without LAS.

## Documentation and checks

- [Analyst walkthrough](endless-tuna/docs/analyst-walkthrough.md)
- [Architecture and data flow](endless-tuna/docs/architecture.md)
- [Configuration reference](endless-tuna/docs/configuration.md)
- [Adapter development](endless-tuna/docs/adapter-development.md) and [collection/CSV contracts](endless-tuna/docs/collection.md)
- [Evidence and identity](endless-tuna/docs/enrichment.md); [search and export semantics](endless-tuna/docs/search-and-exports.md)
- [Backup/restore](endless-tuna/docs/backup-and-restore.md), [troubleshooting](endless-tuna/docs/troubleshooting.md), [limitations](endless-tuna/docs/known-limitations.md)
- [Analyst acceptance checklist](endless-tuna/docs/acceptance.md), [lab preparation results](endless-tuna/docs/lab-readiness.md), [GitHub preparation](endless-tuna/docs/github-readiness.md), [enduring constraints](AGENTS.md)

```bash
cd endless-tuna/backend
../.venv/bin/python -m pytest -q
../.venv/bin/python -m endless_tuna.migrate --status
cd ../frontend
npm run typecheck
npm run build
npm run test:acceptance
cd ../..
python3 scripts/check_publication.py
git diff --check
```

Automated backend/browser tests use mocked source/model transport and fictional demo data; they do not call live external services. The separate prior real smoke collection recorded ten official NeurIPS 2024 main papers, ten proceedings PDFs and indexed text from an observed 4,034-paper main inventory. Full inventory remains incomplete. Live LAS discovery/inference is not claimed by those checks. [Verification reports](endless-tuna/docs/lab-readiness.md) distinguish each category.

CI is prepared in `.github/workflows/endless-tuna.yml`; it needs no credentials or live service access for application tests. Runtime databases, PDFs, logs, exports, backups and `.env` are ignored. Collected third-party documents are separate from original code. No public license has been chosen, no remote repository is created, and no push/publication is performed.
