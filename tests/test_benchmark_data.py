"""Tests that every benchmark ground truth can be answered from the corpus.

benchmark_v2 states that each ground truth is taken from knowledge_data/.
Two were not: they cited GDPR Articles 33 and 34 and PECA Section 32, none of
which the corpus contains, so a grounded answer was scored below one drawn
from model memory. This checks the claim for every question.

Run with:  python -m unittest discover -s tests
"""

import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import citation_validator as cv
from evaluation.benchmark_v2 import all_questions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "ten": "10", "twelve": "12", "thirty": "30"}
NUMERIC_FACT = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")\s*(?:-\s*)?"
    r"(hours?|days?|years?|months?|minutes?|%|percent)\b",
    re.I,
)


def _normalise(text):
    text = cv._normalise(text)
    text = re.sub(r"(\d)\s*-\s*(hour|day|year|month|minute)", r"\1 \2", text)
    text = text.replace(" percent", "%")
    for word, digit in NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    return text


def _corpus():
    paths = glob.glob(os.path.join(ROOT, "knowledge_data", "*.md"))
    return _normalise(" ".join(open(p, encoding="utf-8").read() for p in paths))


def _present(identifier, haystack):
    needle = cv._normalise(identifier)
    if cv._find_identifier(haystack, needle) != -1:
        return True
    # The corpus writes sub-clauses as "(8.2)" under a "Clause 8" heading.
    sub_clause = re.fullmatch(r"clause (\d+\.\d+(?:\.\d+)*)", needle)
    return bool(sub_clause) and f"({sub_clause.group(1)})" in haystack


class TestGroundTruthsComeFromTheCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.corpus = _corpus()
        cls.questions = all_questions(include_holdout=True)

    def test_every_cited_identifier_is_in_the_corpus(self):
        missing = []
        for q in self.questions:
            question = _normalise(q["question"])
            for citation in cv.extract_citations(q["ground_truth"]):
                if not (_present(citation.text, self.corpus) or _present(citation.text, question)):
                    missing.append(f"{q['id']}: {citation.text}")
        self.assertEqual(missing, [], "ground truth cites identifiers the corpus lacks")

    def test_every_duration_and_percentage_is_in_the_corpus(self):
        missing = []
        for q in self.questions:
            question = _normalise(q["question"])
            for match in NUMERIC_FACT.finditer(_normalise(q["ground_truth"])):
                fact = match.group(0)
                if fact not in self.corpus and fact not in question:
                    missing.append(f"{q['id']}: {fact}")
        self.assertEqual(missing, [], "ground truth states values the corpus lacks")

    def test_question_set_is_complete(self):
        ids = [q["id"] for q in self.questions]
        self.assertEqual(len(ids), len(set(ids)), "duplicate question ids")
        self.assertIn("GDPR-01", ids)
        self.assertIn("SF-06", ids)


if __name__ == "__main__":
    unittest.main()
