"""Tests for metrics/trajectory.py and metrics/latency_analysis.py.

ATE/RPE were validated against evo 1.38 (identical to ~1e-13 on random 3D trajectories);
these tests pin the properties without needing evo in CI.
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "metrics"))

from latency_analysis import analyze  # noqa: E402
from trajectory import associate, errors, extract, se2_to_se3  # noqa: E402


def path(n=100, dt=0.1):
    stamps = np.arange(n) * dt + 100.0
    poses = [se2_to_se3(0.3 * t, 0.5 * math.sin(0.2 * t), 0.1 * t) for t in stamps - 100.0]
    return stamps, poses


class TrajectoryTest(unittest.TestCase):
    def test_identical(self):
        s, p = path()
        r = errors(s, p, s, p)
        self.assertEqual(r["pairs"], len(s))
        self.assertAlmostEqual(r["ate_rmse"], 0.0, places=9)
        self.assertAlmostEqual(r["rpe_trans_rmse"], 0.0, places=9)

    def test_rigid_offset_removed_by_alignment(self):
        s, p = path()
        T = se2_to_se3(1.0, -2.0, 0.7)
        q = [T @ x for x in p]
        self.assertAlmostEqual(errors(s, p, s, q)["ate_rmse"], 0.0, places=6)
        self.assertGreater(errors(s, p, s, q, align=False)["ate_rmse"], 1.0)
        self.assertAlmostEqual(errors(s, p, s, q, align=False)["rpe_trans_rmse"], 0.0, places=9)

    def test_constant_offset_ate(self):
        s, p = path()
        q = [x.copy() for x in p]
        for i, x in enumerate(q):
            x[1, 3] += 0.1 if i % 2 else -0.1
        r = errors(s, p, s, q)
        self.assertAlmostEqual(r["ate_rmse"], 0.1, delta=0.005)

    def test_association_tolerance(self):
        a = np.array([0.0, 0.1, 0.2, 0.3])
        b = np.array([0.005, 0.12, 0.2, 0.5])
        self.assertEqual(associate(a, b, 0.01), [(0, 0), (2, 2)])

    def test_extract_composes_map_odom(self):
        ev = [
            {"event": "tf", "wall": 1.0, "ros": 1.0, "stamp": 1.0, "parent": "map", "child": "odom",
             "x": 1.0, "y": 0.0, "yaw": math.pi / 2},
            {"event": "tf", "wall": 1.1, "ros": 1.1, "stamp": 1.1, "parent": "odom", "child": "base_link",
             "x": 2.0, "y": 0.0, "yaw": 0.0},
        ]
        (t, x, y, yaw), = extract(ev)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 2.0)
        self.assertAlmostEqual(yaw, math.pi / 2)


class LatencyTest(unittest.TestCase):
    def events(self):
        ev = []
        for i in range(100):
            if i in (40, 41):
                continue
            t = 10.0 + i * 0.1
            ev.append({"event": "scan", "wall": 1000 + i * 0.1 + 0.002, "ros": t + 0.002, "stamp": t})
        for k in range(1, 4):
            t = 10.0 + k * 3.0
            ev.append({"event": "map", "wall": 1000 + k * 3.0 + 0.05, "ros": t + 0.05, "stamp": t})
        poses = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.1, 0.0, 0.0)]
        for j, (x, y, yaw) in enumerate(poses):
            t = 10.0 + j * 2.5
            ev.append({"event": "tf", "wall": 1000 + j * 2.5 + 0.03, "ros": t + 0.03, "stamp": t,
                       "parent": "map", "child": "odom", "x": x, "y": y, "yaw": yaw})
        return sorted(ev, key=lambda e: e["wall"])

    def test_definitions(self):
        r = analyze(self.events(), expected_scans=100)
        self.assertEqual(r["scans_received"], 98)
        self.assertAlmostEqual(r["scan_drop_rate"], 0.02)
        self.assertEqual(r["scan_gap_missing"], 2)
        self.assertAlmostEqual(r["map_period_mean_s"], 3.0, places=6)
        self.assertAlmostEqual(r["map_period_jitter_ms"], 0.0, places=6)
        self.assertAlmostEqual(r["time_to_first_map_s"], 13.05 - 10.0, places=6)
        self.assertAlmostEqual(r["scan_to_map_latency_ms_median"], 48.0, places=3)
        self.assertAlmostEqual(r["map_age_ms_median"], 50.0, places=3)
        self.assertEqual(r["map_odom_corrections"], 1)
        self.assertAlmostEqual(r["tf_update_latency_ms_median"], 28.0, places=3)


    def test_events_before_clock_and_after_input(self):
        ev = self.events()
        for e in ev:
            if e["event"] == "scan" and e["stamp"] < 10.25:
                e["ros"] = 0.0  # received before the first /clock message
        # a map published 5 s after the last scan (bag ended) must not count as latency
        ev.append({"event": "map", "wall": 1015.0, "ros": 25.0, "stamp": 25.0})
        r = analyze(sorted(ev, key=lambda e: e["wall"]), expected_scans=100)
        self.assertAlmostEqual(r["time_to_first_map_s"], 3.05, places=6)
        self.assertEqual(r["maps_received"], 4)
        self.assertEqual(r["maps_during_input"], 3)
        self.assertAlmostEqual(r["scan_to_map_latency_ms_max"], 48.0, places=3)
        self.assertAlmostEqual(r["map_period_mean_s"], 3.0, places=6)
        self.assertAlmostEqual(r["map_period_wall_mean_s"], 3.0, places=6)


if __name__ == "__main__":
    unittest.main()
