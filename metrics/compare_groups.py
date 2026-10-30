#!/usr/bin/env python3
"""Compare groups of repeated runs with statistics. Standard library only.

Groups are formed by one run property (--group-by):
    stack        ROS1 vs ROS2 (default)
    rmw          ROS2 middlewares: Fast DDS vs Cyclone DDS vs Zenoh
    ros_distro   e.g. Humble vs Jazzy
    variant      stack + distro + RMW in one label (any mix of the above)
    condition    stress conditions, e.g. default vs cpus1 vs quota0.5
    rate, algo   playback rate, SLAM algorithm

Each run is reduced to per-run metrics (system CPU/memory from cpu_mem.csv plus the
headline metrics in run_metrics.json). For every metric the report gives each group's
mean +/- 95% CI and, for every group against the baseline (--baseline, default: first
group), the difference, a two-sided Mann-Whitney U p-value and Cliff's delta. With three
or more groups it adds a Kruskal-Wallis p-value and Holm-adjusted pairwise p-values.

Runs are only pooled when everything except the grouping property matches (algorithm,
mode, bag, rate, role, condition, and stack/distro/RMW where they are not what is being
compared); otherwise the script stops and lists the combinations so you can filter.

Usage:
    compare_groups.py --tag T
    compare_groups.py --tag T --group-by rmw --baseline rmw_fastrtps_cpp
    compare_groups.py --tag T --group-by variant --variant ros1-noetic,ros2-humble-cyclonedds
    compare_groups.py --tag T --group-by variant --json r.json --csv runs.csv --markdown r.md

Filters accept comma-separated values.
    compare_groups.py --tag T --require-identical-params

Parameter equivalence: each run's effective_params.json (what the SLAM node actually
held) is compared across all selected runs; --require-identical-params turns differences
into a failure.
"""

import argparse
import csv
import glob
import json
import os
import sys

from metrics_utils import read_metrics
from stats_utils import (cliffs_delta, cliffs_magnitude, kruskal_wallis, mann_whitney_u, mean_ci95,
                         percentile)

METRICS = [
    ("cpu_mean", "CPU mean", "%"),
    ("cpu_p95", "CPU p95", "%"),
    ("mem_mean_mb", "Memory mean", "MB"),
    ("mem_peak_mb", "Memory peak", "MB"),
    ("mem_growth_mb", "Memory growth", "MB"),
]
# Headline metrics from run_metrics.json (metrics/analyze_run.py). A row appears in the
# report only when every selected run has the value. Definitions: docs/metrics.md.
EXTRA_METRICS = [
    ("slam_cpu_mean", "SLAM process CPU mean", "% core"),
    ("slam_cpu_p95", "SLAM process CPU p95", "% core"),
    ("slam_rss_mean_mb", "SLAM process RSS mean", "MB"),
    ("slam_rss_peak_mb", "SLAM process RSS peak", "MB"),
    ("slam_rss_growth_mb", "SLAM process RSS growth", "MB"),
    ("slam_rss_slope_mb_per_min", "SLAM process RSS trend", "MB/min"),
    ("middleware_cpu_mean", "Middleware CPU mean", "% core"),
    ("middleware_rss_mean_mb", "Middleware RSS mean", "MB"),
    ("launch_cpu_mean", "Launch process CPU mean", "% core"),
    ("bag_player_cpu_mean", "Bag player CPU mean", "% core"),
    ("net_total_mb", "Network traffic", "MB"),
    ("net_rate_kBps", "Network rate", "kB/s"),
    ("scan_drop_rate", "Scan drop rate", ""),
    ("scan_to_map_latency_ms", "Scan→map latency (median)", "ms"),
    ("scan_to_map_latency_p95_ms", "Scan→map latency (p95)", "ms"),
    ("tf_update_latency_ms", "Scan→TF correction latency (median)", "ms"),
    ("tf_update_latency_p95_ms", "Scan→TF correction latency (p95)", "ms"),
    ("map_period_s", "Map update period", "s"),
    ("map_period_jitter_ms", "Map update jitter", "ms"),
    ("map_period_wall_s", "Map update period (wall clock)", "s"),
    ("map_period_wall_jitter_ms", "Map update jitter (wall clock)", "ms"),
    ("time_to_first_map_s", "Time to first map", "s"),
    ("ate_rmse_m", "ATE RMSE", "m"),
    ("rpe_trans_rmse_m", "RPE translation RMSE", "m"),
    ("rpe_rot_rmse_deg", "RPE rotation RMSE", "deg"),
    ("map_cell_accuracy", "Map cell accuracy vs reference", ""),
    ("map_wall_f1", "Map wall F1 (±1 cell) vs reference", ""),
    ("map_wall_error_m", "Map wall error vs reference", "m"),
    ("map_completeness_m", "Map completeness error vs reference", "m"),
]

