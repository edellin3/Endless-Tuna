# Local search and analyst exports

Search uses SQLite FTS5 only. It does not call LAS, an LLM, embeddings, a web search provider or an external search service. Search covers the selected indexed collection, never an implied complete research universe.

## Query behavior

- Case-insensitive, whole-token keyword search using SQLite's Unicode tokenizer. There is no automatic stemming or synonym expansion.
- Multiple terms use **AND**. Each required term may match a different paper field/page or its conference metadata.
- Double quotes keep a phrase together, for example `"shared navigation"`. A phrase must occur within one indexed field or PDF page.
- Punctuation separates words. `robot-learning` behaves like `robot learning`; it is not interpreted as subtraction.
- `AND`, `OR`, `NOT`, `NEAR`, colons, stars and parentheses are not passed through as query syntax. Operator words are searched literally.
- Unclosed quotes degrade safely to ordinary terms, with a query note. Punctuation-only input produces no matches, not a database error.
- Queries are bounded to 500 characters / 32 terms or phrases; the API reports any truncation.

The index covers edition name/year/description/track metadata, paper titles, abstracts, and versioned PDF text with page references. Metadata-only papers remain searchable and are explicitly distinguished from full-text coverage. Incomplete or unverified official inventories are labeled. A keyword that matches conference metadata can match all collected papers in that edition; the evidence snippet identifies that metadata match rather than claiming the word appeared in a paper.

Results are grouped by conference edition. Matching-paper counts use distinct canonical paper IDs, even with multiple track memberships. Ordering is stable: conference year descending, conference name and ID; papers use year descending, title case-insensitively, then stable IDs. The new `/api/search/conferences` and `/api/search/papers` APIs return `items`, `total`, `page`, `page_size`, `pages` and query interpretation. Defaults are 12 conferences / 25 papers per page; maximum 100 per page. Older list endpoints remain available for existing consumers.

Filters: year, conference series, organization, **verified organization country**, available local PDF, and paper review status. Country filtering requires both a verified location assertion and its verified paper-time affiliation; it does not imply a person's nationality or residence. A recorded but missing/outside-storage PDF does not satisfy “Has PDF.”

Search, filter values, page size, page number and demo/real collection are preserved in hash URLs. Browser Back/Forward and reload restore them. Conference and paper links retain their originating filtered list. Query state is not stored solely in component state or browser storage.

## Explicit export scopes

Expand **Export research** on Explore, Library or conference detail:

| Scope | Selection |
| --- | --- |
| Current filters | Every matching paper across **all result pages**, optionally within the opened conference |
| Selected conference | All papers in that edition; keyword/other search filters are ignored |
| All stored records | All records in the selected demo/real database; conference/search filters are ignored |

The action explains its scope before generation. A single visible page never silently limits an export. Exports are local, credential-free operations. They never fetch missing PDFs or call LAS.

## Excel workbook

Seven sheets:

1. **Conferences**: stable edition/series IDs, year, source URL, official/collected counts, inventory completeness, PDF/full-text coverage and retrieval time. Related editions are included as relationship context and marked when outside the matching scope.
2. **Papers**: canonical paper ID, edition/track membership IDs, title, abstract, review status, identifiers, official/inventory evidence URLs and coverage flags. A canonical paper may have multiple membership rows; deduplicate by `paper_id` when counting papers.
3. **Paper Authors**: stable paper/author IDs, original author name, original order and verified ORCID values. Identity merges do not rewrite original authorship.
4. **Affiliations**: assertion IDs, original author IDs, paper-time/current contexts, organization IDs, literal values, evidence URL/excerpt/page, method, timestamp, verification status and correction links. Legacy metadata lacking retained excerpts is explicitly `needs_evidence`.
5. **Sources**: membership, assertion and versioned PDF sources with stable linking IDs, URLs, excerpts, statuses, methods, timestamps and hashes/sizes where available.
6. **Missing PDFs**: selected paper IDs and reasons for unavailable files.
7. **Review Queue**: selected uncertain papers, pending author assertions, PDF candidates, identity matches and per-paper processing failures.

Workbooks use write-only generation to a local file, styled headers, frozen first rows and table filters. All external text is protected against spreadsheet formula injection, including leading whitespace/control characters before `=`, `+`, `-` or `@`. Illegal XML controls are replaced. Individual cells longer than Excel's practical limit are explicitly truncated with a source-reference note; PDFs remain the full-content artifact. IDs and membership fields are separate bounded cells, not collapsed into an oversized relationship blob.

