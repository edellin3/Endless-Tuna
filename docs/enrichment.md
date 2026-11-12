# Evidence-based author and organization enrichment

Enrichment is a separate, non-blocking stage layered on the existing collection pipeline. Original paper titles, author names/order, paper memberships, downloaded versions and full-text indexes are preserved. A name match never merges authors.

## Extraction and limits

New metadata records retain explicit per-author organization mappings as `deterministic_metadata` assertions. The excerpt is a serialized view of the parsed source fields, labeled by method, not a fabricated natural-language quotation. Legacy affiliation rows remain available as **Legacy metadata — evidence not retained**, not as verified assertions.

After a PDF is indexed, the worker attempts deterministic enrichment only. Explicit paper controls can rerun it or request **Enrich with LAS if needed**. The backfill CLI never invokes LAS:

```bash
cd backend
../.venv/bin/python -m endless_tuna.enrichment_cli --collection real --limit 10
# Or target one stored paper:
../.venv/bin/python -m endless_tuna.enrichment_cli --collection real --paper PAPER_UUID
```

Deterministic PDF extraction handles exact author-name affiliation lines, unambiguous first-page vertical author blocks, numeric affiliation markers, symbol footnotes and explicitly paired ORCID links. Identical names within one paper are not mapped by name-only heuristics. Organization strings retain the source wording; organization names are not expanded into guessed locations. Complex layouts, ambiguous mappings and unsupported formats remain evidence-missing or need review.

PDF evidence comes from the preferred available proceedings version (otherwise another available version), first four indexed pages, at most 12,000 characters/page. Sources without a retained public source URL are evidence-missing. Quotes are verbatim and limited to 6,000 characters; long footnote associations retain the contiguous author-to-footnote passage rather than pretending disjoint fragments were a single quote.

When explicitly requested and a language extraction gap remains, only `las.py` is used. Each request contains at most 4,000 passage characters plus an at-most-8,000-character / 40-author roster. At most three chunks are sent per action. The system instruction treats paper/web text and names as untrusted data, forbids executing tools or changing behavior, and disallows demographic/current-affiliation/Scholar inference. No collection worker makes automatic model calls.

Model output is an explicit Pydantic schema with extra fields forbidden: author position/name, one supported assertion kind, literal organization/value, supporting excerpt and page. The source URL, method, timestamp, verification status and paper year are assigned by the backend, not accepted from the model. Author names/positions must match the original roster. Quotes must occur in the supplied page chunk. Organization and location values must occur in the quote; location must be stated outside the organization name itself. A country cannot be derived merely from “University of Toronto,” and a city cannot be derived from that name either. Unsupported claims are flagged; unsupported fields/invalid JSON fail validation. No model output is automatically verified.

## Assertion evidence and review

Each assertion stores:

- Original author ID and name; paper ID and paper year when relevant.
- Assertion kind and literal value, with optional exact organization ID.
- `paper`, `current` or `identity` time context.
- Source URL, supporting excerpt and page when available.
- Extraction method, timestamp and status.
- Superseded assertion link and append-only review events.

Supported kinds: paper-time affiliation, organization country/city in that paper, ORCID, Scholar profile and separately evidenced current affiliation. Multiple affiliations per author are first-class independent assertions. Paper-year context is derived from the paper's primary proceedings edition, not the current date. Current affiliation requires separate evidence and cannot be supplied by paper-time model extraction. Only explicitly verified current assertions appear under **Verified current affiliation**.

Statuses are **Extracted**, **Needs review**, **Verified**, **Rejected**, and **Superseded**. “Verified” means a local analyst explicitly confirmed the evidence, not that a remote service independently certified it. Verification requires a review note. Location verification requires a verified supporting affiliation in the same paper. Author-country filters include only verified organization-country assertions with their verified paper-time affiliation; they never mean nationality, citizenship or residence. Unsupported person fields remain null with an explanatory status.

Correction never overwrites the original value, quote, source or timestamp. It marks the old assertion superseded, creates a replacement needing separate verification, and appends a review event containing the note and replacement ID. Rejected/superseded assertions stay available under history. Re-running the same extraction does not resurrect rejected assertions or overwrite verified/corrected assertions.

