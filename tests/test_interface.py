"""The stable interface (docs/interface.md) must match docs/interface.json (issue #27)."""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "experiments"))

import check_interface as ci  # noqa: E402


class InterfaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        with open(ci.SNAPSHOT) as f:
            cls.recorded = json.load(f)
        cls.current = ci.collect()

    def test_no_breaking_change(self):
        breaking, _ = ci.compare(self.recorded, self.current)
        self.assertEqual(breaking, [], "breaking change to the stable interface; see docs/interface.md")

    def test_snapshot_up_to_date(self):
        _, added = ci.compare(self.recorded, self.current)
        self.assertEqual(added, [], "run `python3 experiments/check_interface.py --update` and commit "
                                    "docs/interface.json")

    def test_documented_in_interface_md(self):
        with open(os.path.join(HERE, os.pardir, "docs", "interface.md")) as f:
            doc = f.read()
        for script in ci.STABLE_CLIS:
            self.assertIn(f"`{script}`", doc)
        for t in self.current["makefile"]["targets"]:
            self.assertIn(f"`{t}`", doc, f"make target {t} not listed in docs/interface.md")

    def test_compare_detects_breaks(self):
        cur = copy.deepcopy(self.current)
        cur["makefile"]["targets"].remove("matrix")
        cur["cli"]["metrics/compare_groups.py"]["options"].remove("--group-by")
        cur["env"]["experiments/common.sh"].remove("RATE")
        schema = cur["schemas"]["run_meta.schema.json"]
        schema["required"].append("brand_new")
        schema["schema_version"] = 2
        prop = next(p for p in schema["properties"] if p != "schema_version")
        del schema["properties"][prop]
        breaking, _ = ci.compare(self.current, cur)
        text = "\n".join(breaking)
        for s in ("removed matrix", "removed --group-by", "removed RATE", "brand_new is now required",
                  "schema_version 1 -> 2", f"removed property {prop}"):
            self.assertIn(s, text)

    def test_additions_are_compatible(self):
        cur = copy.deepcopy(self.current)
        cur["makefile"]["targets"].append("new-target")
        cur["cli"]["metrics/make_report.py"]["options"].append("--new-flag")
        breaking, added = ci.compare(self.current, cur)
        self.assertEqual(breaking, [])
        self.assertEqual(len(added), 2)


if __name__ == "__main__":
    unittest.main()
