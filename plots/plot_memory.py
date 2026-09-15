#!/usr/bin/env python3
"""Plot memory usage over time from a cpu_mem.csv produced by cpu_memory_logger.py."""

import argparse
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")  # headless-safe
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def latest_csv(ros_version):
    pattern = os.path.join("results", "raw", ros_version, "*", "cpu_mem.csv")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def main():
    ap = argparse.ArgumentParser(description="Plot memory usage from a run CSV.")
    ap.add_argument("csv", nargs="?", help="Path to cpu_mem.csv")
    ap.add_argument("--ros", choices=["ros1", "ros2"],
                    help="Plot the latest run for this ROS version instead of a path")
    ap.add_argument("--out", help="Output PNG path (default: alongside the CSV)")
    args = ap.parse_args()

    path = args.csv or (latest_csv(args.ros) if args.ros else None)
    if not path or not os.path.exists(path):
        print("No CSV found. Pass a path or use --ros ros1|ros2.", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(path)
    run_id = os.path.basename(os.path.dirname(path))

    plt.figure()
    plt.plot(df["elapsed_time_sec"], df["memory_mb"])
    plt.xlabel("Elapsed time (s)")
    plt.ylabel("Memory used (MB)")
    plt.title(f"Memory usage — {run_id}")
    plt.grid(True, alpha=0.3)

    out = args.out or (os.path.splitext(path)[0] + "_memory.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
