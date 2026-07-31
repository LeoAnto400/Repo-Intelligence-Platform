import unittest
from unittest.mock import MagicMock

from src.agents.analysis import AnalysisAgent, AnalysisResult
from src.agents.retrieval import RetrievalResult
from src.services.gemini import GeminiService


class TestAnalysisResult(unittest.TestCase):
    def test_analysis_result_serialization(self):
        result = AnalysisResult(
            answer="Use the auth middleware.",
            source_files=["src/auth.py"],
            chunk_count=1
        )

        self.assertEqual(result.to_dict(), {
            "answer": "Use the auth middleware.",
            "source_files": ["src/auth.py"],
            "chunk_count": 1
        })


class TestAnalysisAgent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_gemini_service = MagicMock(spec=GeminiService)
        self.agent = AnalysisAgent(gemini_service=self.mock_gemini_service)

    async def test_generate_analysis_success(self):
        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                file_path="src/auth.py",
                content="def authenticate(token):\n    return validate(token)",
                score=0.1,
                metadata={
                    "chunk_type": "function",
                    "name": "authenticate",
                    "start_line": 10,
                    "end_line": 11
                }
            ),
            RetrievalResult(
                chunk_id="chunk-2",
                file_path="src/routes.py",
                content="router.add_route('/login', login)",
                score=0.2,
                metadata={"chunk_type": "file"}
            ),
            RetrievalResult(
                chunk_id="chunk-3",
                file_path="src/auth.py",
                content="def validate(token):\n    return token == 'ok'",
                score=0.3,
                metadata={"chunk_type": "function", "name": "validate"}
            )
        ]
        self.mock_gemini_service.generate_content.return_value = "Authentication validates tokens."

        result = await self.agent.generate_analysis(
            question="How does authentication work?",
            retrieval_results=retrieval_results
        )

        self.assertEqual(result.answer, "Authentication validates tokens.")
        self.assertEqual(result.source_files, ["src/auth.py", "src/routes.py"])
        self.assertEqual(result.chunk_count, 3)

        self.mock_gemini_service.generate_content.assert_called_once()
        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        self.assertIn("You are a senior software engineer.", prompt)
        self.assertIn("Answer the user's question using ONLY the provided repository context.", prompt)
        self.assertIn("If the answer cannot be determined from the context, say so.", prompt)
        self.assertIn("Repository Context:", prompt)
        self.assertIn("[Chunk 1] | file=src/auth.py:10-11 | type=function | name=authenticate", prompt)
        self.assertIn("def authenticate(token):", prompt)
        self.assertIn("Question:\nHow does authentication work?", prompt)

    async def test_process_accepts_retrieval_result_dicts(self):
        self.mock_gemini_service.generate_content.return_value = "The app uses route handlers."
        payload = {
            "question": "How are routes handled?",
            "retrieval_results": [
                {
                    "chunk_id": "chunk-1",
                    "file_path": "src/routes.py",
                    "content": "router.add_route('/health', health)",
                    "score": 0.12,
                    "metadata": {"chunk_type": "file"}
                }
            ]
        }

        response = await self.agent.process(payload)

        self.assertIsNone(response["error"])
        self.assertEqual(response["answer"], "The app uses route handlers.")
        self.assertEqual(response["source_files"], ["src/routes.py"])
        self.assertEqual(response["chunk_count"], 1)

    async def test_process_accepts_query_alias_and_results_alias(self):
        self.mock_gemini_service.generate_content.return_value = "It prints hello."
        payload = {
            "query": "What does this code do?",
            "results": [
                {
                    "id": "chunk-1",
                    "document": "print('hello')",
                    "metadata": {"path": "src/main.py"}
                }
            ]
        }

        response = await self.agent.process(payload)

        self.assertIsNone(response["error"])
        self.assertEqual(response["answer"], "It prints hello.")
        self.assertEqual(response["source_files"], ["src/main.py"])
        self.assertEqual(response["chunk_count"], 1)

    async def test_empty_context_still_calls_gemini_with_no_context_message(self):
        self.mock_gemini_service.generate_content.return_value = "Cannot determine from the context."

        result = await self.agent.generate_analysis(
            question="What database is used?",
            retrieval_results=[]
        )

        self.assertEqual(result.answer, "Cannot determine from the context.")
        self.assertEqual(result.source_files, [])
        self.assertEqual(result.chunk_count, 0)

        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        self.assertIn("No repository context was retrieved.", prompt)

    async def test_process_validation_errors(self):
        missing_question = await self.agent.process({"retrieval_results": []})
        self.assertEqual(missing_question["answer"], "")
        self.assertIn("question", missing_question["error"])

        missing_results = await self.agent.process({"question": "What happens?"})
        self.assertEqual(missing_results["answer"], "")
        self.assertIn("retrieval_results", missing_results["error"])

        invalid_results = await self.agent.process({
            "question": "What happens?",
            "retrieval_results": "not-a-list"
        })
        self.assertEqual(invalid_results["answer"], "")
        self.assertIn("retrieval_results", invalid_results["error"])

    async def test_process_handles_gemini_failure(self):
        self.mock_gemini_service.generate_content.side_effect = Exception("Gemini down")
        payload = {
            "question": "Explain this",
            "retrieval_results": [
                RetrievalResult(
                    chunk_id="chunk-1",
                    file_path="src/main.py",
                    content="print('hello')",
                    score=0.1,
                    metadata={}
                )
            ]
        }

        response = await self.agent.process(payload)

        self.assertEqual(response["answer"], "")
        self.assertEqual(response["source_files"], [])
        self.assertEqual(response["chunk_count"], 0)
        self.assertIn("Analysis failed", response["error"])

    async def test_stream_analysis_yields_tokens_then_done_event(self):
        async def fake_stream(prompt):
            yield "Auth "
            yield "uses login."

        self.mock_gemini_service.generate_content_stream = fake_stream

        retrieval_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                file_path="src/auth.py",
                content="def authenticate(token):\n    return validate(token)",
                score=0.1,
                metadata={"chunk_type": "function", "name": "authenticate"},
            )
        ]

        events = [
            event
            async for event in self.agent.stream_analysis("How does auth work?", retrieval_results)
        ]

        self.assertEqual(events[0], {"type": "token", "text": "Auth "})
        self.assertEqual(events[1], {"type": "token", "text": "uses login."})
        self.assertEqual(events[2], {
            "type": "done",
            "answer": "Auth uses login.",
            "source_files": ["src/auth.py"],
            "chunk_count": 1,
        })

    async def test_stream_analysis_accepts_retrieval_result_dicts(self):
        async def fake_stream(prompt):
            yield "It prints hello."

        self.mock_gemini_service.generate_content_stream = fake_stream

        events = [
            event
            async for event in self.agent.stream_analysis(
                "What does this do?",
                [{"id": "chunk-1", "document": "print('hello')", "metadata": {"path": "src/main.py"}}],
            )
        ]

        self.assertEqual(events[-1]["answer"], "It prints hello.")
        self.assertEqual(events[-1]["source_files"], ["src/main.py"])

    async def test_generate_analysis_includes_conversation_history_in_prompt(self):
        self.mock_gemini_service.generate_content.return_value = "It also validates the session."
        history = [
            {"role": "user", "content": "How does authentication work?"},
            {"role": "assistant", "content": "It validates tokens via authenticate()."},
        ]

        await self.agent.generate_analysis(
            question="What else does it do?",
            retrieval_results=[],
            history=history,
        )

        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        self.assertIn("Conversation so far", prompt)
        self.assertIn("Developer: How does authentication work?", prompt)
        self.assertIn("Assistant: It validates tokens via authenticate().", prompt)
        self.assertIn("Question:\nWhat else does it do?", prompt)

    async def test_generate_analysis_omits_history_section_when_no_history(self):
        self.mock_gemini_service.generate_content.return_value = "Answer."

        await self.agent.generate_analysis(
            question="What does it do?", retrieval_results=[], history=None
        )

        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        self.assertNotIn("Conversation so far", prompt)

    async def test_generate_analysis_truncates_long_history_messages_and_caps_count(self):
        self.mock_gemini_service.generate_content.return_value = "Answer."
        long_message = "x" * 2000
        history = [{"role": "user", "content": f"turn-{i}"} for i in range(20)]
        history.append({"role": "user", "content": long_message})

        await self.agent.generate_analysis(
            question="What does it do?", retrieval_results=[], history=history
        )

        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        # Only the most recent MAX_HISTORY_MESSAGES turns are included.
        self.assertNotIn("turn-0", prompt)
        self.assertIn(f"turn-{20 - AnalysisAgent.MAX_HISTORY_MESSAGES + 1}", prompt)
        # Long messages are truncated rather than included in full.
        self.assertIn("x" * AnalysisAgent.MAX_HISTORY_MESSAGE_CHARS + "...", prompt)
        self.assertNotIn("x" * (AnalysisAgent.MAX_HISTORY_MESSAGE_CHARS + 1), prompt)

    async def test_process_forwards_history_from_payload(self):
        self.mock_gemini_service.generate_content.return_value = "It also validates the session."
        payload = {
            "question": "What else does it do?",
            "retrieval_results": [],
            "history": [{"role": "user", "content": "How does authentication work?"}],
        }

        response = await self.agent.process(payload)

        self.assertIsNone(response["error"])
        prompt = self.mock_gemini_service.generate_content.call_args.args[0]
        self.assertIn("Developer: How does authentication work?", prompt)

    async def test_stream_analysis_includes_conversation_history_in_prompt(self):
        captured_prompt = {}

        async def fake_stream(prompt):
            captured_prompt["value"] = prompt
            yield "Answer."

        self.mock_gemini_service.generate_content_stream = fake_stream
        history = [{"role": "assistant", "content": "It's a FastAPI backend."}]

        events = [
            event
            async for event in self.agent.stream_analysis("What does it use for auth?", [], history=history)
        ]

        self.assertEqual(events[-1]["answer"], "Answer.")
        self.assertIn("Assistant: It's a FastAPI backend.", captured_prompt["value"])


if __name__ == "__main__":
    unittest.main()
