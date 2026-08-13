import unittest
from unittest.mock import AsyncMock, MagicMock

from src.agents.analysis import AnalysisAgent
from src.agents.orchestrator import AgentState, Orchestrator, OrchestratorResult
from src.agents.retrieval import RetrievalAgent


class TestOrchestratorResult(unittest.TestCase):
    def test_orchestrator_result_fields(self):
        result = OrchestratorResult(
            answer="Use the auth middleware.",
            source_files=["src/auth.py"],
            retrieved_chunks=2,
        )

        self.assertEqual(result.answer, "Use the auth middleware.")
        self.assertEqual(result.source_files, ["src/auth.py"])
        self.assertEqual(result.retrieved_chunks, 2)


class TestOrchestrator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.retrieval_agent = MagicMock(spec=RetrievalAgent)
        self.analysis_agent = MagicMock(spec=AnalysisAgent)
        self.retrieval_agent.process = AsyncMock()
        self.analysis_agent.process = AsyncMock()
        self.orchestrator = Orchestrator(
            retrieval_agent=self.retrieval_agent,
            analysis_agent=self.analysis_agent,
        )

    def test_graph_is_compiled_on_initialization(self):
        self.assertIsNotNone(self.orchestrator._compiled_graph)
        self.assertTrue(hasattr(self.orchestrator._compiled_graph, "ainvoke"))

    async def test_retrieval_node_executes_and_stores_results(self):
        retrieval_results = [
            {
                "chunk_id": "chunk-1",
                "file_path": "src/auth.py",
                "content": "def login(): pass",
                "score": 0.1,
                "metadata": {"chunk_type": "function"},
            }
        ]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }
        state: AgentState = {
            "question": "How does auth work?",
            "retrieval_results": [],
            "analysis_result": None,
            "error": None,
        }

        update = await self.orchestrator.retrieval_node(state)

        self.assertEqual(update, {
            "retrieval_results": retrieval_results,
            "error": None,
        })
        self.retrieval_agent.process.assert_awaited_once_with({
            "query": "How does auth work?"
        })
        self.assertEqual(self.orchestrator.last_state["retrieval_results"], retrieval_results)

    async def test_analysis_node_executes_and_stores_result(self):
        retrieval_results = [
            {
                "chunk_id": "chunk-1",
                "file_path": "src/auth.py",
                "content": "def login(): pass",
                "score": 0.1,
                "metadata": {"chunk_type": "function"},
            }
        ]
        analysis_result = {
            "answer": "Auth uses login.",
            "source_files": ["src/auth.py"],
            "chunk_count": 1,
            "error": None,
        }
        self.analysis_agent.process.return_value = analysis_result
        state: AgentState = {
            "question": "How does auth work?",
            "retrieval_results": retrieval_results,
            "analysis_result": None,
            "error": None,
        }

        update = await self.orchestrator.analysis_node(state)

        self.assertEqual(update, {
            "analysis_result": analysis_result,
            "error": None,
        })
        self.analysis_agent.process.assert_awaited_once_with({
            "question": "How does auth work?",
            "retrieval_results": retrieval_results,
            "history": [],
        })
        self.assertEqual(self.orchestrator.last_state["analysis_result"], analysis_result)

    async def test_process_coordinates_retrieval_and_analysis(self):
        retrieval_results = [
            {
                "chunk_id": "chunk-1",
                "file_path": "src/auth.py",
                "content": "def login(): pass",
                "score": 0.1,
                "metadata": {"chunk_type": "function"},
            },
            {
                "chunk_id": "chunk-2",
                "file_path": "src/routes.py",
                "content": "router.post('/login')",
                "score": 0.2,
                "metadata": {"chunk_type": "file"},
            },
        ]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }
        self.analysis_agent.process.return_value = {
            "answer": "Authentication is handled by login routes.",
            "source_files": ["src/auth.py", "src/routes.py"],
            "chunk_count": 2,
            "error": None,
        }

        result = await self.orchestrator.process(" How does auth work? ")

        self.assertEqual(
            result,
            OrchestratorResult(
                answer="Authentication is handled by login routes.",
                source_files=["src/auth.py", "src/routes.py"],
                retrieved_chunks=2,
            ),
        )
        self.retrieval_agent.process.assert_awaited_once_with({
            "query": "How does auth work?"
        })
        self.analysis_agent.process.assert_awaited_once_with({
            "question": "How does auth work?",
            "retrieval_results": retrieval_results,
            "history": [],
        })
        self.assertEqual(self.orchestrator.last_state["question"], "How does auth work?")
        self.assertEqual(self.orchestrator.last_state["retrieval_results"], retrieval_results)
        self.assertEqual(self.orchestrator.last_state["analysis_result"]["answer"], result.answer)
        self.assertIsNone(self.orchestrator.last_state["error"])

    async def test_process_forwards_history_to_analysis_agent_only(self):
        retrieval_results = [{"chunk_id": "chunk-1", "content": "code"}]
        history = [
            {"role": "user", "content": "What does this repo do?"},
            {"role": "assistant", "content": "It's a FastAPI backend."},
        ]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }
        self.analysis_agent.process.return_value = {
            "answer": "It uses login routes.",
            "source_files": [],
            "chunk_count": 1,
            "error": None,
        }

        await self.orchestrator.process("What about login?", history=history)

        self.retrieval_agent.process.assert_awaited_once_with({"query": "What about login?"})
        self.analysis_agent.process.assert_awaited_once_with({
            "question": "What about login?",
            "retrieval_results": retrieval_results,
            "history": history,
        })

    async def test_complete_graph_execution_runs_retrieve_then_analyze(self):
        calls = []
        retrieval_results = [{"chunk_id": "chunk-1", "content": "code"}]

        async def retrieval_side_effect(payload):
            calls.append(("retrieve", payload))
            return {"results": retrieval_results, "error": None}

        async def analysis_side_effect(payload):
            calls.append(("analyze", payload))
            return {
                "answer": "The code is indexed.",
                "source_files": [],
                "chunk_count": 1,
                "error": None,
            }

        self.retrieval_agent.process.side_effect = retrieval_side_effect
        self.analysis_agent.process.side_effect = analysis_side_effect

        result = await self.orchestrator.process("What is indexed?")

        self.assertEqual(result.answer, "The code is indexed.")
        self.assertEqual(result.retrieved_chunks, 1)
        self.assertEqual(calls, [
            ("retrieve", {"query": "What is indexed?"}),
            ("analyze", {
                "question": "What is indexed?",
                "retrieval_results": retrieval_results,
                "history": [],
            }),
        ])

    async def test_process_rejects_empty_question(self):
        with self.assertRaises(ValueError) as context:
            await self.orchestrator.process("   ")

        self.assertIn("Question cannot be empty", str(context.exception))
        self.assertEqual(self.orchestrator.last_state["error"], "Question cannot be empty.")
        self.retrieval_agent.process.assert_not_awaited()
        self.analysis_agent.process.assert_not_awaited()

    async def test_process_raises_when_retrieval_returns_error(self):
        self.retrieval_agent.process.return_value = {
            "results": [],
            "error": "Required field 'repository_id' is missing or empty.",
        }

        with self.assertLogs("src.agents.orchestrator", level="ERROR") as logs:
            with self.assertRaises(RuntimeError) as context:
                await self.orchestrator.process("Where is login?")

        self.assertIn("Retrieval failed", str(context.exception))
        self.assertIn("repository_id", self.orchestrator.last_state["error"])
        self.assertIn("Retrieval failed during orchestration", "\n".join(logs.output))
        self.analysis_agent.process.assert_not_awaited()

    async def test_process_raises_when_retrieval_results_are_invalid(self):
        self.retrieval_agent.process.return_value = {
            "results": "not-a-list",
            "error": None,
        }

        with self.assertRaises(RuntimeError) as context:
            await self.orchestrator.process("Where is login?")

        self.assertIn("expected a list", str(context.exception))
        self.assertIn("expected a list", self.orchestrator.last_state["error"])
        self.analysis_agent.process.assert_not_awaited()

    async def test_process_raises_when_retrieval_agent_throws(self):
        self.retrieval_agent.process.side_effect = Exception("vector store offline")

        with self.assertRaises(RuntimeError) as context:
            await self.orchestrator.process("Where is login?")

        self.assertIn("Retrieval agent failed", str(context.exception))
        self.assertIn("vector store offline", self.orchestrator.last_state["error"])
        self.analysis_agent.process.assert_not_awaited()

    async def test_process_raises_when_analysis_returns_error(self):
        retrieval_results = [{"chunk_id": "chunk-1", "content": "code"}]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }
        self.analysis_agent.process.return_value = {
            "answer": "",
            "source_files": [],
            "chunk_count": 0,
            "error": "LLM unavailable",
        }

        with self.assertLogs("src.agents.orchestrator", level="ERROR") as logs:
            with self.assertRaises(RuntimeError) as context:
                await self.orchestrator.process("Explain it")

        self.assertIn("Analysis failed", str(context.exception))
        self.assertIn("LLM unavailable", self.orchestrator.last_state["error"])
        self.assertEqual(self.orchestrator.last_state["retrieval_results"], retrieval_results)
        self.assertIn("Analysis failed during orchestration", "\n".join(logs.output))

    async def test_process_raises_when_analysis_agent_throws(self):
        self.retrieval_agent.process.return_value = {
            "results": [],
            "error": None,
        }
        self.analysis_agent.process.side_effect = Exception("Gemini down")

        with self.assertRaises(RuntimeError) as context:
            await self.orchestrator.process("Explain it")

        self.assertIn("Analysis agent failed", str(context.exception))
        self.assertIn("Gemini down", self.orchestrator.last_state["error"])

    async def test_stream_yields_retrieval_event_then_analysis_events(self):
        retrieval_results = [{"chunk_id": "chunk-1", "content": "code"}]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }

        async def fake_stream_analysis(question, results, history=None):
            self.assertEqual(question, "Where is login?")
            self.assertEqual(results, retrieval_results)
            self.assertIsNone(history)
            yield {"type": "token", "text": "Login "}
            yield {"type": "token", "text": "is in auth.py."}
            yield {
                "type": "done",
                "answer": "Login is in auth.py.",
                "source_files": ["src/auth.py"],
                "chunk_count": 1,
            }

        self.analysis_agent.stream_analysis = fake_stream_analysis

        events = [event async for event in self.orchestrator.stream("Where is login?")]

        self.assertEqual(events[0], {"type": "retrieval", "retrieved_chunks": 1})
        self.assertEqual(events[1], {"type": "token", "text": "Login "})
        self.assertEqual(events[2], {"type": "token", "text": "is in auth.py."})
        self.assertEqual(events[3]["answer"], "Login is in auth.py.")
        self.retrieval_agent.process.assert_awaited_once_with({"query": "Where is login?"})

    async def test_stream_forwards_history_to_analysis_agent(self):
        retrieval_results = [{"chunk_id": "chunk-1", "content": "code"}]
        history = [{"role": "user", "content": "What does this repo do?"}]
        self.retrieval_agent.process.return_value = {
            "results": retrieval_results,
            "error": None,
        }

        async def fake_stream_analysis(question, results, history=None):
            self.assertEqual(history, [{"role": "user", "content": "What does this repo do?"}])
            yield {"type": "done", "answer": "Login is in auth.py.", "source_files": [], "chunk_count": 1}

        self.analysis_agent.stream_analysis = fake_stream_analysis

        events = [event async for event in self.orchestrator.stream("Where is login?", history=history)]

        self.assertEqual(events[-1]["answer"], "Login is in auth.py.")

    async def test_stream_rejects_empty_question(self):
        with self.assertRaises(ValueError):
            async for _ in self.orchestrator.stream("   "):
                pass
        self.retrieval_agent.process.assert_not_awaited()

    async def test_stream_raises_when_retrieval_returns_error(self):
        self.retrieval_agent.process.return_value = {
            "results": [],
            "error": "Required field 'repository_id' is missing or empty.",
        }

        with self.assertRaises(RuntimeError) as context:
            async for _ in self.orchestrator.stream("Where is login?"):
                pass

        self.assertIn("Retrieval failed", str(context.exception))

    def test_agent_state_typing_exports_expected_keys(self):
        state: AgentState = {
            "question": "What does this do?",
            "retrieval_results": [],
            "analysis_result": None,
            "error": None,
        }

        self.assertEqual(state["question"], "What does this do?")


if __name__ == "__main__":
    unittest.main()
