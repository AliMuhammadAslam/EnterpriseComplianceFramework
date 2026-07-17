import os
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance
from knowledge.vector_store import VectorStore
from dotenv import load_dotenv

load_dotenv()


class RAGPipeline:
    """Retrieves context from the regulatory KB and user documents for LLM injection."""

    def __init__(self, vector_store: VectorStore = None):
        self.vector_store = vector_store or VectorStore()
        self.top_k = int(os.getenv("RAG_TOP_K", "5"))
        self.logger = logger_instance.get_logger("rag_pipeline")
        self.logger.info("RAGPipeline initialized")

    def retrieve_context(
        self, query: str, user_id: Optional[str] = None
    ) -> str:
        """Query the regulatory KB and the user's company docs, return formatted context."""
        self.logger.info(f"Retrieving context for query: {query[:80]}...")

        kb_results = self.vector_store.query_knowledge(query, top_k=self.top_k)

        company_results = []
        if user_id:
            company_results = self.vector_store.query_company_documents(
                user_id, query, top_k=self.top_k
            )

        context = self._format_context(kb_results, company_results)
        self.logger.info(
            f"Retrieved {len(kb_results)} KB chunks, "
            f"{len(company_results)} company doc chunks"
        )
        return context

    def retrieve_knowledge_only(self, query: str) -> str:
        """Retrieve context only from the regulatory knowledge base."""
        results = self.vector_store.query_knowledge(query, top_k=self.top_k)
        return self._format_section("Regulatory Knowledge Base", results)

    def retrieve_company_docs_only(
        self, user_id: str, query: str, doc_ids: Optional[List[str]] = None
    ) -> str:
        """Retrieve context only from user's company documents.

        doc_ids restricts retrieval to specific uploaded documents, so an
        evaluation can target one company's files without blending in
        others uploaded under the same user.
        """
        results = self.vector_store.query_company_documents(
            user_id, query, top_k=self.top_k, doc_ids=doc_ids
        )
        return self._format_section("Company Documents", results)

    def _format_context(
        self,
        kb_results: List[Dict[str, Any]],
        company_results: List[Dict[str, Any]],
    ) -> str:
        """Format retrieved results into a structured context block."""
        parts = []

        # Prominently flag missing company docs at the very top so the LLM
        # cannot overlook it when framing its response.
        if not company_results:
            parts.append(
                "⚠ IMPORTANT - NO COMPANY DOCUMENTS AVAILABLE: "
                "This user has not uploaded any company documents. "
                "You MUST inform the user of this at the start of your response. "
                "Do NOT answer as if you have reviewed their actual policies or documents. "
                "Base your response solely on the regulatory knowledge base below."
            )

        if kb_results:
            parts.append(
                self._format_section("Regulatory Knowledge Base", kb_results)
            )

        if company_results:
            parts.append(
                self._format_section("Company Documents", company_results)
            )

        if not parts:
            return (
                "[No relevant context found in knowledge base or "
                "company documents.]"
            )

        return "\n\n".join(parts)

    def _format_section(
        self, title: str, results: List[Dict[str, Any]]
    ) -> str:
        """Format a section of retrieved results with source citations."""
        if not results:
            if "Company Documents" in title:
                return (
                    "[No company documents have been uploaded by this user. "
                    "Responses will be based solely on the regulatory knowledge base. "
                    "Please upload your company's policy documents to enable "
                    "document-specific analysis and gap assessments.]"
                )
            return f"[No relevant results found in {title}.]"

        lines = [f"--- {title} ---"]
        for i, result in enumerate(results, 1):
            source = result.get("metadata", {}).get("source", "Unknown")
            section = result.get("metadata", {}).get("section", "")
            score = result.get("relevance_score", 0.0)
            content = result["content"]

            citation = f"[Source: {source}"
            if section:
                citation += f" | Section: {section}"
            citation += f" | Relevance: {score:.2f}]"

            lines.append(f"\nChunk {i} {citation}:")
            lines.append(content)

        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        """Return status information about the RAG pipeline."""
        return {
            "knowledge_base_documents": self.vector_store.knowledge_count(),
            "top_k": self.top_k,
        }
