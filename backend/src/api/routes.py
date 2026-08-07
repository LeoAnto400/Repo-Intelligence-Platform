import json
import logging
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from starlette.concurrency import run_in_threadpool

from src.agents.analysis import AnalysisAgent
from src.agents.orchestrator import Orchestrator
from src.agents.retrieval import RetrievalAgent
from src.api.schemas import (
    CommitSummaryResponse,
    DeleteRepositoryResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    RepositoryContextResponse,
    RepositorySummary,
)
from src.core.config import settings
from src.core.rate_limit import InMemoryRateLimiter
from src.db.chroma import VectorStoreManager
from src.services.chunker import CodeChunker, CodeFile
from src.services.gemini import GeminiService
from src.services.github import GitHubService
from src.services.ingestion import filter_chunks_for_embedding

logger = logging.getLogger(__name__)

router = APIRouter()
_active_repository: Optional[str] = None
_active_repository_context: Optional[Dict[str, Any]] = None

_ingest_rate_limiter = InMemoryRateLimiter(
    max_requests=settings.INGEST_RATE_LIMIT_PER_MINUTE, window_seconds=60.0
)
_query_rate_limiter = InMemoryRateLimiter(
    max_requests=settings.QUERY_RATE_LIMIT_PER_MINUTE, window_seconds=60.0
)
_QUERY_RATE_LIMIT_MESSAGE = "Too many query requests. Please slow down and try again shortly."


def _client_key(client: Optional[Any]) -> str:
    return client.host if client else "unknown"


def enforce_ingest_rate_limit(request: Request) -> None:
    if not _ingest_rate_limiter.allow(_client_key(request.client)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many ingestion requests. Please wait a minute before trying again.",
        )


def enforce_query_rate_limit(request: Request) -> None:
    if not _query_rate_limiter.allow(_client_key(request.client)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_QUERY_RATE_LIMIT_MESSAGE,
        )


def _normalize_history(raw: Any) -> List[Dict[str, str]]:
    """Sanitizes a client-supplied conversation history (REST body or raw
    websocket JSON) into a plain ``[{"role": ..., "content": ...}]`` list,
    dropping anything malformed rather than rejecting the whole request."""
    if not isinstance(raw, list):
        return []

    normalized: List[Dict[str, str]] = []
    for turn in raw:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if not isinstance(role, str) or not isinstance(content, str) or not content.strip():
            continue
        normalized.append({"role": role, "content": content})
    return normalized


class _TaggedLogAdapter(logging.LoggerAdapter):
    """Prefixes every log line with a short request-correlation tag, e.g.
    ``[ingest:3f9a2c1d]``, so every step of a single request can be grepped
    out of interleaved server logs even when requests overlap."""

    def process(self, msg, kwargs):
        return f"[{self.extra['tag']}] {msg}", kwargs


def _build_chunks(files: List[Dict[str, Any]], chunker: CodeChunker, repository: str) -> List:
    chunks = []
    for file_info in files:
        code_file = CodeFile(
            file_path=file_info["path"],
            content=file_info["content"],
            language=file_info["language"],
            metadata={"repository_id": repository},
        )
        chunks.extend(chunker.chunk_file(code_file))
    return chunks


def _store_chunks(
    vector_store: VectorStoreManager,
    repository: str,
    repo_url: str,
    documents: List[str],
    embeddings: List[List[float]],
    metadatas: List[Dict[str, Any]],
    ids: List[str],
) -> None:
    vector_store.reset_collection(repository)
    vector_store.add_documents(
        collection_name=repository,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids,
        collection_metadata={"repo_url": repo_url},
    )


def collection_name_from_repo_url(repo_url: str) -> str:
    repo_name_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_url.rstrip("/").split("/")[-1])
    repo_name_clean = re.sub(r"_+", "_", repo_name_clean).strip("_")
    if len(repo_name_clean) < 3:
        repo_name_clean = "repo_collection"
    return repo_name_clean[:60]


def validate_repo_url(repo_url: str) -> None:
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.path.strip("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid repository URL.",
        )


def set_active_repository(repository: Optional[str]) -> None:
    global _active_repository
    _active_repository = repository


def get_active_repository() -> Optional[str]:
    return _active_repository


def set_active_repository_context(context: Optional[Dict[str, Any]]) -> None:
    global _active_repository_context
    _active_repository_context = context


def get_active_repository_context() -> Optional[Dict[str, Any]]:
    return _active_repository_context


