#!/usr/bin/env python3
"""Analyze one run directory and write run_metrics.json.

    analyze_run.py results/raw/<stack>/<run_id> [--reference-traj f.tum] [--reference-map f.yaml]

Sections (each only when its input exists):
  system      cpu_mem.csv            system-wide CPU and memory
  processes   proc_metrics.csv       per role (slam, middleware, launch, bag_player, ...)
  network     net_io.csv             bytes/packets per interface during the run
  latency     latency_events.csv     scan/map/TF timing, rates, jitter, drops
  trajectory  latency_events.csv     trajectory.tum; ATE/RPE when a reference exists
  map         map.yaml               accuracy vs a reference map when one exists

References default to the bag's companions: data/bags/<bag_id>.groundtruth.tum and
data/bags/<bag_id>.reference.yaml. `summary` holds the headline numbers that
compare_groups.py compares across stacks (docs/metrics.md defines each one).
"""

import argparse
import csv
import json
import math
import os
import sys
from statistics import mean

from metrics_utils import read_metrics
from stats_utils import percentile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _clean(o):
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def system_section(path):
    cpu, mem = read_metrics(path)
    if not cpu:
        return None
    return {
        "samples": len(cpu),
        "cpu_mean": mean(cpu),
        "cpu_p95": percentile(cpu, 95),
        "mem_mean_mb": mean(mem),
        "mem_peak_mb": max(mem),
        "mem_growth_mb": mem[-1] - mem[0],
    }


def processes_section(path):
    per_role = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                n = int(row["n_procs"])
                cpu = float(row["cpu_percent"])
                rss = float(row["rss_mb"])
                t = float(row["elapsed_time_sec"])
            except (KeyError, ValueError):
                continue
            per_role.setdefault(row["role"], []).append((n, cpu, rss, t))
    out = {}
    for role, rows in per_role.items():
        live = [r for r in rows if r[0] > 0]
        if not live:
            continue
        cpu = [r[1] for r in live]
        rss = [r[2] for r in live]
        out[role] = {
            "samples": len(live),
            "procs_max": max(r[0] for r in live),
            "cpu_mean": mean(cpu),
            "cpu_p95": percentile(cpu, 95),
            "cpu_max": max(cpu),
            "rss_mean_mb": mean(rss),
            "rss_peak_mb": max(rss),
            "rss_growth_mb": rss[-1] - rss[0],
            "rss_slope_mb_per_min": slope([r[3] for r in live], rss) * 60.0,
        }
    return out


def slope(x, y):
    """Least-squares slope dy/dx (0 when undefined)."""
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx


