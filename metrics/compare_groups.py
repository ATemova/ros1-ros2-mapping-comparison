#!/usr/bin/env python3
"""Compare repeated ROS1 and ROS2 runs with statistics. Standard library only.

Every run directory under results/raw/<stack>/<run_id>/ that has run_meta.json and
cpu_mem.csv is reduced to per-run metrics, then the ROS1 and ROS2 groups are compared:

    mean +/- 95% CI across runs, ROS2 - ROS1 difference,
    two-sided Mann-Whitney U p-value, Cliff's delta effect size.

Runs are only comparable when they share algorithm, mode, bag and playback rate; if the
selected runs mix those, the script stops and lists the combinations so you can filter.

Usage:
    compare_groups.py --tag matrix_20261030
    compare_groups.py --algo slam_toolbox --mode replay --bag corridor_01
    compare_groups.py --tag T --json report.json --csv runs.csv --markdown report.md
"""

import argparse
import csv
import glob
import json
import os
import sys

from metrics_utils import read_metrics
from stats_utils import cliffs_delta, cliffs_magnitude, mann_whitney_u, mean_ci95, percentile

STACKS = ("ros1", "ros2")
METRICS = [
    ("cpu_mean", "CPU mean", "%"),
    ("cpu_p95", "CPU p95", "%"),
    ("mem_mean_mb", "Memory mean", "MB"),
    ("mem_peak_mb", "Memory peak", "MB"),
    ("mem_growth_mb", "Memory growth", "MB"),
]
COMPAT_KEYS = ("algo", "mode", "bag_id", "rate")


def load_elapsed(path):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out.append(float(row["elapsed_time_sec"]))
            except (KeyError, ValueError):
                out.append(None)
    return out


def run_metrics(csv_path, trim_start):
    cpu, mem = read_metrics(csv_path)
    if trim_start > 0:
        elapsed = load_elapsed(csv_path)
        if len(elapsed) == len(cpu):
            keep = [i for i, t in enumerate(elapsed) if t is not None and t >= trim_start]
            cpu = [cpu[i] for i in keep]
            mem = [mem[i] for i in keep]
    if not cpu:
        return None
    return {
        "samples": len(cpu),
        "cpu_mean": sum(cpu) / len(cpu),
        "cpu_p95": percentile(cpu, 95),
        "mem_mean_mb": sum(mem) / len(mem),
        "mem_peak_mb": max(mem),
        "mem_growth_mb": mem[-1] - mem[0],
    }


def discover(results_dir):
    runs = []
    for meta_path in sorted(glob.glob(os.path.join(results_dir, "*", "*", "run_meta.json"))):
        run_dir = os.path.dirname(meta_path)
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError) as e:
            print(f"Skipping {run_dir}: unreadable run_meta.json ({e})", file=sys.stderr)
            continue
        meta["_dir"] = run_dir
        meta["_csv"] = os.path.join(run_dir, "cpu_mem.csv")
        runs.append(meta)
    return runs


def select(runs, args):
    out = []
    for r in runs:
        if r.get("stack") not in STACKS:
            continue
        if args.algo and r.get("algo") != args.algo:
            continue
        if args.mode and r.get("mode") != args.mode:
            continue
        if args.bag and r.get("bag_id") != args.bag:
            continue
        if args.tag and r.get("run_tag") != args.tag:
            continue
        if not args.include_failed and r.get("exit_status") not in (0, None):
            continue
        if not os.path.exists(r["_csv"]):
            print(f"Skipping {r['_dir']}: no cpu_mem.csv", file=sys.stderr)
            continue
        out.append(r)
    return out


def fmt(v, digits=2):
    if v is None or v != v:
        return "n/a"
    return f"{v:.{digits}f}"


def fmt_p(p):
    if p is None or p != p:
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def build_report(groups, condition, trim_start):
    rows = []
    for key, label, unit in METRICS:
        a = [r["metrics"][key] for r in groups["ros1"]]
        b = [r["metrics"][key] for r in groups["ros2"]]
        ma, sda, ha = mean_ci95(a)
        mb, sdb, hb = mean_ci95(b)
        mw = mann_whitney_u(a, b)
        d = cliffs_delta(b, a)
        rows.append({
            "metric": key, "label": label, "unit": unit,
            "ros1": {"n": len(a), "mean": ma, "sd": sda, "ci95": ha, "values": a},
            "ros2": {"n": len(b), "mean": mb, "sd": sdb, "ci95": hb, "values": b},
            "diff_ros2_minus_ros1": mb - ma,
            "diff_pct": (mb - ma) / ma * 100.0 if ma else float("nan"),
            "mann_whitney_u": mw["u"], "p_value": mw["p"], "p_method": mw["method"],
            "cliffs_delta_ros2_vs_ros1": d, "effect": cliffs_magnitude(d),
        })
    return {
        "condition": condition,
        "trim_start_s": trim_start,
        "runs": {s: [r["_dir"] for r in groups[s]] for s in STACKS},
        "metrics": rows,
    }


