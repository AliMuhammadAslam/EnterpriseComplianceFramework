import os
import json
import uuid
import shutil
import threading
from datetime import datetime
from typing import List, Dict, Any
from utils.logger import logger_instance
from knowledge.vector_store import VectorStore
from document_upload.parser import DocumentParser
from document_upload.chunker import DocumentChunker
from document_upload import validation
from dotenv import load_dotenv

load_dotenv()


class UploadManager:
    """Handles document uploads: validation, parsing, chunking, and storage."""

    def __init__(self, vector_store: VectorStore = None):
        self.upload_dir = os.getenv("UPLOAD_DIR", "./uploads")
        self.max_size_mb = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
        self.allowed_extensions = {"pdf", "docx", "txt"}
        self.vector_store = vector_store or VectorStore()
        self.parser = DocumentParser()
        self.chunker = DocumentChunker()
        self.logger = logger_instance.get_logger("upload_manager")
        self._manifest_locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

        os.makedirs(self.upload_dir, exist_ok=True)

    def upload_document(
        self, file_path: str, original_filename: str, user_id: str
    ) -> Dict[str, Any]:
        """Validate, parse, chunk, embed, and store an uploaded document."""
        # Strip any directory components before the name touches a path.
        safe_name = validation.safe_filename(original_filename)

        ext = os.path.splitext(safe_name)[1].lower().lstrip(".")
        if ext not in self.allowed_extensions:
            raise ValueError(
                f"Unsupported file type: .{ext}. "
                f"Allowed: {', '.join(self.allowed_extensions)}"
            )

        # Check file size
        file_size = os.path.getsize(file_path)
        if file_size > self.max_size_mb * 1024 * 1024:
            raise ValueError(
                f"File too large: {file_size / (1024*1024):.1f}MB. "
                f"Max: {self.max_size_mb}MB"
            )

        # The extension is a claim; check the bytes agree with it.
        validation.verify_file_signature(file_path, ext)
        validation.check_document_limits(file_path, ext)

        doc_id = str(uuid.uuid4())[:8]
        self.logger.info(
            f"Processing upload: {safe_name} "
            f"(user: {user_id}, doc_id: {doc_id})"
        )

        text = self.parser.parse_file(file_path)
        if not text.strip():
            raise ValueError("Document appears to be empty or unreadable")

        validation.check_extracted_size(text)

        text, neutralised = validation.neutralise_instructions(text)
        if neutralised:
            self.logger.warning(
                f"Neutralised {len(neutralised)} embedded instruction(s) "
                f"in {safe_name} (user: {user_id})"
            )

        chunks = self.chunker.chunk_text(
            text,
            metadata={
                "source": safe_name,
                "doc_id": doc_id,
                "user_id": user_id,
                "type": "company_document",
                "uploaded_at": datetime.now().isoformat(),
            },
        )

        documents = [c["text"] for c in chunks]
        metadatas = [c["metadata"] for c in chunks]
        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

        user_dir = os.path.join(self.upload_dir, user_id)
        stored_filename = f"{doc_id}_{safe_name}"
        stored_path = os.path.join(user_dir, stored_filename)

        # Chunks, stored file and manifest entry succeed together or not at
        # all. A failure after the chunks were stored used to leave them
        # searchable but missing from the document list, so they could never
        # be deleted.
        try:
            self.vector_store.add_company_documents(
                user_id=user_id,
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )

            os.makedirs(user_dir, exist_ok=True)
            if file_path != stored_path:
                shutil.copy2(file_path, stored_path)

            doc_record = {
                "doc_id": doc_id,
                "original_filename": safe_name,
                "stored_filename": stored_filename,
                "uploaded_at": datetime.now().isoformat(),
                "file_size": file_size,
                "chunk_count": len(chunks),
                "char_count": len(text),
            }
            self._update_manifest(user_id, doc_record)
        except Exception:
            self._discard_partial_upload(user_id, doc_id, stored_path, file_path)
            raise

        self.logger.info(
            f"Upload complete: {safe_name} -> "
            f"{len(chunks)} chunks stored"
        )

        return {
            "success": True,
            "doc_id": doc_id,
            "filename": safe_name,
            "chunks": len(chunks),
            "characters": len(text),
            "neutralised_instructions": len(neutralised),
        }

    def _discard_partial_upload(self, user_id, doc_id, stored_path, source_path):
        """Remove whatever a failed upload managed to write."""
        try:
            self.vector_store.delete_company_document(user_id, doc_id)
        except Exception as e:
            self.logger.error(f"Could not remove chunks of failed upload {doc_id}: {e}")
        if stored_path != source_path and os.path.exists(stored_path):
            os.remove(stored_path)

    def list_documents(self, user_id: str) -> List[Dict[str, Any]]:
        """List all documents uploaded by a user."""
        manifest = self._load_manifest(user_id)
        return manifest.get("documents", [])

    def delete_document(self, user_id: str, doc_id: str) -> bool:
        """Delete a specific document: its vector store chunks, backing file, and manifest entry.

        Raises if the chunks cannot be removed, leaving the file and the
        manifest entry in place so the user can retry.
        """
        with self._manifest_lock(user_id):
            return self._delete_document_locked(user_id, doc_id)

    def _delete_document_locked(self, user_id: str, doc_id: str) -> bool:
        manifest = self._load_manifest(user_id)
        documents = manifest.get("documents", [])

        doc_to_delete = None
        for doc in documents:
            if doc["doc_id"] == doc_id:
                doc_to_delete = doc
                break

        if not doc_to_delete:
            return False

        # Remove this document's chunks from the vector store
        self.vector_store.delete_company_document(user_id, doc_id)

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

        # Safety net for any pre-existing orphaned chunks from before this fix
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
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"user_id": user_id, "documents": []}

    def _save_manifest(self, user_id: str, manifest: Dict[str, Any]):
        """Save user's document manifest."""
        user_dir = os.path.join(self.upload_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        manifest_path = os.path.join(user_dir, "manifest.json")
        # Write then swap, so an interrupted save cannot truncate the manifest.
        tmp_path = f"{manifest_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp_path, manifest_path)

    def _update_manifest(self, user_id: str, doc_record: Dict[str, Any]):
        """Add a document record to the user's manifest."""
        with self._manifest_lock(user_id):
            manifest = self._load_manifest(user_id)
            manifest["documents"].append(doc_record)
            self._save_manifest(user_id, manifest)

    def _manifest_lock(self, user_id: str) -> threading.Lock:
        """One lock per user, so two concurrent uploads cannot both read the
        manifest, append, and have the second write drop the first record."""
        with self._locks_guard:
            return self._manifest_locks.setdefault(user_id, threading.Lock())
