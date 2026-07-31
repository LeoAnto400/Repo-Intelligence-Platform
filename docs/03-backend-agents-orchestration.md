# 03 — Backend: Agents & Orchestration

Files:

- `backend/src/agents/base.py` — `BaseAgent`
- `backend/src/agents/retrieval.py` — `RetrievalAgent`
- `backend/src/agents/analysis.py` — `AnalysisAgent`
- `backend/src/agents/orchestrator.py` — `Orchestrator`

## `BaseAgent`

A one-method abstract base class every agent implements:

```python
class BaseAgent(ABC):
    @abstractmethod
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...
```

The contract is deliberately loose (dict in, dict out) rather than agent-specific typed
signatures — it's what lets `Orchestrator` call `retrieval_agent.process(...)` and
`analysis_agent.process(...)` polymorphically, and it's also what the API layer's
`ActiveRepositoryRetrievalAgent` adapter (see [04-backend-api-layer.md](04-backend-api-layer.md))
wraps to inject the currently-active repository without `RetrievalAgent` itself needing to know
where that state lives.

## `RetrievalAgent`

### Pipeline

1. **Validate payload** — requires `query` (non-empty string) and `repository_id`
   (non-empty string); `top_k`/`final_k` are optional and parsed defensively
   (`_parse_positive_int` falls back to the configured default on anything non-positive or
   unparseable, logging a warning rather than raising). `final_k` is clamped to never exceed
   `top_k`.
2. **Embed the query** — `gemini_service.generate_embedding(query, task_type="retrieval_query")`.
   This task type is mandatory and different from the `"retrieval_document"` type used at
   ingestion time — see [02-backend-ingestion-pipeline.md](02-backend-ingestion-pipeline.md).
3. **ANN search** — `vector_store.query_similarity(collection_name=repository_id, query_embedding=embedding, top_k=top_k)`,
   default `top_k = settings.RETRIEVAL_TOP_K` (20). Results are mapped from raw Chroma dicts
   into `RetrievalResult` domain objects (`chunk_id`, `file_path`, `content`, `score` = cosine
   distance, `metadata`).
4. **Rerank** (`_rerank`) — see below. Returns the top `final_k` (default `RETRIEVAL_FINAL_K` = 5).

`process(payload)` is the `BaseAgent`-compliant entrypoint; it catches all exceptions and
returns `{"results": [], "error": "..."}` rather than raising, so a retrieval failure surfaces
as a structured error the orchestrator can inspect instead of an unhandled exception.

### Reranking (`_rerank`)

If there are already `<= final_k` candidates, reranking is skipped (nothing to reorder).
Otherwise:

1. Build a numbered, truncated (800 chars each) listing of every candidate: `"[idx] file=<path>\n<preview>"`.
2. Send **one** Gemini prompt containing the query and the full candidate listing, asking for
   a JSON array of indices ordered most→least relevant, with an explicit instruction to
   respond with *only* the JSON array (no markdown fences, no commentary).
