# Configuration reference

Only `.env` is loaded, with process environment taking precedence. Keep API and worker on the same data directory/configuration. Restart after changes. `.env.example` contains placeholders/defaults only. Edit credentials locally; do not paste them into chat, frontend controls or commands containing key values.

## LAS gateway

The backend uses the same environment connection pattern intended for Scientist-on-Call, in a separate application:

```dotenv
LAS_API_BASE_URL=https://llm-west.ncsu-las.net/v1
LAS_API_KEY=
LAS_MODEL=
LAS_TIMEOUT_SECONDS=90
```

`OPENAI_KEY` is a compatibility fallback **only when LAS_API_KEY is absent**. An explicitly empty `LAS_API_KEY=` suppresses fallback. To use fallback, remove the primary assignment and set OPENAI_KEY in this app's local environment. Neither key is logged, exported or sent to the browser. No VITE secret variables are supported.

All application model inference uses the configured LAS gateway. URLs normalize without duplicating `/v1`; bearer authentication is server-side. No model is hard-coded. Settings → **Check connection** explicitly calls `GET /models`; select an exact returned ID and save it. Selection is saved in real SQLite settings and takes precedence over LAS_MODEL for that gateway. **Test model** explicitly calls a tiny ordinary `POST /chat/completions`. Opening Settings does not perform discovery or inference. Discovery success does not establish completion permissions. No automatic fallback to OpenAI's public endpoint, another provider or LM Studio exists.

A previous 403 is evidence of access denial, not proof of an incorrect key. Check lab network/VPN, account/model permissions and gateway access with the operator. See [troubleshooting](troubleshooting.md). The supplied LAS URL is a configurable address; access is not verified by configuration alone.

## Local and collection settings

| Variable | Default | Meaning |
| --- | --- | --- |
| TUNA_DATA_DIR | `var` | Shared SQLite, PDF and export root. Prefer an absolute path on a local disk; `~` expands. Compose forces `/data`. |
| TUNA_API_PORT | 8000 | `start.sh` API port; 1024–65535, loopback only. |
| TUNA_UI_PORT | 5173 | `start.sh` Vite port; differs from API. Ignored by `--built`. |
| TUNA_DOWNLOAD_CONCURRENCY | 2 | Parallel paper workers, 1–4. |
| TUNA_DOWNLOAD_TIMEOUT_SECONDS | 30 | HTTP timeout, 1–90 seconds. |
| TUNA_REQUEST_INTERVAL_SECONDS | 0.4 | Per-process/per-host spacing, 0.05–60 seconds; arXiv uses 3.1 seconds. |
| TUNA_MAX_PDF_MB | 30 | Individual download limit, 1–200 decimal MB. |
| TUNA_SEARCH_ENDPOINT | unset | Optional public JSON search provider. Contract in collection docs. No provider results are invented when absent. |
| TUNA_ZIP_MAX_MB | 100 | Default/max UI bundle part size, 1–500 decimal MB. |
| TUNA_EXPORT_TOTAL_MB | 1024 | Total PDF bundle budget, 1–100000 decimal MB. |
| TUNA_EXPORT_MAX_PAPERS | 10000 | Export selection cap, 1–100000. |
| TUNA_EXPORT_TTL_HOURS | 24 | Artifact registry lifetime, 1–168 hours; cleanup on subsequent generation. |

The exact export range checks live in `exports.py`; invalid values produce explicit errors. LAS timeout accepts values greater than zero and at most 600 seconds. Installation/updates need package registry access. Conference websites, arXiv and optional web search are **separate collection connections** from LAS. Stored records remain locally searchable without external collection access; new collection requires access to relevant sources, and AI enrichment requires LAS connectivity. Accessible stored PDFs can be parsed and exported without either network connection. There is no automatic OCR service or Scholar scraper.
