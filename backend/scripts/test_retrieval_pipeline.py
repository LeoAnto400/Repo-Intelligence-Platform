#!/usr/bin/env python3
import asyncio
import os
import re
import sys
import logging

# Ensure src directory is in Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.config import settings
from src.services.github import GitHubService
from src.services.chunker import CodeChunker, CodeFile
from src.services.gemini import GeminiService
from src.services.ingestion import filter_chunks_for_embedding
from src.db.chroma import VectorStoreManager
from src.agents.retrieval import RetrievalAgent

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_retrieval_pipeline.py <repo_url>")
        sys.exit(1)
        
    repo_url = sys.argv[1]
    
    # 1. Initialize Services
    print("Initializing services...")
    github_service = GitHubService(token=settings.GITHUB_TOKEN)
    chunker = CodeChunker()
    gemini_service = GeminiService()
    vector_store = VectorStoreManager(db_path=settings.CHROMA_DB_DIR)
    
    try:
        # 2. Clone repository & Discover/Load Files
        print(f"\nStep 1 & 2: Cloning repository and discovering files: {repo_url}")
        files = github_service.fetch_repo_files(repo_url)
        if not files:
            print("No files retrieved from repository. Exiting.")
            return
        print(f"Successfully loaded {len(files)} files.")
        
        # 3. Chunk files
        print("\nStep 3: Chunking files using CodeChunker...")
        all_chunks = []
        for file_info in files:
            code_file = CodeFile(
                file_path=file_info["path"],
                content=file_info["content"],
                language=file_info["language"]
            )
            chunks = chunker.chunk_file(code_file)
            all_chunks.extend(chunks)
        print(f"Generated {len(all_chunks)} chunks total.")
        
        if not all_chunks:
            print("No chunks generated. Exiting.")
            return
            
        # 4. Generate embeddings
        print("\nStep 4: Validating chunks before embedding...")
        embeddable_chunks = filter_chunks_for_embedding(all_chunks)
        skipped_chunks = len(all_chunks) - len(embeddable_chunks)
        print(
            f"Skipped {skipped_chunks} empty/whitespace-only chunks. "
            f"Generating embeddings for {len(embeddable_chunks)} chunks using GeminiService (batching)..."
        )
        texts = [c.content for c in embeddable_chunks]
        embeddings = gemini_service.generate_embeddings_batch(texts)
        print(f"Generated {len(embeddings)} embeddings vectors.")
        
        # 5. Store chunks in ChromaDB
        # Derive collection name
        repo_name_clean = re.sub(r'[^a-zA-Z0-9_-]', '_', repo_url.split('/')[-1])
        repo_name_clean = re.sub(r'_+', '_', repo_name_clean).strip('_')
        if len(repo_name_clean) < 3:
            repo_name_clean = "repo_collection"
        collection_name = repo_name_clean[:60]
        
        print(f"\nStep 5: Storing chunks in ChromaDB collection: '{collection_name}'")
        vector_store.reset_collection(collection_name)
        
        documents = [c.content for c in embeddable_chunks]
        ids = [c.chunk_id for c in embeddable_chunks]
        metadatas = []
        for c in embeddable_chunks:
            meta = dict(c.metadata)
            meta["file_path"] = c.file_path
            metadatas.append(meta)
            
        vector_store.add_documents(
            collection_name=collection_name,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print("Successfully indexed all document chunks.")
        
        # 6. Ask Question & Run RetrievalAgent
        question = "How does authentication work?"
        print(f"\nStep 6: Instantiating RetrievalAgent and running query: '{question}'")
        retrieval_agent = RetrievalAgent(vector_store=vector_store, gemini_service=gemini_service)
        
        payload = {
            "query": question,
            "repository_id": collection_name,
            "top_k": 5
        }
        
        response = await retrieval_agent.process(payload)
        
        # 7. Print Results
        if response.get("error"):
            print(f"\n[ERROR] Retrieval failed: {response['error']}")
        else:
            results = response.get("results", [])
            print(f"\n--- Retrieval Results (top_k={len(results)}) ---")
            for idx, result in enumerate(results):
                metadata = result.get("metadata") or {}
                chunk_type = metadata.get("chunk_type") or "unknown"
                content = result.get("content") or ""
                
                # Replace newline with spaces for clean logging/display
                content_snippet = content[:300].replace('\n', ' ').strip()
                
                print(f"\nMatch #{idx + 1}")
                print(f"  File Path:   {result.get('file_path')}")
                print(f"  Score:       {result.get('score')}")
                print(f"  Chunk Type:  {chunk_type}")
                print(f"  Content:     {content_snippet}...")
                
    except Exception as e:
        print(f"\n[ERROR] Pipeline run failed: {e}")
        logger.exception("Verification pipeline error")
    finally:
        print("\nClosing database connection...")
        vector_store.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