GROUP_KEYS = ("stack", "variant", "rmw", "ros_distro", "condition", "rate", "algo")
BASE_COMPAT = ("algo", "mode", "bag_id", "rate", "role", "condition")
STACK_TIED = ("stack", "ros_distro", "rmw")
PREFERRED_ORDER = ("ros1", "tcpros", "rmw_fastrtps_cpp", "humble", "default")


# ---------------------------------------------------------------- run properties
def prop(r, key):
    """Run property with defaults for runs recorded before the property existed."""
    v = r.get(key)
    if v not in (None, ""):
        return str(v)
    if key == "rmw":
        return "tcpros" if r.get("stack") == "ros1" else "rmw_fastrtps_cpp"
    if key == "condition":
        return "default"
    if key == "role":
        return "all"
    if key == "variant":
        rmw = prop(r, "rmw")
        if r.get("stack") == "ros1":
            return f"ros1-{r.get('ros_distro') or 'noetic'}"
        short = rmw[4:] if rmw.startswith("rmw_") else rmw
        short = short[:-4] if short.endswith("_cpp") else short
        return f"ros2-{r.get('ros_distro') or 'humble'}-{short}"
    return "None" if v is None else str(v)


def compat_keys(group_by):
    """(keys that must match across groups, keys that must be constant within a group)."""
    if group_by in ("stack", "variant"):
        return tuple(k for k in BASE_COMPAT if k != group_by), STACK_TIED
    across = tuple(k for k in BASE_COMPAT + STACK_TIED if k != group_by)
    return across, ()


def order_groups(names, baseline=None):
    def key(n):
        return (PREFERRED_ORDER.index(n) if n in PREFERRED_ORDER else len(PREFERRED_ORDER), n)

    names = sorted(names, key=key)
    if baseline:
        if baseline not in names:
            raise SystemExit(f"baseline '{baseline}' is not one of the groups: {', '.join(names)}")
        names.remove(baseline)
        names.insert(0, baseline)
    return names


# ---------------------------------------------------------------- per-run metrics
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


FILTERS = (("algo", "algo"), ("mode", "mode"), ("bag", "bag_id"), ("tag", "run_tag"),
           ("stack", "stack"), ("rmw", "rmw"), ("distro", "ros_distro"),
           ("condition", "condition"), ("variant", "variant"))


def select(runs, args):
    out = []
    for r in runs:
        if r.get("stack") not in ("ros1", "ros2"):
            continue
        if prop(r, "role") == "player":
            continue
        if any(getattr(args, a) and prop(r, k) not in getattr(args, a).split(",") for a, k in FILTERS):
            continue
        if not args.include_failed and r.get("exit_status") not in (0, None):
            continue
        if not os.path.exists(r["_csv"]):
            print(f"Skipping {r['_dir']}: no cpu_mem.csv", file=sys.stderr)
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------- parameters
def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 12)
    return str(v)


