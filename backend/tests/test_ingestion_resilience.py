"""
Tests for the embedding ingestion pipeline resilience features:
- Adaptive batching (batch size shrinks on 429, grows on success)
- Token-aware batching
- Rate limiter (RPM/TPM tracking)
- Exponential backoff with jitter
- Checkpoint/resume (skip already-ingested chunks)
- Duplicate chunk detection
- Error classification (InvalidAPIKeyError, NetworkFailureError, QuotaExhaustedError)
"""
import time
import unittest
from unittest.mock import patch, MagicMock, call

from src.services.gemini import (
    GeminiService,
    RateLimiter,
    estimate_tokens,
    InvalidAPIKeyError,
    QuotaExhaustedError,
    NetworkFailureError,
    get_int_value,
)
from src.services.chunker import Chunk
from src.core.config import settings


class TestEstimateTokens(unittest.TestCase):
    def test_empty_string_returns_zero(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_short_string_returns_at_least_one(self):
        self.assertGreaterEqual(estimate_tokens("hi"), 1)

    def test_approximation_rule(self):
        # 100 chars -> 25 tokens
        self.assertEqual(estimate_tokens("a" * 100), 25)


class TestGetIntValue(unittest.TestCase):
    def test_plain_int(self):
        self.assertEqual(get_int_value(5, 10), 5)

    def test_zero_returns_zero(self):
        self.assertEqual(get_int_value(0, 10), 0)

    def test_string_raises_returns_default(self):
        self.assertEqual(get_int_value("not_an_int", 7), 7)

    def test_mock_object_returns_default(self):
        mock = MagicMock()
        result = get_int_value(mock, 99)
        self.assertEqual(result, 99)


class TestRateLimiter(unittest.TestCase):
    """Test rate limiter logic using real time via freezing the request timestamps."""

    def test_no_wait_needed_under_limits(self):
        """Limiter with high limits should never pause."""
        limiter = RateLimiter(max_rpm=1000, max_tpm=100000)
        limiter.record_request(50)
        # Should not block — we'll use a real sleep patch to verify
        with patch("src.services.gemini.time.sleep") as mock_sleep:
            limiter.wait_if_needed(50)
        mock_sleep.assert_not_called()

    def test_rpm_limit_triggers_wait(self):
        """When at RPM limit, wait_if_needed should call sleep."""
        limiter = RateLimiter(max_rpm=1, max_tpm=100000)
        # Record a request as if it just happened (now)
        limiter.requests.append((time.time(), 10))

        with patch("src.services.gemini.time.sleep") as mock_sleep:
            # Make sleep advance time so the loop exits
            def advance_time(seconds):
                # Force dequeue by clearing requests (simulating 60s passing)
                limiter.requests.clear()
            mock_sleep.side_effect = advance_time
            limiter.wait_if_needed(5)

        mock_sleep.assert_called_once()

    def test_tpm_limit_triggers_wait(self):
        """When at TPM limit, wait_if_needed should call sleep."""
        limiter = RateLimiter(max_rpm=1000, max_tpm=50)
        limiter.requests.append((time.time(), 40))

        with patch("src.services.gemini.time.sleep") as mock_sleep:
            def advance_time(seconds):
                limiter.requests.clear()
            mock_sleep.side_effect = advance_time
            limiter.wait_if_needed(20)  # 40 + 20 = 60 > 50

        mock_sleep.assert_called_once()

    def test_record_request_grows_window(self):
        limiter = RateLimiter(max_rpm=1000, max_tpm=100000)
        limiter.record_request(30)
        limiter.record_request(20)
        self.assertEqual(len(limiter.requests), 2)
        self.assertEqual(sum(r[1] for r in limiter.requests), 50)


class TestAdaptiveBatching(unittest.TestCase):
    """Test that batch size shrinks on rate limit and grows on success."""

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_batch_size_shrinks_on_rate_limit_and_grows_on_success(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        service.current_batch_size = 8

        # Raise rate limit on first attempt, succeed on second
        service._client.embed_content = MagicMock(side_effect=[
            Exception("429 resource_exhausted: rate limit exceeded"),
            {"embedding": [[1.0], [2.0]]},  # Both texts on retry (all fit in 1 batch of size 4)
        ])

        result = service.generate_embeddings_batch(["a", "b"], batch_size=8)

        # Batch shrinks from 8 → 4 on error, then grows +1 = 5 on success
        self.assertEqual(service.current_batch_size, 5)
        self.assertEqual(result, [[1.0], [2.0]])
        self.assertEqual(mock_sleep.call_count, 1)  # One backoff sleep

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_token_aware_batching_splits_on_token_limit(self, mock_configure, mock_sleep):
        """Chunks exceeding token limit should be sent in separate batches."""
        service = GeminiService(api_key="key")
        # Each text = 200 chars = 50 tokens; token limit = 60 so max 1 per batch.
        # Content must differ between the two, or content-hash deduplication
        # collapses them into a single embedding call instead of two batches.
        texts = ["x" * 200, "y" * 200]

        service._client.embed_content = MagicMock(side_effect=[
            {"embedding": [[0.1]]},
            {"embedding": [[0.2]]},
        ])

        with patch.object(settings, "MAX_TOKENS_PER_BATCH", 60):
            result = service.generate_embeddings_batch(texts, batch_size=10)

        self.assertEqual(result, [[0.1], [0.2]])
        self.assertEqual(service._client.embed_content.call_count, 2)


class TestExponentialBackoff(unittest.TestCase):
    """Test exponential backoff on transient rate limits."""

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_retries_with_increasing_delays(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")

        # Fail twice, succeed third
        service._client.embed_content = MagicMock(side_effect=[
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            {"embedding": [[7.0]]},
        ])

        with patch.object(settings, "MAX_RETRIES", 5):
            result = service.generate_embeddings_batch(["hello"], batch_size=1)

        self.assertEqual(result, [[7.0]])
        self.assertEqual(mock_sleep.call_count, 2)

        # Verify delays increase (exponential backoff starting at 2s + jitter)
        first_delay = mock_sleep.call_args_list[0][0][0]
        second_delay = mock_sleep.call_args_list[1][0][0]
        self.assertTrue(2.0 <= first_delay <= 3.1)
        self.assertTrue(4.0 <= second_delay <= 5.1)

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_hard_quota_raises_immediately_no_retry(self, mock_configure, mock_sleep):
        """RESOURCE_EXHAUSTED with 'exceeded your current quota' should not retry."""
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("RESOURCE_EXHAUSTED: You exceeded your current quota")
        )

        with self.assertRaises(QuotaExhaustedError) as ctx:
            service.generate_embeddings_batch(["hello"], batch_size=1)

        self.assertIn("Gemini quota/rate limit was exhausted", str(ctx.exception))
        # No retry sleep should be called for hard quota limit
        mock_sleep.assert_not_called()

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_exhausted_retries_raises_quota_error(self, mock_configure, mock_sleep):
        """After MAX_RETRIES attempts, QuotaExhaustedError should be raised."""
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("429 rate limit reached")
        )

        with patch.object(settings, "MAX_RETRIES", 3):
            with self.assertRaises(QuotaExhaustedError):
                service.generate_embeddings_batch(["hello"], batch_size=1)

        self.assertEqual(mock_sleep.call_count, 2)  # MAX_RETRIES-1 sleeps before final raise


class TestDuplicateChunkDetection(unittest.TestCase):
    """Test that duplicate texts are not embedded twice."""

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_duplicate_texts_generate_single_api_call(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")

        # Two unique texts → API called once with both; duplicated third re-uses the embedding
        service._client.embed_content = MagicMock(
            return_value={"embedding": [[0.1, 0.2], [0.3, 0.4]]}
        )

        texts = ["alpha", "beta", "alpha"]  # "alpha" duplicated
        result = service.generate_embeddings_batch(texts, batch_size=10)

        service._client.embed_content.assert_called_once_with(
            model="models/gemini-embedding-001",
            content=["alpha", "beta"],
            task_type="retrieval_document"
        )
        # Results in correct order: alpha, beta, alpha (same embedding for dupes)
        self.assertEqual(result, [[0.1, 0.2], [0.3, 0.4], [0.1, 0.2]])


class TestCheckpointResume(unittest.TestCase):
    """Test that embeddings already stored in ChromaDB are skipped on resume."""

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_existing_chunks_skipped(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")

        # Setup mock vector store
        mock_vector_store = MagicMock()
        mock_collection = MagicMock()
        mock_vector_store.get_collection.return_value = mock_collection

        # chunk1 already exists in ChromaDB
        mock_collection.get.return_value = {
            "ids": ["chunk1"],
            "embeddings": [[9.9, 8.8]]
        }

        # API should only be called for chunk2
        service._client.embed_content = MagicMock(
            return_value={"embedding": [[1.1, 2.2]]}
        )

        chunks = [
            Chunk(chunk_id="chunk1", file_path="a.py", content="existing content", chunk_type="file"),
            Chunk(chunk_id="chunk2", file_path="b.py", content="new content", chunk_type="file"),
        ]

        result = service.generate_embeddings_batch(
            texts=["existing content", "new content"],
            repository="test_repo",
            embeddable_chunks=chunks,
            vector_store=mock_vector_store,
        )

        # API called only for "new content"
        service._client.embed_content.assert_called_once_with(
            model="models/gemini-embedding-001",
            content=["new content"],
            task_type="retrieval_document"
        )

        # Intermediate save to ChromaDB for the new batch
        mock_vector_store.add_documents.assert_called_once()
        call_kwargs = mock_vector_store.add_documents.call_args.kwargs
        self.assertEqual(call_kwargs["ids"], ["chunk2"])
        self.assertEqual(call_kwargs["embeddings"], [[1.1, 2.2]])

        # Final result should be in original index order
        self.assertEqual(result, [[9.9, 8.8], [1.1, 2.2]])

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_all_chunks_cached_no_api_call(self, mock_configure, mock_sleep):
        """If all chunks are already in ChromaDB, no API call should be made."""
        service = GeminiService(api_key="key")

        mock_vector_store = MagicMock()
        mock_collection = MagicMock()
        mock_vector_store.get_collection.return_value = mock_collection

        # Both chunks already exist
        mock_collection.get.return_value = {
            "ids": ["c1", "c2"],
            "embeddings": [[1.0], [2.0]]
        }

        service._client.embed_content = MagicMock()

        chunks = [
            Chunk(chunk_id="c1", file_path="a.py", content="content one", chunk_type="file"),
            Chunk(chunk_id="c2", file_path="b.py", content="content two", chunk_type="file"),
        ]

        result = service.generate_embeddings_batch(
            texts=["content one", "content two"],
            repository="my_repo",
            embeddable_chunks=chunks,
            vector_store=mock_vector_store,
        )

        service._client.embed_content.assert_not_called()
        self.assertEqual(result, [[1.0], [2.0]])


class TestErrorClassification(unittest.TestCase):
    """Test that different API errors are classified and raised with the right exception type."""

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_invalid_api_key_raises_InvalidAPIKeyError(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("API key not valid. Please check your API key.")
        )

        with self.assertRaises(InvalidAPIKeyError):
            service.generate_embedding("hello")

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_network_failure_raises_NetworkFailureError(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("Connection refused by host")
        )

        with patch.object(settings, "MAX_RETRIES", 2):
            with self.assertRaises(NetworkFailureError):
                service.generate_embedding("hello")

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_quota_exhausted_raises_QuotaExhaustedError(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("RESOURCE_EXHAUSTED: You exceeded your current quota. Check your plan and billing.")
        )

        with self.assertRaises(QuotaExhaustedError):
            service.generate_embeddings_batch(["hello"], batch_size=1)


if __name__ == "__main__":
    unittest.main()
