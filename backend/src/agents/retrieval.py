import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from src.agents.base import BaseAgent
from src.db.chroma import VectorStoreManager
from src.services.gemini import GeminiService
from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """
    Domain model representing a retrieved code chunk with similarity score and metadata.
    Does not expose database-specific client models to the outside.
    """
    chunk_id: str
    file_path: str
    content: str
    score: float
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the RetrievalResult domain model instance into a standard dictionary.
        """
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata
        }


class RetrievalAgent(BaseAgent):
    """
    RetrievalAgent locates and extracts relevant code segments from ChromaDB
    using embeddings matching via the Gemini Embeddings API, followed by an
    optional Gemini-powered reranking step that filters the ANN candidates down
    to the most relevant chunks before they are passed to the analysis agent.

    Retrieval pipeline
    ------------------
    1. Embed the query with ``task_type="retrieval_query"`` (critical: must be
       different from the ``"retrieval_document"`` type used during ingestion).
    2. Fetch ``top_k`` (default: 20) ANN candidates from ChromaDB.
    3. Rerank those candidates with a single batched Gemini prompt.
    4. Return the top ``final_k`` (default: 5) reranked results.
    """

    def __init__(
        self,
        vector_store: VectorStoreManager,
        gemini_service: GeminiService,
        default_top_k: int = settings.RETRIEVAL_TOP_K,
        default_final_k: int = settings.RETRIEVAL_FINAL_K,
    ):
        """
        Initialize RetrievalAgent with dependencies.

        Args:
            vector_store: Instantiated vector database manager client wrapper.
            gemini_service: Instantiated service wrapper for calculating query embeddings.
            default_top_k: Number of ANN candidates to fetch from ChromaDB.
            default_final_k: Number of reranked results to return to the caller.
        """
        self.vector_store = vector_store
        self.gemini_service = gemini_service
        self.default_top_k = default_top_k
        self.default_final_k = default_final_k
        logger.info(
            "RetrievalAgent initialized with default_top_k=%d, default_final_k=%d",
            default_top_k,
            default_final_k,
        )

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query database and return relevant snippets as a structured dictionary.

        Expected payload format::

            {
                "query": str,
                "repository_id": str,
                "top_k": Optional[int],   # ANN candidates (default: RETRIEVAL_TOP_K)
                "final_k": Optional[int]  # reranked results (default: RETRIEVAL_FINAL_K)
            }

        Returns:
            Dict containing retrieved snippets (mapped to dictionary format) and
            status/error details.
        """
        logger.info("Processing retrieval agent task.")

        query = payload.get("query")
        repository_id = payload.get("repository_id")
        top_k = payload.get("top_k")
        final_k = payload.get("final_k")

        # Payload validation
        if not query or not isinstance(query, str) or not query.strip():
            logger.error("Missing or invalid 'query' parameter in retrieval payload.")
            return {"results": [], "error": "Required field 'query' is missing or empty."}
        if not repository_id or not isinstance(repository_id, str) or not repository_id.strip():
            logger.error("Missing or invalid 'repository_id' parameter in retrieval payload.")
            return {"results": [], "error": "Required field 'repository_id' is missing or empty."}

        # Parse and validate top_k
        top_k_val = self._parse_positive_int(top_k, self.default_top_k, "top_k")
        final_k_val = self._parse_positive_int(final_k, self.default_final_k, "final_k")

        # final_k must not exceed the number of candidates we fetch
        final_k_val = min(final_k_val, top_k_val)

        try:
            logger.debug(
                "Executing retrieve_snippets for repository_id: %s, top_k: %d, final_k: %d",
                repository_id,
                top_k_val,
                final_k_val,
            )
            retrieved_objects = await self.retrieve_snippets(
                query=query.strip(),
                repository_id=repository_id.strip(),
                top_k=top_k_val,
                final_k=final_k_val,
            )

            if not retrieved_objects:
                logger.info(
                    "No matching snippets retrieved for query: '%s' in repository_id: '%s'",
                    query,
                    repository_id,
                )

            serialized_results = [obj.to_dict() for obj in retrieved_objects]
            return {"results": serialized_results, "error": None}

        except Exception as e:
            logger.exception("An exception occurred during retrieval process execution")
            return {"results": [], "error": f"Retrieval failed: {str(e)}"}

    async def retrieve_snippets(
        self,
        query: str,
        repository_id: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        final_k: int = settings.RETRIEVAL_FINAL_K,
    ) -> List[RetrievalResult]:
        """
        Internal retrieval helper: embed → ANN search → rerank → return top results.

        Args:
            query: User search query.
            repository_id: Active collection/repository to filter on.
            top_k: Number of ANN candidates to fetch from ChromaDB.
            final_k: Number of reranked results to return.

        Returns:
            List of matching document blocks wrapped as RetrievalResult domain models.
        """
        logger.info(
            "Starting snippet retrieval for query '%s' against repository '%s'",
            query,
            repository_id,
        )

        # ── Step 1: Generate a QUERY embedding ───────────────────────────────
        # task_type MUST be "retrieval_query" here.  Using "retrieval_document"
        # (which is correct only at ingestion time) produces vectors in a
        # different semantic space, causing the ANN search to return random results.
        try:
            logger.debug("Generating retrieval_query embedding for query")
            embedding = self.gemini_service.generate_embedding(
                query, task_type="retrieval_query"
            )
        except Exception as e:
            logger.error("Failed to generate embedding for query '%s': %s", query, e)
            raise RuntimeError(f"Embedding generation failed: {e}") from e

        # ── Step 2: ANN search — fetch more candidates than we'll return ─────
        try:
            logger.debug(
                "Querying vector store collection: %s (top_k=%d)", repository_id, top_k
            )
            db_results = self.vector_store.query_similarity(
                collection_name=repository_id,
                query_embedding=embedding,
                top_k=top_k,
            )
        except Exception as e:
            logger.error(
                "Failed to query vector database for collection '%s': %s", repository_id, e
            )
            raise RuntimeError(f"Vector database query failed: {e}") from e

        # ── Step 3: Map DB records to domain models ───────────────────────────
        candidates: List[RetrievalResult] = []
        for res in db_results:
            chunk_id = res.get("id") or ""
            content = res.get("document") or ""

            score_val = res.get("distance")
            score = float(score_val) if score_val is not None else 0.0

            metadata = res.get("metadata") or {}
            file_path = (
                metadata.get("file_path")
                or metadata.get("file")
                or metadata.get("path")
                or ""
            )

            candidates.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    content=content,
                    score=score,
                    metadata=metadata,
                )
            )

        logger.debug(
            "Mapped %d raw database records to RetrievalResult candidates.", len(candidates)
        )

        if not candidates:
            return []

        # ── Step 4: Gemini reranking ──────────────────────────────────────────
        reranked = await self._rerank(query, candidates, final_k)
        logger.info(
            "Reranking complete: %d candidates → %d results returned.",
            len(candidates),
            len(reranked),
        )
        return reranked

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_positive_int(
        self, value: Any, default: int, name: str
    ) -> int:
        """Parse an integer parameter, falling back to *default* on bad input."""
        if value is None:
            return default
        try:
            parsed = int(value)
            if parsed <= 0:
                logger.warning(
                    "%s must be a positive integer. Got %d. Using default %d.",
                    name,
                    parsed,
                    default,
                )
                return default
            return parsed
        except (ValueError, TypeError):
            logger.warning(
                "Invalid %s format. Got %s. Using default %d.", name, value, default
            )
            return default

    async def _rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        final_k: int,
    ) -> List[RetrievalResult]:
        """
        Rerank *candidates* against *query* using a single Gemini LLM call.

        All candidate chunks are sent in one batched prompt.  The model is
        asked to return a JSON list of indices ordered from most to least
        relevant.  The top ``final_k`` indices are used to select and re-order
        the final results.

        Falls back to the original ANN ordering if the LLM call fails or
        returns an unparseable response, so the pipeline is never blocked by a
        reranking failure.
        """
        if len(candidates) <= final_k:
            # Nothing to rerank — already few enough candidates.
            return candidates

        # Build a compact numbered listing of candidate chunks for the prompt.
        chunk_listings: List[str] = []
        for idx, result in enumerate(candidates):
            # Trim very long chunks to keep the prompt token count manageable.
            preview = result.content[:800].replace("\n", " ")
            chunk_listings.append(
                f"[{idx}] file={result.file_path}\n{preview}"
            )

        chunks_text = "\n\n".join(chunk_listings)

        prompt = (
            "You are a code search relevance engine.\n\n"
            "Given the user QUERY and a numbered list of code CHUNKS, output a "
            "JSON array of chunk indices ordered from MOST to LEAST relevant to "
            "the query. Include ALL indices in your response.\n\n"
            "Respond with ONLY a valid JSON array of integers, nothing else. "
            "Example: [3, 0, 7, 1, 2, 5, 4, 6]\n\n"
            f"QUERY:\n{query}\n\n"
            f"CHUNKS:\n{chunks_text}"
        )

        try:
            logger.debug("Calling Gemini reranker with %d candidates", len(candidates))
            raw_response = self.gemini_service.generate_content(
                prompt=prompt,
                model="gemini-2.5-flash",
            )

            # Strip any markdown fences the model might add
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(
                    line for line in cleaned.splitlines()
                    if not line.strip().startswith("```")
                ).strip()

            ranked_indices: List[int] = json.loads(cleaned)

            if not isinstance(ranked_indices, list):
                raise ValueError("Reranker did not return a list.")

            # Deduplicate while preserving order and guard against out-of-range indices.
            seen = set()
            ordered: List[RetrievalResult] = []
            for idx in ranked_indices:
                if not isinstance(idx, int):
                    continue
                if idx < 0 or idx >= len(candidates):
                    continue
                if idx in seen:
                    continue
                seen.add(idx)
                ordered.append(candidates[idx])

            # Append any candidates the model missed (shouldn't happen, but be safe).
            for i, c in enumerate(candidates):
                if i not in seen:
                    ordered.append(c)

            logger.debug(
                "Reranker returned order: %s",
                [ranked_indices[i] for i in range(min(final_k, len(ranked_indices)))],
            )
            return ordered[:final_k]

        except Exception as e:
            logger.warning(
                "Reranking failed (%s). Falling back to ANN ordering.", e
            )
            # Graceful degradation: return the top final_k ANN results as-is.
            return candidates[:final_k]
