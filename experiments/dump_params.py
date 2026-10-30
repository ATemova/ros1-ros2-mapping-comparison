#!/usr/bin/env python3
"""Compare the parameters a running SLAM node holds with the config file it was given.

Usage: dump_params.py <stack> <dump.yaml> <config.yaml> <out.json>

<dump.yaml> is the output of `rosparam get /<node>` (ROS1) or `ros2 param dump /<node>`
(ROS2). Writes <out.json>:

    effective   value the node holds, for every key in the config file
    mismatched  keys whose effective value differs from the config
    missing     keys the node does not hold (ROS2: not declared, so the value is ignored)

Exits 1 if any value is mismatched, 0 otherwise (missing keys are reported, not fatal).
Needs PyYAML (present in the ROS images).
"""

import json
import math
import sys

import yaml


def flatten(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def node_params(stack, dump):
    if not isinstance(dump, dict):
        return {}
    if stack == "ros2":
        for value in dump.values():
            if isinstance(value, dict) and "ros__parameters" in value:
                return flatten(value["ros__parameters"])
        return {}
    return flatten(dump)


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return str(a) == str(b)


def main():
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    stack, dump_path, config_path, out_path = sys.argv[1:]

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    try:
        with open(dump_path) as f:
            dump = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        print(f"Could not read parameter dump {dump_path}: {e}", file=sys.stderr)
        dump = None

    held = node_params(stack, dump)
    effective, mismatched, missing = {}, {}, []
    for key, expected in config.items():
        if key not in held:
            missing.append(key)
            continue
        effective[key] = held[key]
        if not same(held[key], expected):
            mismatched[key] = {"config": expected, "effective": held[key]}

    report = {
        "stack": stack,
        "dump_ok": bool(held),
        "effective": effective,
        "mismatched": mismatched,
        "missing": missing,
        "use_sim_time": held.get("use_sim_time"),
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    if not held:
        print("WARNING: parameter dump is empty", file=sys.stderr)
    for key, d in mismatched.items():
        print(f"MISMATCH {key}: config={d['config']!r} node={d['effective']!r}", file=sys.stderr)
    if missing:
        print(f"Not held by the node ({len(missing)}): {', '.join(missing)}", file=sys.stderr)
    sys.exit(1 if mismatched or not held else 0)


if __name__ == "__main__":
    main()
