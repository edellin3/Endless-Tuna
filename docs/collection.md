# Conference collection

**Current analyst workflow:** paste a link and click **Collect papers**. Title collection and free-PDF retrieval proceed automatically, with counts and pause/resume on one conference page. Choose Entire conference for full scope; ten papers remains the default. The technical/manual pipeline below remains available in secondary tools. See [automatic collection](automatic-collection.md).

The pipeline runs in the separate SQLite-backed worker. It does not invoke LAS. The existing centralized LAS client is used only by explicit model actions.

## Supported official source

Implemented and inspected on 2026-11-10:

### NeurIPS 2026 official virtual program

- Paper listing: https://neurips.cc/virtual/2026/papers.html (may redirect to a location-specific page).
- Adapter: `neurips-2026-program` in `neurips2026.py`.
- The page's own `start(...)` call names `/static/virtual/data/neurips-2026-orals-posters.json` and the separate `neurips-2026-abstracts.json`. The adapter reads these exact official references, never executes scripts and refuses changed/unrecognized feed URLs, pagination or inconsistent counts.
- Poster records establish published listing membership; oral duplicates are excluded, repeated city presentations are deduplicated using exact official OpenReview IDs, and other papers retain event-specific official identities. Titles alone never merge records. Separate main/datasets/position/journal/other/unspecified tracks are preserved. Workshops outside this listing are not included by this adapter.
- Abstracts, ordered names, official event/poster/OpenReview IDs and inventory retrieval evidence are retained. Profile `institution` fields are deliberately not treated as paper-time affiliation evidence. A missing author-name slot remains explicitly labeled missing and gets an inventory-warning evidence item; unknown tracks need review. Large collaboration author lists retain their order (bounded at 2,000).
- OpenReview PDF URLs use exact IDs supplied by the official inventory and the [documented public PDF endpoint](https://docs.openreview.net/reference/api-v2/openapi-definition). PDF contents must still validate. They are versioned `openreview:ID`, not final proceedings PDFs. Inaccessible official PDFs may resolve to evidence-matched arXiv versions. Journal records without supplied PDF links use the normal conservative resolution workflow.
- Consecutive OpenReview 403 download failures pause remaining work as a partial job, preserving the full inventory, per-paper failures and completed downloads. Retry reuses the durable snapshot; no access controls are bypassed.

Select Real collection, Add conference → **Use NeurIPS 2026 · all listed papers**, then submit. This example explicitly selects the full inventory; ordinary requests still default to ten papers. Auto with year 2026 and the homepage `https://neurips.cc/` also resolves to this listing; selecting CSV for the homepage is rejected. Demo data remains isolated.

**Actual live result, 2026-11-10:** the fresh feed yielded **9,139 distinct papers**: 7,892 Main Conference; 971 Evaluations and Datasets; 137 Position Papers; 63 TMLR, 16 JMLR and 8 Annals of Statistics journal presentations; 36 Bridging the Future; 16 unspecified-track records requiring review. All had indexed metadata/abstracts. Two PDFs were downloaded and parsed; one candidate was ambiguous. The job then paused after repeated OpenReview HTTP 403s, with 9,137 PDFs still unavailable. This is a complete snapshot of that paper listing, **not** complete PDF coverage or coverage of separate workshop sites. Counts can change as the official feed updates. The earlier inspection found 9,137 papers; the subsequent live fetch contained two additional distinct records.

The local result is retained in ignored `var/neurips-2026-collection-result.json`; source files, documents and databases remain outside Git. No LAS request was needed.

### NeurIPS 2024 main proceedings

- Official inventory: https://papers.nips.cc/paper_files/paper/2024
- Equivalent host: https://proceedings.neurips.cc/paper_files/paper/2024
- Adapter: `neurips-2024-main`
- Scope: NeurIPS 2024 **Main Conference Track**, identified by official `-Abstract-Conference.html` links. The current inventory has **4,034** such records. The source also contains **459 Datasets and Benchmarks Track** links; these are excluded from this adapter, as are workshops. Those tracks require separate adapters/imports, not relabeling as Main Conference.

The official root documents the proceedings/track structure at https://papers.nips.cc/. A paper page inspected was https://papers.nips.cc/paper_files/paper/2024/hash/000f947dcaff8fbffcc3f53a1314f358-Abstract-Conference.html. Paper pages expose ordered citation_author meta tags, citation_title, citation_doi, citation_pdf_url, an Abstract section and the official Paper link. Inventory membership is established by the proceedings link, not arXiv or web-search results. No hard-coded live paper list exists.

`ConferenceAdapter` in `backend/endless_tuna/adapters.py` defines `inventory(url, fetch) -> Inventory` and `hydrate(record, fetch) -> Metadata`. Inventory supplies membership and a known official count when available. Hydration fills the abstract, author order, external IDs and preferred PDF URL. Register a new adapter explicitly in `adapter_for`; do not treat an arbitrary website as supported. Existing citation-metadata/JSON parsing remains an explicit adapter; `.json` inventories may be detected by extension. Each manifest record needs its own distinct official source URL.

## Running a collection

In Add conference, enter NeurIPS, year 2024, Main Conference, and the official inventory URL. The default is **10 papers**. Start the worker from the project root:

```bash
cd backend
../.venv/bin/python -m endless_tuna.worker
```

A full-conference download requires explicitly checking full collection on the add form or choosing **Collect full edition…** on conference detail and confirming the scope. A small sample never claims the full inventory was collected.

Use this capped CLI to reproduce the real smoke collection, without downloading the entire conference:

```bash
cd backend
../.venv/bin/python -m endless_tuna.smoke --limit 10
```

This creates/reuses a separate named real collection and processes only its job. The maximum smoke limit is 10. It stores the actual result/failure evidence at `var/neurips-smoke-result.json`, outside Git. To isolate a run further, set an absolute `TUNA_DATA_DIR` before the command. For one selected queued job:

```bash
../.venv/bin/python -m endless_tuna.worker --once --collection real --job JOB_UUID
```

## CSV inventory import

Open a conference and expand **Import a CSV paper inventory**. Upload a UTF-8 CSV file or paste CSV text. API: `POST /api/conferences/EDITION_ID/inventory/csv`, header `X-Collection: real`, JSON `{"csv_text":"..."}`. The importer records analyst-supplied inventory evidence; an imported row is not an independent verification of its membership. It does not claim a complete official inventory total.

Required columns:

| Column | Meaning |
| --- | --- |
| title | Paper title |
| authors | JSON array of names in original author order, correctly CSV-quoted |
| official_url | Official paper page; canonical identity is based on this URL, not a name/title match |
| inventory_url | Official accepted-paper/proceedings listing used as membership evidence |
| year | Edition year, matching the selected edition |
| track | Exact existing track name; import one track at a time |

Optional: `abstract`, `pdf_url`, `doi`, `arxiv`. Example fictional input:

```csv
title,authors,official_url,inventory_url,year,track,pdf_url,doi
Fictional imported paper,"[""Mira Example"",""Alex Example""]",https://conference.example/paper/1,https://conference.example/accepted,2024,Main Conference,https://conference.example/paper/1.pdf,
```

A public `.csv` URL can also use the CSV adapter in Add conference. Workshops must use their own track/edition and matching inventory evidence. Records with different years/tracks are rejected instead of silently reassigned. CSV input is capped at 10 MB / 10,000 rows. A CSV-supplied full list still has unknown official completeness unless the supported official adapter independently establishes it.

## Resolution and review

1. Prefer the PDF URL linked by the official paper page. Label it `proceedings`.
2. If absent, inaccessible or an invalid PDF response, query the documented arXiv API at `https://export.arxiv.org/api/query`. Documentation: https://info.arxiv.org/help/api/user-manual.html. Requests use a title query, at most five results, Atom parsing, 24-hour query caching and at least 3.1 seconds between arXiv requests. No arXiv HTML search scraping.
3. Automatically choose only one candidate with an **exact normalized title and complete normalized author-name multiset**. Unicode names are retained. Weak fuzzy titles, initials-only author overlap and multiple versions are not automatically accepted. Preserve the arXiv ID/version and label the download `arxiv:IDvN`; an arXiv PDF never proves conference membership.
4. Ambiguous candidates appear in the Review Queue with candidate title, author evidence, URL, version and reason. Confirming records review history and queues a download; rejecting records history without downloading.
5. Optional general web search uses a pluggable `SearchProvider`. The built-in `JSONSearchProvider` calls `TUNA_SEARCH_ENDPOINT?q=...` and expects `{"results":[{"url":"https://public.example/file.pdf","title":"...","authors":["..."]}]}`. This endpoint must be public HTTP(S) with no embedded credentials or query string. It can be an organization-managed search gateway backed by a chosen provider. There is no assumed provider, no fake result data, and no scraping of Google results. General search candidates always require review.
6. Without a configured provider, paper detail shows **Web-search provider: not configured**, a manual search link, and a candidate PDF URL form. Manual search opens a normal user browser search; the backend does not scrape it. Analyst-supplied candidates must be confirmed in Review Queue before a download.

## Downloads, indexing and provenance

Collection traffic has a dedicated public-IP-pinned HTTP transport. It validates DNS and every redirect, rejects non-HTTP(S), localhost/private/link-local/reserved addresses, credential-bearing URLs, fragments and credential query parameters. The validated address is pinned for connection while retaining original Host and TLS SNI, preventing DNS rebinding between validation and connection. Redirects cannot forward LAS credentials because this transport never has them. The LAS gateway uses its own client/configuration and is not subject to collection URL rules.

Downloads use bounded concurrency (default 2; 1–4), a per-host rate limiter (default 0.4 seconds), timeouts (default 30 seconds), at most three attempts for network/transient HTTP failures and at most five redirects. Overlong Retry-After delays stop the attempt for a later job retry. File size defaults to 30 MB and is configurable using `TUNA_MAX_PDF_MB` (1–200). URLs and file extensions are not considered proof of PDF content: signature and pypdf parsing must succeed. Malformed, HTML, truncated and encrypted responses do not become available PDFs.

Each available version records original and final URL, version, SHA-256, byte size and retrieval timestamp. Files are content-addressed, so duplicate runs do not duplicate bytes. Page text retains download ID, version and page number, and is indexed in SQLite FTS5. Search matches titles, abstracts and indexed PDF text, returning page references and the relevant version. Image-only PDFs are available but explicitly marked **OCR required**; no OCR engine is included. PDF parsing is limited to 500 pages / 5,000,000 extracted characters.

Canonical papers are shared across edition/track memberships using official paper URL identity; papers and author identities are never merged solely by name/title. Each membership retains official page, inventory URL and retrieval timestamp. DOI and arXiv identifiers are retained when supplied by official metadata/imports. Existing reviewed titles remain intact on re-collection.

## Durable stages and coverage

Jobs display **Inventory → Resolve PDFs → Download → Extract text → Ready for enrichment**, with counts and per-paper failures. SQLite `BEGIN IMMEDIATE` atomically claims queued or expired jobs. Ownership tokens and heartbeat leases prevent an old/cancelled worker from writing progress. Inventory snapshots and per-paper states survive crashes. Resume reuses the snapshot and completed papers; retry resets only unsuccessful paper states. Successful hashed files/pages are reused. To fetch an updated inventory, use **Collect / refresh** to create a new job.

Statuses: queued, running, cancelled, failed (inventory failure), partial (one or more papers unresolved/failed/review), complete (the selected job scope processed). A **complete 10-paper job is not a complete conference**. Every paper failure is retained and other papers continue. Cancellation stops further writes; in-flight network requests can finish up to their configured timeout. On restart, wait for the 120-second lease to expire or use the job actions.

Coverage separately reports official inventory count (or unknown), collected membership records, full-inventory completeness, available/missing PDFs, ambiguous candidates, indexed full text, OCR requirements and failed/partial/pending jobs. Search explicitly warns when the official inventory is incomplete or unverified. The sample's full-inventory flag stays false.

## Verification evidence

Actual network smoke on 2026-11-10: official main-track inventory count 4,034; sample 10 records; **10 proceedings PDFs available, 10 with indexed full text, zero unresolved/ambiguous PDFs**, and **full inventory incomplete**. This is separate from synthetic fixtures, which contain fictional titles/authors. The runtime JSON report retains the actual IDs, titles, job states and coverage. The full conference was not downloaded. No LAS/model request occurred.

Automated checks use offline fixtures and mock transport only. They cover official structure/track separation, CSV author order, ambiguous arXiv versions, Unicode/duplicate-name evidence, PDF validation, OCR flagging, redirects to private destinations, IP pinning, retries, content hashes, cross-collection duplicates, page search, cancellation, active claim ownership, expired leases and resume. If external access fails on another machine, preserve `neurips-smoke-result.json` and rerun the capped command after checking network access.

## Finding additional conferences

Use **Explore → Find conferences** to search the official PMLR volume directory and supported starter sources. PMLR proceedings volumes and RSS 2025 now have deterministic collectors in `proceedings.py`, in addition to the NeurIPS adapters above. Check an official source before adding; the check reads only inventory metadata and does not establish PDF coverage. The Add form is prefilled in Real collection with a ten-paper default and an explicit full-edition opt-in. See [conference discovery](discovery.md) for exact supported layouts, event-year handling, provenance and remaining limits.

## Updated default workflow

Use **Add conference → paste link → preview → save titles → find free PDFs**. Title collection and PDF lookup are separate durable jobs, with direct progress/next actions on the conference page. Generic explicit HTML paper lists and homepage source suggestions supplement supported proceedings adapters. OpenAlex OA-location lookup supplements official PDFs/arXiv in explicit PDF-only jobs; exact title and complete author evidence remain required. See [link-first collection](link-first-collection.md). The existing combined pipeline and CSV import remain under Advanced import for compatibility.

## WACV 2026

The official WACV 2026 homepage, virtual index and Papers listing now work in both default link-first intake and Advanced import (Auto). Main-conference paper IDs, ordered authors and inline abstracts come from the public program feed, checked against its static paper list; oral presentations do not become duplicate papers. Slides/posters are excluded from PDF retrieval. See [WACV source support and verification](wacv-2026.md).
