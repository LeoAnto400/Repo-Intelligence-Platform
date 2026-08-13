import unittest

from src.services.chunker import Chunk
from src.services.ingestion import filter_chunks_for_embedding


class TestIngestionValidation(unittest.TestCase):
    def test_filter_chunks_for_embedding_skips_blank_chunks_with_diagnostics(self):
        chunks = [
            Chunk(
                chunk_id="valid-1",
                file_path="src/valid.py",
                content="def ok():\n    return True",
                chunk_type="function",
            ),
            Chunk(
                chunk_id="empty-1",
                file_path="src/empty.py",
                content="",
                chunk_type="file",
            ),
            Chunk(
                chunk_id="blank-1",
                file_path="src/blank.py",
                content="   \n\t",
                chunk_type="file",
            ),
            Chunk(
                chunk_id="valid-2",
                file_path="README.md",
                content="# Project",
                chunk_type="file",
            ),
        ]

        with self.assertLogs("src.services.ingestion", level="INFO") as logs:
            valid_chunks = filter_chunks_for_embedding(chunks)

        self.assertEqual([chunk.chunk_id for chunk in valid_chunks], ["valid-1", "valid-2"])
        log_output = "\n".join(logs.output)
        self.assertIn("chunk_index=1", log_output)
        self.assertIn("file_path=src/empty.py", log_output)
        self.assertIn("chunk_type=file", log_output)
        self.assertIn("chunk_id=empty-1", log_output)
        self.assertIn("chunk_index=2", log_output)
        self.assertIn("file_path=src/blank.py", log_output)
        self.assertIn("chunk_id=blank-1", log_output)
        self.assertIn("skipped_empty_chunks=2", log_output)

    def test_filter_chunks_for_embedding_fails_when_all_chunks_are_blank(self):
        chunks = [
            Chunk(
                chunk_id="empty-1",
                file_path="src/empty.py",
                content="",
                chunk_type="file",
            )
        ]

        with self.assertLogs("src.services.ingestion", level="INFO"):
            with self.assertRaises(RuntimeError) as context:
                filter_chunks_for_embedding(chunks)

        self.assertIn("All 1 generated chunks were empty", str(context.exception))


if __name__ == "__main__":
    unittest.main()
