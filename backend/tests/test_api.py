import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

import src.api.routes as routes
from src.agents.orchestrator import OrchestratorResult
from src.api.main import app
from src.services.chunker import Chunk


class TestApi(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        routes.get_github_service.cache_clear()
        routes.get_chunker.cache_clear()
        routes.get_gemini_service.cache_clear()
        routes.get_vector_store.cache_clear()
        routes.get_retrieval_agent.cache_clear()
        routes.get_analysis_agent.cache_clear()
        routes.get_orchestrator.cache_clear()
        routes._active_repository = None
        routes._active_repository_context = None
        routes._ingest_rate_limiter.reset()
        routes._query_rate_limiter.reset()
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        routes._active_repository = None
        routes._active_repository_context = None
        routes._ingest_rate_limiter.reset()
        routes._query_rate_limiter.reset()

    def test_health_endpoint(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_ingest_endpoint_success(self):
        github_service = MagicMock()
        files = [
            {
                "path": "src/auth.py",
                "content": "def login():\n    return True",
                "language": "Python",
            }
        ]
        github_service.fetch_repo_files_and_commits.return_value = (files, [])
        github_service.fetch_repository_context.return_value = {
            "metadata": {
                "name": "demo",
                "owner": "example",
                "stars": 0,
                "forks": 0,
                "primary_language": "Python",
                "license": None,
                "default_branch": "main",
                "latest_commit": "Initial commit",
                "size_kb": 1,
                "visibility": "public",
                "contributors": [],
            },
            "files": files,
            "commits": [],
            "pull_requests": [],
        }
        chunk = Chunk(
            chunk_id="chunk-1",
            file_path="src/auth.py",
            content="def login():\n    return True",
            chunk_type="function",
            metadata={"start_line": 1, "end_line": 2},
        )
        chunker = MagicMock()
        chunker.chunk_file.return_value = [chunk]
        gemini_service = MagicMock()
        gemini_service.generate_embeddings_batch.return_value = [[0.1, 0.2, 0.3]]
        vector_store = MagicMock()

        app.dependency_overrides[routes.get_github_service] = lambda: github_service
        app.dependency_overrides[routes.get_chunker] = lambda: chunker
        app.dependency_overrides[routes.get_gemini_service] = lambda: gemini_service
        app.dependency_overrides[routes.get_vector_store] = lambda: vector_store

        response = self.client.post(
            "/api/v1/ingest",
            json={"repo_url": "https://github.com/example/demo"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "success",
            "repository": "demo",
            "files_processed": 1,
            "chunks_created": 1,
            "repo_url": "https://github.com/example/demo",
        })
        github_service.fetch_repo_files_and_commits.assert_called_once_with("https://github.com/example/demo")
        github_service.fetch_repository_context.assert_called_once_with(
            "https://github.com/example/demo",
            files=files,
        )
        gemini_service.generate_embeddings_batch.assert_called_once_with([
            "def login():\n    return True"
        ])
        vector_store.reset_collection.assert_called_once_with("demo")
        vector_store.add_documents.assert_called_once()
        self.assertEqual(routes.get_active_repository(), "demo")

        context_response = self.client.get("/api/v1/repository")
        self.assertEqual(context_response.status_code, 200)
        self.assertEqual(context_response.json()["repository"], "demo")
        self.assertEqual(context_response.json()["metadata"]["name"], "demo")

    def test_repository_endpoint_requires_ingestion(self):
        response = self.client.get("/api/v1/repository")

        self.assertEqual(response.status_code, 404)
        self.assertIn("No repository has been ingested", response.json()["detail"])

    def test_ingest_endpoint_rejects_invalid_url(self):
        response = self.client.post(
            "/api/v1/ingest",
            json={"repo_url": "not-a-url"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid repository URL", response.json()["detail"])

    def test_ingest_endpoint_reports_embedding_failure(self):
        github_service = MagicMock()
        github_service.fetch_repo_files_and_commits.return_value = (
            [
                {
                    "path": "src/auth.py",
                    "content": "def login(): pass",
                    "language": "Python",
                }
            ],
            [],
        )
        chunker = MagicMock()
        chunker.chunk_file.return_value = [
            Chunk(
                chunk_id="chunk-1",
                file_path="src/auth.py",
                content="def login(): pass",
                chunk_type="function",
            )
        ]
        gemini_service = MagicMock()
        gemini_service.generate_embeddings_batch.side_effect = RuntimeError("Gemini down")
        vector_store = MagicMock()

        app.dependency_overrides[routes.get_github_service] = lambda: github_service
        app.dependency_overrides[routes.get_chunker] = lambda: chunker
        app.dependency_overrides[routes.get_gemini_service] = lambda: gemini_service
        app.dependency_overrides[routes.get_vector_store] = lambda: vector_store

        response = self.client.post(
            "/api/v1/ingest",
            json={"repo_url": "https://github.com/example/demo"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Embedding generation failed", response.json()["detail"])
        vector_store.add_documents.assert_not_called()

    def test_query_endpoint_success(self):
        orchestrator = MagicMock()
        orchestrator.process = AsyncMock(return_value=OrchestratorResult(
            answer="Authentication uses login handlers.",
            source_files=["src/auth.py"],
            retrieved_chunks=2,
        ))
        app.dependency_overrides[routes.get_orchestrator] = lambda: orchestrator

        response = self.client.post(
            "/api/v1/query",
            json={"question": "How does auth work?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "answer": "Authentication uses login handlers.",
            "source_files": ["src/auth.py"],
            "retrieved_chunks": 2,
        })
        orchestrator.process.assert_awaited_once_with("How does auth work?", history=[])

    def test_query_endpoint_forwards_conversation_history(self):
        orchestrator = MagicMock()
        orchestrator.process = AsyncMock(return_value=OrchestratorResult(
            answer="It also validates the session.",
            source_files=[],
            retrieved_chunks=0,
        ))
        app.dependency_overrides[routes.get_orchestrator] = lambda: orchestrator

        response = self.client.post(
            "/api/v1/query",
            json={
                "question": "What else does it do?",
                "history": [
                    {"role": "user", "content": "How does auth work?"},
                    {"role": "assistant", "content": "It validates tokens."},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        orchestrator.process.assert_awaited_once_with(
            "What else does it do?",
            history=[
                {"role": "user", "content": "How does auth work?"},
                {"role": "assistant", "content": "It validates tokens."},
            ],
        )

    def test_query_endpoint_rejects_empty_question(self):
        response = self.client.post(
            "/api/v1/query",
            json={"question": "   "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Question cannot be empty", response.json()["detail"])

    def test_query_endpoint_reports_orchestrator_failure(self):
        orchestrator = MagicMock()
        orchestrator.process = AsyncMock(side_effect=RuntimeError("Retrieval failed"))
        app.dependency_overrides[routes.get_orchestrator] = lambda: orchestrator

        response = self.client.post(
            "/api/v1/query",
            json={"question": "How does auth work?"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("Retrieval failed", response.json()["detail"])

    def test_delete_repository_endpoint_removes_collection(self):
        vector_store = MagicMock()
        vector_store.list_collections.return_value = [
            {"name": "demo", "repo_url": "https://github.com/example/demo", "chunk_count": 5}
        ]
        app.dependency_overrides[routes.get_vector_store] = lambda: vector_store
        routes._active_repository = "demo"
        routes._active_repository_context = {"repository": "demo"}

        response = self.client.delete("/api/v1/repositories/demo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"repository": "demo", "status": "deleted"})
        vector_store.reset_collection.assert_called_once_with("demo")
        self.assertIsNone(routes.get_active_repository())
        self.assertIsNone(routes.get_active_repository_context())

    def test_delete_repository_endpoint_requires_existing_repository(self):
        vector_store = MagicMock()
        vector_store.list_collections.return_value = []
        app.dependency_overrides[routes.get_vector_store] = lambda: vector_store

        response = self.client.delete("/api/v1/repositories/missing")

        self.assertEqual(response.status_code, 404)
        self.assertIn("has not been ingested", response.json()["detail"])
        vector_store.reset_collection.assert_not_called()

    def test_delete_repository_endpoint_leaves_other_active_repository_untouched(self):
        vector_store = MagicMock()
        vector_store.list_collections.return_value = [
            {"name": "demo", "repo_url": "https://github.com/example/demo", "chunk_count": 5}
        ]
        app.dependency_overrides[routes.get_vector_store] = lambda: vector_store
        routes._active_repository = "other-repo"
        routes._active_repository_context = {"repository": "other-repo"}

        response = self.client.delete("/api/v1/repositories/demo")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(routes.get_active_repository(), "other-repo")
        self.assertEqual(routes.get_active_repository_context(), {"repository": "other-repo"})

    def test_query_websocket_streams_events(self):
        received_history = []

        class FakeOrchestrator:
            async def stream(self, question, history=None):
                received_history.append(history)
                yield {"type": "retrieval", "retrieved_chunks": 1}
                yield {"type": "token", "text": "Auth "}
                yield {"type": "token", "text": "uses login."}
                yield {
                    "type": "done",
                    "answer": "Auth uses login.",
                    "source_files": ["src/auth.py"],
                    "chunk_count": 1,
                }

        app.dependency_overrides[routes.get_orchestrator] = lambda: FakeOrchestrator()

        with self.client.websocket_connect("/api/v1/ws/query") as websocket:
            websocket.send_json({
                "question": "How does auth work?",
                "history": [{"role": "user", "content": "What does this repo do?"}],
            })
            events = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(events[0], {"type": "retrieval", "retrieved_chunks": 1})
        self.assertEqual(events[1], {"type": "token", "text": "Auth "})
        self.assertEqual(events[2], {"type": "token", "text": "uses login."})
        self.assertEqual(events[3], {
            "type": "done",
            "answer": "Auth uses login.",
            "source_files": ["src/auth.py"],
            "chunk_count": 1,
        })
        self.assertEqual(received_history, [[{"role": "user", "content": "What does this repo do?"}]])

    def test_query_websocket_drops_malformed_history_entries(self):
        received_history = []

        class FakeOrchestrator:
            async def stream(self, question, history=None):
                received_history.append(history)
                yield {"type": "done", "answer": "ok", "source_files": [], "chunk_count": 0}

        app.dependency_overrides[routes.get_orchestrator] = lambda: FakeOrchestrator()

        with self.client.websocket_connect("/api/v1/ws/query") as websocket:
            websocket.send_json({
                "question": "How does auth work?",
                "history": [
                    {"role": "user", "content": "Valid turn"},
                    {"role": "user", "content": "   "},
                    {"content": "missing role"},
                    "not-a-dict",
                    {"role": "assistant"},
                ],
            })
            websocket.receive_json()

        self.assertEqual(received_history, [[{"role": "user", "content": "Valid turn"}]])

    def test_query_websocket_rejects_empty_question(self):
        app.dependency_overrides[routes.get_orchestrator] = lambda: MagicMock()

        with self.client.websocket_connect("/api/v1/ws/query") as websocket:
            websocket.send_json({"question": "   "})
            event = websocket.receive_json()

        self.assertEqual(event, {"type": "error", "detail": "Question cannot be empty."})

    def test_query_websocket_reports_orchestrator_failure(self):
        class FailingOrchestrator:
            async def stream(self, question, history=None):
                raise RuntimeError("Retrieval failed")
                yield  # pragma: no cover - makes this an async generator

        app.dependency_overrides[routes.get_orchestrator] = lambda: FailingOrchestrator()

        with self.client.websocket_connect("/api/v1/ws/query") as websocket:
            websocket.send_json({"question": "How does auth work?"})
            event = websocket.receive_json()

        self.assertEqual(event, {"type": "error", "detail": "Retrieval failed"})

    def test_ingest_endpoint_enforces_rate_limit(self):
        for _ in range(routes._ingest_rate_limiter.max_requests):
            routes._ingest_rate_limiter.allow("testclient")

        response = self.client.post(
            "/api/v1/ingest",
            json={"repo_url": "https://github.com/example/demo"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many ingestion requests", response.json()["detail"])

    def test_query_endpoint_enforces_rate_limit(self):
        for _ in range(routes._query_rate_limiter.max_requests):
            routes._query_rate_limiter.allow("testclient")

        response = self.client.post(
            "/api/v1/query",
            json={"question": "How does auth work?"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many query requests", response.json()["detail"])

    def test_query_websocket_enforces_rate_limit(self):
        app.dependency_overrides[routes.get_orchestrator] = lambda: MagicMock()
        for _ in range(routes._query_rate_limiter.max_requests):
            routes._query_rate_limiter.allow("testclient")

        with self.client.websocket_connect("/api/v1/ws/query") as websocket:
            websocket.send_json({"question": "How does auth work?"})
            event = websocket.receive_json()

        self.assertEqual(event, {"type": "error", "detail": routes._QUERY_RATE_LIMIT_MESSAGE})

    def test_summarize_pull_request_success(self):
        routes._active_repository = "demo"
        routes._active_repository_context = {
            "repository": "demo",
            "pull_requests": [
                {"number": 42, "title": "Add dark mode", "author": "octocat", "status": "open", "labels": [], "body": "Adds a dark theme toggle."},
            ],
        }
        analysis_agent = MagicMock()
        analysis_agent.generate_pr_summary = AsyncMock(return_value="Adds a dark mode toggle to settings.")
        app.dependency_overrides[routes.get_analysis_agent] = lambda: analysis_agent

        response = self.client.post("/api/v1/pull-requests/42/summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"number": 42, "summary": "Adds a dark mode toggle to settings."})
        analysis_agent.generate_pr_summary.assert_awaited_once_with(
            routes._active_repository_context["pull_requests"][0]
        )

    def test_summarize_pull_request_requires_active_repository(self):
        response = self.client.post("/api/v1/pull-requests/42/summary")

        self.assertEqual(response.status_code, 404)
        self.assertIn("No repository has been ingested", response.json()["detail"])

    def test_summarize_pull_request_requires_known_pr_number(self):
        routes._active_repository = "demo"
        routes._active_repository_context = {"repository": "demo", "pull_requests": []}

        response = self.client.post("/api/v1/pull-requests/999/summary")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Pull request #999 was not found", response.json()["detail"])

    def test_summarize_pull_request_reports_generation_failure(self):
        routes._active_repository = "demo"
        routes._active_repository_context = {
            "repository": "demo",
            "pull_requests": [{"number": 7, "title": "Fix bug", "author": "octocat", "status": "closed", "labels": [], "body": ""}],
        }
        analysis_agent = MagicMock()
        analysis_agent.generate_pr_summary = AsyncMock(side_effect=RuntimeError("Gemini down"))
        app.dependency_overrides[routes.get_analysis_agent] = lambda: analysis_agent

        response = self.client.post("/api/v1/pull-requests/7/summary")

        self.assertEqual(response.status_code, 502)
        self.assertIn("Gemini down", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
