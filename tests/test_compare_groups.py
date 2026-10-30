"""Tests for metrics/compare_groups.py grouping, guards and statistics output."""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, os.pardir, "metrics", "compare_groups.py")
sys.path.insert(0, os.path.join(HERE, os.pardir, "metrics"))

from compare_groups import holm  # noqa: E402


def make_run(root, name, cpu, slam_cpu, **meta):
    d = os.path.join(root, meta["stack"], name)
    os.makedirs(d)
    m = {"algo": "slam_toolbox", "mode": "replay", "bag_id": "b", "rate": 1.0, "run_tag": "t",
         "role": "all", "exit_status": 0}
    m.update(meta)
    with open(os.path.join(d, "run_meta.json"), "w") as f:
        json.dump(m, f)
    with open(os.path.join(d, "cpu_mem.csv"), "w") as f:
        f.write("elapsed_time_sec,cpu_percent_total,memory_mb\n")
        for t in range(10):
            f.write(f"{t},{cpu + (t % 3) * 0.1},{900 + t}\n")
    with open(os.path.join(d, "run_metrics.json"), "w") as f:
        json.dump({"summary": {"slam_cpu_mean": slam_cpu}}, f)


class CompareGroupsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        rng = random.Random(1)
        for i in range(5):
            make_run(self.d, f"r1_{i}", 30 + rng.random(), 40 + rng.random(), stack="ros1", ros_distro="noetic",
                     rmw="tcpros")
            for rmw, base in (("rmw_fastrtps_cpp", 20), ("rmw_cyclonedds_cpp", 25), ("rmw_zenoh_cpp", 22)):
                make_run(self.d, f"{rmw}_{i}", base + rng.random(), base + 10 + rng.random(), stack="ros2",
                         ros_distro="humble", rmw=rmw)

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_cg(self, *args):
        return subprocess.run([sys.executable, SCRIPT, "--results", self.d, "--tag", "t"] + list(args),
                              capture_output=True, text=True)

    def test_stack_grouping_refuses_mixed_rmw(self):
        r = self.run_cg()
        self.assertEqual(r.returncode, 1)
        self.assertIn("mixes rmw", r.stderr)

    def test_rmw_grouping(self):
        out = os.path.join(self.d, "r.json")
        r = self.run_cg("--stack", "ros2", "--group-by", "rmw", "--json", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.load(open(out))
        self.assertEqual(rep["groups"][0], "rmw_fastrtps_cpp")
        row = next(m for m in rep["metrics"] if m["metric"] == "slam_cpu_mean")
        self.assertLess(row["kruskal_wallis"]["p"], 0.01)
        self.assertEqual(len(row["comparisons"]), 2)
        self.assertIn("p_holm", row["comparisons"][0])
        self.assertIn("Kruskal-Wallis p", r.stdout)

    def test_variant_grouping_with_baseline(self):
        r = self.run_cg("--group-by", "variant", "--baseline", "ros1-noetic")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ros2-humble-cyclonedds vs ros1-noetic", r.stdout)

    def test_ros1_vs_one_rmw(self):
        r = self.run_cg("--rmw", "rmw_cyclonedds_cpp")
        self.assertEqual(r.returncode, 0)  # the rmw filter drops ROS1 (tcpros): one group, descriptive
        self.assertIn("Single group", r.stdout)
        r = self.run_cg("--group-by", "variant", "--variant", "ros1-noetic,ros2-humble-cyclonedds")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## ros1-noetic vs ros2-humble-cyclonedds", r.stdout)

    def test_conditions_are_not_pooled(self):
        make_run(self.d, "stress", 50, 60, stack="ros2", ros_distro="humble", rmw="rmw_fastrtps_cpp",
                 condition="cpus1")
        r = self.run_cg("--stack", "ros2", "--group-by", "rmw")
        self.assertEqual(r.returncode, 1)
        self.assertIn("condition=cpus1", r.stderr)
        r = self.run_cg("--stack", "ros2", "--rmw", "rmw_fastrtps_cpp", "--group-by", "condition")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_holm(self):
        self.assertEqual(holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])


if __name__ == "__main__":
    unittest.main()