def param_check(groups):
    """Compare effective_params.json across all runs of all groups."""
    values = {}
    missing = {g: set() for g in groups}
    without = []
    for g, runs in groups.items():
        for r in runs:
            path = os.path.join(r["_dir"], "effective_params.json")
            try:
                with open(path) as f:
                    eff = json.load(f)
            except (OSError, ValueError):
                without.append(r["_dir"])
                continue
            missing[g].update(eff.get("missing", []))
            for key, v in eff.get("effective", {}).items():
                values.setdefault(key, {}).setdefault(_norm(v), []).append(f"{g}:{os.path.basename(r['_dir'])}")
    differing = {k: {str(v): rr for v, rr in vals.items()} for k, vals in values.items() if len(vals) > 1}
    checked = sum(len(v) for v in groups.values()) - len(without)
    return {
        "runs_checked": checked,
        "runs_without_dump": without,
        "keys_compared": len(values),
        "differing": differing,
        "missing": {g: sorted(m) for g, m in missing.items()},
        "identical": checked > 0 and not differing and not without,
    }


# ---------------------------------------------------------------- statistics
def holm(pvalues):
    """Holm-Bonferroni adjusted p-values, same order as the input."""
    idx = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m = len(pvalues)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(idx):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adj[i] = running
    return adj


def available_metrics(groups):
    runs = [r for g in groups.values() for r in g]
    extra = [m for m in EXTRA_METRICS if all(r["metrics"].get(m[0]) is not None for r in runs)]
    return METRICS + extra


def build_report(groups, order, group_by, condition, trim_start, params):
    rows = []
    base = order[0]
    for key, label, unit in available_metrics(groups):
        vals = {g: [r["metrics"][key] for r in groups[g]] for g in order}
        stats = {}
        for g in order:
            mu, sd, ci = mean_ci95(vals[g])
            stats[g] = {"n": len(vals[g]), "mean": mu, "sd": sd, "ci95": ci, "values": vals[g]}
        comps = []
        for g in order[1:]:
            mw = mann_whitney_u(vals[base], vals[g])
            d = cliffs_delta(vals[g], vals[base])
            mb, mg = stats[base]["mean"], stats[g]["mean"]
            comps.append({
                "group": g, "baseline": base,
                "diff": mg - mb,
                "diff_pct": (mg - mb) / mb * 100.0 if mb else float("nan"),
                "mann_whitney_u": mw["u"], "p_value": mw["p"], "p_method": mw["method"],
                "cliffs_delta": d, "effect": cliffs_magnitude(d),
            })
        if len(comps) > 1:
            ps = [c["p_value"] for c in comps]
            if all(p == p for p in ps):
                for c, pa in zip(comps, holm(ps)):
                    c["p_holm"] = pa
        row = {"metric": key, "label": label, "unit": unit, "groups": stats, "comparisons": comps}
        if len(order) > 2:
            kw = kruskal_wallis([vals[g] for g in order])
            row["kruskal_wallis"] = kw
        rows.append(row)
    return {
        "group_by": group_by,
        "groups": order,
        "baseline": base,
        "condition": condition,
        "trim_start_s": trim_start,
        "runs": {g: [r["_dir"] for r in groups[g]] for g in order},
        "metrics": rows,
        "parameters": params,
    }


# ---------------------------------------------------------------- output
def fmt(v, digits=None):
    if v is None or v != v:
        return "n/a"
    if digits is None:
        a = abs(v)
        digits = 2 if a >= 10 or a == 0 else 3 if a >= 1 else 4
    return f"{v:.{digits}f}"


def fmt_p(p):
    if p is None or p != p:
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def label(g, group_by):
    if group_by == "stack":
        return g.upper()
    return g


