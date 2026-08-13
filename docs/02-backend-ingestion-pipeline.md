# 02 — Backend: The Ingestion Pipeline

This covers everything that runs when a user submits a repo URL: cloning, scanning,
chunking, embedding, and storing. Files involved:

- `backend/src/services/github.py` — `GitHubService`
- `backend/src/services/chunker.py` — `CodeChunker`
- `backend/src/services/ingestion.py` — `filter_chunks_for_embedding`
- `backend/src/services/gemini.py` — `GeminiService`
- `backend/src/db/chroma.py` — `VectorStoreManager`

## `GitHubService` — cloning and scanning

### Cloning

`clone_repository(repo_url)`:

1. Creates `.temp_clones/` inside the current working directory if it doesn't exist.
2. If a `GITHUB_TOKEN` is configured, rewrites `https://github.com/...` to
   `https://x-access-token:<token>@github.com/...` so private repos and higher rate limits work.
3. Creates a unique temp dir with `tempfile.mkdtemp(dir=temp_base_dir)`.
4. Runs `git clone --depth 1 <url> <tempdir>` via `subprocess.run` — a **shallow clone**
   (history depth 1) to keep downloads fast; only the current source tree is needed, not history.
5. On any failure, cleans up the temp dir and raises `RuntimeError` with the captured stderr.

A helper pair, `is_dead_local_proxy` / `github_network_env` / `without_dead_local_proxy`,
strips `HTTP_PROXY`/`HTTPS_PROXY`/etc. environment variables *only* when they point at
`127.0.0.1:9` or `localhost:9` — a known "blocked proxy" value some sandboxed shells inherit
that would otherwise make outbound `git`/GitHub API calls hang or fail. Real proxy configs are
left untouched.

### Scanning

`fetch_repo_files(repo_url)`:

1. Clones the repo (above).
2. Walks the tree with `os.walk`, pruning `IGNORE_DIRS` in place (`.git`, `node_modules`,
   `build`, `dist`, `venv`, `.venv`, `__pycache__`, ...) so they're never descended into.
3. For every file whose extension is in `SUPPORTED_EXTENSIONS` (`.py`, `.js`, `.jsx`, `.ts`,
   `.tsx`, `.html`, `.css`, `.md`, `.json`, `.yaml`/`.yml`, `.sh`, `.go`, `.rs`, `.java`, `.cpp`,
   `.c`, `.h`, `.cs`, `.txt`), reads it as UTF-8 (`errors="ignore"` to tolerate stray non-UTF8
   bytes) and records `{path (relative, posix-style), language, content}`.
4. Always deletes the temp clone directory in a `finally` block via `safe_rmtree`, whether
   scanning succeeded or not.

`safe_rmtree(path)` exists because `shutil.rmtree` alone fails on Windows for files git marks
read-only (common inside `.git/objects`); on the first failure it retries with an `onerror`
handler that `chmod`s the file writable and removes it.

### Metadata: `fetch_repository_context`

Separate from source scanning — this calls the **GitHub REST API** via PyGithub to get the
data the dashboard needs:

```python
def fetch_repository_context(
    self, repo_url, files=None, commit_limit=50, pull_limit=50, contributor_limit=10
) -> Dict[str, Any]:
    ...
    return {
        "metadata": {...},      # name, description, stars, forks, language, license, ...
        "files": files or self.fetch_repo_files(repo_url),
        "commits": [...],       # up to commit_limit, newest first
        "pull_requests": [...], # up to pull_limit, sorted by updated desc
    }
```

Notable behavior:

- `files` is **accepted as a parameter** so the caller (the `/ingest` route) can pass the file
  list it already fetched during ingestion, avoiding a second clone. Passing `files=[]`
  explicitly skips fetching source files entirely (used by `/repositories/{name}/select`,
  which only needs fresh metadata, not source).
- Each commit is turned into a dict with `hash`, `author`, `message`, `time`, `branch`,
  `filesChanged`, `additions`, `deletions`, and a `diff` string built by concatenating the
  unified-diff `patch` of up to the first 5 changed files — this diff is later fed to
  `AnalysisAgent.generate_commit_summary`.
- Pull request fetching is wrapped in its own `try/except GithubException` so a PR-fetch
  failure (e.g. insufficient token scope) degrades to an empty PR list instead of failing
  the whole metadata fetch.

## `CodeChunker` — turning files into embeddable chunks

Constructor: `CodeChunker(max_chunk_chars=4000, overlap_chars=200)`.

### Python files: AST-based chunking

