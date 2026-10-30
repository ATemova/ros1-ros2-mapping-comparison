"""Unit tests for metrics/stats_utils.py. Reference values computed with scipy 1.x."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "metrics"))

from stats_utils import cliffs_delta, cliffs_magnitude, mann_whitney_u, mean_ci95, percentile  # noqa: E402


class MannWhitneyTest(unittest.TestCase):
    def test_exact_separated(self):
        r = mann_whitney_u([1.1, 2.3, 3.0, 4.2, 5.9], [6.1, 7.4, 8.0, 9.3, 10.2])
        self.assertEqual(r["method"], "exact")
        self.assertAlmostEqual(r["u"], 0.0)
        self.assertAlmostEqual(r["p"], 0.007936507936507936, places=12)

    def test_exact_unequal_sizes(self):
        r = mann_whitney_u([3.1, 1.2, 5.5, 2.4], [2.0, 4.4, 6.1])
        self.assertAlmostEqual(r["u"], 4.0)
        self.assertAlmostEqual(r["p"], 0.6285714285714286, places=12)

    def test_normal_with_ties(self):
        r = mann_whitney_u([1, 2, 2, 3, 4, 4, 5], [3, 4, 4, 5, 6, 7, 7, 8])
        self.assertEqual(r["method"], "normal")
        self.assertAlmostEqual(r["u"], 8.0)
        self.assertAlmostEqual(r["p"], 0.02228731901455301, places=10)

    def test_empty(self):
        self.assertNotEqual(mann_whitney_u([], [1.0])["p"], mann_whitney_u([], [1.0])["p"])


class DescriptiveTest(unittest.TestCase):
    def test_mean_ci95(self):
        m, sd, h = mean_ci95([1.2, 3.4, 2.2, 5.0, 4.1])
        self.assertAlmostEqual(m, 3.18)
        self.assertAlmostEqual(sd, 1.5073154945133418)
        self.assertAlmostEqual(h, 1.8712793416270055)

    def test_percentile_matches_numpy_linear(self):
        self.assertAlmostEqual(percentile([1.2, 3.4, 2.2, 5.0, 4.1], 95), 4.82)
        self.assertAlmostEqual(percentile([7.0], 95), 7.0)

    def test_cliffs_delta(self):
        self.assertAlmostEqual(cliffs_delta([5, 6, 7], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(cliffs_delta([1, 2], [1, 2]), 0.0)
        self.assertEqual(cliffs_magnitude(0.5), "large")
        self.assertEqual(cliffs_magnitude(-0.2), "small")


if __name__ == "__main__":
    unittest.main()
