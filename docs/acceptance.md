# Analyst workflow acceptance

Recorded 2026-11-10. The Option 3 bright dashboard is retained. Search uses local SQLite FTS5 and exports operate on stored records without LAS.

| Check | Result | Evidence and scope |
| --- | --- | --- |
| Backend checks | Passed | 116 offline tests after lab preparation; mocked network/model transports. |
| Frontend production build | Passed | TypeScript and Vite build. |
| Labeled demo; operation without LAS | Passed | Isolated fictional collection; credentials explicitly empty; zero LAS requests. |
| Keyword/phrase search, filters, pagination, URL and browser history | Passed | Browser workflow plus focused FTS tests covering punctuation, malformed quotes, metadata, full text, deduplication and verified-country filtering. |
| Conference, paper and extraction evidence | Passed | Browser navigation and inspection of source excerpt/page/method. |
| Small inventory import | Passed | Two fictional CSV rows imported through the UI; source transport mocked. |
| Failed job inspection and retry without duplicates | Passed | Mocked HTTP 503; durable job retried and canonical records preserved. |
| Uncertain author match review | Passed | Same-name match rejected with a recorded outcome; identities remain separate. |
| Excel export | Passed | Downloaded workbook inspected with openpyxl: all seven sheets, stable relationships, five unique demo papers and no formula cells. Tests cover scope and formula-injection protection. |
| PDF ZIP export | Passed | Downloaded ZIP inspected and PDFs parsed: three included papers, two reported missing. Tests cover limits, splitting, unsafe paths and oversize files. |
| Backend/worker restart and resume | Passed | Actual test subprocesses restarted against the same temporary data; checkpointed job resumed without duplicating its first paper. |
| Desktop and narrow layout | Passed | Two desktop columns, one narrow-screen column, collapsible filters and no horizontal overflow. Screenshots retained. |
| Keyboard, empty state and browser console | Passed | Keyboard search/focus, no-results display and zero console errors in the tested workflow. |
| Automated accessibility scan | Passed | Discovery screen: zero axe WCAG violations. One pseudo-element contrast item required a separate computed-style check; opaque year badge contrast measured 15.53:1. This is not a full manual accessibility audit. |
| Export of existing real-source collection | Passed | Previously collected NeurIPS sample: ten unique papers, ten PDFs, one 41,024,036-byte ZIP, zero missing files; seven-sheet workbook inspected separately. No new upstream calls. |
| Fresh real-source collection in this acceptance run | Unverified | Browser collection transport is mocked. Prior real smoke evidence records ten official NeurIPS 2024 main-track papers/PDFs; full inventory remains incomplete (observed official inventory 4,034). |
| Live LAS inference | Unverified | Not attempted. Automated model tests use mocked transports; no completion was initiated. |

No failed checks remain in the recorded workflow. Other conference-specific adapters, OCR and a comprehensive manual accessibility audit remain outside this verification.

## Reproduce

From the project root:

```bash
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/python -m compileall -q endless_tuna
cd ../frontend
npm run build
npm run test:acceptance
```

The browser harness creates a new temporary data directory, starts its own API and fixture worker, and stops those processes when finished. It does not reset the normal demo or real database. See [search and export documentation](search-and-exports.md) for browser prerequisites and configuration.

Local evidence is retained under ignored `var/acceptance/`: `acceptance.json`, `accessibility.json`, desktop/mobile screenshots, and downloaded workbook/ZIP. Separate existing-real-data verification is `var/real-export-verification.json`; prior live collection evidence is `var/neurips-smoke-result.json`. These runtime files and PDFs are intentionally excluded from Git.

## Development proxy regression coverage

As of 2026-11-12, acceptance launches the actual Vite development server as well as API/worker and runs browser actions through that proxy. `TUNA_ACCEPTANCE_PORT` selects the isolated API port (default 8021); `TUNA_ACCEPTANCE_UI_PORT` selects Vite (default 8022). Step 0 checks a real browser POST with Origin and rejects a foreign-origin POST. This covers the Host/Origin mismatch that earlier direct-to-API browser checks missed. The frontend production build remains a separate check. See the current [lab readiness record](lab-readiness.md).
