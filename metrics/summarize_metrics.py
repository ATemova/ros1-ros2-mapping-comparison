#!/usr/bin/env python3
"""Summarize a cpu_mem.csv into avg/max CPU and memory. Standard library only."""

import csv
import sys
from statistics import median


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

    avg_cpu = sum(cpu) / len(cpu)
    median_cpu = median(cpu)
    min_cpu = min(cpu)
    max_cpu = max(cpu)

    avg_memory = sum(mem) / len(mem)
    median_memory = median(mem)
    min_memory = min(mem)
    max_memory = max(mem)

    samples = len(cpu)

    print("CPU")
    print(f"  Average: {avg_cpu:.2f}%")
    print(f"  Median:  {median_cpu:.2f}%")
    print(f"  Minimum: {min_cpu:.2f}%")
    print(f"  Maximum: {max_cpu:.2f}%")

    print()
    print("Memory")
    print(f"  Average: {avg_memory:.2f} MB")
    print(f"  Median:  {median_memory:.2f} MB")
    print(f"  Minimum: {min_memory:.2f} MB")
    print(f"  Maximum: {max_memory:.2f} MB")

    print()
    print(f"Samples: {samples}")


if __name__ == "__main__":
    main()
