import unittest
from unittest.mock import MagicMock, AsyncMock
from src.agents.retrieval import RetrievalAgent, RetrievalResult
from src.services.gemini import GeminiService
from src.db.chroma import VectorStoreManager

class TestRetrievalAgent(unittest.TestCase):
    """
    Standard synchronous tests for RetrievalResult model.
    """
    def test_retrieval_result_mapping_and_serialization(self):
        """Test that RetrievalResult maps properties correctly and converts to dictionary."""
        result = RetrievalResult(
            chunk_id="chunk_id_123",
            file_path="src/main.py",
            content="print('hello')",
            score=0.15,
            metadata={"repo_name": "test-repo", "author": "dev"}
        )
        
        self.assertEqual(result.chunk_id, "chunk_id_123")
        self.assertEqual(result.file_path, "src/main.py")
        self.assertEqual(result.content, "print('hello')")
        self.assertEqual(result.score, 0.15)
        self.assertEqual(result.metadata["repo_name"], "test-repo")
        
        # Test serialization
        d = result.to_dict()
        self.assertEqual(d["chunk_id"], "chunk_id_123")
        self.assertEqual(d["file_path"], "src/main.py")
        self.assertEqual(d["content"], "print('hello')")
        self.assertEqual(d["score"], 0.15)
        self.assertEqual(d["metadata"], {"repo_name": "test-repo", "author": "dev"})


