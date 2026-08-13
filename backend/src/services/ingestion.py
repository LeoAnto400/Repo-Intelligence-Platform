import logging
from typing import List

from src.services.chunker import Chunk

logger = logging.getLogger(__name__)


def filter_chunks_for_embedding(chunks: List[Chunk]) -> List[Chunk]:
    """
    Remove chunks that cannot be embedded while logging enough context to debug
    the source file and generated chunk identity.
    """
    valid_chunks: List[Chunk] = []
    skipped_count = 0

    for index, chunk in enumerate(chunks):
        if chunk.content and chunk.content.strip():
            valid_chunks.append(chunk)
            continue

        skipped_count += 1
        logger.warning(
            "Skipping empty chunk before embedding: chunk_index=%d, "
            "file_path=%s, chunk_type=%s, chunk_id=%s",
            index,
            chunk.file_path,
            chunk.chunk_type,
            chunk.chunk_id,
        )

    logger.info(
        "Embedding chunk validation complete: total_chunks=%d, valid_chunks=%d, "
        "skipped_empty_chunks=%d",
        len(chunks),
        len(valid_chunks),
        skipped_count,
    )

    if chunks and not valid_chunks:
        raise RuntimeError(
            f"All {len(chunks)} generated chunks were empty or whitespace-only; "
            "nothing can be embedded."
        )

    return valid_chunks
