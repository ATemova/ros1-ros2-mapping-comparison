#!/usr/bin/env python3
"""Write run_meta.json for one experiment run. Standard library only.

Usage: write_meta.py <out.json> key=value [key=value ...]

Values "true"/"false" become booleans, plain integers and decimals become numbers
(identifier keys always stay strings), and empty values become null. Host, container and git information is added automatically.
"""

import json
import os
import re
import platform
import socket
import sys

SCHEMA_VERSION = 1
STRING_KEYS = {"experiment_id", "bag_id", "bag_path", "run_tag", "params_file", "ros_distro",
               "condition", "cpu_set", "variant", "rmw", "ros_domain_id"}
NUMBER_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")


def parse_value(key, text):
    if text == "":
        return None
    if key in STRING_KEYS:
        return text
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if NUMBER_RE.fullmatch(text):
        return float(text) if "." in text else int(text)
    return text


def git_info(repo_root):
    git_dir = os.path.join(repo_root, ".git")
    head_path = os.path.join(git_dir, "HEAD")
    try:
        head = open(head_path).read().strip()
    except OSError:
        return {"commit": None, "branch": None}
    if not head.startswith("ref: "):
        return {"commit": head, "branch": None}
    ref = head[5:]
    branch = ref.rsplit("/", 1)[-1]
    try:
        return {"commit": open(os.path.join(git_dir, ref)).read().strip(), "branch": branch}
    except OSError:
        pass
    try:
        for line in open(os.path.join(git_dir, "packed-refs")):
            parts = line.strip().split(" ")
            if len(parts) == 2 and parts[1] == ref:
                return {"commit": parts[0], "branch": branch}
    except OSError:
        pass
    return {"commit": None, "branch": branch}


def cpu_model():
    try:
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def mem_total_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def resource_limits():
    """CPU/memory limits that actually apply to this process (cgroup v2 or v1, affinity)."""
    out = {"cpu_count": os.cpu_count()}
    try:
        out["cpu_affinity"] = len(os.sched_getaffinity(0))
    except AttributeError:
        out["cpu_affinity"] = out["cpu_count"]
    quota = None
    cpu_max = _read("/sys/fs/cgroup/cpu.max")
    if cpu_max:
        q, period = (cpu_max.split() + ["100000"])[:2]
        if q != "max":
            quota = int(q) / int(period)
    else:
        q, period = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q and period and int(q) > 0:
            quota = int(q) / int(period)
    out["cpu_quota"] = round(quota, 3) if quota else None
    mem = _read("/sys/fs/cgroup/memory.max") or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    limit = None
    if mem and mem != "max":
        try:
            v = int(mem)
            if v < (1 << 60):
                limit = v
        except ValueError:
            pass
    out["mem_limit_mb"] = round(limit / (1024 * 1024)) if limit else None
    return out


def derived_condition(res):
    parts = []
    if res.get("cpu_affinity") and res.get("cpu_count") and res["cpu_affinity"] < res["cpu_count"]:
        parts.append(f"cpus{res['cpu_affinity']}")
    if res.get("cpu_quota"):
        parts.append(f"quota{res['cpu_quota']:g}")
    if res.get("mem_limit_mb"):
        parts.append(f"mem{res['mem_limit_mb']}M")
    return ",".join(parts) or "default"


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    out = sys.argv[1]
    meta = {"schema_version": SCHEMA_VERSION}
    for arg in sys.argv[2:]:
        if "=" not in arg:
            print(f"Ignoring malformed argument: {arg}", file=sys.stderr)
            continue
        key, value = arg.split("=", 1)
        meta[key] = parse_value(key, value)

    res = resource_limits()
    meta["resources"] = res
    if not meta.get("condition"):
        meta["condition"] = derived_condition(res)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    meta["git"] = git_info(repo_root)
    meta["host"] = {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
        "mem_total_mb": mem_total_mb(),
        "in_container": os.path.exists("/.dockerenv"),
        "python": platform.python_version(),
    }

    with open(out, "w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
