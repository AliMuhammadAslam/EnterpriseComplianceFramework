import os
from utils.logger import logger_instance


class DocumentParser:
    """Parses PDF, DOCX, and TXT files into plain text."""

    def __init__(self):
        self.logger = logger_instance.get_logger("document_parser")

    def parse_file(self, file_path: str) -> str:
        """Parse a file and return its text content.
        
        Supports: .pdf, .docx, .txt
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            return self._parse_pdf(file_path)
        elif ext == ".docx":
            return self._parse_docx(file_path)
        elif ext == ".txt":
            return self._parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _parse_pdf(self, file_path: str) -> str:
        """Extract text from PDF using PyPDF2."""
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            text = "\n\n".join(text_parts)
            self.logger.info(
                f"Parsed PDF: {os.path.basename(file_path)} "
                f"({len(reader.pages)} pages, {len(text)} chars)"
            )
            return text
        except Exception as e:
            self.logger.error(f"Error parsing PDF {file_path}: {e}")
            raise

    def _parse_docx(self, file_path: str) -> str:
        """Extract text from DOCX using python-docx.

        Paragraphs and tables are read in document order. Reading paragraphs
        alone dropped every table, and policies often list their controls in
        tables, so an evaluation reported gaps for controls that were there.
        """
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            doc = Document(file_path)
            text_parts = []
            tables = 0
            for block in doc.element.body.iterchildren():
                if block.tag.endswith("}p"):
                    paragraph_text = Paragraph(block, doc).text
                    if paragraph_text.strip():
                        text_parts.append(paragraph_text)
                elif block.tag.endswith("}tbl"):
                    tables += 1
                    table_text = self._docx_table_text(Table(block, doc))
                    if table_text:
                        text_parts.append(table_text)
            text = "\n\n".join(text_parts)
            self.logger.info(
                f"Parsed DOCX: {os.path.basename(file_path)} "
                f"({len(doc.paragraphs)} paragraphs, {tables} tables, {len(text)} chars)"
            )
            return text
        except Exception as e:
            self.logger.error(f"Error parsing DOCX {file_path}: {e}")
            raise

    def _docx_table_text(self, table) -> str:
        """One line per row, cells separated by " | ".

        A merged cell is returned once per row it spans, so a repeat of the
        cell before it is skipped. cell.text holds only the cell's own
        paragraphs, so a table nested in a cell is read separately.
        """
        rows = []
        for row in table.rows:
            cells = []
            for cell in row.cells:
                parts = [cell.text] + [self._docx_table_text(t) for t in cell.tables]
                value = " ".join(" ".join(parts).split())
                if value and (not cells or cells[-1] != value):
                    cells.append(value)
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    def _parse_txt(self, file_path: str) -> str:
        """Read plain text file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.logger.info(
                f"Parsed TXT: {os.path.basename(file_path)} "
                f"({len(text)} chars)"
            )
            return text
        except UnicodeDecodeError:
            # Fallback to latin-1 encoding
            with open(file_path, "r", encoding="latin-1") as f:
                text = f.read()
            return text