def _commits_store_dir() -> Path:
    """Directory where each repository's commit history is persisted as a
    JSON sidecar, so it survives past the in-memory active-repository-context
    (which is lost on restart or when another repo is activated) without
    needing a live GitHub API call every time a repo is reactivated."""
    directory = Path(settings.CHROMA_DB_DIR).parent / "repo_commits"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _commits_file(repository: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repository)
    return _commits_store_dir() / f"{safe_name}.json"


def save_commit_history(repository: str, commits: List[Dict[str, Any]]) -> None:
    try:
        _commits_file(repository).write_text(json.dumps(commits), encoding="utf-8")
    except Exception:
        logger.exception("Failed to persist commit history for %s", repository)


def load_commit_history(repository: str) -> List[Dict[str, Any]]:
    path = _commits_file(repository)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load persisted commit history for %s", repository)
        return []


def delete_commit_history(repository: str) -> None:
    path = _commits_file(repository)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        logger.exception("Failed to delete persisted commit history for %s", repository)


@lru_cache(maxsize=1)
def get_github_service() -> GitHubService:
    return GitHubService(token=settings.GITHUB_TOKEN)


@lru_cache(maxsize=1)
def get_chunker() -> CodeChunker:
    return CodeChunker()


@lru_cache(maxsize=1)
def get_gemini_service() -> GeminiService:
    return GeminiService()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStoreManager:
    return VectorStoreManager(db_path=settings.CHROMA_DB_DIR)


@lru_cache(maxsize=1)
def get_retrieval_agent() -> RetrievalAgent:
    return RetrievalAgent(
        vector_store=get_vector_store(),
        gemini_service=get_gemini_service(),
    )


@lru_cache(maxsize=1)
def get_analysis_agent() -> AnalysisAgent:
    return AnalysisAgent(gemini_service=get_gemini_service())


class ActiveRepositoryRetrievalAgent:
    """
    API-layer adapter that supplies the current ingested repository to RetrievalAgent.
    """

    def __init__(self, retrieval_agent: RetrievalAgent):
        self.retrieval_agent = retrieval_agent

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        repository = get_active_repository()
        if not repository:
            return {
                "results": [],
                "error": "No repository has been ingested yet.",
            }

        scoped_payload = dict(payload)
        scoped_payload.setdefault("repository_id", repository)
        return await self.retrieval_agent.process(scoped_payload)