class TestRetrievalAgentAsync(unittest.IsolatedAsyncioTestCase):
    """
    Asynchronous tests for RetrievalAgent behaviors using standard IsolatedAsyncioTestCase.
    """
    def setUp(self):
        self.mock_vector_store = MagicMock(spec=VectorStoreManager)
        self.mock_gemini_service = MagicMock(spec=GeminiService)
        self.agent = RetrievalAgent(
            vector_store=self.mock_vector_store,
            gemini_service=self.mock_gemini_service,
            default_top_k=5
        )

    async def test_successful_retrieve_snippets(self):
        # Setup mock dependencies
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        
        mock_db_results = [
            {
                "id": "chunk-1",
                "document": "def add(a, b): return a + b",
                "distance": 0.12,
                "metadata": {"file_path": "math.py", "chunk_type": "function"}
            },
            {
                "id": "chunk-2",
                "document": "def sub(a, b): return a - b",
                "distance": 0.28,
                "metadata": {"file": "math.py", "chunk_type": "function"}  # testing "file" key fallback
            }
        ]
        self.mock_vector_store.query_similarity.return_value = mock_db_results
        
        # Execute retrieve_snippets
        results = await self.agent.retrieve_snippets(
            query="addition or subtraction",
            repository_id="math-repo",
            top_k=3
        )
        
        # Assertions
        self.mock_gemini_service.generate_embedding.assert_called_once_with(
            "addition or subtraction", task_type="retrieval_query"
        )
        self.mock_vector_store.query_similarity.assert_called_once_with(
            collection_name="math-repo",
            query_embedding=dummy_embedding,
            top_k=3
        )
        
        self.assertEqual(len(results), 2)
        
        self.assertEqual(results[0].chunk_id, "chunk-1")
        self.assertEqual(results[0].file_path, "math.py")
        self.assertEqual(results[0].content, "def add(a, b): return a + b")
        self.assertEqual(results[0].score, 0.12)
        
        self.assertEqual(results[1].chunk_id, "chunk-2")
        self.assertEqual(results[1].file_path, "math.py")
        self.assertEqual(results[1].content, "def sub(a, b): return a - b")
        self.assertEqual(results[1].score, 0.28)

    async def test_successful_process_flow(self):
        # Setup mock dependencies
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        
        mock_db_results = [
            {
                "id": "chunk-1",
                "document": "print('hello')",
                "distance": 0.05,
                "metadata": {"path": "hello.py"}  # testing "path" key fallback
            }
        ]
        self.mock_vector_store.query_similarity.return_value = mock_db_results
        
        payload = {
            "query": "hello world",
            "repository_id": "hello-repo",
            "top_k": 2
        }
        
        # Execute process
        response = await self.agent.process(payload)
        
        # Verify success structure
        self.assertIsNone(response["error"])
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["chunk_id"], "chunk-1")
        self.assertEqual(response["results"][0]["file_path"], "hello.py")
        self.assertEqual(response["results"][0]["content"], "print('hello')")
        self.assertEqual(response["results"][0]["score"], 0.05)

    async def test_no_matching_results(self):
        # Setup mock dependencies
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        self.mock_vector_store.query_similarity.return_value = []
        
        # Execute retrieve_snippets
        results = await self.agent.retrieve_snippets(
            query="something non-existent",
            repository_id="empty-repo",
            top_k=5
        )
        self.assertEqual(results, [])
        
        # Execute process
        payload = {
            "query": "something non-existent",
            "repository_id": "empty-repo"
        }
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIsNone(response["error"])

    async def test_embedding_service_failure(self):
        # Mock Gemini service exception
        self.mock_gemini_service.generate_embedding.side_effect = Exception("Gemini service down")
        
        # 1. Assert retrieve_snippets propagates exceptions
        with self.assertRaises(RuntimeError) as ctx:
            await self.agent.retrieve_snippets(
                query="crash me",
                repository_id="error-repo"
            )
        self.assertIn("Embedding generation failed", str(ctx.exception))
        
        # 2. Assert process() handles exceptions and returns structured response
        payload = {
            "query": "crash me",
            "repository_id": "error-repo"
        }
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIsNotNone(response["error"])
        self.assertIn("Retrieval failed: Embedding generation failed", response["error"])

    async def test_vector_store_failure(self):
        # Setup mock dependencies
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        
        # Mock vector store exception
        self.mock_vector_store.query_similarity.side_effect = Exception("Chroma index corrupt")
        
        # 1. Assert retrieve_snippets propagates exceptions
        with self.assertRaises(RuntimeError) as ctx:
            await self.agent.retrieve_snippets(
                query="query docs",
                repository_id="broken-repo"
            )
        self.assertIn("Vector database query failed", str(ctx.exception))
        
        # 2. Assert process() handles exceptions and returns structured response
        payload = {
            "query": "query docs",
            "repository_id": "broken-repo"
        }
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIsNotNone(response["error"])
        self.assertIn("Retrieval failed: Vector database query failed", response["error"])

    async def test_retrieval_result_mapping_missing_file_path(self):
        # Setup mock dependencies
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        
        # Setup db result with metadata but without any file path key
        mock_db_results = [
            {
                "id": "chunk-1",
                "document": "code",
                "distance": 0.5,
                "metadata": {"some_other_key": "val"}
            }
        ]
        self.mock_vector_store.query_similarity.return_value = mock_db_results
        
        results = await self.agent.retrieve_snippets(
            query="query",
            repository_id="repo"
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file_path, "")

    async def test_top_k_behavior_payload_override_vs_default(self):
        dummy_embedding = [0.1, 0.2, 0.3]
        self.mock_gemini_service.generate_embedding.return_value = dummy_embedding
        self.mock_vector_store.query_similarity.return_value = []
        
        # 1. Use default top_k configured in agent (which is 5)
        payload_no_top_k = {
            "query": "find stuff",
            "repository_id": "test-repo"
        }
        await self.agent.process(payload_no_top_k)
        self.mock_vector_store.query_similarity.assert_called_with(
            collection_name="test-repo",
            query_embedding=dummy_embedding,
            top_k=5
        )
        
        # Reset mocks
        self.mock_vector_store.query_similarity.reset_mock()
        
        # 2. Use custom top_k in payload (override)
        payload_with_top_k = {
            "query": "find stuff",
            "repository_id": "test-repo",
            "top_k": 8
        }
        await self.agent.process(payload_with_top_k)
        self.mock_vector_store.query_similarity.assert_called_with(
            collection_name="test-repo",
            query_embedding=dummy_embedding,
            top_k=8
        )
        
        # Reset mocks
        self.mock_vector_store.query_similarity.reset_mock()
        
        # 3. Invalid top_k in payload falls back to default
        payload_invalid_top_k = {
            "query": "find stuff",
            "repository_id": "test-repo",
            "top_k": -2  # non-positive
        }
        await self.agent.process(payload_invalid_top_k)
        self.mock_vector_store.query_similarity.assert_called_with(
            collection_name="test-repo",
            query_embedding=dummy_embedding,
            top_k=5
        )

    async def test_process_payload_validation_errors(self):
        # 1. Missing query
        payload = {"repository_id": "test-repo"}
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIn("query' is missing or empty", response["error"])
        
        # 2. Empty query string
        payload = {"query": "   ", "repository_id": "test-repo"}
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIn("query' is missing or empty", response["error"])
        
        # 3. Missing repository_id
        payload = {"query": "hello"}
        response = await self.agent.process(payload)
        self.assertEqual(response["results"], [])
        self.assertIn("repository_id' is missing or empty", response["error"])


if __name__ == "__main__":
    unittest.main()