def to_markdown(report):
    c = report["condition"]
    n1 = len(report["runs"]["ros1"])
    n2 = len(report["runs"]["ros2"])
    lines = [
        "## ROS1 vs ROS2",
        "",
        f"Algorithm: `{c['algo']}` · mode: `{c['mode']}` · bag: `{c['bag_id'] or '-'}` · "
        f"rate: `{c['rate'] if c['rate'] is not None else '-'}` · runs: ROS1 n={n1}, ROS2 n={n2}"
        + (f" · first {report['trim_start_s']:g}s trimmed" if report["trim_start_s"] else ""),
        "",
        "| Metric | ROS1 mean ± 95% CI | ROS2 mean ± 95% CI | Δ ROS2−ROS1 | p (MWU) | Cliff's δ |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["metrics"]:
        u = r["unit"]
        lines.append(
            f"| {r['label']} ({u}) "
            f"| {fmt(r['ros1']['mean'])} ± {fmt(r['ros1']['ci95'])} "
            f"| {fmt(r['ros2']['mean'])} ± {fmt(r['ros2']['ci95'])} "
            f"| {fmt(r['diff_ros2_minus_ros1'])} ({fmt(r['diff_pct'], 1)}%) "
            f"| {fmt_p(r['p_value'])} "
            f"| {fmt(r['cliffs_delta_ros2_vs_ros1'])} ({r['effect']}) |"
        )
    lines += [
        "",
        "Per-run metrics are the run's mean/p95/peak/growth; the table summarises them across runs. "
        "Cliff's δ > 0 means ROS2 is higher.",
    ]
    if min(n1, n2) < 5:
        lines.append("")
        lines.append(
            f"> Only {min(n1, n2)} run(s) in the smaller group. With fewer than 4 runs per group "
            "the two-sided Mann-Whitney test cannot reach p < 0.05; collect at least 5 per stack."
        )
    return "\n".join(lines) + "\n"


def write_runs_csv(path, groups):
    fields = ["stack", "run_dir", "experiment_id", "algo", "mode", "bag_id", "rate", "run_tag",
              "samples"] + [k for k, _, _ in METRICS]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for stack in STACKS:
            for r in groups[stack]:
                row = {
                    "stack": stack, "run_dir": r["_dir"], "experiment_id": r.get("experiment_id"),
                    "algo": r.get("algo"), "mode": r.get("mode"), "bag_id": r.get("bag_id"),
                    "rate": r.get("rate"), "run_tag": r.get("run_tag"),
                    "samples": r["metrics"]["samples"],
                }
                row.update({k: round(r["metrics"][k], 4) for k, _, _ in METRICS})
                w.writerow(row)


def main():
    ap = argparse.ArgumentParser(description="Compare repeated ROS1 vs ROS2 runs.")
    ap.add_argument("--results", default="results/raw", help="results root (default results/raw)")
    ap.add_argument("--algo", help="filter: algorithm (slam_toolbox, gmapping)")
    ap.add_argument("--mode", choices=["live", "replay"], help="filter: run mode")
    ap.add_argument("--bag", help="filter: bag id (bag file stem)")
    ap.add_argument("--tag", help="filter: run_tag")
    ap.add_argument("--trim-start", type=float, default=0.0,
                    help="ignore samples in the first N seconds of each run")
    ap.add_argument("--include-failed", action="store_true", help="keep runs with exit_status != 0")
    ap.add_argument("--json", help="write the full report as JSON")
    ap.add_argument("--csv", help="write per-run metrics as CSV")
    ap.add_argument("--markdown", help="write the markdown table to a file")
    args = ap.parse_args()

    runs = select(discover(args.results), args)

    combos = sorted({tuple(str(r.get(k)) for k in COMPAT_KEYS) for r in runs})
    if len(combos) > 1:
        print("Selected runs mix conditions; filter with --algo/--mode/--bag/--tag:", file=sys.stderr)
        for c in combos:
            print("  " + ", ".join(f"{k}={v}" for k, v in zip(COMPAT_KEYS, c)), file=sys.stderr)
        sys.exit(1)

    groups = {s: [] for s in STACKS}
    for r in runs:
        try:
            m = run_metrics(r["_csv"], args.trim_start)
        except (FileNotFoundError, ValueError) as e:
            print(f"Skipping {r['_dir']}: {e}", file=sys.stderr)
            continue
        if m is None:
            print(f"Skipping {r['_dir']}: no samples", file=sys.stderr)
            continue
        r["metrics"] = m
        groups[r["stack"]].append(r)

    if not groups["ros1"] or not groups["ros2"]:
        print(f"Need at least one run per stack (found ROS1={len(groups['ros1'])}, "
              f"ROS2={len(groups['ros2'])}).", file=sys.stderr)
        sys.exit(1)

    first = groups["ros1"][0]
    condition = {k: first.get(k) for k in COMPAT_KEYS}
    condition["run_tag"] = args.tag
    report = build_report(groups, condition, args.trim_start)
    md = to_markdown(report)
    print(md, end="")

    if args.markdown:
        with open(args.markdown, "w") as f:
            f.write(md)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    if args.csv:
        write_runs_csv(args.csv, groups)


if __name__ == "__main__":
    main()
