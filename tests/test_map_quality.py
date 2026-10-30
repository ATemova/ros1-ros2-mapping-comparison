"""Tests for metrics/map_quality.py on synthetic room maps."""

import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "metrics"))

from map_quality import compare, load_map  # noqa: E402

WALLS = [((-6, -4), (6, -4)), ((6, -4), (6, 4)), ((6, 4), (-6, 4)), ((-6, 4), (-6, -4)),
         ((-1, .5), (.5, .5)), ((.5, .5), (.5, 1.5)), ((.5, 1.5), (-1, 1.5)), ((-1, 1.5), (-1, .5)),
         ((2.5, -3), (3.5, -3)), ((3.5, -3), (3.5, -2))]


def room(theta=0.0, shift=(0.0, 0.0), res=0.05, noise=0.0, seed=1):
    rng = np.random.RandomState(seed)
    R = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    shift = np.asarray(shift, dtype=float)
    pts = []
    for a, b in WALLS:
        a, b = np.array(a, float), np.array(b, float)
        for t in np.linspace(0, 1, int(np.linalg.norm(b - a) / res * 4) + 1):
            pts.append(a + t * (b - a))
    pts = np.array(pts) @ R.T + shift + rng.normal(0, noise, (len(pts), 2))
    origin = (-8.0, -6.0, 0.0)
    H, W = int(12 / res), int(16 / res)
    cls = np.full((H, W), -1, np.int8)
    rr, cc = np.mgrid[0:H, 0:W]
    x = origin[0] + (cc + .5) * res
    y = origin[1] + (H - 1 - rr + .5) * res
    loc = (np.stack([x.ravel(), y.ravel()], 1) - shift) @ R
    cls[((abs(loc[:, 0]) < 6) & (abs(loc[:, 1]) < 4)).reshape(H, W)] = 0
    c = np.floor((pts[:, 0] - origin[0]) / res).astype(int)
    r = H - 1 - np.floor((pts[:, 1] - origin[1]) / res).astype(int)
    ok = (r >= 0) & (r < H) & (c >= 0) & (c < W)
    cls[r[ok], c[ok]] = 1
    return cls, res, origin


class MapQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d)

    def write(self, name, cls_, res, origin):
        img = np.full(cls_.shape, 205, np.uint8)
        img[cls_ == 0] = 254
        img[cls_ == 1] = 0
        with open(os.path.join(self.d, name + ".pgm"), "wb") as f:
            f.write(f"P5\n# comment\n{cls_.shape[1]} {cls_.shape[0]}\n255\n".encode())
            f.write(img.tobytes())
        path = os.path.join(self.d, name + ".yaml")
        with open(path, "w") as f:
            f.write(f"image: {name}.pgm\nresolution: {res}\norigin: [{origin[0]}, {origin[1]}, {origin[2]}]\n"
                    "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
        return load_map(path)

    def test_identical_maps(self):
        ref = self.write("ref", *room())
        r = compare(self.write("same", *room()), ref)
        self.assertAlmostEqual(r["align_yaw_deg"], 0.0)
        self.assertEqual(r["align_shift_m"], [0.0, 0.0])
        self.assertAlmostEqual(r["occ_iou"], 1.0)
        self.assertAlmostEqual(r["occ_f1_1c"], 1.0)
        self.assertAlmostEqual(r["cell_accuracy"], 1.0)
        self.assertAlmostEqual(r["wall_error_m"], 0.0)

    def test_absolute_image_path_from_another_machine(self):
        cls_, res, origin = room()
        self.write("moved_run", cls_, res, origin)
        path = os.path.join(self.d, "moved_run.yaml")
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("image: moved_run.pgm", "image: /__w/repo/repo/results/raw/x/moved_run.pgm"))
        self.assertEqual(load_map(path)["cls"].shape, cls_.shape)

    def test_recovers_rotation_and_shift(self):
        ref = self.write("ref", *room())
        moved = self.write("moved", *room(math.radians(7), (0.6, -0.4), noise=0.01))
        aligned = compare(moved, ref)
        raw = compare(moved, ref, do_align=False)
        self.assertAlmostEqual(abs(aligned["align_yaw_deg"]), 7.0, delta=0.3)
        self.assertGreater(aligned["occ_f1_1c"], 0.95)
        self.assertLess(aligned["wall_error_m"], 0.05)
        self.assertLess(raw["occ_f1_1c"], 0.3)
        self.assertGreater(raw["wall_error_m"], 0.3)

    def test_missing_structure_lowers_recall(self):
        ref = self.write("ref", *room())
        cls_, res, origin = room()
        cls_[:, : cls_.shape[1] // 2][cls_[:, : cls_.shape[1] // 2] == 1] = 0
        r = compare(self.write("half", cls_, res, origin), ref)
        self.assertGreater(r["occ_precision_1c"], 0.95)
        self.assertLess(r["occ_recall_1c"], 0.7)
        self.assertGreater(r["completeness_m"], r["wall_error_m"])


if __name__ == "__main__":
    unittest.main()
