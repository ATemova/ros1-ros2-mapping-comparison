#!/usr/bin/env python3
"""Summarize a cpu_mem.csv into avg/max CPU and memory. Standard library only."""

import csv
import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: summarize_metrics.py <cpu_mem.csv>")
        sys.exit(1)

    cpu = []
    mem = []
    with open(sys.argv[1], newline="") as f:
        for row in csv.DictReader(f):
            try:
                cpu.append(float(row["cpu_percent_total"]))
                mem.append(float(row["memory_mb"]))
            except (KeyError, ValueError):
                continue

    if not cpu:
        print("No data rows found in CSV.", file=sys.stderr)
        sys.exit(1)

    print(
        f"avg_cpu_percent,{sum(cpu) / len(cpu):.2f},"
        f"max_cpu_percent,{max(cpu):.2f},"
        f"avg_memory_mb,{sum(mem) / len(mem):.2f},"
        f"max_memory_mb,{max(mem):.2f}"
    )


if __name__ == "__main__":
    main()