`_chunk_python_file` parses the file with `ast.parse` and, for each **top-level**
`ClassDef`/`FunctionDef`/`AsyncFunctionDef`, extracts the exact source lines (including
decorators, by scanning `decorator_list` for the earliest line) and emits one `Chunk` per
definition, tagged `chunk_type="class"` or `"function"`. If AST parsing fails (syntax error)
or the file has no top-level defs, it falls back to a single file-level chunk.

### Everything else: sliding-window chunking

`_chunk_generic_file` — if the whole file fits under `max_chunk_chars` it's a single chunk;
otherwise `_split_text_with_overlap` walks the text in `max_chunk_chars`-sized windows,
each overlapping the previous by `overlap_chars`, and — importantly — `_find_line_break_before`
snaps each window boundary back to the nearest newline so chunks don't split mid-line.

### Every chunk gets a file-path header

`_add_file_header` prepends `# File: <path>\n` to chunk content before it's embedded, so a
query mentioning a filename can retrieve the right chunk even when the code body itself never
repeats the filename.

### Oversized-chunk safety net

`_finalize_chunks` runs after either strategy: it logs size diagnostics (average/largest/top-10
chunks by size) and re-splits anything still over `max_chunk_chars` (e.g. one giant function)
using the same `_split_text_with_overlap` helper, tagging the result with
`parent_chunk_id`/`chunk_part`/`chunk_parts`/`split_from_oversized` metadata.

### Chunk IDs

`_generate_chunk_id` is a SHA-256 hash of `file_path + chunk_type + content (+ optional
part suffix)` — deterministic and stable across re-ingests of the same content, which is what
lets `GeminiService`'s checkpoint/resume logic recognize "this exact chunk is already embedded."

## `filter_chunks_for_embedding`

A one-function module (`services/ingestion.py`): drops any chunk whose `content` is empty or
whitespace-only (logging file/type/id for each), and raises `RuntimeError` if *every* chunk in
the batch was empty — since embedding an empty string is a hard API error, not something to
retry.

## `GeminiService` — embeddings and generation

### Rate limiting

`RateLimiter(max_rpm, max_tpm)` tracks `(timestamp, token_count)` tuples in a `deque` over a
trailing 60-second window. Before each batch request, `wait_if_needed(next_tokens)` sleeps
until both the request-count and token-count in the window are back under
`MAX_REQUESTS_PER_MINUTE` / `MAX_TOKENS_PER_MINUTE`. Token counts are estimated with
`estimate_tokens` (`len(text) // 4`, the standard "~4 chars per token" heuristic).

### Retrying and error classification

`_call_with_retry(func, *args, **kwargs)` wraps every Gemini SDK call. It inspects the
exception message/type to classify failures:

