import os
import shutil
import tempfile
import unittest
from src.db.chroma import VectorStoreManager

class TestVectorStoreManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for each test run to ensure isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = self.temp_dir.name
        self.manager = VectorStoreManager(db_path=self.db_path)
        self.collection_name = "test_collection"

    def tearDown(self):
        # Close the manager to release file locks on Windows
        self.manager.close()
        # Clean up temporary directory after each test
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_client_lazy_initialization(self):
        # Initially, the private client attribute should be None
        self.assertIsNone(self.manager._client)
        
        # Accessing the client via get_client should initialize it
        client = self.manager.get_client()
        self.assertIsNotNone(client)
        self.assertIsNotNone(self.manager._client)
        
        # Subsequent calls should return the same client instance
        self.assertIs(client, self.manager.get_client())

    def test_get_collection(self):
        collection = self.manager.get_collection(self.collection_name)
        self.assertIsNotNone(collection)
        self.assertEqual(collection.name, self.collection_name)

    def test_add_documents_and_query_similarity(self):
        documents = [
            "def calculate_total(prices): return sum(prices)",
            "def greet_user(name): print(f'Hello, {name}')",
            "class DatabaseConnector: def connect(self): pass"
        ]
        # Using simple 3-dimensional dummy embeddings for testing
        embeddings = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]
        ]
        metadatas = [
            {"file": "math.py", "type": "function"},
            {"file": "ui.py", "type": "function"},
            {"file": "db.py", "type": "class"}
        ]
        ids = ["id1", "id2", "id3"]

        # Add to the store
        self.manager.add_documents(
            collection_name=self.collection_name,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )

        # Similarity query closest to [1.0, 0.1, 0.0]
        results = self.manager.query_similarity(
            collection_name=self.collection_name,
            query_embedding=[1.0, 0.1, 0.0],
            top_k=2
        )

        self.assertEqual(len(results), 2)
        # The first document should be "id1" because of the pricing embedding
        self.assertEqual(results[0]["id"], "id1")
        self.assertEqual(results[0]["document"], documents[0])
        self.assertEqual(results[0]["metadata"], metadatas[0])
        self.assertIsNotNone(results[0]["distance"])

    def test_add_documents_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            self.manager.add_documents(
                collection_name=self.collection_name,
                documents=["doc1"],
                embeddings=[[1.0, 2.0]],
                metadatas=[], # mismatched length
                ids=["id1"]
            )

    def test_add_documents_empty_ids(self):
        # Adding empty list should gracefully return and log warning
        self.manager.add_documents(
            collection_name=self.collection_name,
            documents=[],
            embeddings=[],
            metadatas=[],
            ids=[]
        )
        collection = self.manager.get_collection(self.collection_name)
        self.assertEqual(collection.count(), 0)

    def test_query_similarity_metadata_filter(self):
        documents = [
            "def fast_sort(arr): pass",
            "def bubble_sort(arr): pass"
        ]
        embeddings = [
            [1.0, 0.0],
            [0.9, 0.1]
        ]
        metadatas = [
            {"algorithm": "quicksort", "complexity": "O(N log N)"},
            {"algorithm": "bubblesort", "complexity": "O(N^2)"}
        ]
        ids = ["sort1", "sort2"]

        self.manager.add_documents(
            collection_name=self.collection_name,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )

        # Query with metadata filter for bubblesort complexity
        results = self.manager.query_similarity(
            collection_name=self.collection_name,
            query_embedding=[1.0, 0.0],
            top_k=2,
            where_metadata={"complexity": "O(N^2)"}
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "sort2")
        self.assertEqual(results[0]["metadata"]["algorithm"], "bubblesort")

    def test_reset_collection(self):
        # Create and add a document
        self.manager.add_documents(
            collection_name=self.collection_name,
            documents=["doc"],
            embeddings=[[1.0]],
            metadatas=[{"meta": "data"}],
            ids=["doc_id"]
        )
        
        # Verify collection exists and has item
        collection = self.manager.get_collection(self.collection_name)
        self.assertEqual(collection.count(), 1)
        
        # Reset (delete) collection
        self.manager.reset_collection(self.collection_name)
        
        # Verify collection count starts at 0 if recreated
        new_collection = self.manager.get_collection(self.collection_name)
        self.assertEqual(new_collection.count(), 0)

    def test_reset_database(self):
        # Create two different collections and add documents to them
        self.manager.add_documents(
            collection_name="col1",
            documents=["doc1"],
            embeddings=[[1.0]],
            metadatas=[{"key": "v1"}],
            ids=["id_col1"]
        )
        self.manager.add_documents(
            collection_name="col2",
            documents=["doc2"],
            embeddings=[[2.0]],
            metadatas=[{"key": "v2"}],
            ids=["id_col2"]
        )

        client = self.manager.get_client()
        self.assertEqual(len(client.list_collections()), 2)

        # Reset the entire database
        self.manager.reset_database()

        # The list of collections should now be empty
        self.assertEqual(len(client.list_collections()), 0)

if __name__ == "__main__":
    unittest.main()
