"""Tests for audit filtering and chain checks, account file safety and upload integrity.

Embeddings are stubbed, so this runs without API calls.

Run with:  python -m unittest discover -s tests
"""

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_logger import AuditLogger
from auth.user_store import UserStore
from document_upload.manager import UploadManager
from knowledge.vector_store import VectorStore


class _AuditCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        AuditLogger._reset_singleton()
        self.audit = AuditLogger(log_dir=self.tmp)

    def tearDown(self):
        AuditLogger._reset_singleton()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestAuditDateFilter(_AuditCase):

    def test_end_date_includes_the_whole_day(self):
        entry = self.audit.log("LOGIN", user_id="u")
        day = entry.timestamp[:10]
        self.assertEqual(len(self.audit.query(user_id="u", end_date=day)), 1)

    def test_end_date_before_the_entry_excludes_it(self):
        self.audit.log("LOGIN", user_id="u")
        self.assertEqual(self.audit.query(user_id="u", end_date="2000-01-01"), [])

    def test_full_timestamp_end_date_is_still_exact(self):
        entry = self.audit.log("LOGIN", user_id="u")
        self.assertEqual(len(self.audit.query(user_id="u", end_date=entry.timestamp)), 1)


class TestAuditOrdering(_AuditCase):

    def test_entries_sharing_a_timestamp_are_listed_newest_first(self):
        with mock.patch("audit.audit_logger.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-11-04T12:00:00.000000"
            for action in ("FIRST", "SECOND", "THIRD"):
                self.audit.log(action, user_id="u")
        self.assertEqual([e["action"] for e in self.audit.query(user_id="u")],
                         ["THIRD", "SECOND", "FIRST"])

    def test_chain_verification_still_uses_write_order(self):
        with mock.patch("audit.audit_logger.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-11-04T12:00:00.000000"
            self.audit.log("FIRST", user_id="u")
            self.audit.log("SECOND", user_id="u")
        self.assertTrue(self.audit.verify_chain()["intact"])


class TestAuditChainStripping(_AuditCase):

    def rewrite_last(self, change):
        with open(self.audit.log_file, encoding="utf-8") as f:
            lines = f.read().splitlines()
        record = json.loads(lines[-1])
        change(record)
        lines[-1] = json.dumps(record)
        with open(self.audit.log_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_edited_last_entry_with_hashes_stripped_is_detected(self):
        self.audit.log("LOGIN", user_id="u")
        self.audit.log("REPORT_DELETE", user_id="u", resource_id="abc")

        def tamper(record):
            record["resource_id"] = "TAMPERED"
            record.pop("entry_hash")
            record.pop("prev_hash")

        self.rewrite_last(tamper)
        result = self.audit.verify_chain()
        self.assertFalse(result["intact"])
        self.assertIn("missing after the chain began", result["problems"][0]["problem"])

    def test_legacy_entries_before_the_chain_are_still_accepted(self):
        with open(self.audit.log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"event_id": "old", "timestamp": "2025-01-01T00:00:00",
                                "user_id": "u", "action": "LOGIN"}) + "\n")
        AuditLogger._reset_singleton()
        audit = AuditLogger(log_dir=self.tmp)
        audit.log("LOGIN", user_id="u")
        result = audit.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["unchained_legacy_entries"], 1)


class TestAuditCsvExport(_AuditCase):

    def export(self):
        path = os.path.join(self.tmp, "out.csv")
        self.audit.export_csv(path, user_id="u")
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_formula_in_a_logged_value_is_neutralised(self):
        self.audit.log("DOCUMENT_DELETE", user_id="u", resource_id='=HYPERLINK("http://x")')
        row = self.export()[0]
        self.assertEqual(row["resource_id"], '\'=HYPERLINK("http://x")')

    def test_ordinary_values_are_unchanged(self):
        self.audit.log("REPORT_DELETE", user_id="u", resource_id="1a2b3c4d")
        self.assertEqual(self.export()[0]["resource_id"], "1a2b3c4d")

    def test_export_is_not_capped(self):
        for _ in range(3):
            self.audit.log("LOGIN", user_id="u")
        with mock.patch.object(self.audit, "query", wraps=self.audit.query) as query:
            self.export()
        self.assertEqual(query.call_args.kwargs["limit"], sys.maxsize)


class TestUserStoreFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "users.json")
        with mock.patch("builtins.print"):
            UserStore(store_path=self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_corrupt_file_stops_start_up_and_is_left_untouched(self):
        with open(self.path, encoding="utf-8") as f:
            original = f.read()
        damaged = original[:-20]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(damaged)

        with mock.patch("builtins.print") as printed:
            with self.assertRaises(RuntimeError) as ctx:
                UserStore(store_path=self.path)
        self.assertIn("could not be read", str(ctx.exception))
        printed.assert_not_called()
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), damaged)

    def test_missing_file_still_seeds(self):
        os.remove(self.path)
        with mock.patch("builtins.print"):
            store = UserStore(store_path=self.path)
        self.assertEqual(len(store.users), 4)

    def test_valid_file_loads(self):
        store = UserStore(store_path=self.path)
        self.assertIn("john", store.users)


class _FakeEmbeddings:
    def __init__(self):
        self.batch_sizes = []

    def embed_text(self, text):
        return [b / 255 for b in hashlib.sha256(text.encode()).digest()[:16]]

    def embed_batch(self, texts):
        self.batch_sizes.append(len(texts))
        return [self.embed_text(t) for t in texts]


class TestUploadIntegrity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"UPLOAD_DIR": os.path.join(self.tmp, "up")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = VectorStore(persist_directory=os.path.join(self.tmp, "chroma"))
        self.embeddings = _FakeEmbeddings()
        self.store.embedding_service = self.embeddings
        self.manager = UploadManager(self.store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upload(self, name, text="policy text"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return self.manager.upload_document(path, name, "u")["doc_id"]

    def test_failed_vector_delete_is_reported_and_changes_nothing(self):
        doc_id = self.upload("a.txt")
        collection = self.store.client.get_collection("company_docs_u")
        with mock.patch.object(self.store.client, "get_collection", return_value=collection), \
             mock.patch.object(collection, "delete", side_effect=RuntimeError("db locked")):
            with self.assertRaises(RuntimeError):
                self.manager.delete_document("u", doc_id)
        self.assertEqual([d["doc_id"] for d in self.manager.list_documents("u")], [doc_id])
        self.assertEqual(self.store.company_doc_count("u"), 1)

    def test_successful_delete_removes_everything(self):
        keep, gone = self.upload("a.txt", "keep this"), self.upload("b.txt", "remove this")
        self.assertTrue(self.manager.delete_document("u", gone))
        self.assertEqual([d["doc_id"] for d in self.manager.list_documents("u")], [keep])
        self.assertEqual(self.store.company_doc_count("u"), 1)

    def test_failure_after_chunks_are_stored_leaves_nothing_behind(self):
        self.upload("a.txt")
        with mock.patch("shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.upload("b.txt", "second document")
        self.assertEqual(len(self.manager.list_documents("u")), 1)
        self.assertEqual(self.store.company_doc_count("u"), 1)

    def test_large_document_is_embedded_in_batches(self):
        words = " ".join(f"w{i}" for i in range(500 * 250))
        self.upload("big.txt", words)
        self.assertGreater(len(self.embeddings.batch_sizes), 1)
        self.assertLessEqual(max(self.embeddings.batch_sizes), 100)

    def test_concurrent_uploads_keep_every_manifest_record(self):
        paths = []
        for i in range(8):
            path = os.path.join(self.tmp, f"d{i}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"document {i}")
            paths.append(path)
        real_load = self.manager._load_manifest

        def slow_load(user_id):
            manifest = real_load(user_id)
            threading.Event().wait(0.02)  # widen the read-modify-write window
            return manifest

        with mock.patch.object(self.manager, "_load_manifest", side_effect=slow_load):
            threads = [threading.Thread(target=self.manager._update_manifest,
                                        args=("u", {"doc_id": f"id{i}"})) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(self.manager.list_documents("u")), 8)


if __name__ == "__main__":
    unittest.main()
