"""Tests for the confidence interval arithmetic in evaluation/analysis.py.

Run with:  python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import analysis

# Published two-sided 95% values, for checking the expansion beyond the table.
REFERENCE = {33: 2.0345, 34: 2.0322, 39: 2.0227, 41: 2.0195, 40: 2.0211,
             50: 2.0086, 60: 2.0003, 100: 1.9840, 120: 1.9799}


class TestTValue(unittest.TestCase):

    def test_small_samples_use_the_exact_value_not_the_normal_one(self):
        self.assertAlmostEqual(analysis.t_value(2), 12.7062, places=4)
        self.assertAlmostEqual(analysis.t_value(3), 4.3027, places=4)
        self.assertAlmostEqual(analysis.t_value(4), 3.1824, places=4)

    def test_every_degree_of_freedom_up_to_30_is_tabulated(self):
        self.assertTrue(all(df in analysis.T_CRITICAL for df in range(1, 31)))

    def test_expansion_matches_published_values_beyond_the_table(self):
        for df, expected in REFERENCE.items():
            value = (
                analysis.Z_975
                + (analysis.Z_975 ** 3 + analysis.Z_975) / (4 * df)
                + (5 * analysis.Z_975 ** 5 + 16 * analysis.Z_975 ** 3 + 3 * analysis.Z_975) / (96 * df ** 2)
                + (3 * analysis.Z_975 ** 7 + 19 * analysis.Z_975 ** 5 + 17 * analysis.Z_975 ** 3
                   - 15 * analysis.Z_975) / (384 * df ** 3)
            )
            self.assertAlmostEqual(value, expected, delta=2e-4, msg=f"df={df}")
            self.assertAlmostEqual(analysis.t_value(df + 1), expected, delta=2e-4)

    def test_values_decrease_towards_the_normal_value(self):
        values = [analysis.t_value(n) for n in range(2, 200)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreater(values[-1], analysis.Z_975)

    def test_single_observation_has_no_interval(self):
        with self.assertRaises(ValueError):
            analysis.t_value(1)


class TestPairedDifference(unittest.TestCase):

    def test_three_pairs_use_the_t_value_for_two_degrees_of_freedom(self):
        scores = {"a": {"q1": 4.0, "q2": 5.0, "q3": 3.0}, "b": {"q1": 3.0, "q2": 3.0, "q3": 3.0}}
        n, mean, low, high = analysis.paired_difference(scores, {}, "a", "b")
        self.assertEqual(n, 3)
        self.assertAlmostEqual(mean, 1.0)
        # sd of [1, 2, 0] is 1, so the margin is 4.3027 / sqrt(3).
        self.assertAlmostEqual(high - mean, 4.3027 / 3 ** 0.5, places=4)


if __name__ == "__main__":
    unittest.main()
