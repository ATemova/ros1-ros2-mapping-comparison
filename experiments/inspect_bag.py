#!/usr/bin/env python3
"""Validate a bag before using it for replay experiments.

Usage: inspect_bag.py <bag.bag | rosbag2_dir> [--json]

Checks:
  - required topics (/scan, /tf, and either /odom or odom->base on /tf) are present
  - /tf does not already contain a transform out of the map frame
    (that means SLAM was running while recording)
  - scan rate and frame ids

Exits 0 when the bag is usable, 2 when a check fails. Needs `rosbags`.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    from rosbags.highlevel import AnyReader
    from rosbags.typesys import Stores, get_typestore
except ImportError:
    sys.stderr.write("ERROR: the 'rosbags' package is required (pip install rosbags).\n")
    sys.exit(1)

REQUIRED_TOPICS = ("/scan", "/tf")
MAP_FRAMES = ("map", "/map")


def strip(frame):
    return frame.lstrip("/")


def inspect(path):
    report = {
        "path": str(path),
        "topics": {},
        "duration_s": 0.0,
        "tf_edges": [],
        "static_tf_edges": [],
        "scan_frame": None,
        "problems": [],
    }
    tf_edges = set()
    static_edges = set()
    scan_frame = None

    with AnyReader([path], default_typestore=get_typestore(Stores.ROS2_HUMBLE)) as reader:
        report["duration_s"] = round((reader.end_time - reader.start_time) / 1e9, 3)
        counts = defaultdict(int)
        for conn in reader.connections:
            report["topics"].setdefault(conn.topic, {"type": conn.msgtype, "count": 0})

        wanted = [c for c in reader.connections if c.topic in ("/tf", "/tf_static", "/scan")]
        for conn, _ts, raw in reader.messages(connections=reader.connections):
            counts[conn.topic] += 1
            if conn not in wanted:
                continue
            msg = reader.deserialize(raw, conn.msgtype)
            if conn.topic == "/scan" and scan_frame is None:
                scan_frame = strip(msg.header.frame_id)
            elif conn.topic in ("/tf", "/tf_static"):
                target = tf_edges if conn.topic == "/tf" else static_edges
                for t in msg.transforms:
                    target.add((strip(t.header.frame_id), strip(t.child_frame_id)))

    for topic, n in counts.items():
        report["topics"][topic]["count"] = n
        if report["duration_s"] > 0:
            report["topics"][topic]["rate_hz"] = round(n / report["duration_s"], 2)

    report["tf_edges"] = sorted(f"{p}->{c}" for p, c in tf_edges)
    report["static_tf_edges"] = sorted(f"{p}->{c}" for p, c in static_edges)
    report["scan_frame"] = scan_frame

    for topic in REQUIRED_TOPICS:
        if report["topics"].get(topic, {}).get("count", 0) == 0:
            report["problems"].append(f"missing or empty topic {topic}")
    if "/odom" not in report["topics"] and not any(p == "odom" for p, _ in tf_edges):
        report["problems"].append("no /odom topic and no odom->* transform on /tf")
    for parent, child in tf_edges | static_edges:
        if parent in (strip(f) for f in MAP_FRAMES):
            report["problems"].append(
                f"tf contains {parent}->{child}: SLAM was running while recording; re-record with SLAM stopped"
            )
    if scan_frame and not any(child == scan_frame for _, child in tf_edges | static_edges):
        report["problems"].append(f"scan frame '{scan_frame}' is never a tf child (no base->laser transform)")

    return report


def main():
    ap = argparse.ArgumentParser(description="Validate a bag for replay experiments.")
    ap.add_argument("bag", type=Path)
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args()

    if not args.bag.exists():
        print(f"Bag not found: {args.bag}", file=sys.stderr)
        sys.exit(1)

    report = inspect(args.bag)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Bag:       {report['path']}")
        print(f"Duration:  {report['duration_s']} s")
        print("Topics:")
        for topic, info in sorted(report["topics"].items()):
            rate = info.get("rate_hz")
            rate_s = f"{rate:>8.2f} Hz" if rate is not None else ""
            print(f"  {topic:<20} {info['count']:>8}  {rate_s}  {info['type']}")
        print(f"Scan frame: {report['scan_frame']}")
        print(f"TF:         {', '.join(report['tf_edges']) or '-'}")
        print(f"Static TF:  {', '.join(report['static_tf_edges']) or '-'}")
        if report["problems"]:
            print("Problems:")
            for p in report["problems"]:
                print(f"  - {p}")
        else:
            print("OK: bag is usable for replay.")

    sys.exit(2 if report["problems"] else 0)


if __name__ == "__main__":
    main()
