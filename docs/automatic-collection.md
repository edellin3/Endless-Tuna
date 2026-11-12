# Automatic conference collection

The normal analyst flow is **paste a link → Collect papers → browse the conference**. The application identifies the conference, saves titles and finds/downloads free PDFs automatically. There are no mandatory preview, save-titles, download, or Jobs-tab handoffs.

**Collection scope** is the one optional choice: the default is a ten-paper quick test. Select **Entire conference** before collecting for a full request. The page always distinguishes the selected batch from the official inventory. Full PDF coverage is never promised.

The conference page shows **Titles found**, **PDFs downloaded** and **Need attention**. Titles appear before PDF retrieval finishes. Updates happen automatically. You can leave the page while the worker runs, pause collection there, resume it later, or retry missing copies. Uncertain matches link to review. Technical stages, refresh/import controls and background job history are secondary tools. Demo remains isolated; normal link collection uses Real automatically.

Only ambiguous conference identity or an unreadable paper source requires an initial clarification. Known CoRL/PMLR, WACV and NeurIPS program links use their detected event year/name. A homepage with multiple possible sources offers explicit listing choices. JavaScript-only/sign-in/unrecognized pages may still need a connector or import; there is no universal-site scraping claim.

## Durable implementation

`POST /api/intake/collect` accepts `url`, optional `full_collection` (default false), and `paper_limit` (default 10). It checks the source once and queues one SQLite job of kind `automatic`, backed by a stable metadata snapshot. A missing name/year returns `needs_details` plus a 24-hour source snapshot ID; submitting the clarification reuses the snapshot. The old preview/start endpoints and optional manual page (`#/add/manual`) are retained for advanced workflows and compatibility.

The worker persists paper identities, memberships and title metadata first, then continues automatically through official PDFs, conservative arXiv matching, OpenAlex OA locations and configured/manual candidates. Existing public traffic bounds, author/evidence rules, safe PDF parsing, content hashes, versions and FTS indexing apply. LAS is never used automatically. No new schema migration or infrastructure is required; the existing text-valued job kind supports `automatic` alongside `inventory`, `pdfs`, and legacy `collect`.

Duplicate clicks/repeated source submissions reuse the active edition/job under a SQLite write lock. Continuing a known edition skips papers with existing valid PDF files, preserves paper/author identities and does not downgrade a complete stored inventory to a sampled one. If everything listed already has a PDF, the existing conference opens without another job. Selected scope remains explicit.

Automatic jobs use the same ownership tokens, bounded per-paper checkpoints and cancellation checks as explicit PDF jobs. Pause keeps completed work; resume reuses snapshots and skips finished papers. Source/PDF failures remain per-paper outcomes instead of erasing titles. **Need attention** counts the latest failed/missing/review outcomes for each paper, excluding available files and pending/running work. Historical failures do not inflate the count after a successful retry.

The executable NeurIPS program page stays the edition source; its JSON feed remains inventory evidence. This distinction is required so intake-created jobs and later refresh/resume actions select the correct adapter.

## Verification scope

Offline tests cover one action completing titles and PDFs, titles visible while a PDF is still in flight, active-job deduplication, completed-file reuse, explicit full scope, pause/resume, ambiguity, failures, historical attention counts, collection isolation, stored inventory coverage and program-page/feed provenance. Browser acceptance exercises the actual Vite proxy and an actual worker with fictional snapshots and mocked downloads. Desktop/mobile axe checks cover the simplified entry form.

A separate live WACV two-paper sample used one collect request and one worker run: two titles saved, one PDF downloaded/indexed, one unresolved. This is partial coverage, not a complete conference or a guarantee of all copies. Reports are in ignored runtime storage; existing collections are not changed by isolated smoke runs. See the dated [lab readiness record](lab-readiness.md).
