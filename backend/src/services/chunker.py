import ast
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class CodeFile:
    """
    Represents a code file loaded from a repository.
    """
    file_path: str
    content: str
    language: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Chunk:
    """
    Represents a logical chunk of a code file (e.g. class, function, or entire file).
    """
    chunk_id: str
    file_path: str
    content: str
    chunk_type: str  # "class", "function", or "file"
    metadata: Dict[str, Any] = field(default_factory=dict)


class CodeChunker:
    """
    Handles chunking of CodeFile objects into smaller logical code chunks.
    For Python files, it extracts classes and functions as individual chunks.
    For unsupported languages or parsing failures, it falls back to file-level chunks.
    """

    def __init__(self, max_chunk_chars: int = 4000, overlap_chars: int = 200):
        if max_chunk_chars <= 0:
            raise ValueError("max_chunk_chars must be positive.")
        if overlap_chars < 0:
            raise ValueError("overlap_chars cannot be negative.")
        if overlap_chars >= max_chunk_chars:
            raise ValueError("overlap_chars must be less than max_chunk_chars.")

        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars

    def chunk_file(self, code_file: CodeFile) -> List[Chunk]:
        """
        Chunks a given CodeFile object based on its language and contents.
        
        Args:
            code_file: The CodeFile object to chunk.
            
        Returns:
            A list of Chunk objects.
        """
        chunks: List[Chunk]
        if not code_file.content or not code_file.content.strip():
            logger.info("Empty code file content for: %s", code_file.file_path)
            chunks = [self._create_file_chunk(code_file, "file")]
            return self._finalize_chunks(chunks, code_file.file_path)

        if code_file.language.lower() == "python":
            try:
                chunks = self._chunk_python_file(code_file)
            except Exception as e:
                logger.warning(
                    "Python parsing failed for %s (falling back to file-level chunk): %s", 
                    code_file.file_path, 
                    e
                )
                chunks = [self._create_file_chunk(code_file, "file")]
        else:
            # Use sliding-window chunking for non-Python files so large files
            # are split into manageable, overlapping chunks rather than stored
            # as a single monolithic blob that dilutes the embedding signal.
            chunks = self._chunk_generic_file(code_file)

        return self._finalize_chunks(chunks, code_file.file_path)

    @staticmethod
    def _add_file_header(file_path: str, content: str) -> str:
        """Prepend a file-path comment to chunk content.

        This embeds file-location semantics directly into the chunk text so
        that queries mentioning a file name can retrieve the correct chunks
        even when the code body itself does not repeat the filename.
        """
        return f"# File: {file_path}\n{content}"

    def _create_file_chunk(self, code_file: CodeFile, chunk_type: str) -> Chunk:
        """Helper to create a standard file-level chunk."""
        content_with_header = self._add_file_header(code_file.file_path, code_file.content)
        chunk_id = self._generate_chunk_id(code_file.file_path, chunk_type, content_with_header)

        # Merge original metadata with any extra chunk metadata
        merged_metadata = dict(code_file.metadata)
        merged_metadata.update({
            "chunk_type": chunk_type,
            "start_line": 1,
            "end_line": len(code_file.content.splitlines()) if code_file.content else 1,
        })

        return Chunk(
            chunk_id=chunk_id,
            file_path=code_file.file_path,
            content=content_with_header,
            chunk_type=chunk_type,
            metadata=merged_metadata,
        )

    def _chunk_generic_file(self, code_file: CodeFile) -> List[Chunk]:
        """Sliding-window chunking for non-Python (and non-AST-parseable) files.

        Instead of emitting one huge chunk per file, this method applies the
        same character-level split-with-overlap strategy used by
        ``_split_oversized_chunk`` so every window produces a focused embedding.
        """
        content_with_header = self._add_file_header(code_file.file_path, code_file.content)

        # If the whole file fits in one chunk, emit a single file chunk.
        if len(content_with_header) <= self.max_chunk_chars:
            return [self._create_file_chunk(code_file, "file")]

        lines = code_file.content.splitlines()
        total_lines = len(lines)
        sub_texts = self._split_text_with_overlap(code_file.content)
        total_parts = len(sub_texts)
        chunks: List[Chunk] = []

        char_offset = 0
        for index, sub_text in enumerate(sub_texts, start=1):
            start_line = code_file.content[:char_offset].count("\n") + 1
            end_line = min(start_line + sub_text.count("\n"), total_lines)

            sub_with_header = self._add_file_header(code_file.file_path, sub_text)
            suffix = f"part:{index}/{total_parts}"
            chunk_id = self._generate_chunk_id(
                code_file.file_path, "file", sub_with_header, suffix=suffix
            )

            merged_metadata = dict(code_file.metadata)
            merged_metadata.update({
                "chunk_type": "file",
                "start_line": start_line,
                "end_line": end_line,
                "chunk_part": index,
                "chunk_parts": total_parts,
            })

            chunks.append(Chunk(
                chunk_id=chunk_id,
                file_path=code_file.file_path,
                content=sub_with_header,
                chunk_type="file",
                metadata=merged_metadata,
            ))

            # Advance offset accounting for overlap on the next window
            char_offset = max(char_offset + len(sub_text) - self.overlap_chars, 0)

        return chunks

    def _generate_chunk_id(
        self,
        file_path: str,
        chunk_type: str,
        content: str,
        suffix: Optional[str] = None
    ) -> str:
        """Generates a unique, stable SHA-256 hash for the chunk."""
        hasher = hashlib.sha256()
        hasher.update(file_path.encode("utf-8"))
        hasher.update(chunk_type.encode("utf-8"))
        hasher.update(content.encode("utf-8"))
        if suffix:
            hasher.update(suffix.encode("utf-8"))
        return hasher.hexdigest()

    def _finalize_chunks(self, chunks: List[Chunk], file_path: str) -> List[Chunk]:
        self._log_chunk_size_diagnostics(chunks, file_path)
        oversized_chunks = [
            chunk for chunk in chunks if len(chunk.content) > self.max_chunk_chars
        ]
        if oversized_chunks:
            oversized_summary = [
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_type": chunk.chunk_type,
                    "name": chunk.metadata.get("name"),
                    "start_line": chunk.metadata.get("start_line"),
                    "end_line": chunk.metadata.get("end_line"),
                    "chars": len(chunk.content)
                }
                for chunk in oversized_chunks
            ]
            logger.warning(
                "Found %d chunks exceeding %d characters in %s: %s",
                len(oversized_chunks),
                self.max_chunk_chars,
                file_path,
                oversized_summary
            )

        split_chunks: List[Chunk] = []
        for chunk in chunks:
            split_chunks.extend(self._split_oversized_chunk(chunk))

        if len(split_chunks) != len(chunks):
            self._log_chunk_size_diagnostics(split_chunks, f"{file_path} after splitting")

        return split_chunks

    def _log_chunk_size_diagnostics(self, chunks: List[Chunk], context: str) -> None:
        if not chunks:
            logger.info("Chunk size diagnostics for %s: no chunks generated", context)
            return

        sizes = [len(chunk.content) for chunk in chunks]
        average_size = sum(sizes) / len(sizes)
        largest_size = max(sizes)
        top_chunks = sorted(
            chunks,
            key=lambda chunk: len(chunk.content),
            reverse=True
        )[:10]
        top_summary = [
            {
                "rank": index + 1,
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "name": chunk.metadata.get("name"),
                "start_line": chunk.metadata.get("start_line"),
                "end_line": chunk.metadata.get("end_line"),
                "chars": len(chunk.content)
            }
            for index, chunk in enumerate(top_chunks)
        ]

        logger.info(
            "Chunk size diagnostics for %s: count=%d, average_chars=%.2f, "
            "largest_chars=%d, top_10_largest=%s",
            context,
            len(chunks),
            average_size,
            largest_size,
            top_summary
        )

    def _split_oversized_chunk(self, chunk: Chunk) -> List[Chunk]:
        if len(chunk.content) <= self.max_chunk_chars:
            return [chunk]

        subcontents = self._split_text_with_overlap(chunk.content)
        total_parts = len(subcontents)
        subchunks: List[Chunk] = []

        for index, subcontent in enumerate(subcontents, start=1):
            metadata = dict(chunk.metadata)
            metadata.update({
                "parent_chunk_id": chunk.chunk_id,
                "chunk_part": index,
                "chunk_parts": total_parts,
                "split_from_oversized": True
            })

            suffix = f"part:{index}/{total_parts}"
            subchunks.append(Chunk(
                chunk_id=self._generate_chunk_id(
                    chunk.file_path,
                    chunk.chunk_type,
                    subcontent,
                    suffix=suffix
                ),
                file_path=chunk.file_path,
                content=subcontent,
                chunk_type=chunk.chunk_type,
                metadata=metadata
            ))

        return subchunks

    def _split_text_with_overlap(self, text: str) -> List[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        chunks: List[str] = []
        start = 0
        text_length = len(text)

        while start < text_length:
            hard_end = min(start + self.max_chunk_chars, text_length)
            end = self._find_line_break_before(text, start, hard_end)
            if end <= start:
                end = hard_end

            chunks.append(text[start:end])
            if end >= text_length:
                break

            next_start = max(0, end - self.overlap_chars)
            if next_start <= start:
                next_start = end
            start = next_start

        return chunks

    def _find_line_break_before(self, text: str, start: int, hard_end: int) -> int:
        if hard_end >= len(text):
            return hard_end

        break_at = text.rfind("\n", start + 1, hard_end + 1)
        if break_at == -1:
            return hard_end
        return break_at + 1

    def _chunk_python_file(self, code_file: CodeFile) -> List[Chunk]:
        """Parses a Python file using AST and extracts classes and functions as chunks."""
        tree = ast.parse(code_file.content)
        lines = code_file.content.splitlines()
        chunks: List[Chunk] = []

        # We scan for top-level ClassDef, FunctionDef, and AsyncFunctionDef
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                # Extract text lines for this node
                # Note: lineno in Python is 1-indexed.
                # end_lineno in Python 3.8+ is 1-indexed.
                start_line = node.lineno
                
                # If there are decorators, start from the first decorator's line
                if hasattr(node, "decorator_list") and node.decorator_list:
                    dec_linenos = [dec.lineno for dec in node.decorator_list if hasattr(dec, "lineno")]
                    if dec_linenos:
                        start_line = min(start_line, min(dec_linenos))
                
                end_line = getattr(node, "end_lineno", len(lines))
                
                # Retrieve the lines corresponding to the definition
                # lines are 0-indexed, so we do start_line - 1 to end_line
                node_lines = lines[start_line - 1 : end_line]
                node_content = "\n".join(node_lines)

                chunk_type = "class" if isinstance(node, ast.ClassDef) else "function"

                # Prepend file-path header so the embedding carries location context.
                content_with_header = self._add_file_header(code_file.file_path, node_content)
                chunk_id = self._generate_chunk_id(code_file.file_path, chunk_type, content_with_header)

                # Merge metadata
                merged_metadata = dict(code_file.metadata)
                merged_metadata.update({
                    "name": node.name,
                    "chunk_type": chunk_type,
                    "start_line": start_line,
                    "end_line": end_line,
                })

                chunks.append(Chunk(
                    chunk_id=chunk_id,
                    file_path=code_file.file_path,
                    content=content_with_header,
                    chunk_type=chunk_type,
                    metadata=merged_metadata,
                ))

        # If no classes or functions were found in Python code, fall back to file-level chunk
        if not chunks:
            logger.info("No classes or functions found in Python file %s, returning file chunk.", code_file.file_path)
            return [self._create_file_chunk(code_file, "file")]

        return chunks
