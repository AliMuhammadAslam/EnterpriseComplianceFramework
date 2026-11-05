"""Tests that each standard's evaluation context comes from that standard.

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

from evaluation.engine import DEFAULT_STANDARDS, EvaluationEngine
from knowledge.knowledge_base import KnowledgeBase
from knowledge.vector_store import VectorStore


class _NullLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _CorpusOnly(KnowledgeBase):
    """KnowledgeBase over the real knowledge_data folder, with no vector store."""

    def __init__(self):
        self.vector_store = None
        self.knowledge_path = "./knowledge_data"
        self.logger = _NullLogger()
        self.provenance = self._load_manifest()


class TestResolveStandardSource(unittest.TestCase):

    def setUp(self):
        self.kb = _CorpusOnly()

    def test_every_heading_the_ui_sends_resolves_to_its_own_file(self):
        for standard in self.kb.list_standards():
            self.assertEqual(
                self.kb.resolve_standard_source(standard["title"]), standard["filename"]
            )

    def test_every_default_standard_resolves(self):
        for name in DEFAULT_STANDARDS:
            self.assertIsNotNone(self.kb.resolve_standard_source(name), name)

    def test_short_names_resolve(self):
        self.assertEqual(self.kb.resolve_standard_source("ISO 27001"), "iso_27001.md")
        self.assertEqual(self.kb.resolve_standard_source("FATF"), "fatf_guidelines.md")
        self.assertEqual(self.kb.resolve_standard_source("pakistan  aml/cft"), "pakistan_aml_cft.md")

    def test_unknown_or_empty_name_is_not_guessed(self):
        self.assertIsNone(self.kb.resolve_standard_source("Made Up Standard 9000"))
        self.assertIsNone(self.kb.resolve_standard_source(""))
        self.assertIsNone(self.kb.resolve_standard_source(None))


class _FakeEmbeddings:
    DIM = 16

    def embed_text(self, text):
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[: self.DIM]]

    def embed_batch(self, texts):
        return [self.embed_text(t) for t in texts]


class TestSourceFilter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = VectorStore(persist_directory=self.tmp)
        self.store.embedding_service = _FakeEmbeddings()
        docs = [(f"{src}_{i}", f"{src} text {i}", src)
                for src in ("iso_27001.md", "secp_guidelines.md") for i in range(4)]
        self.store.add_knowledge_documents(
            documents=[d[1] for d in docs],
            metadatas=[{"source": d[2]} for d in docs],
            ids=[d[0] for d in docs],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_filtered_query_returns_only_that_source(self):
        results = self.store.query_knowledge("anything", top_k=5, source="iso_27001.md")
        self.assertTrue(results)
        self.assertEqual({r["metadata"]["source"] for r in results}, {"iso_27001.md"})

    def test_unfiltered_query_is_unchanged(self):
        results = self.store.query_knowledge("anything", top_k=8)
        self.assertEqual(len(results), 8)


class _RecordingRag:
    def __init__(self):
        self.sources = []
        self.company_queries = None

    def retrieve_company_docs_for_queries_with_results(self, user_id, queries, doc_ids=None):
        self.company_queries = queries
        return "", []

    def retrieve_knowledge_with_results(self, query, source=None, **kwargs):
        self.sources.append(source)
        text = f"requirement text from {source}"
        return f"Chunk 1 [Source: {source}]:\n{text}", [{"content": text, "metadata": {}}]


class TestEngineUsesSourceFilter(unittest.TestCase):

    def test_each_standard_is_retrieved_from_its_own_file(self):
        rag = _RecordingRag()
        engine = EvaluationEngine(rag, _CorpusOnly())
        engine._retrieve_per_standard_context(
            ["ISO 27001", "GDPR", "Made Up Standard"], "Fintech", "Pakistan"
        )
        self.assertEqual(rag.sources, ["iso_27001.md", "gdpr.md", None])

    def test_without_a_knowledge_base_retrieval_is_unrestricted(self):
        rag = _RecordingRag()
        EvaluationEngine(rag)._retrieve_per_standard_context(["ISO 27001"], "", "")
        self.assertEqual(rag.sources, [None])

    def test_company_documents_are_searched_with_each_retrieved_requirement(self):
        from unittest import mock
        from types import SimpleNamespace

        rag = _RecordingRag()
        engine = EvaluationEngine(rag, _CorpusOnly())
        reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="report"))])
        with mock.patch("evaluation.engine.completion", return_value=reply):
            engine.evaluate_compliance(user_id="u", standards=["ISO 27001", "GDPR"])
        self.assertEqual(rag.company_queries[1:], [
            "requirement text from iso_27001.md",
            "requirement text from gdpr.md",
        ])


class TestCompanyMultiQuery(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = VectorStore(persist_directory=self.tmp)
        self.store.embedding_service = _FakeEmbeddings()
        texts = [f"policy section {i}" for i in range(6)]
        self.store.add_company_documents(
            "u", texts,
            [{"doc_id": "d1", "chunk_index": i} for i in range(6)],
            [f"d1_chunk_{i}" for i in range(6)],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_batch_matches_single_queries_and_keeps_order(self):
        queries = ["policy section 2", "", "policy section 5"]
        batch = self.store.query_company_documents_batch("u", queries, top_k=2)
        self.assertEqual(len(batch), 3)
        self.assertEqual(batch[1], [])
        for query, results in zip(queries, batch):
            if query:
                single = self.store.query_company_documents("u", query, top_k=2)
                self.assertEqual([r["content"] for r in results], [r["content"] for r in single])

    def test_merged_results_have_no_duplicates(self):
        from knowledge.rag_pipeline import RAGPipeline

        rag = RAGPipeline(self.store)
        rag.top_k = 3
        context = rag.retrieve_company_docs_for_queries(
            "u", ["policy section 1", "policy section 1", "policy section 4"]
        )
        bodies = [line for line in context.splitlines() if line.startswith("policy section")]
        self.assertEqual(len(bodies), len(set(bodies)))

    def test_unknown_user_gets_nothing(self):
        self.assertEqual(self.store.query_company_documents_batch("nobody", ["x"]), [[]])


if __name__ == "__main__":
    unittest.main()
