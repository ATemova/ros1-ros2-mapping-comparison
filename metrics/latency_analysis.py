#!/usr/bin/env python3
"""Turn latency_events.csv (from ros_latency_logger.py) into timing metrics.

Standard library only. Definitions (see docs/metrics.md):

  scan_drop_rate           1 - scans received / scans published (replay: bag count)
  scan_gap_drop_rate       missing scans inferred from header-stamp gaps / expected
  time_to_first_map_s      first /map minus first scan, ROS clock
  map_period_mean_s        mean interval between /map messages, ROS clock
  map_period_jitter_ms     standard deviation of that interval
  scan_to_map_latency_ms   /map receive time minus receive time of the newest scan
                           before it, wall clock (how stale the map is vs. the input)
  map_age_ms               /map receive time minus its header stamp, ROS clock
  tf_update_latency_ms     map->odom value change minus receive time of the newest
                           scan before it, wall clock (scan-to-pose-correction latency)
  map_odom_rate_hz         map->odom publish rate, ROS clock

Usage: latency_analysis.py latency_events.csv [--expected-scans N]
"""

import argparse
import csv
import json
import math
import sys
from bisect import bisect_right
from statistics import mean, median, pstdev

from stats_utils import percentile

TF_CHANGE_EPS = 1e-6


def load_events(path):
    events = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                ev = {"event": row["event"], "wall": float(row["wall"]),
                      "ros": float(row["ros"]), "stamp": float(row["stamp"])}
            except (KeyError, ValueError):
                continue
            if ev["event"] == "tf":
                try:
                    ev.update(parent=row["parent"], child=row["child"], x=float(row["x"]),
                              y=float(row["y"]), yaw=float(row["yaw"]))
                except (KeyError, ValueError):
                    continue
            events.append(ev)
    events.sort(key=lambda e: e["wall"])
    return events


def _stats(values, scale=1.0, prefix=""):
    if not values:
        return {}
    v = [x * scale for x in values]
    return {
        f"{prefix}mean": mean(v),
        f"{prefix}median": median(v),
        f"{prefix}p95": percentile(v, 95),
        f"{prefix}max": max(v),
        f"{prefix}std": pstdev(v) if len(v) > 1 else 0.0,
        f"{prefix}n": len(v),
    }


def _latency_after_scan(event_walls, scan_walls):
    out = []
    for w in event_walls:
        i = bisect_right(scan_walls, w)
        if i > 0:
            out.append(w - scan_walls[i - 1])
    return out


def analyze(events, expected_scans=None, map_frame="map", odom_frame="odom"):
    scans = [e for e in events if e["event"] == "scan"]
    maps = [e for e in events if e["event"] == "map"]
    map_odom = [e for e in events if e["event"] == "tf" and e["parent"] == map_frame and e["child"] == odom_frame]

    res = {"scans_received": len(scans), "maps_received": len(maps), "map_odom_messages": len(map_odom)}

    # ---- scans
    scan_walls = [e["wall"] for e in scans]
    if expected_scans:
        res["scans_expected"] = expected_scans
        res["scan_drop_rate"] = max(0.0, 1.0 - len(scans) / float(expected_scans))
    stamps = sorted(e["stamp"] for e in scans)
    diffs = [b - a for a, b in zip(stamps, stamps[1:]) if b > a]
    if len(diffs) >= 3:
        period = median(diffs)
        missing = sum(max(0, int(round(d / period)) - 1) for d in diffs)
        res["scan_period_s"] = period
        res["scan_gap_missing"] = missing
        res["scan_gap_drop_rate"] = missing / float(len(scans) + missing)
    if len(scan_walls) > 2:
        res.update(_stats([b - a for a, b in zip(scan_walls, scan_walls[1:])], 1000.0, "scan_interarrival_ms_"))

    # ---- maps
    if maps and scans:
        res["time_to_first_map_s"] = maps[0]["ros"] - scans[0]["ros"]
        res["time_to_first_map_wall_s"] = maps[0]["wall"] - scans[0]["wall"]
    if len(maps) >= 2:
        periods = [b["ros"] - a["ros"] for a, b in zip(maps, maps[1:])]
        res["map_period_mean_s"] = mean(periods)
        res["map_period_jitter_ms"] = (pstdev(periods) if len(periods) > 1 else 0.0) * 1000.0
        res["map_period_p95_s"] = percentile(periods, 95)
        wall_periods = [b["wall"] - a["wall"] for a, b in zip(maps, maps[1:])]
        res["map_period_wall_mean_s"] = mean(wall_periods)
        res["map_period_wall_jitter_ms"] = (pstdev(wall_periods) if len(wall_periods) > 1 else 0.0) * 1000.0
    res.update(_stats(_latency_after_scan([m["wall"] for m in maps], scan_walls), 1000.0, "scan_to_map_latency_ms_"))
    res.update(_stats([m["ros"] - m["stamp"] for m in maps], 1000.0, "map_age_ms_"))

    # ---- map->odom
    if len(map_odom) >= 2:
        span = map_odom[-1]["ros"] - map_odom[0]["ros"]
        if span > 0:
            res["map_odom_rate_hz"] = (len(map_odom) - 1) / span
    changes = []
    prev = None
    for e in map_odom:
        cur = (e["x"], e["y"], e["yaw"])
        if prev is not None and max(abs(a - b) for a, b in zip(cur, prev)) > TF_CHANGE_EPS:
            changes.append(e["wall"])
        prev = cur
    res["map_odom_corrections"] = len(changes)
    res.update(_stats(_latency_after_scan(changes, scan_walls), 1000.0, "tf_update_latency_ms_"))
    return res


def main():
    ap = argparse.ArgumentParser(description="Summarize latency_events.csv")
    ap.add_argument("events")
    ap.add_argument("--expected-scans", type=int)
    ap.add_argument("--map-frame", default="map")
    ap.add_argument("--odom-frame", default="odom")
    args = ap.parse_args()
    res = analyze(load_events(args.events), args.expected_scans, args.map_frame, args.odom_frame)
    json.dump(res, sys.stdout, indent=2, sort_keys=True,
              default=lambda o: None if isinstance(o, float) and math.isnan(o) else o)
    print()


if __name__ == "__main__":
    main()
