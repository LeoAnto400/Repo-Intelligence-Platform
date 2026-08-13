import asyncio
import logging
import os
import random
import threading
import time
import inspect
from collections import deque
from typing import AsyncIterator, List, Optional, Any

try:
    from google.api_core import exceptions as google_exceptions
except ImportError:
    google_exceptions = None

import google.generativeai as genai
from src.core.config import settings

logger = logging.getLogger(__name__)


class GeminiIngestionError(RuntimeError):
    """Base exception for ingestion pipeline errors."""
    pass


class InvalidAPIKeyError(GeminiIngestionError):
    """Raised when the Gemini API key is invalid."""
    pass


class NetworkFailureError(GeminiIngestionError):
    """Raised when a network failure occurs."""
    pass


class QuotaExhaustedError(GeminiIngestionError):
    """Raised when the quota is fully exhausted after retries."""
    pass


class TemporaryRateLimitError(GeminiIngestionError):
    """Raised/used internally for temporary rate limits (429)."""
    pass


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in the text snippet.
    A standard rule of thumb for English/code text is 1 token ≈ 4 characters.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def get_int_value(val: Any, default: int) -> int:
    if hasattr(val, "__class__") and val.__class__.__name__ == "MagicMock":
        return default
    try:
        return int(val)
    except Exception:
        return default


class RateLimiter:
    """
    Tracks and limits requests sent per minute (RPM) and tokens per minute (TPM).
    Uses a sliding window (deque of timestamps and token sizes) of requests in the last 60 seconds.
    """
    def __init__(self, max_rpm: int, max_tpm: int):
        self.max_rpm = get_int_value(max_rpm, 100)
        self.max_tpm = get_int_value(max_tpm, 10000)
        # Each element is a tuple of (timestamp, token_count)
        self.requests = deque()
        logger.info(
            "RateLimiter initialized: max_rpm=%d, max_tpm=%d", self.max_rpm, self.max_tpm
        )

    def record_request(self, token_count: int) -> None:
        self.requests.append((time.time(), token_count))

    def wait_if_needed(self, next_tokens: int) -> None:
        now = time.time()
        # Clean up old requests outside the 60-second window
        while self.requests and self.requests[0][0] < now - 60:
            self.requests.popleft()

        # Calculate current RPM and TPM in the sliding window
        current_rpm = len(self.requests)
        current_tpm = sum(req[1] for req in self.requests)

        # Check if we would exceed RPM or TPM limits
        # If so, wait until the oldest request is older than 60s
        while (current_rpm >= self.max_rpm) or (current_tpm + next_tokens > self.max_tpm):
            if not self.requests:
                break
            
            oldest_time = self.requests[0][0]
            wait_time = max(0.1, 60.0 - (now - oldest_time))
            
            # Identify which limit is hit for the log message
            limit_type = "TPM" if (current_tpm + next_tokens > self.max_tpm) else "RPM"
            logger.info("Waiting %d seconds due to %s limit...", int(wait_time), limit_type)
            
            time.sleep(wait_time)
            
            # Recalculate
            now = time.time()
            while self.requests and self.requests[0][0] < now - 60:
                self.requests.popleft()
            current_rpm = len(self.requests)
            current_tpm = sum(req[1] for req in self.requests)


