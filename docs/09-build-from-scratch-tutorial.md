# 09 — Build This Project From Scratch

A practical build order for reproducing this whole system yourself, starting from an empty
directory. Each stage names the exact files you'll create and points back at the detailed docs
for the *why*; this file is the *in-what-order* and *how-do-I-know-it-works* guide. Build and
verify bottom-up — the ingestion pipeline before the agents, the agents before the API, the API
before the frontend — so every layer has something real underneath it to test against.

## Stage 0 — Project skeleton

```
repo-intelligence-Platform/
├── main.py
├── requirements.txt
├── backend/
│   ├── src/{__init__.py, agents/__init__.py, api/__init__.py, core/__init__.py, db/__init__.py, services/__init__.py}
│   └── tests/
└── frontend/            # created in Stage 5 via `npx create-next-app`
```

`requirements.txt` at the repo root:
```
fastapi>=0.100.0
uvicorn>=0.22.0
pydantic-settings>=2.0.0
chromadb>=0.4.0
google-generativeai>=0.3.0
langgraph>=0.0.15
PyGithub>=1.59.0
python-dotenv>=1.0.0
```

Get a Gemini API key (https://ai.dev) before going further — nothing embeds or generates
without one.

## Stage 1 — Core config, logging, rate limiting

Build these three first; everything else imports them.

1. `backend/src/core/config.py` — a `pydantic_settings.BaseSettings` subclass with every field
   listed in [04-backend-api-layer.md](04-backend-api-layer.md#settings-coreconfigpy), a
   `class Config: env_file = ".env"`, and a module-level `settings = Settings()` singleton.
2. `backend/src/core/logging.py` — `configure_logging()` attaching a `StreamHandler` to the
   root logger, guarded by an idempotency flag. Call it once, early, in your FastAPI app module.
3. `backend/src/core/rate_limit.py` — `InMemoryRateLimiter(max_requests, window_seconds)` with
   an `allow(key) -> bool` sliding-window check backed by `Dict[str, deque[float]]`.

**Checkpoint**: write `test_rate_limit.py` — assert `allow()` returns `True` up to the limit,
`False` after, and `True` again once the window has elapsed (use a short window and
`time.sleep` or monkeypatch `time.time`).

## Stage 2 — GitHub service (clone + scan + metadata)

Build `backend/src/services/github.py`:

1. `SUPPORTED_EXTENSIONS` dict and `IGNORE_DIRS` set (see
   [02-backend-ingestion-pipeline.md](02-backend-ingestion-pipeline.md#scanning) for the exact
   lists).
2. `safe_rmtree(path)` — try `shutil.rmtree`, fall back to a `chmod`+retry `onerror` handler for
   Windows read-only files.
3. `GitHubService.clone_repository(repo_url)` — validate non-empty URL, create
   `.temp_clones/<tmp>` under cwd, inject a token into the clone URL if configured, run
   `subprocess.run(["git", "clone", "--depth", "1", url, tempdir], check=True, ...)`, clean up
   and raise on failure.
4. `GitHubService.fetch_repo_files(repo_url)` — clone, `os.walk` pruning `IGNORE_DIRS`, read
   every supported-extension file as UTF-8 (`errors="ignore"`), always `safe_rmtree` in a
   `finally` block.
5. `GitHubService.fetch_repository_context(repo_url, files=None, ...)` — use `PyGithub`
   (`Github(token) if token else Github()`) to pull repo metadata, contributors, commits
   (with per-commit diffs from the first 5 changed files' patches), and pull requests
   (wrapped in its own try/except so a PR-fetch failure doesn't kill metadata fetch).

**Checkpoint**: clone a small public repo manually (`GitHubService().fetch_repo_files("https://github.com/octocat/Hello-World")`)
and confirm you get back a non-empty list of `{path, language, content}` dicts, and that
`.temp_clones/` is empty again afterward.

## Stage 3 — Code chunker

Build `backend/src/services/chunker.py`:

1. `CodeFile` and `Chunk` dataclasses.
2. `CodeChunker.__init__(max_chunk_chars=4000, overlap_chars=200)` with validation.
3. `_chunk_python_file` — `ast.parse`, iterate `tree.body` for top-level
   `ClassDef`/`FunctionDef`/`AsyncFunctionDef`, extract exact source lines (including
   decorators), fall back to a whole-file chunk on parse failure or zero top-level defs.
4. `_chunk_generic_file` + `_split_text_with_overlap` + `_find_line_break_before` — sliding
   window chunking for non-Python files, snapping window boundaries to line breaks.
5. `_add_file_header` — prepend `# File: <path>` to every chunk's content.
6. `_generate_chunk_id` — SHA-256 of `file_path + chunk_type + content (+ part suffix)`.
7. `_finalize_chunks` + `_split_oversized_chunk` — the safety net that re-splits anything still
   over `max_chunk_chars` after the primary strategy ran.

**Checkpoint**: chunk a real multi-function Python file and a real long non-Python file (e.g.
a big `.md`); assert every chunk's `len(content) <= max_chunk_chars`, chunk IDs are stable
across two runs on identical input, and IDs differ if content differs by even one character.

## Stage 4 — Gemini service (embeddings + generation)

Build `backend/src/services/gemini.py` incrementally — this is the most complex single file,
so build and test it in pieces:

1. `estimate_tokens(text)` (`len(text) // 4`) and `get_int_value(val, default)`.
2. `RateLimiter(max_rpm, max_tpm)` — `record_request(token_count)` appends to a deque;
   `wait_if_needed(next_tokens)` prunes entries older than 60s, then sleeps if adding
   `next_tokens` would exceed either limit.
3. `GeminiService.__init__` — read the API key from param → env → settings (raise if none),
   `genai.configure(api_key=...)`, construct the `RateLimiter` from settings.
4. `_call_with_retry` — classify exceptions into invalid-key / hard-quota / soft-rate-limit /
   network / other, exponential backoff with jitter on the retryable ones, custom exception
   types (`InvalidAPIKeyError`, `QuotaExhaustedError`, `NetworkFailureError`) for the rest.
5. `generate_embedding(text, task_type="retrieval_query")` — single embed call.
6. `generate_content(prompt, system_instruction=None, model="gemini-2.5-flash")` — single
   blocking generation call.
7. `generate_content_stream(...)` — an async generator backed by a background thread pushing
   into an `asyncio.Queue` (needed because the SDK's streaming iterator is synchronous).
8. `generate_embeddings_batch(texts, ...)` — build item/char/token-bounded batches, rate-limit
   and retry each, checkpoint against ChromaDB if a `vector_store`+`repository`+
   `embeddable_chunks` are available, dedupe identical chunk texts, adaptively shrink/grow
   `current_batch_size`. **Build this last** — it composes everything above it.

**Checkpoint**: `generate_embedding("def foo(): pass", task_type="retrieval_document")` returns
a `List[float]` of consistent length; `generate_content("Say hello in one word.")` returns text;
`generate_content_stream(...)` yields multiple non-empty string chunks that concatenate to a
sensible answer.

## Stage 5 — Vector store (ChromaDB)

Build `backend/src/db/chroma.py`:

1. `VectorStoreManager(db_path)` — lazy `chromadb.PersistentClient(path=db_path,
   settings=Settings(allow_reset=True))`.
2. `get_collection(name, extra_metadata=None)` — **always** `metadata={"hnsw:space": "cosine", **extra}`.
3. `add_documents`, `query_similarity` (flatten Chroma's list-of-lists response shape into a
   flat list of dicts), `sample_documents`, `reset_collection` (swallow "not found"),
   `list_collections`.

**Checkpoint**: embed two very different sentences and one near-duplicate of the first, add all
three to a test collection, query with the first sentence's embedding, and confirm the
near-duplicate ranks above the unrelated one (i.e. cosine ordering is sane).

## Stage 6 — Ingestion glue

Build `backend/src/services/ingestion.py`: `filter_chunks_for_embedding(chunks)` — drop
empty/whitespace chunks, raise if the whole batch is now empty.

At this point you can write a **standalone script** (like `backend/scripts/test_rag_pipeline.py`
in this repo) that runs the whole ingestion path end-to-end without any HTTP layer yet: clone →
chunk → filter → embed → store. Get this working and manually verified before adding FastAPI.

## Stage 7 — Agents

Build in this order, each depending only on what came before:

1. `backend/src/agents/base.py` — `BaseAgent(ABC)` with one abstract `async def process(self, payload) -> dict`.
2. `backend/src/agents/retrieval.py` — `RetrievalResult` dataclass, `RetrievalAgent`:
   payload validation → `generate_embedding(query, task_type="retrieval_query")` →
   `query_similarity(top_k)` → map to `RetrievalResult` → `_rerank` (single batched Gemini
   prompt asking for a ranked JSON index array, with a raw-ANN-order fallback on any failure).
3. `backend/src/agents/analysis.py` — `AnalysisResult` dataclass, `AnalysisAgent`:
   `_build_context_block` (numbered chunk sections with file/line/type headers),
   `_build_history_block` (last 8 turns, 1500 chars each, framed as reference-resolution-only),
   `_build_prompt`, `generate_analysis`/`stream_analysis`, plus
   `generate_repository_overview` (strict-JSON prompt + tolerant parsing) and
   `generate_commit_summary`.
4. `backend/src/agents/orchestrator.py` — `AgentState` TypedDict, `OrchestratorResult`
   dataclass, `Orchestrator`: build a 2-node `StateGraph` (`retrieve` → `analyze` → `END`) for
   `process()`, and a separate hand-written async generator `stream()` that calls the two
   agents directly (bypassing the compiled graph, since LangGraph nodes can't yield partial
   output).

**Checkpoint**: with one collection already populated (from Stage 6), call
`Orchestrator.process("What does this project do?")` directly (no HTTP yet) and confirm you get
a grounded `OrchestratorResult` back; then call `.stream(...)` and confirm you get a `retrieval`
event followed by multiple `token` events and a final `done`-shaped end.

## Stage 8 — FastAPI layer

1. `backend/src/api/schemas.py` — every Pydantic model from
   [04-backend-api-layer.md](04-backend-api-layer.md#schemaspy--pydantic-models).
2. `backend/src/api/routes.py` — `@lru_cache` singleton factories for every
   service/agent/orchestrator, the `_active_repository`/`_active_repository_context` globals
   and their getters/setters, `ActiveRepositoryRetrievalAgent` adapter,
   `collection_name_from_repo_url`, `validate_repo_url`, `_TaggedLogAdapter`, then the routes
   themselves in this order (each is easiest to test once the previous one works):
   `POST /ingest` → `GET /repository` → `GET /repositories` →
   `DELETE /repositories/{repository}` → `POST /repositories/{repository}/select` →
   `POST /query` → `WS /ws/query` → `POST /commits/{commit_hash}/summary`.
3. `backend/src/api/main.py` — `FastAPI(...)`, CORS middleware, `lifespan` calling
   `_clear_stale_temp_clones()`, the global exception handler, `/health`, and
   `app.include_router(api_router, prefix=settings.API_V1_STR)`.
4. Root `main.py` — `uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)`.

**Checkpoint**: `python main.py`, open `http://127.0.0.1:8000/docs`, and manually drive
`POST /ingest` with a small public repo URL through the Swagger UI, then `POST /query` against
it. Confirm `/health` returns `200`.

## Stage 9 — Frontend scaffold

```bash
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*"
cd frontend
npm install axios zustand @tanstack/react-query react-markdown remark-gfm \
  react-syntax-highlighter lucide-react framer-motion class-variance-authority \
  clsx tailwind-merge @base-ui/react
npm install -D vitest @vitejs/plugin-react vite-tsconfig-paths jsdom \
  @testing-library/react @testing-library/dom @testing-library/jest-dom
```

Then, in order:

1. `next.config.ts` — add `allowedDevOrigins` for your LAN IP if needed; **do not** add a
   rewrite proxy to the backend (see [05-frontend-architecture.md](05-frontend-architecture.md#api-client-libapi-clientts)
   for why).
2. `src/types/api.ts` — hand-write TypeScript interfaces mirroring every backend schema from
   Stage 8.1. Keep this file and the backend schemas in sync manually going forward.
3. `src/lib/api-client.ts` — `resolveApiBaseUrl()` (env override → `window.location.hostname`
   → `localhost` fallback), the Axios instance (10-minute timeout), the error-unwrapping
   response interceptor, `API_WS_BASE_URL`.
4. `src/lib/utils.ts` (`cn()`), `src/lib/runtime-safety.ts` (all the `normalize*`/`getErrorMessage`/`appendLogLines` helpers).
5. `src/services/base-service.ts` — the `BaseService` abstract class.
6. `components.json` (shadcn config) then generate the `Button` component
   (`npx shadcn@latest add button`, or hand-write it against `@base-ui/react`'s `Button` +
   `cva` following `frontend/src/components/ui/button.tsx`'s variant/size scheme).

**Checkpoint**: `npm run dev`, confirm the default Next.js page renders with Tailwind styling
applied.

## Stage 10 — Frontend features, in dependency order

Build each feature's **service → store → components**, in this order (later features depend on
earlier ones' stores):

1. **repo-metadata**: `services/repository.ts` → `store/useRepoStore.ts` → `components/RepositoryPicker.tsx`, `RepositoryDashboard.tsx`, `RepositoryManager.tsx`.
2. **ingestion**: `services/ingestion.ts` → `store/useIngestStore.ts` → `components/IngestPanel.tsx` (the fake-progress simulation is optional polish — get the real `ingestRepo` call working first).
3. `src/components/DashboardShell.tsx` — wire up `useRepoStore().fetchContext()` on mount and
   the conditional landing-vs-app-shell rendering.
4. `src/app/layout.tsx` + `src/app/providers.tsx` + `src/app/page.tsx` — assemble what you've
   built so far. **Checkpoint**: ingest a real repo through the UI and see the dashboard
   populate.
5. **chat**: `services/query.ts` (REST) → `services/queryStream.ts` (WebSocket client,
   connect/reuse/timeout logic) → `store/useChatStore.ts` (optimistic messages, streaming with
   REST fallback, retry) → components (`MarkdownRenderer` → `SourceCitations` →
   `TypingIndicator` → `MessageBubble` → `MessageList` → `ChatInput` → `ChatHeader` →
   `ChatWindow`) → `src/app/chat/page.tsx`.
6. **commits**: `services/commits.ts` → `store/useCommitSummaryStore.ts` →
   `components/CommitsList.tsx` → `src/app/commits/page.tsx`.
7. `src/app/settings/page.tsx` (just renders `RepositoryManager`, already built in step 1).
8. `error.tsx`, `not-found.tsx`, and per-route `loading.tsx` fallbacks.

**Checkpoint**: full manual pass — ingest a repo, watch the dashboard populate with an AI
summary/tech list/suggested questions, ask a question in chat and watch it stream, click a
suggested question, view commits and generate an AI summary for one, go to Settings and
re-activate/delete a repository.

## Stage 11 — Tests

Backend (`pytest`, `unittest`-style, one file per module — see
[07-testing-and-ci.md](07-testing-and-ci.md) for the exact list): write these **as you build
each module in Stages 1-8**, not all at the end — the granularity there (e.g.
`test_ingestion_resilience.py` having a dedicated `TestCase` per concern: rate limiting,
adaptive batching, backoff, dedup, checkpoint/resume, error classification) is much easier to
achieve incrementally.

Frontend (`vitest` + Testing Library): prioritize the stateful/async logic over rendering —
this project's own suite spends the most effort on `useChatStore` (streaming + fallback + retry
state machine) and `runtime-safety.ts` (every normalization branch), and comparatively little on
pure presentational components.

## Stage 12 — CI

Add `.github/workflows/ci.yml` with two jobs (`backend`, `frontend`) as documented in
[07-testing-and-ci.md](07-testing-and-ci.md#ci-githubworkflowsciyml) — backend runs
`pip install` + `pytest -q`; frontend runs `npm ci --legacy-peer-deps` then lint → type-check →
test → build, in that order, so cheap checks fail fast before the expensive build step.

## What to build next (beyond this codebase's current scope)

If you want to extend rather than just reproduce, the natural next additions — visible as
UI placeholders or explicit simplifications in the current code — are: a `Pull Requests`/
`Issues`/`File Explorer` page (nav items already exist in `DashboardShell` with no route wired
up), multi-user/session-scoped "active repository" state instead of a process-global, a shared
rate-limiter/session store (e.g. Redis) for multi-worker deployment, and streaming ingestion
progress over a WebSocket instead of the frontend's cosmetic progress simulation.
