import os
import glob
from typing import List, Dict, Any
from utils.logger import logger_instance
from knowledge.vector_store import VectorStore
from dotenv import load_dotenv

load_dotenv()


class KnowledgeBase:
    """Manages the regulatory/compliance knowledge base.
    
    Reads structured markdown/text files from the knowledge_data directory,
    chunks and embeds them, and stores in the vector store. Designed to be
    extensible — simply add new .md or .txt files to the knowledge_data
    directory and call ingest().
    """

    def __init__(self, vector_store: VectorStore = None):
        self.vector_store = vector_store or VectorStore()
        self.knowledge_path = os.getenv(
            "KNOWLEDGE_BASE_PATH", "./knowledge_data"
        )
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "500"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "50"))
        self.logger = logger_instance.get_logger("knowledge_base")
        self.logger.info(
            f"KnowledgeBase initialized, path: {self.knowledge_path}"
        )

    def is_populated(self) -> bool:
        """Check if the knowledge base already has documents loaded."""
        return self.vector_store.knowledge_count() > 0

    def ingest(self, force: bool = False):
        """Ingest all documents from the knowledge data directory.
        
        Args:
            force: If True, re-ingest even if already populated.
        """
        if self.is_populated() and not force:
            self.logger.info(
                "Knowledge base already populated, skipping ingestion"
            )
            return

        if not os.path.exists(self.knowledge_path):
            self.logger.warning(
                f"Knowledge path does not exist: {self.knowledge_path}"
            )
            return

        files = (
            glob.glob(os.path.join(self.knowledge_path, "*.md"))
            + glob.glob(os.path.join(self.knowledge_path, "*.txt"))
        )

        if not files:
            self.logger.warning("No .md or .txt files found in knowledge path")
            return

        self.logger.info(f"Ingesting {len(files)} knowledge files...")

        all_chunks = []
        all_metadatas = []
        all_ids = []

        for filepath in files:
            filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                chunks = self._chunk_document(content, filename)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"kb_{filename}_{i}"
                    all_chunks.append(chunk["text"])
                    all_metadatas.append(chunk["metadata"])
                    all_ids.append(chunk_id)

                self.logger.info(
                    f"  Processed {filename}: {len(chunks)} chunks"
                )
            except Exception as e:
                self.logger.error(f"  Error processing {filename}: {e}")

        if all_chunks:
            # Batch insert — ChromaDB handles batching internally
            batch_size = 50
            for start in range(0, len(all_chunks), batch_size):
                end = start + batch_size
                self.vector_store.add_knowledge_documents(
                    documents=all_chunks[start:end],
                    metadatas=all_metadatas[start:end],
                    ids=all_ids[start:end],
                )

            self.logger.info(
                f"Knowledge base ingestion complete: "
                f"{len(all_chunks)} total chunks"
            )

    def _chunk_document(
        self, content: str, filename: str
    ) -> List[Dict[str, Any]]:
        """Split a document into overlapping chunks with metadata.
        
        Uses section-aware chunking: splits on markdown headings first,
        then by character count within sections.
        """
        chunks = []
        current_section = "General"

        # Split by markdown headings to preserve section context
        lines = content.split("\n")
        sections = []
        current_lines = []

        for line in lines:
            if line.startswith("# ") or line.startswith("## "):
                if current_lines:
                    sections.append((current_section, "\n".join(current_lines)))
                current_section = line.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_section, "\n".join(current_lines)))

        # Chunk each section
        for section_name, section_text in sections:
            section_chunks = self._split_text(
                section_text, self.chunk_size, self.chunk_overlap
            )
            for chunk_text in section_chunks:
                if chunk_text.strip():
                    chunks.append({
                        "text": chunk_text.strip(),
                        "metadata": {
                            "source": filename,
                            "section": section_name,
                            "type": "regulatory_knowledge",
                        },
                    })

        return chunks

    def _split_text(
        self, text: str, chunk_size: int, overlap: int
    ) -> List[str]:
        """Split text into chunks by word count with overlap."""
        words = text.split()
        if len(words) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk = " ".join(words[start:end])
            chunks.append(chunk)
            start = end - overlap

        return chunks

    def get_status(self) -> Dict[str, Any]:
        """Return status of the knowledge base."""
        return {
            "populated": self.is_populated(),
            "document_count": self.vector_store.knowledge_count(),
            "knowledge_path": self.knowledge_path,
        }