3. Parse the response: strip any accidental ` ``` ` fences, `json.loads` it, validate it's a
   list, deduplicate indices while preserving order, drop out-of-range indices, and append any
   candidate the model omitted (so nothing silently disappears).
4. Return the top `final_k` from that reordered list.
5. **On any failure** (bad JSON, API error, etc.) — log a warning and fall back to
   `candidates[:final_k]`, the raw ANN ordering. Reranking can never fail the whole query.

## `AnalysisAgent`

### Answer generation

`process(payload)` accepts `question` (or `query`), and retrieval results under any of
`retrieval_results` / `retrieved_context` / `results` (defensive key aliasing for different
callers), plus optional `history`. It normalizes inputs (`_normalize_retrieval_results` accepts
either `RetrievalResult` objects or plain dicts — useful since the payload may come from JSON
over the wire) and calls `generate_analysis`.

`generate_analysis` / `stream_analysis` both:

1. Build a **context block** (`_build_context_block`) — one section per chunk, formatted as:
   ```
   [Chunk 1] | file=src/foo.py:10-42 | type=function | name=do_thing
   <chunk content>
   ```
2. Build the **prompt** (`_build_prompt`):
   ```
   You are a senior software engineer.

   Answer the user's question using ONLY the provided repository context.

   If the answer cannot be determined from the context, say so.

   [optional conversation-history section]
   Repository Context:
   <context block>

   Question:
   <question>
   ```
3. Call Gemini — `generate_content` (blocking, for `process`/`generate_analysis`) or
   `generate_content_stream` (for `stream_analysis`, yielding `{"type": "token", "text": ...}`
   events and a final `{"type": "done", "answer": ..., "source_files": ..., "chunk_count": ...}`).
4. Collect `source_files` — the ordered, de-duplicated list of `file_path`s across all
   retrieved chunks (`_source_files`).

### Conversation history handling

`_build_history_block` takes at most the last `MAX_HISTORY_MESSAGES = 8` turns, truncates each
turn's content to `MAX_HISTORY_MESSAGE_CHARS = 1500` characters (appending `...`), and labels
turns `Assistant:`/`Developer:`. The prompt explicitly instructs the model that history is only
for resolving references (pronouns like "it") in the new question — **the repository context
block remains the sole source of factual truth for the answer**, so old conversation turns
can't leak stale or hallucinated "facts" into a new answer.

### Repository overview generation

`generate_repository_overview(repository, chunk_samples)` — used right after ingestion (and on
`/repositories/{name}/select`) to produce the dashboard's AI summary:

1. `_build_overview_prompt` takes up to 12 distinct-file chunk samples (800 chars each) and
   asks Gemini for a strict JSON object:
   ```json
   {
     "summary": "2-4 sentence plain-English description",
     "technologies": ["..."],
     "suggested_questions": ["... up to 4 ..."]
   }
   ```
2. `_parse_overview_response` finds the outermost `{...}` in the raw response (tolerant of
   stray text around the JSON), parses it, and defensively coerces each field back to its
   expected type — returning an all-empty fallback (`{"summary": None, "technologies": [],
   "suggested_questions": []}`) on any parse failure rather than raising.

This method works from **vector-store content alone** (chunk samples, not the original clone),
which is why re-activating a previously-ingested repository via `/repositories/{name}/select`
can regenerate a fresh overview even without the original GitHub URL being available.

### Commit summaries

`generate_commit_summary(commit)` builds a prompt from the commit's author/message/diff
(already captured at ingestion time by `GitHubService._commit_to_dict`, so this needs no
additional GitHub API calls) and asks for a 2-4 sentence plain-English summary. If no diff was
captured, the prompt tells the model to summarize from the message alone and say so.

## `Orchestrator`

### `process()` — LangGraph state machine

```python
class AgentState(TypedDict):
    question: str
    history: List[Dict[str, Any]]
    retrieval_results: List[Dict[str, Any]]
    analysis_result: Optional[Dict[str, Any]]
    error: Optional[str]
```

`compile_workflow_graph()` builds a two-node `StateGraph(AgentState)`:

```python
graph.add_node("retrieve", self.retrieval_node)
graph.add_node("analyze", self.analysis_node)
graph.add_edge(START, "retrieve")
graph.add_edge("retrieve", "analyze")
graph.add_edge("analyze", END)
```

`process(question, history=None)`:

1. Validates `question` is non-empty (raises `ValueError` immediately otherwise — before ever
   touching the graph).
2. Builds the initial `AgentState` and runs `self._compiled_graph.ainvoke(state)`.
3. `retrieval_node` calls `RetrievalAgent.process`; if the agent returns an `error` key, the
   node raises `RuntimeError` (LangGraph propagates node exceptions up through `ainvoke`).
4. `analysis_node` calls `AnalysisAgent.process` with the retrieval results and history from
   state; same error-propagation pattern.
5. After the graph completes, `process()` re-checks `final_state["error"]` and re-validates
   that `analysis_result` is a well-formed dict, raising `RuntimeError` if anything is off —
   belt-and-suspenders on top of the node-level checks.
6. Returns an `OrchestratorResult(answer, source_files, retrieved_chunks)`.

`self.last_state` is kept as an instance attribute purely for debugging/observability (e.g. so
an exception handler can surface the last known state's error message even if the exception
itself came from deep inside LangGraph's `ainvoke`).

### `stream()` — bypasses the compiled graph

```python
async def stream(self, question, history=None) -> AsyncIterator[Dict[str, Any]]:
    ...
    retrieval_response = await self.retrieval_agent.process({"query": normalized_question})
    ...
    yield {"type": "retrieval", "retrieved_chunks": len(retrieval_results)}
    async for event in self.analysis_agent.stream_analysis(normalized_question, retrieval_results, history):
        yield event
```

Retrieval has no incremental output worth streaming (it's one ANN query + one rerank call), so
it runs to completion up front and emits a single `retrieval` event with the count. Then it
delegates directly to `AnalysisAgent.stream_analysis`, forwarding its `token`/`done` events
as-is. This is why `stream()` doesn't go through `compile_workflow_graph()` at all — LangGraph
nodes return complete state, which can't express "yield a token every time the LLM produces
one."

### Error contract

Both `process()` and `stream()` raise `ValueError` for an empty/invalid question (→ HTTP 400 at
the API layer) and `RuntimeError` for any downstream agent failure (→ HTTP 500), which is what
lets `routes.py` map orchestrator exceptions to the correct status codes without inspecting
error message strings.