## PDF ZIP bundles

ZIPs contain one preferred accessible version per selected paper (proceedings first, otherwise another available version), plus:

- `manifest.json`: export scope/filters, all-pages flag, part counts, paper IDs, original titles, included/missing/excluded status, safe entry name, source/final URL, version, SHA-256, size, retrieval time and paper review status when available.
- `missing-files.csv`: missing, unreadable, hash-mismatched, outside-boundary or size-excluded files with reasons.

Source PDFs are read/hashed in bounded chunks and copied directly to disk-backed ZIP files. The server never loads the whole collection of PDF bytes into memory. Entry names are sanitized, ID-suffixed, relative paths under `papers/`, preventing traversal or title collisions. Missing files are reported rather than aborting the other files. A single PDF larger than the chosen per-bundle limit is excluded with an explicit reason; it is not silently oversized or cut into invalid fragments. Larger selections split into numbered bundles, each with its own manifest/report. The UI shows each bundle's byte-derived size and included-paper count.

Configuration in server-side `.env`:

```dotenv
TUNA_ZIP_MAX_MB=100
TUNA_EXPORT_TOTAL_MB=1024
TUNA_EXPORT_MAX_PAPERS=10000
TUNA_EXPORT_TTL_HOURS=24
```

MB means 1,000,000 bytes. A requested ZIP limit can lower, but never exceed, the server cap (1–500 MB). Total size is a per-export budget. Narrow filters when the selection exceeds the size/paper budget. Defaults favor a local laptop rather than an unbounded full-conference archive.

Completed artifacts are stored under `TUNA_DATA_DIR/demo-exports` or `real-exports`, with SQLite metadata. Downloads use streamed file responses and do not require a browser Blob containing a large bundle. Artifact links survive backend restart until expiry. Expired artifacts are cleaned on subsequent export generation. Regenerate an expired/missing file. Export registry writes use a separate short transaction from the consistent read snapshot, allowing collection work to continue.

API: `POST /api/exports/workbook` or `/api/exports/pdf-bundles` with `X-Collection` and a JSON body such as:

```json
{"scope":"filtered","edition_id":null,"filters":{"q":"robotics","year":2025,"pdf":"yes"},"max_bundle_mb":50}
```

The response contains scoped counts and download URLs. Download links carry only an opaque local artifact ID and collection name, never model credentials.

## Reproduce the acceptance workflow

After installing backend/frontend dependencies and building the frontend:

```bash
cd backend
../.venv/bin/python -m pytest -q
cd ../frontend
npm run build
npm run test:acceptance
```

The browser runner reuses installed Google Chrome on Ubuntu/macOS. To select another browser binary, set `CHROME_EXECUTABLE`; alternatively install Playwright Chromium with `npx playwright install chromium`. Set `TUNA_ACCEPTANCE_PORT` if the default local test port 8021 is occupied.

The runner creates a fresh temporary database/filesystem, explicitly empties LAS credentials, starts real FastAPI/worker subprocesses, and mocks only source/PDF transport using `backend/tests/acceptance_fixture.py`. That fixture is never used by the production worker. It performs the analyst steps through browser controls, downloads actual workbook/ZIP artifacts, inspects them with openpyxl/pypdf, restarts both processes on the same persisted state, resumes a cancelled paper checkpoint, and runs keyboard/narrow-layout/axe checks.

Runtime evidence is ignored by Git under `var/acceptance/`: `acceptance.json`, `accessibility.json`, desktop/mobile screenshots, `acceptance.xlsx`, and `acceptance.zip`. Temporary fixture databases/logs are retained at the report's `data_directory` for diagnosis; test subprocesses are stopped on exit. The runner does not alter the user's real or demo database.

Separately, Excel/ZIP generation was checked against the previously collected real NeurIPS sample: **10 real papers, 10 PDFs, one 41,024,036-byte bundle, no missing PDFs**. This export check made no fresh source or model requests. Existing real collection evidence remains in `neurips-smoke-result.json`; real export evidence is in `real-export-verification.json`. Live LAS inference is a separate unverified check, not implied by mocked extraction tests or local search/export success.
