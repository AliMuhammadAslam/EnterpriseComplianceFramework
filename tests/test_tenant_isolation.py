"""Tests that one user's documents cannot be reached through another user.

Isolation is by collection name, so these check that every entry point derives
the collection from the user_id it was given and never widens the search.

Embeddings are stubbed, so this runs without API calls.

Run with:  python -m unittest discover -s tests
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.vector_store import VectorStore


class _FakeEmbeddings:
    """Deterministic stand-in for the embedding service."""

    DIM = 16

    def embed_text(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[: self.DIM]]

    def embed_batch(self, texts):
        return [self.embed_text(t) for t in texts]


class _IsolationTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = VectorStore(persist_directory=self.tmp)
        self.store.embedding_service = _FakeEmbeddings()

        self.add("alpha", "alpha_doc", "Alpha Bank card data policy, Requirement 3.4.")
        self.add("beta", "beta_doc", "Beta Bank card data policy, Requirement 3.4.")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, user_id, doc_id, text):
        self.store.add_company_documents(
            user_id=user_id,
            documents=[text],
            metadatas=[{"doc_id": doc_id, "user_id": user_id, "source": f"{doc_id}.pdf"}],
            ids=[f"{doc_id}_0"],
        )


class TestQueryIsolation(_IsolationTestCase):

    def test_a_user_only_sees_their_own_documents(self):
        results = self.store.query_company_documents("alpha", "card data policy")
        contents = " ".join(r["content"] for r in results)
        self.assertIn("Alpha Bank", contents)
        self.assertNotIn("Beta Bank", contents)

    def test_the_same_query_returns_the_other_users_own_documents(self):
        # Near-identical text in both collections, so a leak would be visible.
        results = self.store.query_company_documents("beta", "card data policy")
        contents = " ".join(r["content"] for r in results)
        self.assertIn("Beta Bank", contents)
        self.assertNotIn("Alpha Bank", contents)

    def test_a_user_with_no_uploads_gets_nothing(self):
        self.assertEqual(
            self.store.query_company_documents("gamma", "card data policy"), []
        )

    def test_an_unknown_user_does_not_fall_back_to_another_collection(self):
        results = self.store.query_company_documents("nonexistent", "Alpha Bank")
        self.assertEqual(results, [])

    def test_a_user_id_resembling_another_collection_does_not_cross_over(self):
        # "docs_alpha" must not resolve to alpha's collection.
        self.assertEqual(
            self.store.query_company_documents("docs_alpha", "card data policy"), []
        )

    def test_counts_are_per_user(self):
        self.assertEqual(self.store.company_doc_count("alpha"), 1)
        self.assertEqual(self.store.company_doc_count("beta"), 1)
        self.assertEqual(self.store.company_doc_count("gamma"), 0)


class TestDeletionIsolation(_IsolationTestCase):

    def test_deleting_one_users_collection_leaves_the_other_intact(self):
        self.store.delete_company_collection("alpha")
        self.assertEqual(self.store.company_doc_count("alpha"), 0)
        self.assertEqual(self.store.company_doc_count("beta"), 1)

    def test_deleting_a_document_does_not_touch_the_other_user(self):
        # Same doc_id in both collections, so a leaky delete would show up.
        self.add("alpha", "shared_id", "Alpha second document.")
        self.add("beta", "shared_id", "Beta second document.")

        self.store.delete_company_document("alpha", "shared_id")

        self.assertEqual(self.store.company_doc_count("alpha"), 1)
        self.assertEqual(self.store.company_doc_count("beta"), 2)

        remaining = self.store.query_company_documents("beta", "second document")
        self.assertIn("Beta", " ".join(r["content"] for r in remaining))


class TestDocIdFilterIsolation(_IsolationTestCase):

    def test_a_doc_id_from_another_user_returns_nothing(self):
        results = self.store.query_company_documents(
            "alpha", "card data policy", doc_ids=["beta_doc"]
        )
        self.assertEqual(results, [])

    def test_a_users_own_doc_id_still_works(self):
        results = self.store.query_company_documents(
            "alpha", "card data policy", doc_ids=["alpha_doc"]
        )
        self.assertTrue(results)
        self.assertIn("Alpha Bank", results[0]["content"])


class TestKnowledgeBaseSeparation(_IsolationTestCase):

    def test_company_queries_do_not_reach_the_regulatory_collection(self):
        self.store.add_knowledge_documents(
            documents=["ISO 27001 control A.8.12 covers data leakage prevention."],
            metadatas=[{"source": "iso27001.md"}],
            ids=["kb_iso_0"],
        )
        results = self.store.query_company_documents("alpha", "data leakage prevention")
        self.assertNotIn("A.8.12", " ".join(r["content"] for r in results))

    def test_regulatory_queries_do_not_reach_company_documents(self):
        self.store.add_knowledge_documents(
            documents=["ISO 27001 control A.8.12 covers data leakage prevention."],
            metadatas=[{"source": "iso27001.md"}],
            ids=["kb_iso_0"],
        )
        results = self.store.query_knowledge("card data policy")
        self.assertNotIn("Alpha Bank", " ".join(r["content"] for r in results))


if __name__ == "__main__":
    unittest.main()
