# 07 — Testing & CI

## Backend tests (`backend/tests/`, `pytest`, `unittest`-style)

Written with Python's built-in `unittest` (via `TestCase` / `IsolatedAsyncioTestCase` for async
code), collected and run by `pytest`. One file per module, generally named `test_<module>.py`:

| File | Covers |
|---|---|
| `test_chunker.py` (`TestCodeChunker`) | AST-based Python chunking, sliding-window chunking for other languages, oversized-chunk splitting, chunk ID stability |
| `test_github_service.py` (`TestGitHubService`) | URL parsing, clone/scan behavior, `SUPPORTED_EXTENSIONS`/`IGNORE_DIRS` filtering, `safe_rmtree` |
| `test_gemini_service.py` (`TestGeminiService`, `TestGeminiServiceStreaming`) | Embedding/generation calls, retry classification, streaming generator behavior |
| `test_ingestion.py` (`TestIngestionValidation`) | `filter_chunks_for_embedding` — dropping empty chunks, raising when nothing survives |
| `test_ingestion_resilience.py` | The most granular suite — dedicated `TestCase` classes for `estimate_tokens`, `get_int_value`, `RateLimiter` (RPM/TPM sliding window), adaptive batch sizing, exponential backoff, duplicate-chunk detection, checkpoint/resume against ChromaDB, and error classification (`InvalidAPIKeyError`/`QuotaExhaustedError`/`NetworkFailureError`) |
| `test_chroma.py` (`TestVectorStoreManager`) | Collection creation (cosine metric), `add_documents`, `query_similarity` result mapping, `reset_collection` idempotency, `list_collections`, `sample_documents` |
| `test_retrieval_agent.py` | Payload validation, the embed→ANN→rerank pipeline, and the rerank fallback-to-ANN-order path on failure |
| `test_analysis_agent.py` (`TestAnalysisResult`, `TestAnalysisAgent`) | Context-block/prompt construction, history truncation, `generate_repository_overview` JSON parsing, `generate_commit_summary` |
| `test_orchestrator.py` (`TestOrchestratorResult`, `TestOrchestrator`) | The LangGraph `process()` path (success + error propagation from each node) and the `stream()` path |
| `test_api.py` (`TestApi`) | Route-level behavior — request validation, status codes, response shapes |
| `test_main.py` (`TestClearStaleTempClones`) | The startup cleanup of stale `.temp_clones/` directories |
| `test_rate_limit.py` (`TestInMemoryRateLimiter`) | Sliding-window allow/deny behavior, window expiry, `reset()` |
| `personal_test.py` | Ad hoc/manual test scratch file (not a structured suite) |

`backend/scripts/test_rag_pipeline.py` and `test_retrieval_pipeline.py` are **manual
integration scripts**, not part of the pytest/CI suite — they exercise the real Gemini/ChromaDB
pipeline end-to-end against live services for local debugging.

Run locally:

```bash
cd backend
pip install -r requirements.txt   # from the repo root's requirements.txt (or backend's own copy)
pytest -q
```

## Frontend tests (`frontend/src/**/*.test.{ts,tsx}`, Vitest + Testing Library)

Configured in `frontend/vitest.config.ts`: `jsdom` environment, `vite-tsconfig-paths` (so
`@/...` imports resolve the same as in the app), setup file `vitest.setup.ts`.

| File | Covers |
|---|---|
| `components/ui/button.test.tsx` | Renders children, respects `disabled` |
| `features/chat/components/MarkdownRenderer.test.tsx` | Plain text, fenced code blocks (syntax highlighter doesn't crash), inline code |
| `features/chat/components/MessageBubble.test.tsx` | Typing indicator while pending/empty, live-growing content while streaming, source citations + timestamp once complete, retry button when errored |
| `features/chat/services/queryStream.test.ts` | `QueryStreamClient` — connect/send/token-forward/resolve-on-done, sending history, **socket reuse across queries**, rejecting on an `error` event, rejecting on early close, rejecting on connect error |
| `features/chat/store/useChatStore.test.ts` | The full `sendMessage`/`retryMessage` state machine: progressive token streaming, history payload construction (none on first message, prior completed turns on follow-ups, excluding pending/errored messages), **REST fallback when the WebSocket stream fails**, error state when both paths fail, ignoring empty questions, ignoring sends while already loading, `clearChat` |
| `features/repo-metadata/store/useRepoStore.test.ts` | `deleteRepository` — removes from `availableRepositories`; clears active-repo fields only if the deleted repo was active; leaves everything else untouched otherwise; rethrows and leaves state unchanged on a failed delete call |
| `lib/runtime-safety.test.ts` | Every normalization helper — `getErrorMessage`, `appendLogLines`, `normalizeRepositoryContext`, `normalizeIngestResponse` (including the "missing `repository` throws" case), `normalizeRepositorySummaries`, `normalizeQueryResponse` |
| `lib/utils.test.ts` | `cn()` — Tailwind class merging and falsy-value dropping |

Notice the frontend test suite deliberately targets **behavior that's easy to regress
silently**: the streaming/fallback logic in `useChatStore`, the WebSocket reconnect/reuse logic,
and every defensive-normalization branch in `runtime-safety.ts` — not just "does it render."

Run locally:

```bash
cd frontend
npm install
npm test          # vitest run (single pass)
npm run test:watch  # vitest, watch mode
```

## CI (`.github/workflows/ci.yml`)

Two independent jobs, both triggered on push to `main` and on every pull request:

```yaml
backend:
  runs-on: ubuntu-latest
  working-directory: backend
  steps: checkout → setup-python 3.10 (pip cache) → pip install -r requirements.txt → pytest -q

frontend:
  runs-on: ubuntu-latest
  working-directory: frontend
  steps: checkout → setup-node 22 (npm cache) → npm ci --legacy-peer-deps →
         npm run lint → npx tsc --noEmit → npm test → npm run build
```

Key details worth preserving if you reproduce this:

- The frontend job runs **lint → type-check → test → build**, in that order — fail fast on the
  cheapest check first.
- `npm ci --legacy-peer-deps` is required, not optional — some dependency in this project's
  tree has peer-dependency ranges that plain `npm ci` would refuse to resolve strictly.
- The backend job's `cache-dependency-path` points at `backend/requirements.txt` explicitly
  (needed because `working-directory` doesn't retarget cache key resolution automatically).
- Neither job needs secrets (no `GEMINI_API_KEY`/`GITHUB_TOKEN`) — the test suites mock the
  Gemini/GitHub/ChromaDB calls rather than hitting real services, which is exactly why the
  manual scripts in `backend/scripts/` are kept out of the pytest/CI path.