- **Invalid API key** → raises `InvalidAPIKeyError` immediately, no retry.
- **Hard quota exhausted** (message contains "exceeded your current quota" / "check your plan
  and billing") → raises `QuotaExhaustedError` immediately.
- **Rate limit (429, soft)** → shrinks `current_batch_size` by half, sleeps with exponential
  backoff + jitter, and retries up to `MAX_RETRIES` times before eventually raising
  `QuotaExhaustedError`.
- **Network failure** (connection/timeout/DNS-ish message) → same exponential backoff retry,
  raising `NetworkFailureError` after exhausting retries.
- Anything else is re-raised as-is.

### Single embeddings vs batch embeddings

- `generate_embedding(text, task_type="retrieval_query")` — one text → one vector. **Always
  called with `task_type="retrieval_query"` for search queries** and `"retrieval_document"`
  for anything being indexed; mixing these up is called out repeatedly in comments as the
  single most common cause of broken retrieval.
- `generate_embeddings_batch(texts, ...)` — the ingestion-time bulk path:
  1. **Checkpoint check**: if `repository`/`vector_store`/`embeddable_chunks` are available
     (either passed explicitly or recovered from the caller's stack frame via `inspect.stack()`
     — a pragmatic way to avoid threading three extra parameters through every call site), it
     queries ChromaDB for chunk IDs that already have embeddings and skips re-embedding them.
  2. **Deduplication**: identical chunk texts (by chunk ID) are only sent to the API once.
  3. **Batch construction**: groups remaining texts into sub-batches bounded by *three*
     independent limits — item count (`EMBED_BATCH_SIZE`), character count
     (`GEMINI_EMBEDDING_MAX_BATCH_CHARS`), and estimated tokens (`MAX_TOKENS_PER_BATCH`) —
     whichever limit is hit first closes the current batch.
  4. **Per-batch execution**: rate-limits via `RateLimiter.wait_if_needed`, calls
     `embed_content` with `task_type="retrieval_document"`, then **immediately writes that
     batch's embeddings to ChromaDB** (if a vector store was supplied) before moving to the
     next batch — so a mid-ingestion crash only loses the in-flight batch, not the whole job.
  5. **Adaptive batch size**: grows `current_batch_size` back toward the configured limit by
     1 after each success (and, per the retry logic above, halves it on a rate-limit hit).
  6. Sleeps `EMBED_BATCH_DELAY` seconds between batches.
  7. Reassembles the final embedding list in the caller's original order.

### Text generation

- `generate_content(prompt, system_instruction=None, model="gemini-2.5-flash")` — blocking,
  returns the full response text. Used for answer generation, reranking, and JSON summaries.
- `generate_content_stream(...)` — an **async generator**. The underlying `google-generativeai`
  SDK only exposes a *synchronous* streaming iterator, so this spins up a background thread
  (`threading.Thread`) that pushes each chunk's text into an `asyncio.Queue` via
  `loop.call_soon_threadsafe`, and the async generator just awaits and yields from that queue
  until a sentinel `done` object appears (or an exception is forwarded and re-raised).

## `VectorStoreManager` — ChromaDB wrapper

- `get_client()` lazily creates a `chromadb.PersistentClient(path=db_path, settings=Settings(allow_reset=True))`.
- `get_collection(name, extra_metadata=None)` — **always** creates/opens with
  `metadata={"hnsw:space": "cosine", **extra_metadata}`. `extra_metadata` (typically
  `{"repo_url": ...}`) only takes effect the first time a collection is created — Chroma
  ignores metadata on subsequent `get_or_create_collection` calls for an existing collection.
- `add_documents(collection_name, documents, embeddings, metadatas, ids, collection_metadata)` —
  validates all four lists are the same length, then calls `collection.add(...)`.
- `query_similarity(collection_name, query_embedding, top_k, where_metadata=None)` — wraps
  `collection.query(query_embeddings=[embedding], n_results=top_k, where=where_metadata)` and
  flattens Chroma's `{ids: [[...]], documents: [[...]], ...}` (one list-of-lists per query)
  into a flat list of `{id, document, distance, metadata}` dicts.
- `sample_documents(collection_name, limit=20)` — a plain `collection.get(limit=...)`, no
  similarity search — used only to pull representative chunks for the repository-overview
  prompt.
- `reset_collection(name)` — deletes a collection; swallows "not found" errors as a no-op
  (idempotent), re-raises anything else.
- `list_collections()` — enumerates every collection with its `repo_url` metadata and
  `.count()`, which is what powers the frontend's "already indexed repositories" picker.

## Putting it together: what `POST /ingest` actually does

The route handler (`backend/src/api/routes.py::ingest_repository`) is the orchestration glue
for all of the above, executed as six explicitly-logged, individually-timed steps:

1. **Clone + scan** — `github_service.fetch_repo_files(repo_url)` (run in a thread pool since
   it's blocking I/O/subprocess work inside an async route).
2. **Chunk** — every file → `chunker.chunk_file()` → `filter_chunks_for_embedding()`.
3. **Embed** — `gemini_service.generate_embeddings_batch(texts)`.
4. **Persist** — `vector_store.reset_collection(repo)` (wipe any prior ingest of the same repo
   name) then `add_documents(...)`.
5. **Fetch GitHub metadata** — `github_service.fetch_repository_context(repo_url, files=files)`
   (reuses the file list from step 1, no second clone).
6. **Generate the AI overview** — sample 20 chunks, call
   `analysis_agent.generate_repository_overview(...)`, and merge `ai_summary` /
   `detected_technologies` / `suggested_questions` into the metadata dict. This step is
   wrapped in its own `try/except` that only logs a warning on failure — a broken overview
   should never fail the whole ingestion.
7. **Activate** — `set_active_repository(repo)` + `set_active_repository_context({...})`,
   making this repo the one `/query` operates against.

Every step raises a distinct HTTP status on failure (400 for bad URLs, 502 for
GitHub/Gemini upstream failures, 500 for internal chunking/storage errors), and repository
name collisions are resolved by deriving the collection name from the URL's last path segment
(`collection_name_from_repo_url`, sanitized to `[a-zA-Z0-9_-]`, max 60 chars) — re-ingesting the
same URL overwrites the same collection rather than creating a duplicate.