def network_section(path):
    first, last = {}, {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                vals = [float(row["elapsed_time_sec"])] + [int(row[k]) for k in
                                                           ("bytes_sent", "bytes_recv", "packets_sent", "packets_recv")]
            except (KeyError, ValueError):
                continue
            first.setdefault(row["iface"], vals)
            last[row["iface"]] = vals
    ifaces = {}
    total = 0
    duration = 0.0
    for iface in last:
        a, b = first[iface], last[iface]
        d = [y - x for x, y in zip(a, b)]
        duration = max(duration, d[0])
        if d[1] + d[2] == 0:
            continue
        ifaces[iface] = {"bytes_sent": d[1], "bytes_recv": d[2], "packets_sent": d[3], "packets_recv": d[4]}
        total += d[1] + d[2]
    return {
        "duration_s": duration,
        "interfaces": ifaces,
        "total_mb": total / 1e6,
        "rate_kBps": total / 1e3 / duration if duration > 0 else None,
    }


def frames_from_params(run_dir, algo):
    path = os.path.join(run_dir, f"{algo}.yaml")
    frames = {"map": "map", "odom": "odom", "base": "base_link"}
    if os.path.exists(path):
        from map_quality import _parse_yaml
        p = _parse_yaml(path) or {}
        frames = {"map": str(p.get("map_frame", "map")), "odom": str(p.get("odom_frame", "odom")),
                  "base": str(p.get("base_frame", "base_link"))}
    return frames


def summarize(m):
    s = {}

    def put(key, value):
        if value is not None:
            s[key] = value

    procs = m.get("processes") or {}
    for role, prefix in (("slam", "slam"), ("middleware", "middleware"), ("launch", "launch"),
                         ("bag_player", "bag_player")):
        r = procs.get(role)
        if r:
            put(f"{prefix}_cpu_mean", r["cpu_mean"])
            put(f"{prefix}_cpu_p95", r["cpu_p95"])
            put(f"{prefix}_rss_mean_mb", r["rss_mean_mb"])
            put(f"{prefix}_rss_peak_mb", r["rss_peak_mb"])
            if prefix == "slam":
                put("slam_rss_growth_mb", r["rss_growth_mb"])
                put("slam_rss_slope_mb_per_min", r["rss_slope_mb_per_min"])
    net = m.get("network") or {}
    put("net_total_mb", net.get("total_mb"))
    put("net_rate_kBps", net.get("rate_kBps"))
    lat = m.get("latency") or {}
    for key, src in (
        ("scan_drop_rate", "scan_drop_rate"),
        ("scan_gap_drop_rate", "scan_gap_drop_rate"),
        ("scan_to_map_latency_ms", "scan_to_map_latency_ms_median"),
        ("scan_to_map_latency_p95_ms", "scan_to_map_latency_ms_p95"),
        ("tf_update_latency_ms", "tf_update_latency_ms_median"),
        ("tf_update_latency_p95_ms", "tf_update_latency_ms_p95"),
        ("map_period_s", "map_period_mean_s"),
        ("map_period_jitter_ms", "map_period_jitter_ms"),
        ("map_period_wall_s", "map_period_wall_mean_s"),
        ("map_period_wall_jitter_ms", "map_period_wall_jitter_ms"),
        ("map_age_ms", "map_age_ms_median"),
        ("time_to_first_map_s", "time_to_first_map_s"),
    ):
        put(key, lat.get(src))
    tr = (m.get("trajectory") or {}).get("error") or {}
    put("ate_rmse_m", tr.get("ate_rmse"))
    put("rpe_trans_rmse_m", tr.get("rpe_trans_rmse"))
    put("rpe_rot_rmse_deg", tr.get("rpe_rot_deg_rmse"))
    mp = (m.get("map") or {}).get("vs_reference") or {}
    put("map_cell_accuracy", mp.get("cell_accuracy"))
    put("map_wall_f1", mp.get("occ_f1_1c"))
    put("map_wall_error_m", mp.get("wall_error_m"))
    put("map_completeness_m", mp.get("completeness_m"))
    return s


def analyze(run_dir, reference_traj=None, reference_map=None, ref_max_angle=10.0):
    meta = {}
    meta_path = os.path.join(run_dir, "run_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    bag_id = meta.get("bag_id")
    if bag_id and not reference_traj:
        cand = os.path.join(REPO, "data", "bags", f"{bag_id}.groundtruth.tum")
        reference_traj = cand if os.path.exists(cand) else None
    if bag_id and not reference_map:
        cand = os.path.join(REPO, "data", "bags", f"{bag_id}.reference.yaml")
        reference_map = cand if os.path.exists(cand) else None

    m = {"run_dir": run_dir, "stack": meta.get("stack"), "algo": meta.get("algo")}
    errs = {}

    def p(name):
        return os.path.join(run_dir, name)

    def section(name, fn):
        try:
            m[name] = fn()
        except Exception as e:  # noqa: BLE001 - one broken input must not hide the others
            errs[name] = f"{type(e).__name__}: {e}"

    def latency_and_trajectory():
        from latency_analysis import analyze as latency
        from latency_analysis import load_events
        from trajectory import errors, extract, read_tum, write_tum

        frames = frames_from_params(run_dir, meta.get("algo", "slam_toolbox"))
        events = load_events(p("latency_events.csv"))
        m["latency"] = latency(events, meta.get("scans_expected"), frames["map"], frames["odom"])
        rows = extract(events, frames["map"], frames["odom"], frames["base"])
        traj = {"poses": len(rows)}
        if rows:
            write_tum(p("trajectory.tum"), rows)
            traj["file"] = "trajectory.tum"
            if reference_traj:
                traj["reference"] = reference_traj
                traj["error"] = errors(*read_tum(reference_traj), *read_tum(p("trajectory.tum")))
        return traj

    def map_section():
        mp = {"file": "map.yaml"}
        if reference_map:
            from map_quality import compare, load_map
            mp["reference"] = reference_map
            mp["vs_reference"] = compare(load_map(p("map.yaml")), load_map(reference_map), ref_max_angle)
        return mp

    if os.path.exists(p("cpu_mem.csv")):
        section("system", lambda: system_section(p("cpu_mem.csv")))
    if os.path.exists(p("proc_metrics.csv")):
        section("processes", lambda: processes_section(p("proc_metrics.csv")))
    if os.path.exists(p("net_io.csv")):
        section("network", lambda: network_section(p("net_io.csv")))
    if os.path.exists(p("latency_events.csv")):
        section("trajectory", latency_and_trajectory)
    if os.path.exists(p("map.yaml")):
        section("map", map_section)

    if errs:
        m["errors"] = errs
    m["summary"] = summarize(m)
    return _clean(m)


def main():
    ap = argparse.ArgumentParser(description="Analyze one run directory.")
    ap.add_argument("run_dir")
    ap.add_argument("--reference-traj", help="reference trajectory (TUM); default: bag ground truth")
    ap.add_argument("--reference-map", help="reference map (.yaml); default: bag reference map")
    ap.add_argument("--ref-max-angle", type=float, default=10.0,
                    help="rotation search range when aligning to the reference map [deg]")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    res = analyze(args.run_dir, args.reference_traj, args.reference_map, args.ref_max_angle)
    with open(os.path.join(args.run_dir, "run_metrics.json"), "w") as f:
        json.dump(res, f, indent=2, sort_keys=True)
        f.write("\n")
    for name, err in (res.get("errors") or {}).items():
        print(f"WARNING: {name}: {err}", file=sys.stderr)
    if not args.quiet:
        for k, v in sorted(res["summary"].items()):
            print(f"{k:28} {v:.4g}" if isinstance(v, float) else f"{k:28} {v}")


if __name__ == "__main__":
    main()
