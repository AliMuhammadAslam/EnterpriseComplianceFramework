import os
import chromadb
from chromadb.errors import NotFoundError
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance
from knowledge.embeddings import EmbeddingService
from dotenv import load_dotenv

load_dotenv()


# Ablation runs index the same corpus under a second collection name, so this
# is a parameter rather than a hardcoded string.
KNOWLEDGE_COLLECTION = "regulatory_knowledge"

# Chunks per embeddings request for uploads. A chunk is up to ~500 words, so
# 100 stays well inside the API's per-request token limit.
COMPANY_EMBED_BATCH = 100


class VectorStore:
    """ChromaDB wrapper with separate collections for the regulatory KB and per-user docs."""

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

    def add_knowledge_documents(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        collection_name: str = KNOWLEDGE_COLLECTION,
    ):
        """Add or replace documents in a regulatory knowledge collection.

        Upsert rather than add: chunk ids are derived from the filename and
        position, so a re-ingest reuses them. add() ignores ids that already
        exist, which silently kept stale text and metadata in the store.
        """
        collection = self._get_or_create_collection(collection_name)
        embeddings = self.embedding_service.embed_batch(documents)
        collection.upsert(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        self.logger.info(
            f"Added {len(documents)} docs to {collection_name}"
        )

    def replace_knowledge_collection(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
        collection_name: str = KNOWLEDGE_COLLECTION,
        batch_size: int = 50,
    ):
        """Make a knowledge collection hold exactly these documents.

        Upserting alone left chunks from deleted files, or from the old tail
        of a shortened file, retrievable forever. Every current chunk is
        upserted first and only then are ids no longer in the corpus deleted,
        so a failure part way never leaves the collection emptier than before.
        """
        for start in range(0, len(documents), batch_size):
            end = start + batch_size
            self.add_knowledge_documents(
                documents=documents[start:end],
                metadatas=metadatas[start:end],
                ids=ids[start:end],
                collection_name=collection_name,
            )

        collection = self._get_or_create_collection(collection_name)
        stale = sorted(set(collection.get(include=[])["ids"]) - set(ids))
        if stale:
            collection.delete(ids=stale)
        self.logger.info(
            f"Rebuilt {collection_name} with {len(documents)} docs, "
            f"removed {len(stale)} stale"
        )

    def query_knowledge(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = KNOWLEDGE_COLLECTION,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query a regulatory knowledge collection, optionally within one source file."""
        try:
            collection = self._get_or_create_collection(collection_name)
            if collection.count() == 0:
                return []
            query_embedding = self.embedding_service.embed_text(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
                where={"source": source} if source else None,
            )
            return self._format_results(results)
        except Exception as e:
            self.logger.warning(
                f"ChromaDB query failed for {collection_name}, "
                f"returning empty results: {e}"
            )
            return []

    def knowledge_count(self, collection_name: str = KNOWLEDGE_COLLECTION) -> int:
        """Return number of documents in a regulatory knowledge collection."""
        collection = self._get_or_create_collection(collection_name)
        return collection.count()

    def add_company_documents(
        self,
        user_id: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
    ):
        """Add documents to a user-specific company document collection.

        Embedded in batches: one request for a whole large document exceeded
        the embeddings API's per-request token limit, so the upload failed.
        """
        collection_name = f"company_docs_{user_id}"
        collection = self._get_or_create_collection(collection_name)
        for start in range(0, len(documents), COMPANY_EMBED_BATCH):
            end = start + COMPANY_EMBED_BATCH
            embeddings = self.embedding_service.embed_batch(documents[start:end])
            collection.add(
                documents=documents[start:end],
                embeddings=embeddings,
                metadatas=metadatas[start:end],
                ids=ids[start:end],
            )
        self.logger.info(
            f"Added {len(documents)} docs to {collection_name}"
        )

    def query_company_documents(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        doc_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query a user's company document collection.

        If doc_ids is given, restricts results to chunks from those specific
        documents so an evaluation doesn't blend unrelated uploaded files.
        """
        collection_name = f"company_docs_{user_id}"
        try:
            collection = self.client.get_collection(collection_name)
            if collection.count() == 0:
                return []
            query_embedding = self.embedding_service.embed_text(query)
            where_filter = {"doc_id": {"$in": doc_ids}} if doc_ids else None
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count()),
                where=where_filter,
            )
            return self._format_results(results)
        except Exception as e:
            self.logger.warning(
                f"ChromaDB query failed for {collection_name}, "
                f"returning empty results: {e}"
            )
            return []

    def query_company_documents_batch(
        self,
        user_id: str,
        queries: List[str],
        top_k: int = 5,
        doc_ids: Optional[List[str]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """Run several queries against a user's documents in one round trip.

        Returns one result list per query, in the order given. Blank queries
        get an empty list rather than shifting the others out of alignment.
        """
        collection_name = f"company_docs_{user_id}"
        answers: List[List[Dict[str, Any]]] = [[] for _ in queries]
        live = [(i, q) for i, q in enumerate(queries) if q and q.strip()]
        if not live:
            return answers
        try:
            collection = self.client.get_collection(collection_name)
            if collection.count() == 0:
                return answers
            embeddings = self.embedding_service.embed_batch([q for _, q in live])
            where_filter = {"doc_id": {"$in": doc_ids}} if doc_ids else None
            results = collection.query(
                query_embeddings=embeddings,
                n_results=min(top_k, collection.count()),
                where=where_filter,
            )
            for position, (index, _) in enumerate(live):
                answers[index] = self._format_results({
                    "documents": [results["documents"][position]],
                    "metadatas": [results["metadatas"][position]] if results.get("metadatas") else None,
                    "distances": [results["distances"][position]] if results.get("distances") else None,
                })
        except Exception as e:
            self.logger.warning(
                f"ChromaDB batch query failed for {collection_name}, "
                f"returning empty results: {e}"
            )
        return answers

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

    def delete_company_document(self, user_id: str, doc_id: str):
        """Delete a single document's chunks from a user's collection by doc_id.

        Raises on failure. Swallowing the error let the caller report the
        document deleted while its chunks stayed searchable.
        """
        collection_name = f"company_docs_{user_id}"
        try:
            collection = self.client.get_collection(collection_name)
        except NotFoundError:
            # No collection means there are no chunks left to remove.
            return
        try:
            collection.delete(where={"doc_id": doc_id})
        except Exception as e:
            self.logger.error(f"Error deleting document {doc_id} from {collection_name}: {e}")
            raise
        self.logger.info(f"Deleted chunks for doc_id {doc_id} from {collection_name}")

    def _format_results(self, results: dict) -> List[Dict[str, Any]]:
        """Format ChromaDB query results into a clean list of dicts."""
        formatted = []
        if not results or not results.get("documents"):
            return formatted
        documents = results["documents"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(documents)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(documents)
        for doc, meta, dist in zip(documents, metadatas, distances):
            # Convert cosine distance to similarity. Cosine distance ranges
            # [0, 2], so clamp to [0, 1] to avoid displaying negative relevance
            # for weakly-related chunks.
            relevance = max(0.0, min(1.0, 1.0 - dist))
            formatted.append({
                "content": doc,
                "metadata": meta,
                "relevance_score": relevance,
            })
        return formatted
