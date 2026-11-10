# Troubleshooting

| Symptom | Action |
| --- | --- |
| `command not found` or missing virtualenv Python | Start in the repository root and follow setup. Use `./start.sh`; the Python executable is `endless-tuna/.venv/bin/python`, not the root prototype's environment. Activate the Node version manager in the terminal if npm is missing. |
| Python 3.10 on Ubuntu 22.04 | Install an approved 3.11–3.13 interpreter and recreate the app venv using it. |
| Startup says port in use | Stop the old instance or set unused TUNA_API_PORT/TUNA_UI_PORT values. The supervisor does not kill unrelated processes or silently change ports. |
| FTS5 unavailable | Use a Python distribution whose linked SQLite includes FTS5. Startup probes support. Do not replace search with an LLM. |
| API works but frontend is missing/stale | `npm ci && npm run build` in `endless-tuna/frontend`; `--built` serves that build. Normal startup launches Vite. |
| No search results | Check collection selector, filters and URL. Search covers indexed records only. Clear filters/try an unquoted term; inspect collection inventory/full-text coverage. New real mode is empty. |
| Jobs remain queued | Start the worker; native `start.sh` services both collections. Ensure API/worker share TUNA_DATA_DIR. Check job source/adapter and failures. |
| Job shows running after a crash | Lease recovery takes up to 120 seconds. Resume/retry uses saved checkpoints; do not delete DB rows to force it. Graceful shutdown requeues remaining work. |
| Source network failure/403 | Verify external source access from the lab network. This is independent of LAS. Private/local URLs, redirects to them, credential URLs and unsupported ports are deliberately rejected. |
| Unsupported conference URL | Use the supported NeurIPS 2024 main adapter or a documented CSV/metadata inventory; arbitrary conference scraping is not implemented. |
| No PDF/ambiguous candidates | Inspect source status/version, review candidates, use manual search or supply a public PDF candidate. Unconfigured web search produces no invented results. |
| PDF has no text | Image-only PDFs are marked OCR required. OCR is not included. Invalid/encrypted PDFs fail parsing rather than becoming indexed. |
| Export has fewer PDFs than papers | Read missing-files.csv/manifest in every ZIP. Missing, corrupt, oversized or absent files are reported. Download every bundle part. Check selection scope and configured limits. |
| Export download expired | Generate again; artifacts expire by TTL, and metadata/files persist only in the selected data directory. |
| SQLite locked/disk full | Use a local writable filesystem with space for DB/PDF/export growth, one normal worker, matching data paths. Avoid network filesystems/cloud sync for live SQLite. Stop services before backup/maintenance. |
| Docker cannot bind/create volumes | Check Docker Engine/Desktop and loopback port 8000; do not expose it publicly to work around a conflict. Compose 2.24+ is required. |

## LAS diagnostics

Only the backend reads credentials; edit `endless-tuna/.env` locally and restart. Never include a key or full upstream error body in a support report.

- **Missing configuration**: fill LAS_API_KEY locally; set the gateway URL. OPENAI_KEY applies only if the primary variable is absent, not explicitly empty. Browsing/search/parsing/exports continue without it.
- **401 authentication failure**: check the supplied credential with the gateway operator. Neither key is printed by diagnostics.
- **403 access denial**: check gateway/model permissions, lab network/VPN and access policy. A previous 403 does **not** establish that the key is wrong.
- **Invalid model**: explicitly Check connection, then select an exact discovered ID and save. A saved choice for that gateway overrides LAS_MODEL. Discovery permission and inference permission can differ.
- **Rate limited (429)**: wait and retry explicitly. Discovery retries appropriate transient failures with a bound; inference is not automatically replayed.
- **Timeout**: check network/gateway load and LAS_TIMEOUT_SECONDS (>0 and ≤600). A model request may have reached the server; do not assume a timeout means it did no work.
- **Unreachable endpoint/network failure**: verify the configured base URL, VPN/DNS/firewall and gateway availability. Changing collection URL validation will not fix LAS connectivity; they use separate transports.
- **Malformed JSON/HTML reply**: diagnostics classify it without displaying raw upstream bodies. The gateway must support ordinary `/models` and `/chat/completions`. Do not enable unsupported provider extensions or substitute another provider.
- **Extraction schema/evidence failure**: stored text/papers remain available. Review the concise error and retry explicitly; unsupported claims are flagged, not filled with demo data.

Settings opens without making a completion. **Check connection** verifies model discovery only. **Test model** is the explicit tiny live completion test. Successful local/mocked tests do not verify live gateway access.
