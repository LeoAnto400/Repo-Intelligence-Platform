#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import re
import sys
from typing import Any, Dict, List

# Ensure src directory is in Python path when running this script directly.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agents.analysis import AnalysisAgent
from src.agents.retrieval import RetrievalAgent
from src.core.config import settings
from src.db.chroma import VectorStoreManager
from src.services.chunker import CodeChunker, CodeFile
from src.services.gemini import GeminiService
from src.services.github import GitHubService
from src.services.ingestion import filter_chunks_for_embedding

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def collection_name_from_repo_url(repo_url: str) -> str:
    repo_name_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_url.rstrip("/").split("/")[-1])
    repo_name_clean = re.sub(r"_+", "_", repo_name_clean).strip("_")
    if len(repo_name_clean) < 3:
        repo_name_clean = "repo_collection"
    return repo_name_clean[:60]


def collection_count(vector_store: VectorStoreManager, collection_name: str) -> int:
    client = vector_store.get_client()
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as e:
        err_msg = str(e).lower()
        if "not exist" in err_msg or "not found" in err_msg or "notfound" in err_msg:
            return 0
        raise
    return collection.count()


def ingest_repository(
    repo_url: str,
    collection_name: str,
    github_service: GitHubService,
    chunker: CodeChunker,
    gemini_service: GeminiService,
    vector_store: VectorStoreManager
) -> None:
    print(f"\n[Ingestion] Fetching repository files: {repo_url}")
    files = github_service.fetch_repo_files(repo_url)
    if not files:
        raise RuntimeError("No files retrieved from repository.")

    print(f"[Ingestion] Loaded {len(files)} files. Chunking...")
    all_chunks = []
    for file_info in files:
        code_file = CodeFile(
            file_path=file_info["path"],
            content=file_info["content"],
            language=file_info["language"],
            metadata={"repository_id": collection_name}
        )
        all_chunks.extend(chunker.chunk_file(code_file))

    if not all_chunks:
        raise RuntimeError("No chunks generated from repository.")

    print(f"[Ingestion] Generated {len(all_chunks)} chunks. Validating before embedding...")
    embeddable_chunks = filter_chunks_for_embedding(all_chunks)
    skipped_chunks = len(all_chunks) - len(embeddable_chunks)
    print(
        f"[Ingestion] Skipped {skipped_chunks} empty/whitespace-only chunks. "
        f"Embedding {len(embeddable_chunks)} chunks..."
    )
    texts = [chunk.content for chunk in embeddable_chunks]
    embeddings = gemini_service.generate_embeddings_batch(texts)

    documents = [chunk.content for chunk in embeddable_chunks]
    ids = [chunk.chunk_id for chunk in embeddable_chunks]
    metadatas: List[Dict[str, Any]] = []
    for chunk in embeddable_chunks:
        metadata = dict(chunk.metadata)
        metadata["file_path"] = chunk.file_path
        metadatas.append(metadata)

    print(f"[Ingestion] Writing {len(ids)} chunks to Chroma collection '{collection_name}'...")
    vector_store.reset_collection(collection_name)
    vector_store.add_documents(
        collection_name=collection_name,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    print("[Ingestion] Complete.")


async def run_rag_pipeline(repo_url: str, question: str, top_k: int) -> None:
    collection_name = collection_name_from_repo_url(repo_url)

    print("Initializing services...")
    github_service = GitHubService(token=settings.GITHUB_TOKEN)
    chunker = CodeChunker()
    gemini_service = GeminiService()
    vector_store = VectorStoreManager(db_path=settings.CHROMA_DB_DIR)
    retrieval_agent = RetrievalAgent(vector_store=vector_store, gemini_service=gemini_service)
    analysis_agent = AnalysisAgent(gemini_service=gemini_service)

    try:
        existing_count = collection_count(vector_store, collection_name)
        if existing_count > 0:
            print(
                f"\n[Ingestion] Skipping. Collection '{collection_name}' "
                f"already has {existing_count} stored chunks."
            )
        else:
            ingest_repository(
                repo_url=repo_url,
                collection_name=collection_name,
                github_service=github_service,
                chunker=chunker,
                gemini_service=gemini_service,
                vector_store=vector_store
            )

        print(f"\n[Retrieval] Question: {question}")
        retrieval_response = await retrieval_agent.process({
            "query": question,
            "repository_id": collection_name,
            "top_k": top_k
        })
        if retrieval_response.get("error"):
            print(f"\n[ERROR] Retrieval failed: {retrieval_response['error']}")
            return

        retrieval_results = retrieval_response.get("results", [])
        print(f"\nRetrieved files and similarity scores ({len(retrieval_results)} chunks):")
        if not retrieval_results:
            print("  No chunks retrieved.")
        for index, result in enumerate(retrieval_results, start=1):
            print(f"  {index}. {result.get('file_path') or 'unknown'}")
            print(f"     score: {result.get('score')}")

        print("\n[Analysis] Generating final answer...")
        analysis_response = await analysis_agent.process({
            "question": question,
            "retrieval_results": retrieval_results
        })
        if analysis_response.get("error"):
            print(f"\n[ERROR] Analysis failed: {analysis_response['error']}")
            return

        print("\nFinal answer:")
        print(analysis_response["answer"])
        print("\nSource files:")
        source_files = analysis_response.get("source_files", [])
        if not source_files:
            print("  None")
        for source_file in source_files:
            print(f"  - {source_file}")
        print(f"\nChunk count: {analysis_response.get('chunk_count', 0)}")

    except Exception as e:
        print(f"\n[ERROR] RAG pipeline failed: {e}")
        logger.exception("Manual RAG pipeline failed")
    finally:
        print("\nClosing database connection...")
        vector_store.close()
        print("Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual end-to-end RAG validation for RetrievalAgent and AnalysisAgent."
    )
    parser.add_argument("repo_url", help="GitHub repository URL to query.")
    parser.add_argument(
        "-q",
        "--question",
        help="Question to ask about the repository. If omitted, you will be prompted."
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve before analysis. Defaults to 5."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    question = args.question or input("Question: ").strip()
    if not question:
        print("[ERROR] Question cannot be empty.")
        sys.exit(1)

    asyncio.run(run_rag_pipeline(args.repo_url, question, args.top_k))


if __name__ == "__main__":
    main()
