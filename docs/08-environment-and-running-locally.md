# 08 — Environment & Running Locally

## Prerequisites

- **Python 3.10** (CI pins this version; the code uses no syntax newer than 3.10 supports)
- **Node.js 22** (CI pins this version) + npm
- **git** on `PATH` — the backend shells out to it (`git clone --depth 1 ...`) rather than
  using a Python git library
- A **Google Gemini API key** (required — the app cannot embed or generate anything without one)
- Optionally, a **GitHub personal access token** — raises GitHub API rate limits and allows
  cloning private repositories

## Backend environment variables

Copy `backend/.env.example` to `backend/.env` and fill in real values. Full reference (see also
[04-backend-api-layer.md](04-backend-api-layer.md#settings-coreconfigpy) for defaults not shown
in the example file):

```bash
# backend/.env
GEMINI_API_KEY=                          # required
GITHUB_TOKEN=                            # optional, raises rate limits / enables private repos
CHROMA_DB_DIR=./chroma_db                # local persistent vector store directory

# Gemini embedding batching (optional overrides)
GEMINI_EMBEDDING_BATCH_SIZE=4
GEMINI_EMBEDDING_MAX_BATCH_CHARS=8000
GEMINI_EMBEDDING_BATCH_DELAY_SECONDS=2.0

# Per-client-IP request rate limiting (optional overrides)
INGEST_RATE_LIMIT_PER_MINUTE=5
QUERY_RATE_LIMIT_PER_MINUTE=20
```

`Settings` (`pydantic-settings`) also reads `LOG_LEVEL`, `EMBED_BATCH_SIZE`, `EMBED_BATCH_DELAY`,
`MAX_RETRIES`, `MAX_TOKENS_PER_BATCH`, `MAX_REQUESTS_PER_MINUTE`, `MAX_TOKENS_PER_MINUTE`,
`RETRIEVAL_TOP_K`, `RETRIEVAL_FINAL_K` — all have sane defaults baked into `core/config.py`, so
only override them if you need to tune throughput/behavior.

## Frontend environment variables

Copy `frontend/.env.local.example` to `frontend/.env.local`:

```bash
# frontend/.env.local
# Left unset intentionally by default — api-client.ts resolves the backend host
# dynamically from the page's own hostname. Only set this if the backend runs
# on a different host/port than the convention (same host, port 8000).
# NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1
```

## Running the backend

```bash
cd backend                     # or: run from repo root if using the root main.py
pip install -r ../requirements.txt   # repo-root requirements.txt (backend has no separate one for prod deps)
python ../main.py              # OR: uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

`main.py` (repo root) is the dev entrypoint:

```python
uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)
```

Once running:

- API base: `http://127.0.0.1:8000/api/v1`
- Interactive docs: `http://127.0.0.1:8000/docs` (Swagger) or `/redoc`
- Health check: `http://127.0.0.1:8000/health`

The first ingestion request creates `chroma_db/` (persistent vector store) and a transient
`.temp_clones/<random>/` directory (cleaned up automatically at the end of the request, and
swept again on the next process startup if anything was left behind by a crash).

## Running the frontend

```bash
cd frontend
npm install
npm run dev
```

Opens on `http://localhost:3000`. Because `api-client.ts` resolves the backend host from
`window.location.hostname`, opening the app via `http://<your-LAN-ip>:3000` from another device
will correctly call `http://<your-LAN-ip>:8000/api/v1` — as long as that IP is present in the
backend's CORS `allow_origins` list (`backend/src/api/main.py`) and the frontend's
`allowedDevOrigins` (`frontend/next.config.ts`). Update both if your LAN IP differs from the
`192.168.1.7` example baked into this codebase.

## Notes and gotchas

- **CORS is currently hardcoded** to `localhost:3000` / `127.0.0.1:3000` / one example LAN IP.
  Deploying the frontend anywhere else requires adding that origin to
  `backend/src/api/main.py`'s `CORSMiddleware` `allow_origins`.
- **No database migrations, no auth, no multi-tenancy.** ChromaDB collections persist to
  `CHROMA_DB_DIR` as plain files; there's no user/session model — "active repository" is a
  single process-global value (see [01-architecture.md](01-architecture.md)).
- **Rate limits are per-process, in-memory.** Restarting the backend resets both the
  `InMemoryRateLimiter` counters and the Gemini `RateLimiter`'s sliding window.
- **A real ingestion is slow and rate-limited on purpose.** Expect anywhere from tens of
  seconds to several minutes depending on repo size — this is why the frontend's Axios client
  has a 10-minute timeout and why the ingestion UI shows a progress simulation rather than a
  static spinner.
- **Windows note**: `safe_rmtree` in `github.py` exists specifically because `.git/objects`
  files are often read-only on Windows and plain `shutil.rmtree` fails on them without the
  `chmod`-and-retry fallback it implements.
