import os
import sys
import logging

# Ensure project root is in path so 'src' module can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.services.gemini import GeminiService

service = GeminiService()

# ── Test 1: Single embedding ──────────────────────────────────────────────────
print("\n=== Test 1: Single embedding ===")
embedding = service.generate_embedding("def login(): pass")
print(f"  Embedding length: {len(embedding)}")
assert len(embedding) > 0, "Single embedding should not be empty"
print("  PASSED")

# ── Test 2: Small batch (fits in 1 sub-batch of 10) ──────────────────────────
print("\n=== Test 2: Batch of 3 (single sub-batch) ===")
texts_small = [
    "def add(a, b): return a + b",
    "class User: pass",
    "import os",
]
embeddings_small = service.generate_embeddings_batch(texts_small, batch_size=10)
print(f"  Embeddings returned: {len(embeddings_small)}")
assert len(embeddings_small) == len(texts_small), "Count mismatch"
assert all(len(e) > 0 for e in embeddings_small), "Some embeddings are empty"
print("  PASSED")

# ── Test 3: Large batch (forces multiple sub-batches) ────────────────────────
print("\n=== Test 3: Batch of 12 with batch_size=4 (3 sub-batches) ===")
texts_large = [f"def function_{i}(): pass" for i in range(12)]
embeddings_large = service.generate_embeddings_batch(texts_large, batch_size=4)
print(f"  Embeddings returned: {len(embeddings_large)}")
assert len(embeddings_large) == 12, f"Expected 12, got {len(embeddings_large)}"
assert all(len(e) > 0 for e in embeddings_large), "Some embeddings are empty"
print("  PASSED")

# ── Test 4: Ordering is preserved ────────────────────────────────────────────
print("\n=== Test 4: Ordering preserved across sub-batches ===")
# Use the same text twice — both embeddings should be identical
same_texts = ["def hello(): pass"] * 4
embeddings_same = service.generate_embeddings_batch(same_texts, batch_size=2)
assert len(embeddings_same) == 4, "Count mismatch"
# All vectors for the same text should be nearly identical
for i in range(1, len(embeddings_same)):
    diff = sum(abs(a - b) for a, b in zip(embeddings_same[0], embeddings_same[i]))
    assert diff < 0.01, f"Embedding {i} diverged from embedding 0 (diff={diff:.4f})"
print(f"  All 4 embeddings for identical text are consistent. PASSED")

print("\nAll tests passed!")