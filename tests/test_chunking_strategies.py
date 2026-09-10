"""Tests for the two chunking strategies compared in the ablation study.

Exercises the chunkers directly, without a vector store or any API call.

Run with:  python -m unittest discover -s tests
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge import knowledge_base as kb
from knowledge.vector_store import KNOWLEDGE_COLLECTION


# Mirrors the shape of a real regulatory file: headings followed by dense
# control lists, which is the case section awareness is meant to protect.
DOCUMENT = "\n".join(
    ["# ISO 27001", "", "## Overview", "Overview text here."]
    + ["", "## Annex A Theme 1"]
    + [f"- A.5.{n} Control number {n} with some descriptive text." for n in range(1, 60)]
    + ["", "## Annex A Theme 2"]
    + [f"- A.8.{n} Another control with descriptive text." for n in range(1, 40)]
)


class _ChunkerOnly(kb.KnowledgeBase):
    """KnowledgeBase with the vector store stubbed out, for chunking tests."""

    def __init__(self, chunk_strategy):
        self.vector_store = None
        self.chunk_strategy = chunk_strategy
        self.collection_name = "test"
        self.knowledge_path = "./knowledge_data"
        self.chunk_size = 500
        self.chunk_overlap = 50
        self.logger = _NullLogger()


def control_families(text):
    """Annex A families present in a chunk, e.g. {'5', '8'} for A.5.x and A.8.x."""
    return set(re.findall(r"A\.(\d+)\.", text))


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class TestDefaults(unittest.TestCase):

    def test_default_strategy_and_collection_unchanged(self):
        # Production behaviour must be identical to before the ablation work.
        instance = _ChunkerOnly(kb.SECTION_AWARE)
        self.assertEqual(kb.SECTION_AWARE, "section_aware")
        self.assertEqual(KNOWLEDGE_COLLECTION, "regulatory_knowledge")
        self.assertEqual(instance.chunk_strategy, kb.SECTION_AWARE)


class TestSectionAware(unittest.TestCase):

    def setUp(self):
        self.chunks = _ChunkerOnly(kb.SECTION_AWARE)._chunk_document(
            DOCUMENT, "iso_27001.md"
        )

    def test_every_chunk_carries_its_parent_heading(self):
        self.assertTrue(all(c["metadata"]["section"] for c in self.chunks))

    def test_strategy_recorded_in_metadata(self):
        self.assertTrue(
            all(c["metadata"]["chunk_strategy"] == kb.SECTION_AWARE for c in self.chunks)
        )

    def test_no_chunk_mixes_control_families(self):
        # The point of section awareness: A.5.x and A.8.x controls belong to
        # different Annex A themes and should never share a chunk.
        for chunk in self.chunks:
            self.assertLessEqual(
                len(control_families(chunk["text"])),
                1,
                "a chunk merged controls from two separate Annex A themes",
            )


class TestFixedSize(unittest.TestCase):

    def setUp(self):
        self.chunks = _ChunkerOnly(kb.FIXED_SIZE)._chunk_document(
            DOCUMENT, "iso_27001.md"
        )

    def test_no_section_metadata(self):
        self.assertTrue(all(c["metadata"]["section"] == "" for c in self.chunks))

    def test_strategy_recorded_in_metadata(self):
        self.assertTrue(
            all(c["metadata"]["chunk_strategy"] == kb.FIXED_SIZE for c in self.chunks)
        )

    def test_merges_control_families_across_headings(self):
        # The baseline severs the control list at the word boundary and merges
        # the tail of one theme with the head of the next. This is precisely the
        # behaviour difference the ablation is designed to measure.
        merged = any(len(control_families(c["text"])) > 1 for c in self.chunks)
        self.assertTrue(
            merged,
            "fixed-size chunking should merge control families across headings",
        )


class TestStrategiesDiffer(unittest.TestCase):

    def test_strategies_produce_different_chunkings(self):
        section = _ChunkerOnly(kb.SECTION_AWARE)._chunk_document(DOCUMENT, "f.md")
        fixed = _ChunkerOnly(kb.FIXED_SIZE)._chunk_document(DOCUMENT, "f.md")
        self.assertNotEqual(
            [c["text"] for c in section],
            [c["text"] for c in fixed],
            "the two strategies must not be equivalent, or the ablation is vacuous",
        )


if __name__ == "__main__":
    unittest.main()
