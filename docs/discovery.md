# Find conferences

The normal collection handoff now opens the [one-click Add conference flow](automatic-collection.md): click Collect papers to save titles and retrieve free PDFs automatically. Source inspection in discovery is optional; it is not required when pasting a link directly.

Open **Explore → Find conferences**, or use the link in **Add conference**. This is discovery of new official paper sources, separate from Explore's search of already indexed papers. No model or general search-provider credentials are required.

The initial screen offers starter source links for CoRL 2024, ICML 2024, RSS 2025 and the existing supported NeurIPS editions. **Search official directory** retrieves the public PMLR volume directory and searches conference names, abbreviations and a small documented set of subject aliases. It does not search the full web or the contents of papers that have not been collected. Edition year, publisher, search, pagination and collection context are preserved in the URL and browser history. The directory cache is process-local for one hour. A failed refresh retains the previous cached entries and starter sources with a visible warning; failures are cached for one minute. The cache is lost on API restart.

**Collector available** means an adapter exists for that source format; it is not a claim that the source was tested live or that every PDF is available. **Check source** reads the official inventory, counts recognized distinct paper URLs and previews up to three paper titles. It neither downloads PDFs nor creates collection records/jobs. It shows the check timestamp and preserves HTTP/access/structure failures. The Add action becomes available after a successful check and a known event year. Existing real editions can be opened directly.

**Add to Real collection** prefills the ordinary Add conference form with the official source, adapter, event year and proceedings scope. It switches to Real collection explicitly, keeps the default ten-paper sample and leaves full collection unchecked. The analyst must submit the form to create a durable job and explicitly opt in to full collection. A readable complete paper inventory never guarantees complete downloadable PDFs. Copyright remains with the respective rights holders; access controls are never bypassed.

## New official collectors

- `pmlr-volume`: official `https://proceedings.mlr.press/vNUMBER/` volumes using the inspected `.paper` title/details/abstract-link layout. Distinct official per-paper HTML URLs establish membership. Paper citation tags establish ordered authors, abstracts, DOI when present and official PDF links. Event year comes from the volume's event heading, not the publication date: CoRL 2024's volume was published in 2025. Tracks such as oral/poster presentation categories are represented as one **Published proceedings** scope, not invented as separate research tracks. Historical or differently structured volumes fail explicitly when unrecognized; adapter availability is not blanket verification of all 331 directory entries.
- `rss-2025`: RSS XXI / 2025 only, at `https://www.roboticsproceedings.org/rss21/`. Uses the official table of contents and citation metadata; excludes other editions and external links. Official legacy HTTP PDF links are normalized to HTTPS on the same host. No other RSS year is implicitly supported.

All collection uses the existing public-IP-pinned `network.py` transport, size/time/rate bounds, durable leased worker, per-paper failures, PDF validation, provenance and FTS. Neither adapter infers affiliations from author names or calls LAS. New PMLR/RSS records must be added to Real collection; demo is preserved. The inventory event year must match the selected edition year; a mismatch fails before paper insertion.

## API

- `GET /api/discovery/conferences`: `q`, optional `year`, `publisher=all|PMLR|RSS|NeurIPS`, `directory=starter|official`, `page`, `page_size`. Default starter mode performs no external requests. Official mode adds PMLR-directory entries, with retrieval time and a visible fallback warning if inaccessible. Does not write records.
- `POST /api/discovery/inspect`: `{ "source_url": "https://proceedings.mlr.press/v270/" }`. Official adapter allowlist only; rejects private/credential-bearing/unsupported URLs before fetching. Returns an accessible inventory or a truthful unavailable result. PDF access stays `not_checked`.

General conference web search, arbitrary-site scraping, automatic adapter generation, universal topic classification and guaranteed complete PDF access are not implemented. Unsupported conferences still need a CSV inventory or a reviewed adapter.
