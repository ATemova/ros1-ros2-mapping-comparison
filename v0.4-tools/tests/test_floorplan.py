"""Tests for experiments/floorplan_to_map.py and map_quality.register on a drawn floor plan."""

import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path[:0] = [os.path.join(REPO, "experiments"), os.path.join(REPO, "metrics")]

import make_synthetic_bag as synth  # noqa: E402
from floorplan_to_map import FREE, UNKNOWN, WALL, convert  # noqa: E402
from map_quality import compare, load_map  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def draw_plan(path, angle_deg=37.0, mpp=0.02, width=3):
    a = math.radians(angle_deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    pts = [R @ np.array(p) for w in synth.WALLS for p in w]
    x0 = min(p[0] for p in pts) - 1.5
    y0 = max(p[1] for p in pts) + 1.5
    w_px = int((max(p[0] for p in pts) - x0 + 1.5) / mpp)
    h_px = int((y0 - min(p[1] for p in pts) + 1.5) / mpp)
    img = Image.new("L", (w_px, h_px), 255)
    d = ImageDraw.Draw(img)
    for a_, b_ in synth.WALLS:
        A, B = R @ np.array(a_), R @ np.array(b_)
        d.line([((A[0] - x0) / mpp, (y0 - A[1]) / mpp), ((B[0] - x0) / mpp, (y0 - B[1]) / mpp)],
               fill=0, width=width)
    img.save(path)
    return img.size


@unittest.skipIf(Image is None, "Pillow not installed")
class FloorplanTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_py(self, *args):
        r = subprocess.run([sys.executable] + list(args), cwd=REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_convert_classes_and_scale(self):
        gray = np.full((200, 300), 255.0)
        gray[20:22, 20:280] = 0
        gray[178:180, 20:280] = 0
        gray[20:180, 20:22] = 0
        gray[20:180, 278:280] = 0
        gray[60:62, 100:200] = 0
        img, info = convert(gray, mpp=0.01, resolution=0.05)
        self.assertEqual(img.shape, (40, 60))
        self.assertEqual(info["rooms"], 1)
        self.assertAlmostEqual(info["free_m2"], (2.56 - 0.1) * (1.56 - 0.1), delta=0.2)
        self.assertEqual(img[0, 0], UNKNOWN)
        self.assertEqual(img[20, 30], FREE)
        self.assertTrue((img == WALL).any())

    def test_thick_walls_keep_only_surfaces(self):
        gray = np.full((200, 200), 255.0)
        gray[10:30, 10:190] = 0
        gray[170:190, 10:190] = 0
        gray[10:190, 10:30] = 0
        gray[10:190, 170:190] = 0
        thin, _ = convert(gray, 0.01, 0.05)
        thick, _ = convert(gray, 0.01, 0.05, keep_thick=True)
        self.assertLess((thin == WALL).sum(), (thick == WALL).sum())

    def test_open_plan_needs_seed(self):
        gray = np.full((100, 100), 255.0)
        gray[40:42, :] = 0
        with self.assertRaises(SystemExit):
            convert(gray, 0.01, 0.05)
        img, info = convert(gray, 0.01, 0.05, seeds=[(50, 80)])
        self.assertEqual(img[16, 10], FREE)
        self.assertEqual(img[2, 10], UNKNOWN)

    def test_register_recovers_rotation(self):
        bag = os.path.join(self.d, "s.bag")
        self.run_py("experiments/make_synthetic_bag.py", "--out", bag)
        plan_png = os.path.join(self.d, "plan.png")
        draw_plan(plan_png, angle_deg=37.0)
        self.run_py("experiments/floorplan_to_map.py", plan_png, "--meters-per-pixel", "0.02",
                    "--out", os.path.join(self.d, "plan"))
        out = os.path.join(self.d, "reg.yaml")
        r = self.run_py("metrics/map_quality.py", "register", os.path.join(self.d, "plan.yaml"),
                        os.path.join(self.d, "s.reference.yaml"), "--out", out, "--no-overlay")
        self.assertIn("rotated -3", r.stdout)
        res = compare(load_map(out), load_map(os.path.join(self.d, "s.reference.yaml")), do_align=False)
        self.assertGreater(res["occ_f1_1c"], 0.85)
        self.assertLess(res["wall_error_m"], 0.05)

    def test_scale_from_two_points(self):
        plan_png = os.path.join(self.d, "plan.png")
        draw_plan(plan_png, angle_deg=0.0, mpp=0.02)
        r = self.run_py("experiments/floorplan_to_map.py", plan_png, "--scale", "0,0,600,0,12.0",
                        "--out", os.path.join(self.d, "p"))
        self.assertIn("0.0200 m/px", r.stdout)


if __name__ == "__main__":
    unittest.main()
