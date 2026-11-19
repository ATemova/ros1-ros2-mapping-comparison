#!/usr/bin/env python3
"""Check the stable public interface against docs/interface.json.

The stable surface (docs/interface.md) is recorded in docs/interface.json:

  makefile   targets with a `## ` help line, and the variables the Makefile reads
  env        environment variables documented in the headers of experiments/common.sh
             (run_ros1.sh / run_ros2.sh) and experiments/run_matrix.sh
  cli        options, positionals and subcommands of the stable Python scripts (from --help)
  schemas    schema_version, properties (with types) and required fields of schemas/*.json

A check fails when something recorded is gone or changed incompatibly: a target, variable,
option or schema property removed, a property's type changed, a field made required, or
schema_version changed. Those are breaking changes and need a major release. Additions are
reported and allowed; record them with --update in the same pull request.

  check_interface.py              check (exit 1 on a breaking change)
  check_interface.py --update     rewrite docs/interface.json from the current tree
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
SNAPSHOT = os.path.join(ROOT, "docs", "interface.json")

# Stable scripts and the subcommands whose options are covered. Anything not listed here is
# internal or experimental (docs/interface.md).
STABLE_CLIS = {
    "metrics/compare_groups.py": [None],
    "metrics/make_report.py": [None],
    "metrics/analyze_run.py": [None],
    "metrics/sample_size.py": [None],
    "metrics/map_quality.py": ["compare", "consistency"],
    "metrics/trajectory.py": ["extract", "error"],
    "experiments/validate_runs.py": [None],
    "experiments/cut_bag.py": [None],
    "experiments/make_synthetic_bag.py": [None],
}
ENV_SOURCES = ["experiments/common.sh", "experiments/run_matrix.sh"]
# documented but set by the tooling, not by users
ENV_INTERNAL = {"IMAGE_ID", "IMAGE_TAG", "GIT_DIRTY"}
MAKE_INTERNAL = {"MAKEFILE_LIST", "MATRIX", "VARIANT", "SHELL"}


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


# ---------------------------------------------------------------- collectors
def makefile_surface():
    text = read("Makefile")
    targets = sorted(set(re.findall(r"^([a-z0-9_-]+):[^\n]*?## ", text, re.M)))
    variables = set(re.findall(r"^([A-Z_]+)\s*\?=", text, re.M))
    variables |= set(re.findall(r"\$\(([A-Z_]+)\)", text))
    for line in re.findall(r"^export ([A-Z_ ]+)$", text, re.M):
        variables |= set(line.split())
    return {"targets": targets, "variables": sorted(variables - MAKE_INTERNAL)}


_ENV_LINE = re.compile(r"^#\s{2,3}([A-Z][A-Z0-9_]+(?:\s*/\s*[A-Z][A-Z0-9_]+)*)(?:=\S*)?(?=\s|$)", re.M)


def env_surface():
    out = {}
    for rel in ENV_SOURCES:
        header, in_env = [], False
        for line in read(rel).splitlines():
            if line.startswith("#!"):
                continue
            if not line.startswith("#"):
                break
            if "Environment:" in line:
                in_env = True
            elif in_env:
                header.append(line)
        names = set()
        for m in _ENV_LINE.finditer("\n".join(header)):
            names |= {n.strip() for n in m.group(1).split("/")}
        out[rel] = sorted(names - ENV_INTERNAL)
    return out


def _help(script, sub):
    cmd = [sys.executable, os.path.join(ROOT, script)] + ([sub] if sub else []) + ["--help"]
    env = dict(os.environ, COLUMNS="200")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[1:])} failed:\n{r.stderr.strip()}")
    return r.stdout


def _parse_help(text):
    options, positionals, subcommands = set(), [], []
    section = None
    for line in text.splitlines():
        if re.match(r"^\S.*:$", line):
            section = line[:-1].lower()
            continue
        if section is None:
            continue
        options |= set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", line))
        if section.startswith("positional arguments"):
            m = re.match(r"^  ([a-z_][a-z0-9_-]*|\{[^}]+\})(\s|$)", line)
            if m:
                if m.group(1).startswith("{"):
                    subcommands = m.group(1)[1:-1].split(",")
                else:
                    positionals.append(m.group(1))
    options.discard("--help")
    return {"options": sorted(options), "positionals": positionals, "subcommands": sorted(subcommands)}


def cli_surface():
    out = {}
    for script, subs in STABLE_CLIS.items():
        for sub in subs:
            key = f"{script} {sub}" if sub else script
            parsed = _parse_help(_help(script, sub))
            if not parsed["subcommands"]:
                del parsed["subcommands"]
            out[key] = parsed
    return out


def schema_surface():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "schemas", "*.schema.json"))):
        with open(path) as f:
            s = json.load(f)
        props = {}
        for name, spec in s.get("properties", {}).items():
            t = spec.get("type")
            if t is None and "const" in spec:
                t = type(spec["const"]).__name__.replace("int", "integer").replace("str", "string")
            props[name] = sorted(t) if isinstance(t, list) else t
        out[os.path.basename(path)] = {
            "schema_version": s.get("properties", {}).get("schema_version", {}).get("const"),
            "required": sorted(s.get("required", [])),
            "properties": props,
        }
    return out


def collect():
    return {"makefile": makefile_surface(), "env": env_surface(), "cli": cli_surface(), "schemas": schema_surface()}


# ---------------------------------------------------------------- comparison
def compare(old, new):
    """Return (breaking, additions) as lists of human-readable strings."""
    breaking, added = [], []

    def lists(where, a, b):
        breaking.extend(f"{where}: removed {x}" for x in a if x not in b)
        added.extend(f"{where}: new {x}" for x in b if x not in a)

    lists("make target", old["makefile"]["targets"], new["makefile"]["targets"])
    lists("make variable", old["makefile"]["variables"], new["makefile"]["variables"])
    for src, names in old["env"].items():
        lists(f"env ({src})", names, new["env"].get(src, []))
    for src in set(new["env"]) - set(old["env"]):
        added.append(f"env: new source {src}")

    for key, spec in old["cli"].items():
        cur = new["cli"].get(key)
        if cur is None:
            breaking.append(f"cli: {key} no longer covered")
            continue
        lists(f"cli {key} option", spec["options"], cur["options"])
        lists(f"cli {key} subcommand", spec.get("subcommands", []), cur.get("subcommands", []))
        if spec["positionals"] != cur["positionals"]:
            breaking.append(f"cli {key}: positionals {spec['positionals']} -> {cur['positionals']}")
    for key in set(new["cli"]) - set(old["cli"]):
        added.append(f"cli: new {key}")

    for name, spec in old["schemas"].items():
        cur = new["schemas"].get(name)
        if cur is None:
            breaking.append(f"schema {name}: removed")
            continue
        if spec["schema_version"] != cur["schema_version"]:
            breaking.append(f"schema {name}: schema_version {spec['schema_version']} -> {cur['schema_version']}")
        for prop, t in spec["properties"].items():
            if prop not in cur["properties"]:
                breaking.append(f"schema {name}: removed property {prop}")
            elif cur["properties"][prop] != t:
                breaking.append(f"schema {name}: {prop} type {t} -> {cur['properties'][prop]}")
        for prop in cur["properties"]:
            if prop not in spec["properties"]:
                added.append(f"schema {name}: new property {prop}")
        for req in cur["required"]:
            if req not in spec["required"]:
                breaking.append(f"schema {name}: {req} is now required")
    for name in set(new["schemas"]) - set(old["schemas"]):
        added.append(f"schema: new {name}")
    return breaking, added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the stable interface against docs/interface.json.")
    ap.add_argument("--update", action="store_true", help="rewrite docs/interface.json from the current tree")
    ap.add_argument("--snapshot", default=SNAPSHOT, help="snapshot file (default docs/interface.json)")
    args = ap.parse_args(argv)

    try:
        current = collect()
    except RuntimeError as e:
        print(f"check_interface: {e}", file=sys.stderr)
        return 2
    if args.update:
        with open(args.snapshot, "w") as f:
            json.dump(current, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {os.path.relpath(args.snapshot, ROOT)}")
        return 0
    if not os.path.isfile(args.snapshot):
        print(f"{args.snapshot} missing; create it with --update", file=sys.stderr)
        return 2
    with open(args.snapshot) as f:
        recorded = json.load(f)
    breaking, added = compare(recorded, current)
    for a in added:
        print(f"added: {a}")
    if added:
        print("Additions are compatible; record them with `python3 experiments/check_interface.py --update`.")
    if breaking:
        print("\nBreaking changes to the stable interface (docs/interface.md):", file=sys.stderr)
        for b in breaking:
            print(f"  {b}", file=sys.stderr)
        print("Revert them, or deprecate first (keep the old name working with a warning) and remove only "
              "in a major release.", file=sys.stderr)
        return 1
    print(f"interface OK ({len(current['cli'])} CLIs, {len(current['makefile']['targets'])} make targets, "
          f"{len(current['schemas'])} schemas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
