"""Tests for the power computation (stats_utils) and metrics/sample_size.py.

Reference values from statsmodels.stats.power.TTestIndPower (two-sided, alpha 0.05).
"""

import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, os.pardir, "metrics"), HERE]

from stats_utils import min_detectable_d, runs_needed, t_crit_two_sided, ttest_power  # noqa: E402
from test_compare_groups import make_run  # noqa: E402

SCRIPT = os.path.join(HERE, os.pardir, "metrics", "sample_size.py")


class PowerTest(unittest.TestCase):
    def test_critical_values(self):
        self.assertAlmostEqual(t_crit_two_sided(0.05, 2), 4.302652729749462, places=8)
        self.assertAlmostEqual(t_crit_two_sided(0.05, 8), 2.306004135204166, places=8)

    def test_power_matches_statsmodels(self):
        for d, n, ref in ((1.0, 5, 0.28629549338059757), (2.0, 5, 0.7905423779725714),
                          (2.0, 6, 0.8764177714119884), (0.5, 64, 0.8014595579222542)):
            self.assertAlmostEqual(ttest_power(d, n), ref, places=8)

    def test_runs_needed_matches_statsmodels(self):
        for d, power, ref in ((0.5, 0.8, 64), (1.0, 0.8, 17), (1.5, 0.8, 9), (2.0, 0.8, 6),
                              (3.0, 0.9, 4), (5.0, 0.8, 3)):
            self.assertEqual(runs_needed(d, power), ref)
        self.assertIsNone(runs_needed(0.01))
        self.assertEqual(runs_needed(math.inf), 2)

    def test_min_detectable_d(self):
        self.assertAlmostEqual(min_detectable_d(5), 2.0244, places=3)
        self.assertAlmostEqual(min_detectable_d(10), 1.3249, places=3)


class SampleSizeScriptTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        rng = random.Random(7)
        for i in range(3):
            make_run(self.d, f"a{i}", 30 + rng.gauss(0, 1), 40 + rng.gauss(0, 1), stack="ros1",
                     ros_distro="noetic", rmw="tcpros")
            make_run(self.d, f"b{i}", 30 + rng.gauss(0, 1), 41 + rng.gauss(0, 1), stack="ros2",
                     ros_distro="humble", rmw="rmw_fastrtps_cpp")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_plan(self):
        out = os.path.join(self.d, "plan.json")
        r = subprocess.run([sys.executable, SCRIPT, "--results", self.d, "--tag", "t", "--json", out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Runs needed per group", r.stdout)
        res = json.load(open(out))
        row = next(x for x in res["rows"] if x["metric"] == "slam_cpu_mean")
        self.assertGreater(row["d"], 0)
        self.assertGreaterEqual(row["runs"], 4)
        self.assertEqual(row["runs"], max(4, math.ceil(runs_needed(row["d"]) / 0.864)))
        self.assertAlmostEqual(row["mde_planned"], min_detectable_d(5) * row["pooled_sd"], places=9)


if __name__ == "__main__":
    unittest.main()