@lru_cache(maxsize=1)
def get_orchestrator() -> Orchestrator:
    return Orchestrator(
        retrieval_agent=ActiveRepositoryRetrievalAgent(get_retrieval_agent()),
        analysis_agent=get_analysis_agent(),
    )


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_200_OK)
async def ingest_repository(
    payload: IngestRequest,
    github_service: GitHubService = Depends(get_github_service),
    chunker: CodeChunker = Depends(get_chunker),
    gemini_service: GeminiService = Depends(get_gemini_service),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    analysis_agent: AnalysisAgent = Depends(get_analysis_agent),
    _rate_limit: None = Depends(enforce_ingest_rate_limit),
) -> IngestResponse:
    ingestion_id = uuid.uuid4().hex[:8]
    log = _TaggedLogAdapter(logger, {"tag": f"ingest:{ingestion_id}"})
    request_start = time.perf_counter()

    repo_url = payload.repo_url.strip() if payload.repo_url else ""
    validate_repo_url(repo_url)
    repository = collection_name_from_repo_url(repo_url)

    log.info("Ingestion start: repo_url=%s repository=%s", repo_url, repository)

    # ── Step 1: Clone + scan the repository (also captures commit history
    # locally via `git log`, so the commits tab works without a live GitHub
    # API call) ────────────────────────────────────────────────────────────
    step_start = time.perf_counter()
    try:
        files, local_commits = await run_in_threadpool(
            github_service.fetch_repo_files_and_commits, repo_url
        )
    except ValueError as e:
        log.exception("Invalid repository URL during ingestion")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid repository URL: {e}",
        ) from e
    except Exception as e:
        log.exception("Repository clone/read failed during ingestion")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Repository clone/read failed: {e}",
        ) from e

    if not files:
        log.error("Repository ingestion produced no readable files")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No supported files were found in the repository.",
        )
    log.info(
        "Clone/scan complete: %d files in %.2fs", len(files), time.perf_counter() - step_start
    )

    # ── Step 2: Chunk every file ─────────────────────────────────────────
    step_start = time.perf_counter()
    try:
        all_chunks = await run_in_threadpool(_build_chunks, files, chunker, repository)
        embeddable_chunks = filter_chunks_for_embedding(all_chunks)
        if not embeddable_chunks:
            raise RuntimeError("No embeddable chunks were created from repository files.")
    except Exception as e:
        log.exception("Chunking failed during ingestion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Repository chunking failed: {e}",
        ) from e
    log.info(
        "Chunking complete: %d chunks (from %d raw) in %.2fs",
        len(embeddable_chunks), len(all_chunks), time.perf_counter() - step_start
    )

    # ── Step 3: Generate embeddings via Gemini ───────────────────────────
    step_start = time.perf_counter()
    try:
        texts = [chunk.content for chunk in embeddable_chunks]
        embeddings = await run_in_threadpool(gemini_service.generate_embeddings_batch, texts)
    except Exception as e:
        log.exception("Embedding generation failed during ingestion")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Embedding generation failed: {e}",
        ) from e
    log.info(
        "Embedding generation complete: %d vectors in %.2fs",
        len(embeddings), time.perf_counter() - step_start
    )

    documents = [chunk.content for chunk in embeddable_chunks]
    ids = [chunk.chunk_id for chunk in embeddable_chunks]
    metadatas: List[Dict[str, Any]] = []
    for chunk in embeddable_chunks:
        metadata = dict(chunk.metadata)
        metadata["file_path"] = chunk.file_path
        metadata["chunk_type"] = chunk.chunk_type
        metadatas.append(metadata)

    # ── Step 4: Persist to ChromaDB ───────────────────────────────────────
    step_start = time.perf_counter()
    try:
        await run_in_threadpool(
            _store_chunks, vector_store, repository, repo_url, documents, embeddings, metadatas, ids
        )
    except Exception as e:
        log.exception("ChromaDB storage failed during ingestion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ChromaDB storage failed: {e}",
        ) from e
    log.info("ChromaDB storage complete in %.2fs", time.perf_counter() - step_start)

    # ── Step 5: Fetch repository metadata/PRs for the dashboard from the
    # GitHub API. This is now best-effort: commit history no longer depends
    # on it (see local_commits from Step 1), so a GitHub API failure (rate
    # limit, non-github.com host, network) no longer fails the whole
    # ingestion — it only means stars/forks/description stay empty. ───────
    step_start = time.perf_counter()
    try:
        repository_context = await run_in_threadpool(
            github_service.fetch_repository_context, repo_url, files=files
        )
    except Exception as e:
        log.warning("GitHub repository metadata fetch failed, continuing with local data only: %s", e)
        repository_context = {"metadata": {}, "files": files, "commits": [], "pull_requests": []}
    log.info("Repository metadata fetch complete in %.2fs", time.perf_counter() - step_start)

    # Prefer commit history captured locally during clone/scan (Step 1) — it
    # works for any git host and doesn't depend on a live GitHub API call.
    if local_commits:
        repository_context["commits"] = local_commits
    await run_in_threadpool(save_commit_history, repository, repository_context.get("commits") or [])

    # ── Step 5.5: Generate an AI summary, detected technologies, and
    # suggested questions from the freshly ingested chunks ────────────────
    step_start = time.perf_counter()
    try:
        samples = await run_in_threadpool(vector_store.sample_documents, repository, 20)
        overview = await analysis_agent.generate_repository_overview(repository, samples)
        repository_context["metadata"] = {
            **repository_context.get("metadata", {}),
            "ai_summary": overview.get("summary"),
            "detected_technologies": overview.get("technologies", []),
            "suggested_questions": overview.get("suggested_questions", []),
        }
    except Exception as e:
        log.warning("Repository overview generation failed, continuing without it: %s", e)
    log.info("Repository overview generation complete in %.2fs", time.perf_counter() - step_start)

    # ── Step 6: Activate the ingested repository for /query and /repository ──
    try:
        set_active_repository(repository)
        set_active_repository_context(
            {
                "repository": repository,
                "repo_url": repo_url,
                **repository_context,
            }
        )
    except Exception as e:
        log.exception("Failed to activate ingested repository")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate ingested repository: {e}",
        ) from e

    log.info(
        "Ingestion complete: files_processed=%d chunks_created=%d total_time=%.2fs",
        len(files), len(embeddable_chunks), time.perf_counter() - request_start,
    )
    return IngestResponse(
        status="success",
        repository=repository,
        files_processed=len(files),
        chunks_created=len(embeddable_chunks),
        repo_url=repo_url,
    )


