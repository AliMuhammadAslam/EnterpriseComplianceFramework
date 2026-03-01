import os
import chromadb
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance
from knowledge.embeddings import EmbeddingService
from dotenv import load_dotenv

load_dotenv()


class VectorStore:
    """ChromaDB-backed vector store with namespace isolation.
    
    Uses separate collections for:
    - 'regulatory_knowledge': global compliance/regulatory knowledge base
    - 'company_docs_{user_id}': per-user uploaded company documents
    """

    def __init__(self, persist_directory: str = None):
        self.persist_directory = persist_directory or os.getenv(
            "CHROMA_DB_PATH", "./chroma_db"
        )
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.embedding_service = EmbeddingService()
        self.logger = logger_instance.get_logger("vector_store")
        self.logger.info(
            f"VectorStore initialized at: {self.persist_directory}"
        )

    def _get_or_create_collection(self, name: str):
        """Get or create a ChromaDB collection by name."""
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )

    # ---- Knowledge Base (global) ----

    def add_knowledge_documents(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
    ):
        """Add documents to the global regulatory knowledge base."""
        collection = self._get_or_create_collection("regulatory_knowledge")
        embeddings = self.embedding_service.embed_batch(documents)
        collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        self.logger.info(
            f"Added {len(documents)} docs to regulatory_knowledge"
        )

    def query_knowledge(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Query the global regulatory knowledge base."""
        try:
            collection = self._get_or_create_collection("regulatory_knowledge")
            if collection.count() == 0:
                return []
            query_embedding = self.embedding_service.embed_text(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
            )
            return self._format_results(results)
        except Exception as e:
            self.logger.warning(
                f"ChromaDB query failed for regulatory_knowledge, "
                f"returning empty results: {e}"
            )
            return []

    def knowledge_count(self) -> int:
        """Return number of documents in the knowledge base."""
        collection = self._get_or_create_collection("regulatory_knowledge")
        return collection.count()

    # ---- Company Documents (per-user) ----

    def add_company_documents(
        self,
        user_id: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
    ):
        """Add documents to a user-specific company document collection."""
        collection_name = f"company_docs_{user_id}"
        collection = self._get_or_create_collection(collection_name)
        embeddings = self.embedding_service.embed_batch(documents)
        collection.add(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        self.logger.info(
            f"Added {len(documents)} docs to {collection_name}"
        )

    def query_company_documents(
        self, user_id: str, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Query a user's company document collection."""
        collection_name = f"company_docs_{user_id}"
        try:
            collection = self.client.get_collection(collection_name)
            if collection.count() == 0:
                return []
            query_embedding = self.embedding_service.embed_text(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
            )
            return self._format_results(results)
        except Exception as e:
            self.logger.warning(
                f"ChromaDB query failed for {collection_name}, "
                f"returning empty results: {e}"
            )
            return []

    def company_doc_count(self, user_id: str) -> int:
        """Return number of chunks in a user's company docs."""
        collection_name = f"company_docs_{user_id}"
        try:
            collection = self.client.get_collection(collection_name)
            return collection.count()
        except Exception:
            return 0

    def delete_company_collection(self, user_id: str):
        """Delete a user's entire company document collection."""
        collection_name = f"company_docs_{user_id}"
        try:
            self.client.delete_collection(collection_name)
            self.logger.info(f"Deleted collection: {collection_name}")
        except Exception as e:
            self.logger.error(f"Error deleting collection: {e}")

    # ---- Helpers ----

    def _format_results(self, results: dict) -> List[Dict[str, Any]]:
        """Format ChromaDB query results into a clean list of dicts."""
        formatted = []
        if not results or not results.get("documents"):
            return formatted
        documents = results["documents"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(documents)
        for doc, meta, dist in zip(documents, metadatas, distances):
            formatted.append({
                "content": doc,
                "metadata": meta,
                "relevance_score": 1.0 - dist,  # cosine distance to similarity
            })
        return formatted
