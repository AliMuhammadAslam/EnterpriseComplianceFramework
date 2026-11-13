"""Tests that DOCX extraction keeps table content, in document order.

Run with:  python -m unittest discover -s tests
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docx import Document

from document_upload.parser import DocumentParser


class TestDocxTables(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def parse(self, doc):
        path = os.path.join(self.tmp, "policy.docx")
        doc.save(path)
        return DocumentParser().parse_file(path)

    def control_table_doc(self):
        doc = Document()
        doc.add_paragraph("Acme Access Control Policy")
        table = doc.add_table(rows=3, cols=2)
        rows = [("Control", "Implementation"),
                ("Privileged access review", "Quarterly, signed off by CISO"),
                ("MFA", "Required for all remote access")]
        for r, (a, b) in enumerate(rows):
            table.cell(r, 0).text, table.cell(r, 1).text = a, b
        doc.add_paragraph("Approved by the board.")
        return doc

    def test_table_content_is_extracted(self):
        text = self.parse(self.control_table_doc())
        self.assertIn("Privileged access review | Quarterly, signed off by CISO", text)
        self.assertIn("MFA | Required for all remote access", text)

    def test_paragraphs_and_tables_keep_document_order(self):
        text = self.parse(self.control_table_doc())
        self.assertLess(text.index("Acme Access Control Policy"), text.index("MFA"))
        self.assertLess(text.index("MFA"), text.index("Approved by the board."))

    def test_merged_cell_text_appears_once_per_row(self):
        doc = Document()
        table = doc.add_table(rows=1, cols=3)
        merged = table.cell(0, 0).merge(table.cell(0, 1))
        merged.text = "Encryption at rest"
        table.cell(0, 2).text = "AES-256"
        text = self.parse(doc)
        self.assertEqual(text.count("Encryption at rest"), 1)
        self.assertIn("Encryption at rest | AES-256", text)

    def test_nested_table_content_is_extracted(self):
        doc = Document()
        outer = doc.add_table(rows=1, cols=1)
        inner = outer.cell(0, 0).add_table(rows=1, cols=2)
        inner.cell(0, 0).text, inner.cell(0, 1).text = "Backup", "Daily, offsite"
        self.assertIn("Backup | Daily, offsite", self.parse(doc))

    def test_document_without_tables_is_unchanged(self):
        doc = Document()
        doc.add_paragraph("First paragraph.")
        doc.add_paragraph("")
        doc.add_paragraph("Second paragraph.")
        self.assertEqual(self.parse(doc), "First paragraph.\n\nSecond paragraph.")


if __name__ == "__main__":
    unittest.main()
