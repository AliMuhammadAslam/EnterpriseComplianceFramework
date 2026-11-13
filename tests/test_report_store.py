"""Tests that report ids cannot reach files outside the user's report folder.

Run with:  python -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.report_store import ReportStore


class TestReportIdContainment(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reports_dir = os.path.join(self.tmp, "reports")
        self.store = ReportStore(reports_dir=self.reports_dir)

        # A file one level above the reports folder, standing in for users.json.
        self.secret = os.path.join(self.tmp, "users.json")
        with open(self.secret, "w", encoding="utf-8") as f:
            json.dump({"john": {"password_hash": "x"}}, f)

        self.other = self.store.save_report("analyst", "analyst report", ["GDPR"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_saved_report_round_trips(self):
        meta = self.store.save_report("default", "my report", ["ISO 27001"])
        report = self.store.get_report("default", meta["report_id"])
        self.assertEqual(report["report_text"], "my report")

    def test_backslash_traversal_cannot_read_a_file_outside_the_folder(self):
        self.assertIsNone(self.store.get_report("default", "..\\..\\users"))

    def test_forward_slash_traversal_is_rejected(self):
        self.assertIsNone(self.store.get_report("default", "../../users"))

    def test_another_users_report_cannot_be_read_by_traversal(self):
        crafted = "..\\analyst\\" + self.other["report_id"]
        self.assertIsNone(self.store.get_report("default", crafted))
        crafted = "../analyst/" + self.other["report_id"]
        self.assertIsNone(self.store.get_report("default", crafted))

    def test_traversal_cannot_delete_a_file_outside_the_folder(self):
        self.assertFalse(self.store.delete_report("default", "..\\..\\users"))
        self.assertTrue(os.path.exists(self.secret))

    def test_traversal_cannot_delete_another_users_report(self):
        crafted = "..\\analyst\\" + self.other["report_id"]
        self.assertFalse(self.store.delete_report("default", crafted))
        self.assertIsNotNone(self.store.get_report("analyst", self.other["report_id"]))

    def test_own_report_can_still_be_deleted(self):
        meta = self.store.save_report("default", "to delete", [])
        self.assertTrue(self.store.delete_report("default", meta["report_id"]))
        self.assertIsNone(self.store.get_report("default", meta["report_id"]))

    def test_non_string_and_empty_ids_are_rejected(self):
        self.assertIsNone(self.store.get_report("default", ""))
        self.assertIsNone(self.store.get_report("default", None))


if __name__ == "__main__":
    unittest.main()
