"""Tests that run records say exactly what produced a result.

Run with:  python -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import citation_audit, export_contexts
from utils import run_config


class TestUncommittedChanges(unittest.TestCase):

    def status(self, stdout, returncode=0):
        return mock.patch("utils.run_config.subprocess.run",
                          return_value=SimpleNamespace(returncode=returncode, stdout=stdout))

    def test_clean_tree_is_not_dirty(self):
        with self.status(""):
            manifest = run_config.run_manifest()
        self.assertIs(manifest["git_dirty"], False)
        self.assertEqual(manifest["git_uncommitted_files"], [])

    def test_modified_and_new_files_mark_the_run_dirty(self):
        with self.status(" M evaluation/ablation_eval.py\n?? evaluation/new_script.py\n"):
            manifest = run_config.run_manifest()
        self.assertIs(manifest["git_dirty"], True)
        self.assertEqual(manifest["git_uncommitted_files"],
                         ["evaluation/ablation_eval.py", "evaluation/new_script.py"])

    def test_results_written_by_the_run_itself_do_not_count(self):
        with self.status("?? evaluation/results/ablation_20260101.csv\n"):
            self.assertIs(run_config.run_manifest()["git_dirty"], False)

    def test_unknown_when_git_is_unavailable(self):
        with mock.patch("utils.run_config.subprocess.run", side_effect=FileNotFoundError):
            manifest = run_config.run_manifest()
        self.assertIsNone(manifest["git_dirty"])


class _ResultsFolder(unittest.TestCase):

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "evaluation", "results"))
        os.makedirs(os.path.join(self.tmp, "knowledge_data"))
        with open(os.path.join(self.tmp, "knowledge_data", "a.md"), "w") as f:
            f.write("# A\ncorpus text")
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.old_cwd)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"KNOWLEDGE_BASE_PATH": "./knowledge_data"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_run(self, stamp, corpus_hash):
        csv_path = f"evaluation/results/ablation_{stamp}.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("question_id,standard,category,condition,question,answer\n"
                    "Q1,GDPR,single_fact,fixed_rag,What?,See Article 32.\n")
        with open(f"evaluation/results/ablation_manifest_{stamp}.json", "w") as f:
            json.dump({"corpus_sha256": corpus_hash}, f)
        return csv_path

    def write_export(self, stamp, source_csv):
        path = f"evaluation/results/retrieved_contexts_{stamp}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"question_id": "Q1", "condition": "fixed_rag",
                                "retrieved_context": f"context from {source_csv}"}) + "\n")
        with open(path.replace(".jsonl", "_manifest.json"), "w") as f:
            json.dump({"source_csv": source_csv}, f)


class TestCorpusCheck(_ResultsFolder):

    def test_matches_when_the_corpus_is_unchanged(self):
        csv_path = self.write_run("1", run_config.hash_corpus("./knowledge_data"))
        self.assertTrue(export_contexts.corpus_check(csv_path)[0])

    def test_detects_a_changed_corpus(self):
        csv_path = self.write_run("1", "0" * 64)
        self.assertFalse(export_contexts.corpus_check(csv_path)[0])

    def test_run_without_a_manifest_does_not_match(self):
        csv_path = self.write_run("1", "x")
        os.remove("evaluation/results/ablation_manifest_1.json")
        matches, recorded, _ = export_contexts.corpus_check(csv_path)
        self.assertFalse(matches)
        self.assertIsNone(recorded)


class TestAuditUsesTheRightExport(_ResultsFolder):

    def test_export_from_another_run_is_not_used(self):
        mine = self.write_run("1", "x")
        self.write_run("2", "x")
        self.write_export("a", "ablation_1.csv")
        self.write_export("b", "ablation_2.csv")  # newer, but for the other run
        contexts = citation_audit.stored_contexts(mine)
        self.assertEqual(contexts[("Q1", "fixed_rag")], "context from ablation_1.csv")

    def test_no_matching_export_gives_nothing(self):
        mine = self.write_run("1", "x")
        self.write_export("b", "ablation_2.csv")
        self.assertEqual(citation_audit.stored_contexts(mine), {})

    def test_refuses_to_rebuild_from_a_changed_corpus(self):
        mine = self.write_run("1", "0" * 64)
        with mock.patch.object(citation_audit, "build_context") as build:
            with self.assertRaises(SystemExit) as ctx:
                citation_audit.audit(mine)
        build.assert_not_called()
        self.assertIn("corpus has changed", str(ctx.exception))

    def test_recorded_export_is_used_even_after_the_corpus_changed(self):
        mine = self.write_run("1", "0" * 64)
        self.write_export("a", "ablation_1.csv")
        with mock.patch.object(citation_audit, "build_context") as build:
            results = citation_audit.audit(mine)
        build.assert_not_called()
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
