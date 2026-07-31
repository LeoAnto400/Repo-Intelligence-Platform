import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from src.agents.base import BaseAgent
from src.agents.retrieval import RetrievalResult
from src.services.gemini import GeminiService

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """
    Domain model for a synthesized repository answer and its supporting context.
    """
    answer: str
    source_files: List[str]
    chunk_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "source_files": self.source_files,
            "chunk_count": self.chunk_count
        }


class AnalysisAgent(BaseAgent):
    """
    AnalysisAgent generates natural language explanations from retrieved code chunks.
    """

    # Conversation history is only used to help the model resolve references
    # in the latest question (e.g. "it", "that function") - kept short so it
    # doesn't crowd out the repository context, which remains the sole source
    # of truth for the answer itself.
    MAX_HISTORY_MESSAGES = 8
    MAX_HISTORY_MESSAGE_CHARS = 1500

    def __init__(self, gemini_service: GeminiService):
        """
        Initialize AnalysisAgent with dependencies.

        Args:
            gemini_service: Service wrapper for prompt generations using Gemini LLM models.
        """
        self.gemini_service = gemini_service
        logger.info("AnalysisAgent initialized.")

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze retrieved repository context against a user question.

        Expected payload format:
        {
            "question": str,  # "query" is also accepted for compatibility
            "retrieval_results": List[RetrievalResult | Dict[str, Any]]
        }

        Returns:
            Dict containing answer, source_files, chunk_count, and error.
        """
        logger.info("Processing analysis agent task.")

        question = payload.get("question") or payload.get("query")
        raw_results = payload.get("retrieval_results")
        if raw_results is None:
            raw_results = payload.get("retrieved_context")
        if raw_results is None:
            raw_results = payload.get("results")
        history = payload.get("history")

        if not question or not isinstance(question, str) or not question.strip():
            logger.error("Missing or invalid question in analysis payload.")
            return {
                "answer": "",
                "source_files": [],
                "chunk_count": 0,
                "error": "Required field 'question' is missing or empty."
            }

        if raw_results is None or not isinstance(raw_results, list):
            logger.error("Missing or invalid retrieval results in analysis payload.")
            return {
                "answer": "",
                "source_files": [],
                "chunk_count": 0,
                "error": "Required field 'retrieval_results' must be a list."
            }

        try:
            retrieval_results = self._normalize_retrieval_results(raw_results)
            result = await self.generate_analysis(question.strip(), retrieval_results, history)
            return {**result.to_dict(), "error": None}
        except Exception as e:
            logger.exception("An exception occurred during analysis process execution")
            return {
                "answer": "",
                "source_files": [],
                "chunk_count": 0,
                "error": f"Analysis failed: {str(e)}"
            }

    async def generate_analysis(
        self,
        question: str,
        retrieval_results: List[RetrievalResult],
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisResult:
        """
        Generate a natural language explanation from retrieved repository chunks.

        Args:
            question: Question asked by the user.
            retrieval_results: Retrieved code chunks to use as the only answer context.
            history: Prior conversation turns (``{"role": ..., "content": ...}``),
                most recent last, used only to resolve references in ``question``.

        Returns:
            AnalysisResult containing the answer and source summary.
        """
        logger.info(
            "Generating analysis for question using %d retrieved chunks.",
            len(retrieval_results)
        )

        context = self._build_context_block(retrieval_results)
        prompt = self._build_prompt(question, context, history)
        logger.debug("Calling GeminiService.generate_content for analysis.")

        answer = self.gemini_service.generate_content(prompt)
        source_files = self._source_files(retrieval_results)

        logger.info(
            "Analysis generated successfully. chunk_count=%d, source_file_count=%d",
            len(retrieval_results),
            len(source_files)
        )
        return AnalysisResult(
            answer=answer,
            source_files=source_files,
            chunk_count=len(retrieval_results)
        )

    async def stream_analysis(
        self,
        question: str,
        retrieval_results: List[Any],
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Streaming counterpart to :meth:`process`. Yields ``{"type": "token",
        "text": ...}`` events as the answer is generated, followed by a final
        ``{"type": "done", "answer": ..., "source_files": ..., "chunk_count":
        ...}`` event carrying the same payload shape ``process()`` returns.
        """
        normalized = self._normalize_retrieval_results(retrieval_results)
        context = self._build_context_block(normalized)
        prompt = self._build_prompt(question, context, history)
        source_files = self._source_files(normalized)

        chunks: List[str] = []
        async for text in self.gemini_service.generate_content_stream(prompt):
            chunks.append(text)
            yield {"type": "token", "text": text}

        logger.info(
            "Streaming analysis complete. chunk_count=%d, source_file_count=%d",
            len(normalized),
            len(source_files),
        )
        yield {
            "type": "done",
            "answer": "".join(chunks),
            "source_files": source_files,
            "chunk_count": len(normalized),
        }

    def _normalize_retrieval_results(self, raw_results: List[Any]) -> List[RetrievalResult]:
        retrieval_results: List[RetrievalResult] = []

        for index, raw_result in enumerate(raw_results):
            if isinstance(raw_result, RetrievalResult):
                retrieval_results.append(raw_result)
                continue

            if not isinstance(raw_result, dict):
                raise ValueError(f"Retrieval result at index {index} must be a RetrievalResult or dict.")

            metadata = raw_result.get("metadata") or {}
            file_path = (
                raw_result.get("file_path")
                or metadata.get("file_path")
                or metadata.get("file")
                or metadata.get("path")
                or ""
            )
            retrieval_results.append(
                RetrievalResult(
                    chunk_id=raw_result.get("chunk_id") or raw_result.get("id") or "",
                    file_path=file_path,
                    content=raw_result.get("content") or raw_result.get("document") or "",
                    score=float(raw_result.get("score", 0.0) or 0.0),
                    metadata=metadata
                )
            )

        return retrieval_results

    def _build_context_block(self, retrieval_results: List[RetrievalResult]) -> str:
        if not retrieval_results:
            return "No repository context was retrieved."

        context_blocks: List[str] = []
        for index, result in enumerate(retrieval_results, start=1):
            metadata = result.metadata or {}
            chunk_type = metadata.get("chunk_type") or "unknown"
            name = metadata.get("name") or ""
            start_line = metadata.get("start_line")
            end_line = metadata.get("end_line")
            line_range = ""
            if start_line is not None and end_line is not None:
                line_range = f":{start_line}-{end_line}"

            heading_parts = [
                f"[Chunk {index}]",
                f"file={result.file_path or 'unknown'}{line_range}",
                f"type={chunk_type}"
            ]
            if name:
                heading_parts.append(f"name={name}")

            context_blocks.append(
                "\n".join([
                    " | ".join(heading_parts),
                    result.content
                ])
            )

        return "\n\n".join(context_blocks)

    def _build_prompt(
        self,
        question: str,
        context: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        history_block = self._build_history_block(history)
        history_section = (
            "Conversation so far (most recent last - refer to it only to resolve what "
            f"the question below means, e.g. pronouns like \"it\"; the repository "
            f"context above remains the only source of facts for the answer):\n"
            f"{history_block}\n\n"
            if history_block else ""
        )
        return (
            "You are a senior software engineer.\n\n"
            "Answer the user's question using ONLY the provided repository context.\n\n"
            "If the answer cannot be determined from the context, say so.\n\n"
            f"{history_section}"
            "Repository Context:\n"
            f"{context}\n\n"
            "Question:\n"
            f"{question}"
        )

    def _build_history_block(self, history: Optional[List[Dict[str, Any]]]) -> str:
        if not history:
            return ""

        lines: List[str] = []
        for turn in history[-self.MAX_HISTORY_MESSAGES:]:
            if not isinstance(turn, dict):
                continue
            content = turn.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            content = content.strip()
            if len(content) > self.MAX_HISTORY_MESSAGE_CHARS:
                content = content[: self.MAX_HISTORY_MESSAGE_CHARS] + "..."
            speaker = "Assistant" if turn.get("role") == "assistant" else "Developer"
            lines.append(f"{speaker}: {content}")

        return "\n".join(lines)

    def _source_files(self, retrieval_results: List[RetrievalResult]) -> List[str]:
        seen = set()
        source_files: List[str] = []

        for result in retrieval_results:
            if result.file_path and result.file_path not in seen:
                seen.add(result.file_path)
                source_files.append(result.file_path)

        return source_files

    async def generate_repository_overview(
        self, repository: str, chunk_samples: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate a short AI summary, detected technologies, and suggested
        questions for a repository from a sample of its already-ingested
        chunks. Works from vector-store content alone, so it applies equally
        to repositories re-activated without their original GitHub URL.
        """
        prompt = self._build_overview_prompt(repository, chunk_samples)
        try:
            raw = self.gemini_service.generate_content(prompt)
        except Exception:
            logger.exception("Failed to generate repository overview for %s", repository)
            return {"summary": None, "technologies": [], "suggested_questions": []}
        return self._parse_overview_response(raw)

    def _build_overview_prompt(self, repository: str, chunk_samples: List[Dict[str, Any]]) -> str:
        seen_files = set()
        file_blocks: List[str] = []
        for chunk in chunk_samples:
            metadata = chunk.get("metadata") or {}
            file_path = metadata.get("file_path") or "unknown"
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            content = (chunk.get("document") or "")[:800]
            file_blocks.append(f"--- {file_path} ---\n{content}")
            if len(file_blocks) >= 12:
                break

        context = "\n\n".join(file_blocks) if file_blocks else "No source content is available."

        return (
            "You are a senior software engineer producing a short repository overview "
            "for a codebase search tool. Base your answer ONLY on the code samples below; "
            "do not invent details the samples do not support.\n\n"
            f"Repository: {repository}\n\n"
            "Code samples:\n"
            f"{context}\n\n"
            "Respond with ONLY a valid JSON object (no markdown fences, no commentary) "
            "matching this exact shape:\n"
            "{\n"
            '  "summary": "2-4 sentence plain-English description of what this project does",\n'
            '  "technologies": ["short list of languages/frameworks/libraries actually used"],\n'
            '  "suggested_questions": ["4 short questions a developer could ask a chat '
            'assistant about this codebase"]\n'
            "}"
        )

    def _parse_overview_response(self, raw: str) -> Dict[str, Any]:
        fallback: Dict[str, Any] = {"summary": None, "technologies": [], "suggested_questions": []}
        if not raw:
            return fallback

        text = raw.strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return fallback

        try:
            data = json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            return fallback
        if not isinstance(data, dict):
            return fallback

        summary = data.get("summary")
        technologies = data.get("technologies")
        suggested_questions = data.get("suggested_questions")

        return {
            "summary": summary if isinstance(summary, str) and summary.strip() else None,
            "technologies": (
                [t for t in technologies if isinstance(t, str) and t.strip()]
                if isinstance(technologies, list) else []
            ),
            "suggested_questions": (
                [q for q in suggested_questions if isinstance(q, str) and q.strip()]
                if isinstance(suggested_questions, list) else []
            ),
        }

    async def generate_commit_summary(self, commit: Dict[str, Any]) -> str:
        """
        Generate a short plain-English summary of a single commit from its
        message and diff (already captured during repository ingestion, so
        this needs no additional GitHub calls).
        """
        prompt = self._build_commit_summary_prompt(commit)
        raw = self.gemini_service.generate_content(prompt)
        return raw.strip()

    def _build_commit_summary_prompt(self, commit: Dict[str, Any]) -> str:
        message = commit.get("message") or "(no commit message)"
        author = commit.get("author") or "unknown"
        additions = commit.get("additions") or 0
        deletions = commit.get("deletions") or 0
        files_changed = commit.get("filesChanged") or 0
        diff = (commit.get("diff") or "").strip()
        diff_block = diff if diff else "No diff content is available for this commit."

        return (
            "You are a senior software engineer summarizing a git commit for a teammate.\n\n"
            f"Author: {author}\n"
            f"Commit message: {message}\n"
            f"Files changed: {files_changed} (+{additions}/-{deletions})\n\n"
            "Diff (may be limited to a subset of the changed files):\n"
            f"{diff_block}\n\n"
            "Write a concise 2-4 sentence plain-English summary of what this commit actually "
            "changes and why, based only on the message and diff above. If the diff is empty, "
            "summarize from the commit message alone and say that no diff was available."
        )