## Identity resolution and undo

Author records remain anchored to their original ordered paper associations. A confirmed identity match creates a reversible edge; it does not move authorship rows, rename people or transfer assertions. Directory/detail views aggregate only connected confirmed records. Undo deactivates the edge, restoring separate views without losing papers, claims or review history.

Manual proposals can be reviewed, but confirmation requires either matching **verified ORCID assertions**, or verified affiliation overlap together with supplied publication-list evidence naming publications on both sides. Same-name evidence is insufficient. Conflicting verified ORCIDs and distinct coauthors on the same paper cannot be merged by this workflow. A **Find verified ORCID matches** action creates bounded proposals from matching verified ORCIDs; it never creates name-based merges or automatic links. Rejected/undone proposals are not silently recreated by discovery.

ORCID format/checksum follows the [official ORCID identifier documentation](https://support.orcid.org/hc/en-us/articles/360006897674-Structure-of-the-ORCID-Identifier). The checksum validates format, not ownership; ownership remains subject to source evidence and analyst review. A manually supplied ORCID must also be tied to a known publication in its source or supporting excerpt before verification; a matching name and valid checksum alone are insufficient.

## Google Scholar

There is no automatic Scholar scraping, fabricated profile ID, same-name attachment or mandatory lookup stage. The author page provides a manual profile search link and accepts an actual supplied `https://scholar.google.com/citations?user=ID` URL, following [Scholar's documented public-profile URL format](https://scholar.google.com/intl/en/scholar/citations.html).

The evidence must include the author's name, actual supplied URL and a known publication title or verified ORCID. A same-name search result alone is rejected. Candidate assertions remain **Needs review**; only analyst-verified links appear in **Verified Scholar profile**. Source excerpts supplied manually are analyst attestations, not claims of a successful live Scholar fetch. Missing/private/blocked Scholar access never blocks paper collection, PDF indexing, browsing or export.

## Failures and API

`POST /api/papers/PAPER_ID/enrich` accepts `{"use_las":false}` (default) or an explicit `true`. `GET /api/papers/PAPER_ID/enrichment` returns durable status, attempt count, assertions and run history. LAS configuration/auth/access/rate-limit/timeout/schema failures are stored with a concise safe code/error and retryable state. Previously accepted assertions and all indexed text survive. Missing results are never filled from demo records. Concurrent runs are rejected; a stale running state can retry after ten minutes.

Other routes:

- `GET /api/authors?q=&organization=&country=&review=` and `/api/author-filters`.
- `POST /api/authors/AUTHOR_ID/assertions` for supplied evidence.
- `GET /api/assertions?status=pending|all` and `POST /api/assertions/ID/review` (`confirm`, `reject`, `correct`).
- `POST /api/identity/proposals`, `GET /api/identity/proposals`, and `/api/identity/proposals/ID/review` (`confirm`, `reject`, `undo`).
- `POST /api/identity/discover` for verified-ORCID proposals.

All API operations honor the isolated `X-Collection: demo|real` databases. Credentials remain server-side; this feature does not change LAS configuration or the public collection network boundary.

## Verification

Offline tests inject mocked LAS transports and prohibit live HTTP. They cover multiple affiliations, numeric/symbol markers, vertical blocks, identical names, missing source evidence, country inference rejection, invalid JSON/extra unsupported fields, verbatim excerpts, current-versus-paper time, failure retries, immutable corrections, manual Scholar corroboration, ORCID checksums, same-name rejection, confirmed identity links and merge undo with all paper associations intact. Browser checks exercise filters, assertion evidence and review controls separately.

The existing ten real NeurIPS PDFs were processed locally with **zero model requests**. A deterministic pass produced 15 unverified evidence-backed assertions: four papers had extracted mappings, one needed review, and five lacked an unambiguous mapping. They were not automatically marked verified; country/current affiliation/Scholar fields were not filled with guesses. Runtime evidence is in ignored `var/enrichment-result.json`. Live LAS extraction was not tested; it requires local credentials and an explicit user action.
