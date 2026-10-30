"""End-to-end test of metrics/analyze_run.py on a fabricated run directory (no ROS)."""

import csv
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, os.pardir, "metrics"))
sys.path.insert(0, HERE)

from analyze_run import analyze  # noqa: E402
from test_map_quality import room  # noqa: E402


def write_map(stem, cls_, res, origin):
    img = np.full(cls_.shape, 205, np.uint8)
    img[cls_ == 0] = 254
    img[cls_ == 1] = 0
    with open(stem + ".pgm", "wb") as f:
        f.write(f"P5\n{cls_.shape[1]} {cls_.shape[0]}\n255\n".encode())
        f.write(img.tobytes())
    with open(stem + ".yaml", "w") as f:
        f.write(f"image: {os.path.basename(stem)}.pgm\nresolution: {res}\n"
                f"origin: [{origin[0]}, {origin[1]}, {origin[2]}]\nnegate: 0\n"
                "occupied_thresh: 0.65\nfree_thresh: 0.196\n")


class AnalyzeRunTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        run = self.run = os.path.join(self.d, "run")
        os.makedirs(run)
        with open(os.path.join(run, "run_meta.json"), "w") as f:
            json.dump({"stack": "ros2", "algo": "slam_toolbox", "scans_expected": 200}, f)
        with open(os.path.join(run, "slam_toolbox.yaml"), "w") as f:
            f.write("map_frame: map\nodom_frame: odom\nbase_frame: base_link\n")
        with open(os.path.join(run, "cpu_mem.csv"), "w") as f:
            f.write("timestamp_unix,elapsed_time_sec,cpu_percent_total,memory_mb,ros_version,experiment_id\n")
            for i in range(10):
                f.write(f"{i},{i},{20 + i},{1000 + i},ROS2,x\n")
        with open(os.path.join(run, "proc_metrics.csv"), "w") as f:
            f.write("timestamp_unix,elapsed_time_sec,role,n_procs,cpu_percent,rss_mb\n")
            for i in range(10):
                f.write(f"{i},{i},slam,1,{50 + i},{200 + i}\n{i},{i},middleware,0,0,0\n")
        with open(os.path.join(run, "net_io.csv"), "w") as f:
            f.write("timestamp_unix,elapsed_time_sec,iface,bytes_sent,bytes_recv,packets_sent,packets_recv\n")
            f.write("0,0,lo,1000,1000,10,10\n0,0,eth0,5,5,1,1\n")
            f.write("10,10,lo,501000,501000,110,110\n10,10,eth0,5,5,1,1\n")

        # straight drive at 0.5 m/s for 20 s; SLAM estimate has a 2 cm lateral wobble
        events, gt = [], []
        for i in range(200):
            t = 100.0 + i * 0.1
            events.append(("scan", 1000 + i * 0.1, t, t, "", "", "", "", ""))
        for i in range(1000):
            t = 100.0 + i * 0.02
            x = 0.5 * (t - 100.0)
            y = 0.02 * math.sin(i)
            events.append(("tf", 1000 + i * 0.02 + 0.001, t, t, "odom", "base_link", x, y, 0.0))
            if i % 5 == 0:
                gt.append(f"{t:.6f} {x:.6f} 0 0 0 0 0 1")
        for k in range(4):
            t = 101.0 + k * 5.0
            events.append(("tf", 1000 + t - 100 + 0.004, t, t, "map", "odom", 0.0, 0.0, 0.0))
            events.append(("map", 1000 + t - 100 + 0.03, t + 0.03, t, "", "", "", "", ""))
        events.sort(key=lambda e: e[1])
        with open(os.path.join(run, "latency_events.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["event", "wall", "ros", "stamp", "parent", "child", "x", "y", "yaw", "width", "height"])
            for e in events:
                w.writerow(list(e) + ["", ""])
        self.ref_traj = os.path.join(self.d, "gt.tum")
        with open(self.ref_traj, "w") as f:
            f.write("\n".join(gt) + "\n")

        write_map(os.path.join(run, "map"), *room(noise=0.01))
        self.ref_map = os.path.join(self.d, "ref")
        write_map(self.ref_map, *room())

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_summary(self):
        m = analyze(self.run, self.ref_traj, self.ref_map + ".yaml")
        s = m["summary"]
        self.assertAlmostEqual(s["slam_cpu_mean"], 54.5)
        self.assertNotIn("middleware_cpu_mean", s)
        self.assertAlmostEqual(s["net_total_mb"], 1.0)
        self.assertAlmostEqual(s["scan_drop_rate"], 0.0)
        self.assertAlmostEqual(s["map_period_s"], 5.0, places=6)
        self.assertLess(s["ate_rmse_m"], 0.02)
        self.assertGreater(s["map_wall_f1"], 0.95)
        self.assertGreater(s["map_cell_accuracy"], 0.95)
        self.assertTrue(os.path.exists(os.path.join(self.run, "trajectory.tum")))


if __name__ == "__main__":
    unittest.main()