def to_markdown(report):
    c = report["condition"]
    gb = report["group_by"]
    order = report["groups"]
    base = report["baseline"]
    ns = {g: len(report["runs"][g]) for g in order}
    names = [label(g, gb) for g in order]
    k = len(order)
    title = " vs ".join(names) if k <= 4 else f"{k} groups by {gb}"
    fixed = [f"{key}: `{c[key] if c.get(key) not in (None, '') else '-'}`"
             for key in ("algo", "mode", "bag_id", "rate", "condition", "stack", "ros_distro", "rmw")
             if key in c]
    lines = [
        f"## {title}",
        "",
        " · ".join(fixed) + " · runs: " + ", ".join(f"{label(g, gb)} n={ns[g]}" for g in order)
        + (f" · first {report['trim_start_s']:g}s trimmed" if report["trim_start_s"] else ""),
        "",
    ]
    head = ["Metric"] + [f"{n} mean ± 95% CI" for n in names]
    head += [f"{label(g, gb)} vs {label(base, gb)}" for g in order[1:]]
    if k > 2:
        head.append("Kruskal-Wallis p")
    lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    for r in report["metrics"]:
        u = r["unit"]
        means = [r["groups"][g]["mean"] for g in order]
        scale = max([abs(x) for x in means if x == x] + [0.0])
        d = 2 if scale >= 10 or scale == 0 else 3 if scale >= 1 else 4
        cells = [f"{r['label']}{f' ({u})' if u else ''}"]
        cells += [f"{fmt(r['groups'][g]['mean'], d)} ± {fmt(r['groups'][g]['ci95'], d)}" for g in order]
        for cmp_ in r["comparisons"]:
            p = cmp_.get("p_holm", cmp_["p_value"])
            cells.append(f"{'+' if cmp_['diff'] > 0 else ''}{fmt(cmp_['diff'], d)} ({fmt(cmp_['diff_pct'], 1)}%), "
                         f"p={fmt_p(p)}, δ={fmt(cmp_['cliffs_delta'], 2)}")
        if k > 2:
            cells.append(fmt_p(r["kruskal_wallis"]["p"]))
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        "Single group: no comparison." if k == 1 else
        f"Comparisons are against **{label(base, gb)}**: difference (percent), two-sided Mann-Whitney U "
        "p-value" + (", Holm-adjusted across the comparisons in a row" if k > 2 else "")
        + ", and Cliff's δ (> 0 means higher than the baseline). "
        "Per-run values are each run's mean/p95/peak/growth; the table summarises them across runs.",
    ]
    p = report["parameters"]
    lines.append("")
    if p["identical"]:
        lines.append(f"Parameters: identical across all {p['runs_checked']} runs "
                     f"({p['keys_compared']} keys, from each node's effective_params.json).")
    else:
        lines.append("> **Parameters are not verified identical.**")
        if p["runs_without_dump"]:
            lines.append(f"> {len(p['runs_without_dump'])} run(s) have no effective_params.json.")
        for key, vals in sorted(p["differing"].items()):
            lines.append(f"> `{key}` differs: " + "; ".join(f"{v} ({len(rr)} run(s))" for v, rr in vals.items()))
    for g in order:
        if p["missing"].get(g):
            lines.append("")
            lines.append(f"Not held by the {label(g, gb)} node (ignored by that version): "
                         + ", ".join(f"`{x}`" for x in p["missing"][g]))
    smallest = min(ns.values())
    if smallest < 5:
        lines.append("")
        lines.append(
            f"> Only {smallest} run(s) in the smallest group. With fewer than 4 runs per group "
            "the two-sided Mann-Whitney test cannot reach p < 0.05; collect at least 5 per group."
        )
    return "\n".join(lines) + "\n"