@router.get("/repository", response_model=RepositoryContextResponse)
async def get_repository_context() -> RepositoryContextResponse:
    context = get_active_repository_context()
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository has been ingested yet.",
        )

    return RepositoryContextResponse(**context)


@router.get("/repositories", response_model=List[RepositorySummary])
async def list_repositories(
    vector_store: VectorStoreManager = Depends(get_vector_store),
) -> List[RepositorySummary]:
    """Lists every repository already indexed in the vector store, so the
    frontend can offer to reactivate one instead of re-ingesting it."""
    collections = await run_in_threadpool(vector_store.list_collections)
    return [
        RepositorySummary(
            repository=item["name"],
            repo_url=item["repo_url"],
            chunk_count=item["chunk_count"],
        )
        for item in collections
    ]


@router.delete("/repositories/{repository}", response_model=DeleteRepositoryResponse)
async def delete_repository(
    repository: str,
    vector_store: VectorStoreManager = Depends(get_vector_store),
) -> DeleteRepositoryResponse:
    """Deletes a previously ingested repository's vector collection. If the
    deleted repository was the active one, clears the active selection too
    so /query and /repository correctly report that nothing is active."""
    delete_id = uuid.uuid4().hex[:8]
    log = _TaggedLogAdapter(logger, {"tag": f"delete:{delete_id}"})

    collections = await run_in_threadpool(vector_store.list_collections)
    match = next((item for item in collections if item["name"] == repository), None)
    if match is None:
        log.error("Repository not found for deletion: %s", repository)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repository}' has not been ingested.",
        )

    try:
        await run_in_threadpool(vector_store.reset_collection, repository)
    except Exception as e:
        log.exception("Failed to delete repository: %s", repository)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete repository: {e}",
        ) from e

    if get_active_repository() == repository:
        set_active_repository(None)
        set_active_repository_context(None)
        log.info("Cleared active repository after deletion: %s", repository)

    delete_commit_history(repository)
    log.info("Repository deleted: %s", repository)
    return DeleteRepositoryResponse(repository=repository, status="deleted")


@router.post("/repositories/{repository}/select", response_model=RepositoryContextResponse)
async def select_repository(
    repository: str,
    vector_store: VectorStoreManager = Depends(get_vector_store),
    github_service: GitHubService = Depends(get_github_service),
    analysis_agent: AnalysisAgent = Depends(get_analysis_agent),
) -> RepositoryContextResponse:
    """Activates a previously ingested repository for /query without re-cloning
    or re-embedding it. Repository metadata (stars, commits, PRs) is refreshed
    live from GitHub when the repo's URL was recorded at ingestion time; the
    AI summary/technologies/suggested questions are regenerated from the
    already-ingested chunks either way, so this works even for repositories
    activated without a known GitHub URL. The repository is still activated
    for chat even if either refresh fails."""
    select_id = uuid.uuid4().hex[:8]
    log = _TaggedLogAdapter(logger, {"tag": f"select:{select_id}"})

    collections = await run_in_threadpool(vector_store.list_collections)
    match = next((item for item in collections if item["name"] == repository), None)
    if match is None:
        log.error("Selected repository not found in vector store: %s", repository)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repository}' has not been ingested.",
        )

    repo_url = match["repo_url"]
    context: Dict[str, Any] = {
        "repository": repository,
        "repo_url": repo_url or "",
        "metadata": {},
        "files": [],
        "commits": [],
        "pull_requests": [],
    }

    if repo_url:
        try:
            fetched = await run_in_threadpool(
                github_service.fetch_repository_context, repo_url, files=[]
            )
            context.update(fetched)
        except Exception as e:
            log.warning(
                "Metadata refresh failed for %s, activating with minimal context: %s", repo_url, e
            )

    # Commit history captured locally at ingestion time (see save_commit_history
    # in /ingest) is the reliable source here — it doesn't need a repo_url or a
    # live GitHub call, so it also covers repositories ingested before that URL
    # was recorded. Prefer it over whatever the live GitHub refresh above returned.
    persisted_commits = await run_in_threadpool(load_commit_history, repository)
    if persisted_commits:
        context["commits"] = persisted_commits

    try:
        samples = await run_in_threadpool(vector_store.sample_documents, repository, 20)
        overview = await analysis_agent.generate_repository_overview(repository, samples)
        context["metadata"] = {
            **context.get("metadata", {}),
            "ai_summary": overview.get("summary"),
            "detected_technologies": overview.get("technologies", []),
            "suggested_questions": overview.get("suggested_questions", []),
        }
    except Exception as e:
        log.warning("Repository overview generation failed for %s: %s", repository, e)

    set_active_repository(repository)
    set_active_repository_context(context)
    log.info("Activated repository: %s", repository)

    return RepositoryContextResponse(**context)


