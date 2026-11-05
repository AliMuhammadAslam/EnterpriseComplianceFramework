"""Tests that re-ingesting the knowledge base replaces it rather than layering on it.

Embeddings are stubbed, so this runs without API calls.

Run with:  python -m unittest discover -s tests
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.knowledge_base import KnowledgeBase
from knowledge.vector_store import VectorStore


class _FakeEmbeddings:
    DIM = 16

    def embed_text(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[: self.DIM]]

    def embed_batch(self, texts):
        return [self.embed_text(t) for t in texts]


class _ReingestTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb_dir = os.path.join(self.tmp, "knowledge_data")
        os.makedirs(self.kb_dir)
        self.store = VectorStore(persist_directory=os.path.join(self.tmp, "chroma"))
        self.store.embedding_service = _FakeEmbeddings()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        with open(os.path.join(self.kb_dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def knowledge_base(self):
        with mock.patch.dict(os.environ, {"KNOWLEDGE_BASE_PATH": self.kb_dir}):
            return KnowledgeBase(self.store)

    def stored(self):
        collection = self.store.client.get_collection("regulatory_knowledge")
        return collection.get(include=["documents", "metadatas"])


class TestReingestReplaces(_ReingestTestCase):

    def test_removed_file_leaves_no_chunks_behind(self):
        self.write("keep.md", "# Keep\n\nRetained text.")
        self.write("old.md", "# Old\n\nWithdrawn regulation text.")
        self.knowledge_base().ingest(force=True)

        os.remove(os.path.join(self.kb_dir, "old.md"))
        self.knowledge_base().ingest(force=True)

        sources = {m["source"] for m in self.stored()["metadatas"]}
        self.assertEqual(sources, {"keep.md"})

    def test_file_that_shrinks_leaves_no_extra_chunks(self):
        self.write("a.md", "# A\n\none\n\n## B\n\ntwo\n\n## C\n\nthree")
        self.knowledge_base().ingest(force=True)
        self.assertEqual(len(self.stored()["ids"]), 3)

        self.write("a.md", "# A\n\nonly one section now")
        self.knowledge_base().ingest(force=True)

        stored = self.stored()
        self.assertEqual(len(stored["ids"]), 1)
        self.assertNotIn("three", " ".join(stored["documents"]))

    def test_failed_reingest_keeps_the_previous_index(self):
        self.write("a.md", "# A\n\noriginal text")
        self.knowledge_base().ingest(force=True)

        self.write("a.md", "# A\n\nnew text")
        with mock.patch.object(self.store.embedding_service, "embed_batch",
                               side_effect=ConnectionError("embedding API down")):
            with self.assertRaises(ConnectionError):
                self.knowledge_base().ingest(force=True)

        self.assertEqual(self.stored()["documents"], ["# A\n\noriginal text"])

    def test_rebuilt_collection_still_answers_queries(self):
        self.write("a.md", "# A\n\nAccess control rules.")
        self.knowledge_base().ingest(force=True)
        self.knowledge_base().ingest(force=True)
        results = self.store.query_knowledge("Access control rules.", top_k=1)
        self.assertEqual(results[0]["metadata"]["source"], "a.md")


class TestIndexFingerprint(_ReingestTestCase):
    """The re-index trigger must notice every input that shapes the index."""

    def setUp(self):
        super().setUp()
        self.write("a.md", "# A\n\ntext")
        self.write("corpus_manifest.json", '{"documents": {"a.md": {"version": "1"}}}')

    def fingerprint(self, **env):
        with mock.patch.dict(os.environ, {"KNOWLEDGE_BASE_PATH": self.kb_dir, **env}):
            return KnowledgeBase(self.store).index_fingerprint()

    def test_stable_when_nothing_changes(self):
        self.assertEqual(self.fingerprint(), self.fingerprint())

    def test_changes_with_file_contents(self):
        before = self.fingerprint()
        self.write("a.md", "# A\n\nedited")
        self.assertNotEqual(before, self.fingerprint())

    def test_changes_when_provenance_manifest_changes(self):
        before = self.fingerprint()
        self.write("corpus_manifest.json", '{"documents": {"a.md": {"version": "2"}}}')
        self.assertNotEqual(before, self.fingerprint())

    def test_changes_when_a_file_is_renamed(self):
        before = self.fingerprint()
        os.rename(os.path.join(self.kb_dir, "a.md"), os.path.join(self.kb_dir, "b.md"))
        self.assertNotEqual(before, self.fingerprint())

    def test_changes_with_chunk_settings(self):
        before = self.fingerprint(CHUNK_SIZE="500", CHUNK_OVERLAP="50")
        self.assertNotEqual(before, self.fingerprint(CHUNK_SIZE="400", CHUNK_OVERLAP="50"))
        self.assertNotEqual(before, self.fingerprint(CHUNK_SIZE="500", CHUNK_OVERLAP="20"))

    def test_changes_with_embedding_model(self):
        self.assertNotEqual(
            self.fingerprint(EMBEDDING_MODEL="text-embedding-3-small"),
            self.fingerprint(EMBEDDING_MODEL="text-embedding-3-large"),
        )

    def test_corpus_identifier_used_by_run_manifests_is_unchanged(self):
        # The fingerprint is separate; the recorded corpus hash keeps its meaning.
        from utils import run_config
        before = run_config.hash_corpus(self.kb_dir)
        self.write("corpus_manifest.json", '{"documents": {}}')
        self.assertEqual(before, run_config.hash_corpus(self.kb_dir))


if __name__ == "__main__":
    unittest.main()
