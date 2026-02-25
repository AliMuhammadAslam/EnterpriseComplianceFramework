import os
from typing import List
from openai import OpenAI
from utils.logger import logger_instance
from dotenv import load_dotenv

load_dotenv()


class EmbeddingService:
    """Generates text embeddings using OpenAI's embedding models.
    
    Uses litellm-compatible OpenAI client. Can be swapped to other
    providers (Gemini, Cohere, etc.) by changing the client and model.
    """

    def __init__(self, model: str = None):
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.logger = logger_instance.get_logger("embeddings")
        self.logger.info(f"EmbeddingService initialized with model: {self.model}")

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text string."""
        try:
            text = text.replace("\n", " ").strip()
            if not text:
                return []
            response = self.client.embeddings.create(
                input=[text],
                model=self.model
            )
            return response.data[0].embedding
        except Exception as e:
            self.logger.error(f"Error generating embedding: {e}")
            raise

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        try:
            cleaned = [t.replace("\n", " ").strip() for t in texts if t.strip()]
            if not cleaned:
                return []
            response = self.client.embeddings.create(
                input=cleaned,
                model=self.model
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            self.logger.error(f"Error generating batch embeddings: {e}")
            raise