@router.post("/commits/{commit_hash}/summary", response_model=CommitSummaryResponse)
async def summarize_commit(
    commit_hash: str,
    analysis_agent: AnalysisAgent = Depends(get_analysis_agent),
) -> CommitSummaryResponse:
    """Generates an AI summary of a single commit belonging to the active
    repository, using the message/diff already captured at ingestion time."""
    summary_id = uuid.uuid4().hex[:8]
    log = _TaggedLogAdapter(logger, {"tag": f"commit-summary:{summary_id}"})

    context = get_active_repository_context()
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository has been ingested yet.",
        )

    commits = context.get("commits") or []
    commit = next((c for c in commits if c.get("hash") == commit_hash), None)
    if commit is None:
        log.error("Commit not found in active repository: %s", commit_hash)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commit '{commit_hash}' was not found in the active repository's recent commits.",
        )

    try:
        summary = await analysis_agent.generate_commit_summary(commit)
    except Exception as e:
        log.exception("Commit summary generation failed for %s", commit_hash)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate commit summary: {e}",
        ) from e

    log.info("Commit summary generated for %s", commit_hash)
    return CommitSummaryResponse(hash=commit_hash, summary=summary)


@router.post("/query", response_model=QueryResponse)
async def query_repository(
    payload: QueryRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    _rate_limit: None = Depends(enforce_query_rate_limit),
) -> QueryResponse:
    query_id = uuid.uuid4().hex[:8]
    log = _TaggedLogAdapter(logger, {"tag": f"query:{query_id}"})
    request_start = time.perf_counter()

    question = payload.question.strip() if payload.question else ""
    history = [{"role": turn.role, "content": turn.content} for turn in payload.history]
    log.info("Query start: question=%r history_length=%d", question, len(history))

    if not question:
        log.error("Query rejected because question was empty")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )

    try:
        result = await orchestrator.process(question, history=history)
    except ValueError as e:
        log.exception("Invalid query request")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        log.exception("Query orchestration failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    except Exception as e:
        log.exception("Unexpected query failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {e}",
        ) from e

    log.info(
        "Query complete: retrieved_chunks=%d total_time=%.2fs",
        result.retrieved_chunks, time.perf_counter() - request_start,
    )
    return QueryResponse(
        answer=result.answer,
        source_files=result.source_files,
        retrieved_chunks=result.retrieved_chunks,
    )


@router.websocket("/ws/query")
async def query_repository_ws(
    websocket: WebSocket,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> None:
    """
    Streaming counterpart to POST /query. Accepts a persistent connection and,
    for each ``{"question": "..."}`` message received, streams back:
      - one ``{"type": "retrieval", "retrieved_chunks": N}`` event,
      - a series of ``{"type": "token", "text": "..."}`` events as the answer
        is generated,
      - a final ``{"type": "done", "answer": ..., "source_files": ...,
        "chunk_count": ...}`` event,
    or a ``{"type": "error", "detail": "..."}`` event on failure. The
    connection stays open across multiple questions until the client
    disconnects.
    """
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            question = (payload.get("question") or "").strip() if isinstance(payload, dict) else ""
            history = _normalize_history(payload.get("history") if isinstance(payload, dict) else None)

            if not question:
                await websocket.send_json({"type": "error", "detail": "Question cannot be empty."})
                continue

            if not _query_rate_limiter.allow(_client_key(websocket.client)):
                await websocket.send_json({"type": "error", "detail": _QUERY_RATE_LIMIT_MESSAGE})
                continue

            query_id = uuid.uuid4().hex[:8]
            log = _TaggedLogAdapter(logger, {"tag": f"query-ws:{query_id}"})
            request_start = time.perf_counter()
            log.info("Query start: question=%r history_length=%d", question, len(history))

            try:
                async for event in orchestrator.stream(question, history=history):
                    await websocket.send_json(event)
                log.info("Query complete: total_time=%.2fs", time.perf_counter() - request_start)
            except (ValueError, RuntimeError) as e:
                log.exception("Query streaming failed")
                await websocket.send_json({"type": "error", "detail": str(e)})
            except Exception as e:
                log.exception("Unexpected query streaming failure")
                await websocket.send_json({"type": "error", "detail": f"Query failed: {e}"})
    except WebSocketDisconnect:
        logger.info("Query websocket disconnected")