def write_runs_csv(path, groups, group_by):
    fields = ["group", "stack", "ros_distro", "rmw", "variant", "condition", "run_dir", "experiment_id",
              "algo", "mode", "bag_id", "rate", "run_tag", "samples"]
    fields += [k for k, _, _ in METRICS + EXTRA_METRICS]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for g, runs in groups.items():
            for r in runs:
                row = {"group": g, "run_dir": r["_dir"], "samples": r["metrics"]["samples"]}
                for key in ("stack", "ros_distro", "rmw", "variant", "condition", "experiment_id",
                            "algo", "mode", "bag_id", "rate", "run_tag"):
                    row[key] = prop(r, key) if key in ("rmw", "variant", "condition") else r.get(key)
                row.update({k: (round(r["metrics"][k], 6) if r["metrics"].get(k) is not None else None)
                            for k, _, _ in METRICS + EXTRA_METRICS})
                w.writerow(row)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Compare groups of repeated runs.")
    ap.add_argument("--results", default="results/raw", help="results root (default results/raw)")
    ap.add_argument("--group-by", default="stack", choices=GROUP_KEYS)
    ap.add_argument("--baseline", help="group the others are compared with (default: first group)")
    ap.add_argument("--algo", help="filter: algorithm (slam_toolbox, gmapping)")
    ap.add_argument("--mode", choices=["live", "replay"], help="filter: run mode")
    ap.add_argument("--bag", help="filter: bag id (bag file stem)")
    ap.add_argument("--tag", help="filter: run_tag")
    ap.add_argument("--stack", choices=["ros1", "ros2"], help="filter: stack")
    ap.add_argument("--rmw", help="filter: RMW (e.g. rmw_cyclonedds_cpp)")
    ap.add_argument("--distro", help="filter: ROS distribution")
    ap.add_argument("--condition", help="filter: run condition")
    ap.add_argument("--variant", help="filter: variant label(s), e.g. ros1-noetic,ros2-humble-zenoh")
    ap.add_argument("--trim-start", type=float, default=0.0,
                    help="ignore samples in the first N seconds of each run")
    ap.add_argument("--include-failed", action="store_true", help="keep runs with exit_status != 0")
    ap.add_argument("--require-identical-params", action="store_true",
                    help="exit 1 unless every run holds identical effective parameters")
    ap.add_argument("--json", help="write the full report as JSON")
    ap.add_argument("--csv", help="write per-run metrics as CSV")
    ap.add_argument("--markdown", help="write the markdown table to a file")
    args = ap.parse_args()

    runs = select(discover(args.results), args)
    across, within = compat_keys(args.group_by)

    combos = sorted({tuple(prop(r, k) for k in across) for r in runs})
    if len(combos) > 1:
        print(f"Selected runs differ in more than '{args.group_by}'; filter with --tag/--algo/--bag/...:",
              file=sys.stderr)
        for c in combos:
            print("  " + ", ".join(f"{k}={v}" for k, v in zip(across, c)), file=sys.stderr)
        sys.exit(1)

    groups = {}
    for r in runs:
        try:
            m = run_metrics(r["_csv"], args.trim_start)
        except (FileNotFoundError, ValueError) as e:
            print(f"Skipping {r['_dir']}: {e}", file=sys.stderr)
            continue
        if m is None:
            print(f"Skipping {r['_dir']}: no samples", file=sys.stderr)
            continue
        summary_path = os.path.join(r["_dir"], "run_metrics.json")
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    m.update(json.load(f).get("summary", {}))
            except (OSError, ValueError) as e:
                print(f"{r['_dir']}: unreadable run_metrics.json ({e})", file=sys.stderr)
        r["metrics"] = m
        groups.setdefault(prop(r, args.group_by), []).append(r)

    for g, rr in groups.items():
        for k in within:
            vals = sorted({prop(r, k) for r in rr})
            if len(vals) > 1:
                print(f"Group '{g}' mixes {k}: {', '.join(vals)}. Use --group-by variant, or filter.",
                      file=sys.stderr)
                sys.exit(1)

    if not groups:
        print("No runs match the selection.", file=sys.stderr)
        sys.exit(1)
    if len(groups) == 1:
        print(f"Only one group by '{args.group_by}' ({next(iter(groups))}): descriptive statistics only.",
              file=sys.stderr)

    order = order_groups(list(groups), args.baseline)
    first = groups[order[0]][0]
    condition = {k: prop(first, k) for k in across}
    condition["run_tag"] = args.tag
    params = param_check(groups)
    report = build_report(groups, order, args.group_by, condition, args.trim_start, params)
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
        write_runs_csv(args.csv, groups, args.group_by)

    if args.require_identical_params and not params["identical"]:
        print("ERROR: effective parameters are not identical across runs.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
