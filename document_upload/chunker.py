import os
from typing import List, Dict, Any
from utils.logger import logger_instance


class DocumentChunker:
    """Splits documents into overlapping chunks for embedding."""

    def __init__(self, chunk_size: int = None, chunk_overlap: int = None):
        self.chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", "500"))
        self.chunk_overlap = chunk_overlap or int(
            os.getenv("CHUNK_OVERLAP", "50")
        )
        self.logger = logger_instance.get_logger("document_chunker")

    def chunk_text(
        self,
        text: str,
        metadata: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """Split text into overlapping word-count chunks, each with attached metadata."""
        if not text or not text.strip():
            return []

        base_metadata = metadata or {}
        words = text.split()

        if len(words) <= self.chunk_size:
            return [{
                "text": text.strip(),
                "metadata": {**base_metadata, "chunk_index": 0},
            }]

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(words):
            end = start + self.chunk_size
            chunk_text = " ".join(words[start:end])

            chunks.append({
                "text": chunk_text.strip(),
                "metadata": {
                    **base_metadata,
                    "chunk_index": chunk_index,
                    "word_start": start,
                    "word_end": min(end, len(words)),
                },
            })

            start = end - self.chunk_overlap
            chunk_index += 1

        self.logger.info(
            f"Split text ({len(words)} words) into {len(chunks)} chunks"
        )
        return chunks
