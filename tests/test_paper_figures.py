"""Tests for metrics/paper_figures.py on fabricated runs (issue #22)."""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path[:0] = [os.path.join(REPO, "metrics"), HERE]

import paper_figures as pf  # noqa: E402
from test_compare_groups import make_run  # noqa: E402

CG = os.path.join(REPO, "metrics", "compare_groups.py")
PF = os.path.join(REPO, "metrics", "paper_figures.py")

try:
    import matplotlib  # noqa: F401
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False


class PaperFiguresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        raw = os.path.join(cls.d, "raw")
        rng = random.Random(3)
        for i in range(6):
            make_run(raw, f"r1_{i}", 30 + rng.random(), 40 + rng.random(), stack="ros1", ros_distro="noetic",
                     rmw="tcpros")
            for rmw, base in (("rmw_fastrtps_cpp", 20), ("rmw_cyclonedds_cpp", 25), ("rmw_zenoh_cpp", 22)):
                make_run(raw, f"{rmw}_{i}", base + rng.random(), base + 10 + rng.random(), stack="ros2",
                         ros_distro="humble", rmw=rmw)
        cls.reports = os.path.join(cls.d, "reports")
        for tag, extra in (("main", ["--rmw", "tcpros,rmw_fastrtps_cpp", "--group-by", "stack"]),
                           ("rmw", ["--stack", "ros2", "--group-by", "rmw"])):
            os.makedirs(os.path.join(cls.reports, tag))
            r = subprocess.run([sys.executable, CG, "--results", raw, "--tag", "t",
                                "--json", os.path.join(cls.reports, tag, "report.json")] + extra,
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d)

    def run_pf(self, out, *args):
        return subprocess.run([sys.executable, PF, "--reports", self.reports, "--out", out] + list(args),
                              capture_output=True, text=True)

    def test_tables(self):
        out = os.path.join(self.d, "tables_only")
        r = self.run_pf(out, "--tags", "main", "rmw", "--tables-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        main = open(os.path.join(out, "tables", "main.tex")).read()
        for s in (r"\toprule", r"\midrule", r"\bottomrule", r"\label{tab:main}", r"\begin{table}[t]",
                  "ROS 1", "ROS 2", r"SLAM process CPU mean (\% core)", r"$\pm$", "$-$"):
            self.assertIn(s, main)
        self.assertNotIn("p_{\\mathrm{Holm}}", main)  # one comparison: no adjustment
        rmw = open(os.path.join(out, "tables", "rmw.tex")).read()
        for s in (r"\begin{table*}[t]", r"$p_{\mathrm{Holm}}$", r"$p_{\mathrm{KW}}$", "Fast DDS", "Cyclone DDS",
                  "Zenoh"):
            self.assertIn(s, rmw)
        # every data row has as many cells as the column spec
        spec = rmw.split(r"\begin{tabular}{")[1].split("}")[0]
        for line in rmw.splitlines():
            if line.startswith(r"\quad"):
                self.assertEqual(line.count(" & ") + 1, len(spec), line)
        idx = json.load(open(os.path.join(out, "generated.json")))
        self.assertEqual([e["name"] for e in idx["reports"]], ["main", "rmw"])
        self.assertEqual(len(idx["reports"][0]["report_sha256"]), 64)

    def test_values_match_report(self):
        rep = json.load(open(os.path.join(self.reports, "main", "report.json")))
        row = next(r for r in rep["metrics"] if r["metric"] == "cpu_mean")
        tex = pf.table_tex(rep, [row], "x")
        m = row["groups"]["ros1"]
        self.assertIn(f"{m['mean']:.2f} $\\pm$ {m['ci95']:.2f}", tex)
        c = row["comparisons"][0]
        self.assertIn(f"{abs(c['cliffs_delta']):.2f}", tex)

    def test_escaping_and_names(self):
        self.assertEqual(pf.tex("a_b & 5% #1"), r"a\_b \& 5\% \#1")
        self.assertEqual(pf.tex("Scan→map"), r"Scan$\rightarrow$map")
        self.assertEqual(pf.display_name("ros2-jazzy-cyclonedds"), "ROS 2 Jazzy / Cyclone DDS")
        self.assertEqual(pf.display_name("rmw_zenoh_cpp"), "Zenoh")
        self.assertEqual(pf.display_name("rpi4-like"), "rpi4-like")
        self.assertEqual(pf.slug("a,b+c d"), "a-b-c-d")
        colors = pf.assign_colors(["ros1", "ros2", "x", "y"])
        self.assertEqual(colors["ros1"], pf.KNOWN_COLORS["ros1"])
        self.assertEqual(len(set(colors.values())), 4)

    def test_missing_report_and_bad_args(self):
        out = os.path.join(self.d, "missing")
        r = self.run_pf(out, "--tags", "nope", "--tables-only")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found", r.stderr)
        r = self.run_pf(out, "--tables-only")
        self.assertEqual(r.returncode, 2)
        r = self.run_pf(out, "--tags", "main", "--formats", "gif")
        self.assertEqual(r.returncode, 2)

    def test_metric_selection(self):
        rep = json.load(open(os.path.join(self.reports, "rmw", "report.json")))
        self.assertEqual([r["metric"] for r in pf.select_rows(rep, ["cpu_mean"], False)], ["cpu_mean"])
        self.assertEqual(len(pf.select_rows(rep, None, True)), len(rep["metrics"]))
        default = [r["metric"] for r in pf.select_rows(rep, None, False)]
        self.assertEqual(default, [m for m in pf.DEFAULT_METRICS if m in default])

    @unittest.skipUnless(HAVE_MPL, "matplotlib not installed")
    def test_figures_deterministic(self):
        outs = []
        for k in range(2):
            out = os.path.join(self.d, f"figs{k}")
            r = self.run_pf(out, "--tags", "main", "rmw")
            self.assertEqual(r.returncode, 0, r.stderr)
            outs.append(out)
        figs = sorted(os.listdir(os.path.join(outs[0], "figures")))
        for name in ("main_overview.pdf", "main_overview.svg", "main_effects.pdf", "rmw_effects.svg",
                     "rmw_cpu_mean.pdf", "rmw_slam_cpu_mean.svg"):
            self.assertIn(name, figs)
        for name in figs:
            a = open(os.path.join(outs[0], "figures", name), "rb").read()
            b = open(os.path.join(outs[1], "figures", name), "rb").read()
            self.assertEqual(a, b, f"{name} differs between runs")
            if name.endswith(".pdf"):
                self.assertTrue(a.startswith(b"%PDF"))
                self.assertNotIn(b"/Type3", a)
            else:
                self.assertIn(b"<svg", a)


if __name__ == "__main__":
    unittest.main()
