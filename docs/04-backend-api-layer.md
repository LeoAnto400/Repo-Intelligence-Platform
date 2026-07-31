# 04 — Backend: API Layer

Files:

- `backend/src/api/main.py` — FastAPI app construction
- `backend/src/api/routes.py` — all endpoints
- `backend/src/api/schemas.py` — Pydantic models
- `backend/src/core/config.py` — `Settings`
- `backend/src/core/logging.py` — logging setup
- `backend/src/core/rate_limit.py` — `InMemoryRateLimiter`

## App construction (`main.py`)

```python
app = FastAPI(
    title=settings.PROJECT_NAME,
    docs_url="/docs", redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=[...], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix=settings.API_V1_STR)  # "/api/v1"
```

- **CORS origins are hardcoded** to `http://localhost:3000`, `http://127.0.0.1:3000`, and one
  LAN IP example (`192.168.1.7:3000`, matching `allowedDevOrigins` in the frontend's
  `next.config.ts`). A comment flags that production deployments must replace these with the
  real frontend domain.
- **`lifespan`** — on startup, `_clear_stale_temp_clones()` wipes any leftover directories
  under `.temp_clones/`. Each ingestion cleans up its own clone dir on success *and* failure
  (see `GitHubService.fetch_repo_files`'s `finally` block), so anything still present at
  startup can only be debris from a process that was killed mid-clone.
- **Global exception handler** — any exception that escapes a route handler is caught, logged
  with a full traceback, and turned into a `500 {"detail": "Internal server error: ..."}`
  instead of crashing the ASGI worker/connection.
- **`GET /health`** — trivial `{"status": "healthy"}`, unauthenticated, outside the `/api/v1`
  prefix.

## `Settings` (`core/config.py`)

A `pydantic_settings.BaseSettings` subclass, loaded from environment variables and/or a
`.env` file in `backend/`. Full field reference:

| Field | Default | Purpose |
|---|---|---|
| `PROJECT_NAME` | `"GitHub Repository Intelligence Assistant"` | FastAPI app title |
| `API_V1_STR` | `"/api/v1"` | Route prefix |
| `LOG_LEVEL` | `"INFO"` | Root logger level |
| `GEMINI_API_KEY` | `""` | **Required** — Google Gemini API key |
| `GITHUB_TOKEN` | `None` | Optional — GitHub PAT for higher rate limits / private repos |
| `GEMINI_EMBEDDING_BATCH_SIZE` | `8` | Max chunks per embedding request (see also `EMBED_BATCH_SIZE`) |
| `GEMINI_EMBEDDING_MAX_BATCH_CHARS` | `12000` | Max total chars per embedding request |
| `GEMINI_EMBEDDING_BATCH_DELAY_SECONDS` | `0.5` | Delay between embedding sub-batches |
| `EMBED_BATCH_SIZE` | `5` | Max chunks per request (used by `GeminiService.generate_embeddings_batch`) |
| `EMBED_BATCH_DELAY` | `0.5` | Delay (seconds) between embedding batches |
| `MAX_RETRIES` | `5` | Retry attempts for rate-limited/network-failed Gemini calls |
| `MAX_TOKENS_PER_BATCH` | `10000` | Max estimated tokens per single embedding request |
| `MAX_REQUESTS_PER_MINUTE` | `100` | RateLimiter RPM ceiling |
| `MAX_TOKENS_PER_MINUTE` | `1_000_000` | RateLimiter TPM ceiling (must stay well above `MAX_TOKENS_PER_BATCH`) |
| `CHROMA_DB_DIR` | `"./chroma_db"` | Local directory for persisted ChromaDB collections |
| `RETRIEVAL_TOP_K` | `20` | ANN candidates fetched before reranking |
| `RETRIEVAL_FINAL_K` | `5` | Reranked chunks passed to the LLM |
| `INGEST_RATE_LIMIT_PER_MINUTE` | `5` | Per-client-IP `/ingest` request cap |
| `QUERY_RATE_LIMIT_PER_MINUTE` | `20` | Per-client-IP `/query` (REST or WS) request cap |

`class Config: env_file = ".env"; case_sensitive = True`. Instantiated once as a module-level
`settings` singleton, imported everywhere else.

## Logging (`core/logging.py`)

`configure_logging()` is idempotent (`_CONFIGURED` guard) and attaches a `StreamHandler(sys.stdout)`
with a timestamped formatter directly to the **root logger**. This exists because Uvicorn's own
`LOGGING_CONFIG` only wires up `uvicorn`/`uvicorn.access`/`uvicorn.error` loggers — without this
call, every `logging.getLogger(__name__)` call throughout the app (used pervasively — see the
ingestion pipeline's per-step timing logs) would be silently dropped by Python's default "last
resort" handler, which only surfaces `WARNING`+. Called once at import time in `api/main.py`.

## Rate limiting (`core/rate_limit.py`)

`InMemoryRateLimiter(max_requests, window_seconds)` — a per-key sliding-window limiter backed
by `Dict[str, Deque[float]]` (one timestamp deque per key, e.g. client IP). `allow(key)` pops
timestamps older than the window, checks the remaining count against `max_requests`, and either
appends the current time and returns `True`, or returns `False`. Explicitly documented as
**single-process, in-memory** — a multi-worker deployment would need a shared store (e.g.
Redis) instead; fine for this single-process FastAPI app.

Two instances live in `routes.py`:
```python
_ingest_rate_limiter = InMemoryRateLimiter(max_requests=settings.INGEST_RATE_LIMIT_PER_MINUTE, window_seconds=60.0)
_query_rate_limiter = InMemoryRateLimiter(max_requests=settings.QUERY_RATE_LIMIT_PER_MINUTE, window_seconds=60.0)
```
enforced as FastAPI dependencies (`enforce_ingest_rate_limit`, `enforce_query_rate_limit`) that
raise `HTTPException(429)` — and, separately, checked manually inside the WebSocket loop (which
can't use a `Depends()` per-message) before processing each incoming question.

## Dependency injection pattern

Every service/agent is exposed as an `@lru_cache(maxsize=1)`-decorated factory function —
effectively a manual singleton, resolved once per process and injected via FastAPI's
`Depends(...)`:

```python
@lru_cache(maxsize=1)
def get_github_service() -> GitHubService: ...
@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreManager: ...
@lru_cache(maxsize=1)
def get_orchestrator() -> Orchestrator: ...
```

`ActiveRepositoryRetrievalAgent` is a small adapter class implementing the same `process(payload)`
interface as `RetrievalAgent`, but it injects `repository_id` from the process-global active
repository before delegating — this is what lets `get_orchestrator()` be constructed once at
startup while still always querying whatever repository is currently active, without
`RetrievalAgent` itself needing any notion of "active repository."

## Process-global active-repository state

```python
_active_repository: Optional[str] = None
_active_repository_context: Optional[Dict[str, Any]] = None
```

Set by `/ingest` and `/repositories/{name}/select`, cleared by `/repositories/{name}` DELETE
(only if the deleted repo was the active one). Read by `/query`, `/ws/query` (via
`ActiveRepositoryRetrievalAgent`), and `/repository`/`/commits/{hash}/summary`. This is a
deliberate single-tenant simplification — see [01-architecture.md](01-architecture.md#key-design-decisions-and-why).

## Endpoint reference

All paths below are relative to `API_V1_STR` (`/api/v1`).

### `POST /ingest`

- **Body**: `IngestRequest { repo_url: str }`
- **Response**: `IngestResponse { status, repository, files_processed, chunks_created, repo_url? }`
- Rate-limited via `enforce_ingest_rate_limit`. Validates URL shape with `validate_repo_url`
  (scheme must be http/https, non-empty host and path) before doing anything expensive.
  Full step-by-step behavior is documented in
  [02-backend-ingestion-pipeline.md](02-backend-ingestion-pipeline.md#putting-it-together-what-post-ingest-actually-does).

### `GET /repository`

- **Response**: `RepositoryContextResponse { repository, repo_url, metadata, files, commits, pull_requests }`
- Returns the current `_active_repository_context`; `404` if nothing has been ingested/activated yet.

### `GET /repositories`

- **Response**: `List[RepositorySummary] { repository, repo_url?, chunk_count }`
- Lists every collection currently in ChromaDB (via `VectorStoreManager.list_collections`) so
  the frontend can offer to reactivate a previously-ingested repo instead of re-ingesting it.

### `DELETE /repositories/{repository}`

- **Response**: `DeleteRepositoryResponse { repository, status: "deleted" }`
- `404` if the named collection doesn't exist. Deletes the ChromaDB collection; if it was the
  active repository, also clears `_active_repository`/`_active_repository_context`.

### `POST /repositories/{repository}/select`

- **Response**: `RepositoryContextResponse`
- Activates an already-ingested repository **without re-cloning or re-embedding**. If the
  collection has a recorded `repo_url`, refreshes live metadata/commits/PRs from GitHub
  (failure here only logs a warning — activation proceeds with minimal context). Always
  regenerates the AI summary/technologies/suggested-questions from the collection's existing
  chunks via `sample_documents` + `AnalysisAgent.generate_repository_overview` (this is what
  makes it work even for a collection whose original URL isn't known). The repository is
  activated for chat regardless of whether either refresh step succeeds.

### `POST /commits/{commit_hash}/summary`

- **Response**: `CommitSummaryResponse { hash, summary }`
- `404` if no repository is active, or if `commit_hash` isn't among the active repository's
  captured recent commits. Otherwise calls `AnalysisAgent.generate_commit_summary` using the
  message/diff already captured at ingestion time (no extra GitHub call).

### `POST /query`

- **Body**: `QueryRequest { question: str, history?: ConversationMessage[] }`
- **Response**: `QueryResponse { answer, source_files, retrieved_chunks }`
- Rate-limited via `enforce_query_rate_limit`. `400` on empty question, `400` on
  orchestrator `ValueError`, `500` on orchestrator `RuntimeError` or any other exception.
  Calls `orchestrator.process(question, history=...)` (blocking — waits for the full answer).

### `WS /ws/query`

Streaming counterpart to `POST /query`. Protocol, one connection, many questions:

- **Client → server**, per question: `{"question": "...", "history"?: [{"role", "content"}, ...]}`
- **Server → client**, per question, in order:
  1. `{"type": "retrieval", "retrieved_chunks": N}`
  2. zero or more `{"type": "token", "text": "..."}`
  3. either `{"type": "done", "answer": ..., "source_files": [...], "chunk_count": N}`
     or `{"type": "error", "detail": "..."}`
- Empty questions get an immediate `{"type": "error", "detail": "Question cannot be empty."}`
  without touching the rate limiter. Rate-limit violations get
  `{"type": "error", "detail": "Too many query requests..."}`. Both cases **keep the connection
  open** for the next question rather than closing it.
- The connection stays open across multiple questions until the client disconnects
  (`WebSocketDisconnect`, logged and allowed to end the handler cleanly).
- `_normalize_history` sanitizes the raw incoming JSON history into
  `[{"role": str, "content": str}, ...]`, silently dropping malformed turns instead of
  rejecting the whole message.

### Shared helpers worth knowing

- `collection_name_from_repo_url(repo_url)` — derives a ChromaDB-safe collection name from the
  URL's last path segment (strip to `[a-zA-Z0-9_-]`, collapse repeated underscores, minimum 3
  chars else `"repo_collection"`, max 60 chars). This is why re-ingesting the same URL reuses
  the same collection.
- `_TaggedLogAdapter` — prefixes every log line for a single request with a short correlation
  tag like `[ingest:3f9a2c1d]` or `[query-ws:7ab1]`, so interleaved concurrent requests can be
  grepped apart in server logs.

## `schemas.py` — Pydantic models

| Model | Fields |
|---|---|
| `IngestRequest` | `repo_url: str` |
| `IngestResponse` | `status, repository, files_processed, chunks_created, repo_url?` |
| `ConversationMessage` | `role: str, content: str` |
| `QueryRequest` | `question: str, history: List[ConversationMessage] = []` |
| `QueryResponse` | `answer: str, source_files: List[str], retrieved_chunks: int` |
| `DeleteRepositoryResponse` | `repository: str, status: str` |
| `RepositorySummary` | `repository: str, repo_url?: str, chunk_count: int = 0` |
| `CommitSummaryResponse` | `hash: str, summary: str` |
| `RepositoryContextResponse` | `repository, repo_url, metadata: dict, files: list[dict], commits: list[dict], pull_requests: list[dict]` |

These are the source of truth that `frontend/src/types/api.ts` is hand-kept in sync with (see
[05-frontend-architecture.md](05-frontend-architecture.md)).