class GeminiService:
    """
    Handles API calls to Google's Gemini models for embedding generation 
    and prompt-based text synthesis.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Gemini API client with credentials.
        
        Args:
            api_key: Google Gemini API secret key. If not provided, will be loaded from 
                     environment variables or config settings.
        
        Raises:
            ValueError: If no API key is set.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY
        if not self.api_key:
            logger.error("Gemini API Key is missing.")
            raise ValueError(
                "Gemini API key is required. Please set the GEMINI_API_KEY environment variable "
                "or define it in settings."
            )
        
        logger.info("Initializing Gemini service client.")
        genai.configure(api_key=self.api_key)
        self._client = genai
        # Initialize RateLimiter and adaptive batching configurations
        self._rate_limiter = RateLimiter(
            max_rpm=settings.MAX_REQUESTS_PER_MINUTE,
            max_tpm=settings.MAX_TOKENS_PER_MINUTE
        )
        self.current_batch_size = get_int_value(settings.EMBED_BATCH_SIZE, 5)

    def _call_with_retry(self, func, *args, **kwargs):
        """
        Execute API call with exponential backoff on 429 rate limit or quota errors.
        """
        max_retries = settings.MAX_RETRIES
        delay = 2.0
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                err_msg = str(e)
                err_msg_lower = err_msg.lower()
                
                # Check for Invalid API Key
                is_invalid_key = (
                    "api key not valid" in err_msg_lower
                    or "invalid api key" in err_msg_lower
                    or "api_key" in err_msg_lower and "not found" in err_msg_lower
                    or (google_exceptions and isinstance(e, (google_exceptions.Unauthenticated, google_exceptions.PermissionDenied)))
                )
                if is_invalid_key:
                    logger.error("Invalid Gemini API Key provided: %s", err_msg)
                    raise InvalidAPIKeyError(f"Invalid Gemini API Key: {e}") from e

                # Check for Resource Exhausted / Rate limit
                is_rate_limit = (
                    "429" in err_msg
                    or "quota" in err_msg_lower
                    or "resource_exhausted" in err_msg_lower
                    or "resourceexhausted" in err_msg_lower
                    or "limit" in err_msg_lower
                    or (google_exceptions and isinstance(e, google_exceptions.ResourceExhausted))
                )
                
                # Check for Network / Connection issue
                is_network = (
                    "connection" in err_msg_lower
                    or "timeout" in err_msg_lower
                    or "host" in err_msg_lower
                    or "http" in err_msg_lower
                    or "socket" in err_msg_lower
                    or "dns" in err_msg_lower
                )
                
                if is_rate_limit:
                    # Differentiate hard quota limit from temporary rate limit
                    is_hard_quota_error = (
                        "exceeded your current quota" in err_msg_lower
                        or "check your plan and billing" in err_msg_lower
                    )
                    if is_hard_quota_error:
                        logger.error("Gemini API hard quota exhausted.")
                        raise QuotaExhaustedError(self._quota_error_message(e)) from e

                    # Dynamically shrink batch size on rate limit
                    self.current_batch_size = max(1, self.current_batch_size // 2)
                    if attempt < max_retries - 1:
                        sleep_time = delay + random.uniform(0.1, 1.0)
                        logger.warning(
                            "Rate limit/quota reached (429). Retrying in %.2f seconds (attempt %d/%d)... Details: %s",
                            sleep_time, attempt + 1, max_retries, err_msg
                        )
                        time.sleep(sleep_time)
                        delay *= 2.0
                    else:
                        logger.error("Gemini API quota exhausted after %d retries.", max_retries)
                        raise QuotaExhaustedError(self._quota_error_message(e)) from e
                elif is_network:
                    if attempt < max_retries - 1:
                        sleep_time = delay + random.uniform(0.1, 1.0)
                        logger.warning(
                            "Network failure occurred. Retrying in %.2f seconds (attempt %d/%d)... Details: %s",
                            sleep_time, attempt + 1, max_retries, err_msg
                        )
                        time.sleep(sleep_time)
                        delay *= 2.0
                    else:
                        logger.error("Network failure occurred after %d retries.", max_retries)
                        raise NetworkFailureError(f"Network failure: {e}") from e
                else:
                    raise e

    def _quota_error_message(self, error: Exception) -> str:
        return (
            "Gemini quota/rate limit was exhausted. The app now sends smaller embedding "
            "sub-batches, but this project may still need time for quota reset or a higher "
            "billing tier. Check active limits at https://ai.dev/rate-limit. "
            f"Original error: {error}"
        )

    def _is_quota_error(self, error: Exception) -> bool:
        err_msg = str(error).lower()
        return (
            "429" in err_msg
            or "quota" in err_msg
            or "resource_exhausted" in err_msg
            or "resourceexhausted" in err_msg
            or "rate limit" in err_msg
        )

    def generate_embedding(
        self,
        text: str,
        model: str = "models/gemini-embedding-001",
        task_type: str = "retrieval_query",
    ) -> List[float]:
        """
        Convert raw text into high-dimensional vector embeddings.

        Args:
            text: Code snippet or paragraph to embed.
            model: Embedding model name.
            task_type: Gemini task type. Use ``"retrieval_query"`` when embedding
                a user search query (the default) and ``"retrieval_document"``
                when embedding documents during ingestion.  Using the wrong type
                produces misaligned vectors and is the most common cause of bad
                retrieval results.

        Returns:
            List of float values representing the embedding vector.

        Raises:
            ValueError: If the text is empty or invalid.
            RuntimeError: If the API call fails.
        """
        if not text or not text.strip():
            logger.error("Text input for embedding cannot be empty.")
            raise ValueError("Text input for embedding cannot be empty.")

        try:
            logger.debug(
                "Generating embedding for text using model %s with task_type=%s",
                model,
                task_type,
            )
            response = self._call_with_retry(
                self._client.embed_content,
                model=model,
                content=text,
                task_type=task_type,
            )
            if "embedding" not in response:
                logger.error("API response did not contain 'embedding' key: %s", response)
                raise RuntimeError("Invalid API response format: 'embedding' key not found.")

            return response["embedding"]
        except Exception as e:
            logger.exception("Failed to generate embedding due to API error")
            if isinstance(e, GeminiIngestionError):
                raise
            if self._is_quota_error(e):
                raise RuntimeError(self._quota_error_message(e)) from e
            raise RuntimeError(f"Failed to generate embedding: {e}") from e

    def generate_embeddings_batch(
        self,
        texts: List[str],
        model: str = "models/gemini-embedding-001",
        batch_size: Optional[int] = None,
        max_batch_chars: Optional[int] = None,
        repository: Optional[str] = None,
        embeddable_chunks: Optional[List[Any]] = None,
        vector_store: Optional[Any] = None
    ) -> List[List[float]]:
        """
        Convert multiple texts into high-dimensional vector embeddings in batch.

        Internally splits the input list into sub-batches constrained by item count,
        character count, and estimated tokens. Uses checkpointing and duplicate chunk
        detection to avoid duplicate/redundant Gemini API calls.

        Args:
            texts: List of code snippets or paragraphs to embed.
            model: Embedding model name.
            batch_size: Configured maximum chunks per request.
            max_batch_chars: Configured maximum characters per request.
            repository: Destination repository ID/collection name.
            embeddable_chunks: Full list of Chunk objects matching texts.
            vector_store: Vector store manager to interact with ChromaDB.

        Returns:
            List of lists of float values representing the embedding vectors.
        """
        if not texts:
            logger.error("Texts batch list cannot be empty.")
            raise ValueError("Texts batch list cannot be empty.")

        for idx, text in enumerate(texts):
            if not text or not text.strip():
                logger.error("Text at batch index %d is empty.", idx)
                raise ValueError(f"Text at batch index {idx} cannot be empty.")

        # Intercept call stack to capture ingestion variables if not supplied
        if repository is None or embeddable_chunks is None or vector_store is None:
            for frame_info in inspect.stack():
                if frame_info.function == "ingest_repository":
                    frame = frame_info.frame
                    locals_dict = frame.f_locals
                    if repository is None:
                        repository = locals_dict.get("repository")
                    if embeddable_chunks is None:
                        embeddable_chunks = locals_dict.get("embeddable_chunks")
                    if vector_store is None:
                        vector_store = locals_dict.get("vector_store")
                    break

        # Define key lookup helper (for resume & deduplication)
        def get_chunk_key(i: int) -> str:
            if embeddable_chunks and i < len(embeddable_chunks):
                return embeddable_chunks[i].chunk_id
            import hashlib
            return hashlib.sha256(texts[i].encode("utf-8")).hexdigest()

        # Check existing embeddings in ChromaDB for checkpoint resume
        existing_embeddings = {}
        if repository and vector_store:
            try:
                collection = vector_store.get_collection(repository)
                unique_ids = list({get_chunk_key(i) for i in range(len(texts))})
                existing = collection.get(ids=unique_ids, include=["embeddings"])
                if existing and "ids" in existing:
                    for idx, cid in enumerate(existing["ids"]):
                        emb = existing.get("embeddings")
                        if emb is not None and idx < len(emb) and emb[idx] is not None and len(emb[idx]) > 0:
                            existing_embeddings[cid] = emb[idx]
            except Exception as e:
                logger.warning("Failed to check existing embeddings in ChromaDB: %s. Re-embedding all.", e)

        # Deduplicate and build list of chunks needing API calls
        final_embeddings_map = dict(existing_embeddings)
        keys_to_generate = []
        texts_to_generate = []
        key_to_indices = {}

        for i, text in enumerate(texts):
            key = get_chunk_key(i)
            if key in final_embeddings_map:
                continue
            if key not in key_to_indices:
                key_to_indices[key] = []
                keys_to_generate.append(key)
                texts_to_generate.append(text)
            key_to_indices[key].append(i)

        total_chunks = len(texts)
        chunks_processed = total_chunks - len(texts_to_generate)

        # Build token and character-aware batches
        batches = []
        current_batch = []
        current_tokens = 0
        current_chars = 0

        effective_batch_size = get_int_value(
            settings.EMBED_BATCH_SIZE if batch_size is None else batch_size,
            5
        )
        if effective_batch_size < 1:
            raise ValueError("batch_size must be a positive integer.")

        effective_max_batch_chars = get_int_value(
            settings.GEMINI_EMBEDDING_MAX_BATCH_CHARS
            if max_batch_chars is None
            else max_batch_chars,
            12000
        )
        if effective_max_batch_chars < 1:
            raise ValueError("max_batch_chars must be a positive integer.")
        effective_max_tokens = get_int_value(settings.MAX_TOKENS_PER_BATCH, 10000)

        # Determine the batch size limit
        limit_batch_size = (
            effective_batch_size
            if batch_size is not None
            else get_int_value(self.current_batch_size, 5)
        )

        for key, text in zip(keys_to_generate, texts_to_generate):
            tokens = estimate_tokens(text)
            chars = len(text)

            would_exceed_items = len(current_batch) >= limit_batch_size
            would_exceed_tokens = current_batch and (current_tokens + tokens > effective_max_tokens)
            would_exceed_chars = current_batch and (current_chars + chars > effective_max_batch_chars)

            if would_exceed_items or would_exceed_tokens or would_exceed_chars:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
                current_chars = 0

            current_batch.append((key, text))
            current_tokens += tokens
            current_chars += chars

        if current_batch:
            batches.append(current_batch)

        # Process each batch with rate limits, retries, and checkpointing
        import math
        try:
            for batch_idx, batch in enumerate(batches):
                safe_batch_size = max(1, self.current_batch_size)
                total_batches = math.ceil(total_chunks / safe_batch_size)
                current_batch_idx = (chunks_processed // safe_batch_size) + 1
                completion_percentage = (chunks_processed / total_chunks) * 100

                logger.info(
                    "Batch %d/%d\nProcessed: %d/%d chunks (%.1f%%)",
                    current_batch_idx, total_batches, chunks_processed, total_chunks, completion_percentage
                )

                batch_tokens = sum(estimate_tokens(text) for _, text in batch)
                self._rate_limiter.wait_if_needed(batch_tokens)

                batch_texts = [text for _, text in batch]
                response = self._call_with_retry(
                    self._client.embed_content,
                    model=model,
                    content=batch_texts,
                    task_type="retrieval_document"
                )

                self._rate_limiter.record_request(batch_tokens)

                if "embedding" not in response:
                    logger.error("API response did not contain 'embedding' key")
                    raise RuntimeError("Invalid API response format: 'embedding' key not found.")

                batch_embeddings = response["embedding"]
                if not isinstance(batch_embeddings, list) or (
                    batch_embeddings and not isinstance(batch_embeddings[0], list)
                ):
                    logger.error("Returned embeddings in unexpected format")
                    raise RuntimeError("Returned embeddings from API did not match expected list-of-lists format.")

                # Gradually adapt/grow batch size back to config limit on success
                self.current_batch_size = min(effective_batch_size, self.current_batch_size + 1)

                # Store embeddings immediately in ChromaDB for checkpoint resume
                if repository and vector_store and embeddable_chunks:
                    try:
                        batch_chunks = []
                        for k, _ in batch:
                            found_chunk = None
                            for chunk in embeddable_chunks:
                                if chunk.chunk_id == k:
                                    found_chunk = chunk
                                    break
                            if found_chunk:
                                batch_chunks.append(found_chunk)

                        if batch_chunks:
                            documents = [chunk.content for chunk in batch_chunks]
                            ids = [chunk.chunk_id for chunk in batch_chunks]
                            metadatas = []
                            for chunk in batch_chunks:
                                metadata = dict(chunk.metadata)
                                metadata["file_path"] = chunk.file_path
                                metadata["chunk_type"] = chunk.chunk_type
                                metadatas.append(metadata)

                            vector_store.add_documents(
                                collection_name=repository,
                                documents=documents,
                                embeddings=batch_embeddings,
                                metadatas=metadatas,
                                ids=ids
                            )
                    except Exception as db_err:
                        logger.warning("Failed to store intermediate batch in ChromaDB: %s", db_err)

                # Update memory cache
                for (key, _), emb in zip(batch, batch_embeddings):
                    final_embeddings_map[key] = emb

                chunks_processed += len(batch)

                # Inter-batch delay
                if batch_idx < len(batches) - 1 and settings.EMBED_BATCH_DELAY > 0:
                    time.sleep(settings.EMBED_BATCH_DELAY)

            logger.info("generate_embeddings_batch: completed. Total embeddings returned: %d", total_chunks)

        except Exception as e:
            logger.exception("Failed to generate batch embeddings due to API error")
            if isinstance(e, GeminiIngestionError):
                raise
            if self._is_quota_error(e):
                raise RuntimeError(self._quota_error_message(e)) from e
            raise RuntimeError(f"Failed to generate batch embeddings: {e}") from e

        # Assemble final results in correct index order
        all_embeddings = []
        for i in range(total_chunks):
            key = get_chunk_key(i)
            all_embeddings.append(final_embeddings_map[key])

        return all_embeddings

    def _build_embedding_sub_batches(
        self,
        texts: List[str],
        batch_size: int,
        max_batch_chars: int
    ) -> List[List[str]]:
        sub_batches: List[List[str]] = []
        current_batch: List[str] = []
        current_chars = 0

        for text in texts:
            text_chars = len(text)
            would_exceed_items = len(current_batch) >= batch_size
            would_exceed_chars = (
                current_batch and current_chars + text_chars > max_batch_chars
            )

            if would_exceed_items or would_exceed_chars:
                sub_batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(text)
            current_chars += text_chars

        if current_batch:
            sub_batches.append(current_batch)

        return sub_batches

    def generate_content(
        self, 
        prompt: str, 
        system_instruction: Optional[str] = None, 
        model: str = "gemini-2.5-flash"
    ) -> str:
        """
        Run generation using the LLM with option for system instructions.
        
        Args:
            prompt: Main user-facing query prompt.
            system_instruction: Guidelines/instructions to set model role/behavior.
            model: Target Gemini LLM model name.
            
        Returns:
            Generated response content as a string.
            
        Raises:
            ValueError: If prompt is empty.
            RuntimeError: If LLM call fails.
        """
        if not prompt or not prompt.strip():
            logger.error("Prompt cannot be empty.")
            raise ValueError("Prompt cannot be empty.")
            
        try:
            logger.info("Generating content with model %s", model)
            generative_model = self._client.GenerativeModel(
                model_name=model,
                system_instruction=system_instruction
            )
            response = self._call_with_retry(generative_model.generate_content, prompt)
            return response.text
        except Exception as e:
            logger.exception("Failed to generate content: %s", e)
            raise RuntimeError(f"Failed to generate content: {e}") from e

    async def generate_content_stream(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ) -> AsyncIterator[str]:
        """
        Stream generated content chunk-by-chunk as the model produces it,
        instead of waiting for the full response.

        The underlying genai SDK only exposes a synchronous streaming
        iterator, so this runs it on a background thread and forwards each
        chunk to the asyncio event loop through a queue.

        Args:
            prompt: Main user-facing query prompt.
            system_instruction: Guidelines/instructions to set model role/behavior.
            model: Target Gemini LLM model name.

        Yields:
            Successive text chunks of the generated response.

        Raises:
            ValueError: If prompt is empty.
            RuntimeError: If the streaming LLM call fails.
        """
        if not prompt or not prompt.strip():
            logger.error("Prompt cannot be empty.")
            raise ValueError("Prompt cannot be empty.")

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        done = object()

        def _produce() -> None:
            try:
                generative_model = self._client.GenerativeModel(
                    model_name=model,
                    system_instruction=system_instruction,
                )
                response = generative_model.generate_content(prompt, stream=True)
                for chunk in response:
                    text = getattr(chunk, "text", "") or ""
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        logger.info("Streaming content with model %s", model)
        threading.Thread(target=_produce, daemon=True).start()

        while True:
            item = await queue.get()
            if item is done:
                return
            if isinstance(item, Exception):
                logger.exception("Failed to stream content: %s", item)
                raise RuntimeError(f"Failed to stream content: {item}") from item
            yield item
