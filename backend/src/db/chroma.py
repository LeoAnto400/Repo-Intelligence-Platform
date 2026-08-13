import logging
from typing import Any, Dict, List, Optional
import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

class VectorStoreManager:
    """
    Manages vector database operations with ChromaDB, including collections 
    management, document insertion, and similarity searching.
    """
    
    def __init__(self, db_path: str):
        """
        Initialize the vector store manager pointing to the local directory.
        
        Args:
            db_path: Path to the persistent Chroma directory.
        """
        self.db_path = db_path
        self._client: Optional[ClientAPI] = None

    def get_client(self) -> ClientAPI:
        """
        Lazily initialize and return the Chroma persistent client.
        """
        if self._client is None:
            logger.info("Initializing persistent Chroma client at %s", self.db_path)
            self._client = chromadb.PersistentClient(
                path=self.db_path,
                settings=chromadb.config.Settings(allow_reset=True)
            )
        return self._client

    def get_collection(
        self, collection_name: str, extra_metadata: Optional[Dict[str, Any]] = None
    ) -> Collection:
        """
        Get or create a Chroma collection by name.

        The collection is always created with cosine similarity as the distance
        metric (``hnsw:space = "cosine"``).  Gemini embeddings are unit-
        normalised, so cosine distance is the correct choice and produces
        significantly better ranking than the ChromaDB default (L2 / Euclidean).

        Args:
            collection_name: Name of the vector collection.
            extra_metadata: Additional metadata to persist on the collection
                (e.g. ``repo_url``) so it can be recovered later without a
                separate registry. Only applied when the collection is first
                created; ignored if it already exists.

        Returns:
            The collection object.
        """
        logger.info("Getting or creating collection: %s", collection_name)
        client = self.get_client()
        return client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", **(extra_metadata or {})},
        )

    def list_collections(self) -> List[Dict[str, Any]]:
        """
        List every collection currently persisted in the vector store, along
        with whatever metadata (e.g. ``repo_url``) and document count each one
        carries. Used to let the frontend offer already-ingested repositories
        without re-ingesting them.
        """
        client = self.get_client()
        collections = client.list_collections()
        results: List[Dict[str, Any]] = []
        for collection in collections:
            metadata = collection.metadata or {}
            results.append({
                "name": collection.name,
                "repo_url": metadata.get("repo_url"),
                "chunk_count": collection.count(),
            })
        return results
        
    def add_documents(
        self,
        collection_name: str,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        collection_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add raw documents and their corresponding vector embeddings to ChromaDB.

        Args:
            collection_name: Destination collection.
            documents: List of plain text code snippets/documents.
            embeddings: List of calculated float vectors.
            metadatas: Associated file metadata (file path, range, etc.).
            ids: List of unique document identifiers.
            collection_metadata: Extra metadata to stamp on the collection itself
                (e.g. ``repo_url``), forwarded to :meth:`get_collection`.
        """
        if not ids:
            logger.warning("Empty list of document IDs provided. No documents added.")
            return

        if not (len(documents) == len(embeddings) == len(metadatas) == len(ids)):
            logger.error(
                "Mismatched list sizes: documents=%d, embeddings=%d, metadatas=%d, ids=%d",
                len(documents), len(embeddings), len(metadatas), len(ids)
            )
            raise ValueError("All lists must be of the same length.")

        logger.info("Adding %d documents to collection: %s", len(ids), collection_name)
        collection = self.get_collection(collection_name, extra_metadata=collection_metadata)
        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents
        )
        logger.debug("Successfully added documents to collection %s", collection_name)
        
    def query_similarity(
        self, 
        collection_name: str, 
        query_embedding: List[float], 
        top_k: int = 5,
        where_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query a vector collection for the closest matches using similarity search.
        
        Args:
            collection_name: The collection to search in.
            query_embedding: The search query embedded as a vector.
            top_k: Number of results to return.
            where_metadata: Optional filters on metadata attributes.
            
        Returns:
            List of documents, distances, and metadata corresponding to matches.
        """
        logger.info("Querying collection: %s for similarity", collection_name)
        collection = self.get_collection(collection_name)
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_metadata
        )
        
        mapped_results: List[Dict[str, Any]] = []
        if results and "ids" in results and results["ids"]:
            ids = results["ids"][0]
            documents = results.get("documents", [None])[0] if results.get("documents") else [None] * len(ids)
            distances = results.get("distances", [None])[0] if results.get("distances") else [None] * len(ids)
            metadatas = results.get("metadatas", [None])[0] if results.get("metadatas") else [None] * len(ids)
            
            for idx in range(len(ids)):
                mapped_results.append({
                    "id": ids[idx],
                    "document": documents[idx] if documents else None,
                    "distance": distances[idx] if distances else None,
                    "metadata": metadatas[idx] if metadatas else None
                })
        
        logger.debug("Query similarity returned %d results", len(mapped_results))
        return mapped_results

    def sample_documents(self, collection_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Fetch an arbitrary sample of documents from a collection (no similarity
        search, no query embedding needed) for repository-level summarization.
        """
        collection = self.get_collection(collection_name)
        result = collection.get(limit=limit, include=["documents", "metadatas"])

        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []

        samples: List[Dict[str, Any]] = []
        for idx in range(len(ids)):
            samples.append({
                "document": documents[idx] if idx < len(documents) else None,
                "metadata": metadatas[idx] if idx < len(metadatas) else None,
            })
        return samples

    def reset_collection(self, collection_name: str) -> None:
        """
        Delete a collection by name if it exists, effectively resetting it.
        
        Args:
            collection_name: The collection to delete.
        """
        logger.info("Resetting collection: %s", collection_name)
        client = self.get_client()
        try:
            client.delete_collection(name=collection_name)
            logger.debug("Successfully deleted collection %s", collection_name)
        except Exception as e:
            err_msg = str(e)
            if "not exist" in err_msg.lower() or "notfound" in err_msg.lower() or "not found" in err_msg.lower():
                logger.info("Collection %s does not exist, skipping deletion.", collection_name)
            else:
                logger.exception("Unexpected error resetting collection %s", collection_name)
                raise

    def reset_database(self) -> None:
        """
        Completely reset the persistent database client, deleting all collections.
        """
        logger.info("Resetting entire persistent database at %s", self.db_path)
        client = self.get_client()
        try:
            client.reset()
            logger.debug("Successfully reset the database client.")
        except Exception as e:
            logger.exception("Failed to reset database client")
            raise

    def close(self) -> None:
        """
        Close the persistent Chroma client connection, releasing any file locks.
        """
        if self._client is not None:
            logger.info("Closing persistent Chroma client.")
            try:
                self._client.close()
            except Exception as e:
                logger.warning("Error closing Chroma client: %s", e)
            finally:
                self._client = None
