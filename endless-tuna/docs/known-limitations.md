# Known limitations

- Local single-user lab tool, without login, role isolation, TLS termination or multi-user audit identity. Bind loopback. Remote hosting is not prepared or authorized here.
- The only conference-specific live adapter is NeurIPS 2024 main proceedings. Workshops, other years/conferences and Datasets and Benchmarks require explicit separate adapters/imports. CSV/metadata imports do not establish a publisher's full inventory count by themselves.
- The verified real smoke dataset is a ten-paper sample, not a complete conference. Prior evidence observed 4,034 official main-track papers. No fresh full collection is claimed by offline acceptance tests.
- arXiv resolution is conservative; weak matches remain unresolved/reviewable. Optional web search needs a configured public JSON endpoint; no default provider, automatic Scholar lookup, Google scraping or invented URLs exists.
- Deterministic affiliation extraction covers limited explicit layouts and the first four bounded PDF pages. LAS enrichment is bounded, optional, evidence-validated and analyst-reviewed. It cannot guarantee complete affiliations. Nationality/residence are not inferred.
- Image-only PDFs require OCR, which is not implemented. PDF parsing is bounded to 500 pages/5,000,000 extracted characters. Access-controlled/paywalled documents are not bypassed.
- Canonical paper identity currently follows official source identity; unrelated URLs for the same publication may need future corroborated identity handling. Author identities never merge on names alone. Identity edges require explicit review and are reversible.
- SQLite and local files suit one workstation and modest collections. Search uses FTS but current filtering/count assembly includes Python-side work; large multi-conference benchmarks have not been run. Exports are synchronous with bounded disk-backed files, not queued background export jobs.
- ZIPs contain one preferred available PDF per paper; an oversized single PDF is reported rather than split. Exports have configured caps/TTL; keep original storage/backups for long-term provenance.
- Graceful worker shutdown waits for submitted network work; forced kills can leave leases until expiry. Rate limiting is per process, so use one normal worker unless carefully coordinating source traffic.
- Offline/browser checks use mocked network transports. Live LAS discovery/inference has not been verified in this preparation. macOS, the full CI version matrix, and Docker runtime are only verified if specifically recorded in the preparation report.
- Automated accessibility checks and a tested keyboard/responsive workflow are not a comprehensive manual accessibility audit.
- No public license has been selected. Copyright/redistribution of collected third-party documents is separate from the application's original code; runtime documents never belong in this repository.
