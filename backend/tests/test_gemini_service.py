import os
import unittest
from unittest.mock import patch, MagicMock
from src.services.gemini import GeminiService

class TestGeminiService(unittest.TestCase):
    
    @patch("google.generativeai.configure")
    def test_init_success_direct_key(self, mock_configure):
        service = GeminiService(api_key="direct-key-123")
        self.assertEqual(service.api_key, "direct-key-123")
        mock_configure.assert_called_once_with(api_key="direct-key-123")

    @patch("os.environ", {"GEMINI_API_KEY": "env-key-456"})
    @patch("google.generativeai.configure")
    def test_init_success_env_key(self, mock_configure):
        service = GeminiService()
        self.assertEqual(service.api_key, "env-key-456")
        mock_configure.assert_called_once_with(api_key="env-key-456")

    @patch("os.environ", {})
    @patch("src.services.gemini.settings")
    def test_init_missing_key_error(self, mock_settings):
        mock_settings.GEMINI_API_KEY = ""
        with self.assertRaises(ValueError) as context:
            GeminiService()
        self.assertIn("Gemini API key is required", str(context.exception))

    @patch("google.generativeai.configure")
    def test_generate_embedding_success(self, mock_configure):
        service = GeminiService(api_key="key")
        
        dummy_embedding = [0.1, 0.2, 0.3]
        service._client.embed_content = MagicMock(return_value={"embedding": dummy_embedding})
        
        result = service.generate_embedding("hello world", model="models/gemini-embedding-001")
        
        service._client.embed_content.assert_called_once_with(
            model="models/gemini-embedding-001",
            content="hello world",
            task_type="retrieval_query"
        )
        self.assertEqual(result, dummy_embedding)

    @patch("google.generativeai.configure")
    def test_generate_embedding_empty_text_error(self, mock_configure):
        service = GeminiService(api_key="key")
        with self.assertRaises(ValueError):
            service.generate_embedding("")
        with self.assertRaises(ValueError):
            service.generate_embedding("   ")

    @patch("google.generativeai.configure")
    def test_generate_embedding_api_error(self, mock_configure):
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(side_effect=Exception("API failure"))
        
        with self.assertRaises(RuntimeError) as context:
            service.generate_embedding("hello")
        self.assertIn("Failed to generate embedding", str(context.exception))

    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_single_batch(self, mock_configure):
        """All texts fit within one sub-batch — single API call expected."""
        service = GeminiService(api_key="key")

        dummy_embeddings = [[0.1, 0.2], [0.3, 0.4]]
        service._client.embed_content = MagicMock(return_value={"embedding": dummy_embeddings})

        result = service.generate_embeddings_batch(["hello", "world"], batch_size=10)

        service._client.embed_content.assert_called_once_with(
            model="models/gemini-embedding-001",
            content=["hello", "world"],
            task_type="retrieval_document"
        )
        self.assertEqual(result, dummy_embeddings)

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_multi_batch_ordering(self, mock_configure, mock_sleep):
        """Texts split across multiple sub-batches are returned in original order."""
        service = GeminiService(api_key="key")

        # 5 texts split into 3 sub-batches: [a,b], [c,d], [e]
        texts = ["a", "b", "c", "d", "e"]
        emb_batch1 = [[1.0, 0.0], [2.0, 0.0]]
        emb_batch2 = [[3.0, 0.0], [4.0, 0.0]]
        emb_batch3 = [[5.0, 0.0]]

        service._client.embed_content = MagicMock(side_effect=[
            {"embedding": emb_batch1},
            {"embedding": emb_batch2},
            {"embedding": emb_batch3},
        ])

        result = service.generate_embeddings_batch(texts, batch_size=2)

        self.assertEqual(result, emb_batch1 + emb_batch2 + emb_batch3)
        self.assertEqual(service._client.embed_content.call_count, 3)

        # Verify inter-batch sleep called between batches (num_batches-1 times)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_no_sleep_after_last_batch(self, mock_configure, mock_sleep):
        """No sleep call after the final sub-batch."""
        service = GeminiService(api_key="key")

        service._client.embed_content = MagicMock(return_value={"embedding": [[0.1, 0.2]]})

        service.generate_embeddings_batch(["only one"], batch_size=10)

        # Only one batch → no inter-batch sleep
        mock_sleep.assert_not_called()

    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_validation_error(self, mock_configure):
        service = GeminiService(api_key="key")
        # Empty list
        with self.assertRaises(ValueError):
            service.generate_embeddings_batch([])
        # Empty element in list
        with self.assertRaises(ValueError):
            service.generate_embeddings_batch(["hello", ""])
        # Invalid batch_size
        with self.assertRaises(ValueError):
            service.generate_embeddings_batch(["hello"], batch_size=0)
        # Invalid max_batch_chars
        with self.assertRaises(ValueError):
            service.generate_embeddings_batch(["hello"], max_batch_chars=0)

    @patch("src.services.gemini.settings")
    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_uses_default_settings(
        self,
        mock_configure,
        mock_sleep,
        mock_settings
    ):
        mock_settings.GEMINI_EMBEDDING_BATCH_SIZE = 8
        mock_settings.GEMINI_EMBEDDING_MAX_BATCH_CHARS = 12000
        mock_settings.GEMINI_EMBEDDING_BATCH_DELAY_SECONDS = 0.5
        service = GeminiService(api_key="key")

        service._client.embed_content = MagicMock(return_value={"embedding": [[1.0], [2.0]]})

        result = service.generate_embeddings_batch(["hello", "world"])

        self.assertEqual(result, [[1.0], [2.0]])
        service._client.embed_content.assert_called_once()
        self.assertEqual(service._client.embed_content.call_args.kwargs["content"], ["hello", "world"])
        mock_sleep.assert_not_called()

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_splits_by_character_budget(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        texts = ["a" * 50, "b" * 50, "c" * 50, "d" * 50]
        service._client.embed_content = MagicMock(side_effect=[
            {"embedding": [[1.0], [2.0]]},
            {"embedding": [[3.0], [4.0]]},
        ])

        result = service.generate_embeddings_batch(
            texts,
            batch_size=8,
            max_batch_chars=120
        )

        self.assertEqual(result, [[1.0], [2.0], [3.0], [4.0]])
        self.assertEqual(service._client.embed_content.call_count, 2)
        self.assertEqual(
            service._client.embed_content.call_args_list[0].kwargs["content"],
            ["a" * 50, "b" * 50]
        )
        self.assertEqual(
            service._client.embed_content.call_args_list[1].kwargs["content"],
            ["c" * 50, "d" * 50]
        )
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("src.services.gemini.time.sleep")
    @patch("google.generativeai.configure")
    def test_generate_embeddings_batch_quota_error_is_actionable(self, mock_configure, mock_sleep):
        service = GeminiService(api_key="key")
        service._client.embed_content = MagicMock(
            side_effect=Exception("RESOURCE_EXHAUSTED: You exceeded your current quota")
        )

        with self.assertRaises(RuntimeError) as context:
            service.generate_embeddings_batch(["hello"], batch_size=1)

        self.assertIn("Gemini quota/rate limit was exhausted", str(context.exception))
        self.assertIn("https://ai.dev/rate-limit", str(context.exception))
        mock_sleep.assert_not_called()

    @patch("google.generativeai.configure")
    def test_generate_content_success(self, mock_configure):
        service = GeminiService(api_key="key")
        
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "generated response text"
        mock_model.generate_content.return_value = mock_response
        
        service._client.GenerativeModel = MagicMock(return_value=mock_model)
        
        result = service.generate_content("tell me a story", system_instruction="be brief")
        
        service._client.GenerativeModel.assert_called_once_with(
            model_name="gemini-2.5-flash",
            system_instruction="be brief"
        )
        mock_model.generate_content.assert_called_once_with("tell me a story")
        self.assertEqual(result, "generated response text")

    @patch("google.generativeai.configure")
    def test_generate_content_validation_error(self, mock_configure):
        service = GeminiService(api_key="key")
        with self.assertRaises(ValueError):
            service.generate_content("")


class TestGeminiServiceStreaming(unittest.IsolatedAsyncioTestCase):
    @patch("google.generativeai.configure")
    async def test_generate_content_stream_yields_chunks_in_order(self, mock_configure):
        service = GeminiService(api_key="key")

        def make_chunk(text):
            chunk = MagicMock()
            chunk.text = text
            return chunk

        mock_model = MagicMock()
        mock_model.generate_content.return_value = [
            make_chunk("Hello"), make_chunk(" "), make_chunk("world"),
        ]
        service._client.GenerativeModel = MagicMock(return_value=mock_model)

        chunks = [chunk async for chunk in service.generate_content_stream("tell me a story")]

        self.assertEqual(chunks, ["Hello", " ", "world"])
        mock_model.generate_content.assert_called_once_with("tell me a story", stream=True)

    @patch("google.generativeai.configure")
    async def test_generate_content_stream_validation_error(self, mock_configure):
        service = GeminiService(api_key="key")
        with self.assertRaises(ValueError):
            async for _ in service.generate_content_stream(""):
                pass

    @patch("google.generativeai.configure")
    async def test_generate_content_stream_propagates_errors(self, mock_configure):
        service = GeminiService(api_key="key")

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("model unavailable")
        service._client.GenerativeModel = MagicMock(return_value=mock_model)

        with self.assertRaises(RuntimeError):
            async for _ in service.generate_content_stream("tell me a story"):
                pass


if __name__ == "__main__":
    unittest.main()
