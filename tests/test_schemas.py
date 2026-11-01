"""Contract tests: the files the pipeline writes must match schemas/ (docs/data-format.md)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path[:0] = [os.path.join(REPO, "experiments"), os.path.join(REPO, "metrics"), HERE]

from validate_runs import load_schemas, self_test, validate, validate_run  # noqa: E402

META_ARGS = [  # the arguments experiments/common.sh passes for a replay run
    "experiment_id=20261101_120000_ros2-humble-fastrtps_amd64", "stack=ros2", "ros_distro=humble", "role=all",
    "rmw=rmw_fastrtps_cpp", "variant=ros2-humble-fastrtps", "condition=", "cpu_set=", "arch=amd64",
    "algo=slam_toolbox", "mode=replay", "bag_id=synthetic", "bag_path=data/bags/synthetic", "rate=1.0",
    "duration_s=", "settle_s=5", "use_sim_time=true", "run_tag=ci", "bag_exit_code=0", "scans_expected=400",
    "map_received=true", "map_saved=true", "pose_graph_saved=true", "params_ok=true", "metrics_samples=42",
    "latency_events=1200", "exit_status=0", "started_at=2026-11-01T11:00:00Z", "finished_at=2026-11-01T11:01:00Z",
    "params_file=slam_toolbox.yaml", "rmw_implementation=rmw_fastrtps_cpp", "ros_master_uri=", "ros_domain_id=",
]
PLAYER_ARGS = [
    "experiment_id=p", "stack=ros1", "ros_distro=noetic", "role=player", "rmw=tcpros", "variant=ros1-noetic",
    "condition=", "cpu_set=", "arch=arm64", "mode=replay", "bag_id=b", "bag_path=data/bags/b.bag", "rate=1.0",
    "run_tag=net", "bag_exit_code=0", "metrics_samples=10", "exit_status=0", "started_at=a", "finished_at=b",
    "ros_master_uri=http://10.0.0.1:11311", "ros_domain_id=", "rmw_implementation=",
]


def run(*cmd, **kw):
    subprocess.run([sys.executable] + list(cmd), check=True, cwd=REPO, capture_output=True, **kw)


class SchemaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = load_schemas()

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def load(self, name):
        with open(os.path.join(self.d, name)) as f:
            return json.load(f)

    def assertValid(self, doc, name):
        self.assertEqual(validate(doc, self.schemas[name]), [], name)

    def test_schemas_self_test(self):
        self.assertEqual(self_test(self.schemas), [])

    def test_run_meta_from_writer(self):
        run("experiments/write_meta.py", os.path.join(self.d, "run_meta.json"), *META_ARGS)
        meta = self.load("run_meta.json")
        self.assertValid(meta, "run_meta")
        self.assertEqual(meta["condition"], "default")

    def test_player_meta_needs_no_slam_fields(self):
        run("experiments/write_meta.py", os.path.join(self.d, "run_meta.json"), *PLAYER_ARGS)
        self.assertValid(self.load("run_meta.json"), "run_meta")

    def test_slam_run_without_params_ok_is_rejected(self):
        run("experiments/write_meta.py", os.path.join(self.d, "run_meta.json"),
            *[a for a in META_ARGS if not a.startswith("params_ok=")])
        errs = validate(self.load("run_meta.json"), self.schemas["run_meta"])
        self.assertTrue(any("params_ok" in e for e in errs), errs)

    def test_manifest_from_writer(self):
        run("experiments/write_meta.py", os.path.join(self.d, "run_meta.json"), *META_ARGS)
        bag = os.path.join(self.d, "b.bag")
        with open(bag, "wb") as f:
            f.write(b"x" * 100)
        run("experiments/write_manifest.py", self.d, "--params", "config/slam_toolbox.yaml",
            "--launch", "ros2/launch/mapping.launch.py", "--qos", "config/qos_overrides.yaml", "--bag", bag,
            env=dict(os.environ, IMAGE_TAG="ros2-mapping:humble", IMAGE_ID="sha256:" + "0" * 64,
                     IMAGE_REPO_DIGESTS="a@sha256:1,b@sha256:2", IMAGE_BASE="ros:humble@sha256:" + "1" * 64))
        man = self.load("run_manifest.json")
        self.assertValid(man, "run_manifest")
        self.assertEqual(len(man["image"]["repo_digests"]), 2)

    def test_effective_params_from_writer(self):
        dump = os.path.join(self.d, "dump.yaml")
        with open(os.path.join(REPO, "config", "slam_toolbox.yaml")) as f, open(dump, "w") as g:
            g.write("/slam_toolbox:\n  ros__parameters:\n")
            for line in f:
                if line.strip() and not line.startswith("#"):
                    g.write("    " + line)
            g.write("    use_sim_time: true\n")
        run("experiments/dump_params.py", "ros2", dump, "config/slam_toolbox.yaml",
            os.path.join(self.d, "effective_params.json"))
        self.assertValid(self.load("effective_params.json"), "effective_params")

    def test_run_metrics_from_analysis(self):
        import test_analyze_run
        from analyze_run import analyze
        fixture = test_analyze_run.AnalyzeRunTest()
        fixture.setUp()
        try:
            m = analyze(fixture.run, fixture.ref_traj, fixture.ref_map + ".yaml")
            self.assertValid(m, "run_metrics")
            os.makedirs(os.path.join(self.d, "run"))
            for name, doc in (("run_metrics", m),):
                with open(os.path.join(self.d, "run", f"{name}.json"), "w") as f:
                    json.dump(doc, f)
            with open(os.path.join(self.d, "run", "run_meta.json"), "w") as f:
                json.dump({"schema_version": 1}, f)
            problems = validate_run(os.path.join(self.d, "run"), self.schemas)
            self.assertIn("run_meta", problems)
            self.assertNotIn("run_metrics", problems)
        finally:
            fixture.tearDown()

    def test_wrong_types_are_rejected(self):
        bad = {"schema_version": 1, "run_dir": "x", "summary": {"slam_cpu_mean": "high"}}
        self.assertTrue(validate(bad, self.schemas["run_metrics"]))
        self.assertTrue(validate({"schema_version": 2, "run_dir": "x", "summary": {}}, self.schemas["run_metrics"]))


if __name__ == "__main__":
    unittest.main()
