import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance
from knowledge.vector_store import VectorStore
from document_upload.parser import DocumentParser
from document_upload.chunker import DocumentChunker
from dotenv import load_dotenv

load_dotenv()


class UploadManager:
    """Manages company document uploads, parsing, chunking, and vector storage.
    
    Each user's documents are stored in a separate namespace in the vector
    store (company_docs_{user_id}) and tracked via a JSON manifest.
    """

    def __init__(self, vector_store: VectorStore = None):
        self.upload_dir = os.getenv("UPLOAD_DIR", "./uploads")
        self.max_size_mb = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
        self.allowed_extensions = {"pdf", "docx", "txt"}
        self.vector_store = vector_store or VectorStore()
        self.parser = DocumentParser()
        self.chunker = DocumentChunker()
        self.logger = logger_instance.get_logger("upload_manager")

        os.makedirs(self.upload_dir, exist_ok=True)

    def upload_document(
        self, file_path: str, original_filename: str, user_id: str
    ) -> Dict[str, Any]:
        """Full upload pipeline: validate, parse, chunk, embed, store.
        
        Args:
            file_path: Path to the uploaded file on disk.
            original_filename: Original filename from the upload.
            user_id: User identifier for namespace isolation.
            
        Returns:
            Dict with upload status and document metadata.
        """
        # Validate extension
        ext = os.path.splitext(original_filename)[1].lower().lstrip(".")
        if ext not in self.allowed_extensions:
            raise ValueError(
                f"Unsupported file type: .{ext}. "
                f"Allowed: {', '.join(self.allowed_extensions)}"
            )

        # Validate size
        file_size = os.path.getsize(file_path)
        if file_size > self.max_size_mb * 1024 * 1024:
            raise ValueError(
                f"File too large: {file_size / (1024*1024):.1f}MB. "
                f"Max: {self.max_size_mb}MB"
            )

        doc_id = str(uuid.uuid4())[:8]
        self.logger.info(
            f"Processing upload: {original_filename} "
            f"(user: {user_id}, doc_id: {doc_id})"
        )

        # 1. Parse file to text
        text = self.parser.parse_file(file_path)
        if not text.strip():
            raise ValueError("Document appears to be empty or unreadable")

        # 2. Chunk the text
        chunks = self.chunker.chunk_text(
            text,
            metadata={
                "source": original_filename,
                "doc_id": doc_id,
                "user_id": user_id,
                "type": "company_document",
                "uploaded_at": datetime.now().isoformat(),
            },
        )

        # 3. Store chunks in user-specific vector store
        documents = [c["text"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]
        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

        self.vector_store.add_company_documents(
            user_id=user_id,
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )

        # 4. Save to user directory and update manifest
        user_dir = os.path.join(self.upload_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)

        # Copy file to user's upload directory
        stored_filename = f"{doc_id}_{original_filename}"
        stored_path = os.path.join(user_dir, stored_filename)
        if file_path != stored_path:
            import shutil
            shutil.copy2(file_path, stored_path)

        # Update manifest
        doc_record = {
            "doc_id": doc_id,
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "uploaded_at": datetime.now().isoformat(),
            "file_size": file_size,
            "chunk_count": len(chunks),
            "char_count": len(text),
        }
        self._update_manifest(user_id, doc_record)

        self.logger.info(
            f"Upload complete: {original_filename} -> "
            f"{len(chunks)} chunks stored"
        )

        return {
            "success": True,
            "doc_id": doc_id,
            "filename": original_filename,
            "chunks": len(chunks),
            "characters": len(text),
        }

    def list_documents(self, user_id: str) -> List[Dict[str, Any]]:
        """List all documents uploaded by a user."""
        manifest = self._load_manifest(user_id)
        return manifest.get("documents", [])

    def delete_document(self, user_id: str, doc_id: str) -> bool:
        """Delete a specific document and its chunks.
        
        Note: ChromaDB doesn't support deletion by metadata filter natively
        in all versions. This deletes the backing file and manifest entry.
        To fully remove from vector store, the user's collection can be
        rebuilt.
        """
        manifest = self._load_manifest(user_id)
        documents = manifest.get("documents", [])

        doc_to_delete = None
        for doc in documents:
            if doc["doc_id"] == doc_id:
                doc_to_delete = doc
                break

        if not doc_to_delete:
            return False

        # Delete stored file
        user_dir = os.path.join(self.upload_dir, user_id)
        stored_path = os.path.join(user_dir, doc_to_delete["stored_filename"])
        if os.path.exists(stored_path):
            os.remove(stored_path)

        # Remove from manifest
        manifest["documents"] = [
            d for d in documents if d["doc_id"] != doc_id
        ]
        self._save_manifest(user_id, manifest)

        # If no documents left, delete the vector store collection
        if not manifest["documents"]:
            self.vector_store.delete_company_collection(user_id)

        self.logger.info(
            f"Deleted document {doc_id} for user {user_id}"
        )
        return True

    def get_user_doc_count(self, user_id: str) -> int:
        """Get number of vector store chunks for a user."""
        return self.vector_store.company_doc_count(user_id)

    def _load_manifest(self, user_id: str) -> Dict[str, Any]:
        """Load user's document manifest."""
        manifest_path = os.path.join(
            self.upload_dir, user_id, "manifest.json"
        )
        if os.path.exists(manifest_path):
            with open(manifest_path, "r") as f:
                return json.load(f)
        return {"user_id": user_id, "documents": []}

    def _save_manifest(self, user_id: str, manifest: Dict[str, Any]):
        """Save user's document manifest."""
        user_dir = os.path.join(self.upload_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        manifest_path = os.path.join(user_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

    def _update_manifest(self, user_id: str, doc_record: Dict[str, Any]):
        """Add a document record to the user's manifest."""
        manifest = self._load_manifest(user_id)
        manifest["documents"].append(doc_record)
        self._save_manifest(user_id, manifest)
