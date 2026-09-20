#!/usr/bin/env python3
"""Summarize a cpu_mem.csv into avg/max CPU and memory. Standard library only."""

import sys
from metrics_utils import read_metrics, calculate_stats


def main():
    if len(sys.argv) != 2:
        print("Usage: summarize_metrics.py <cpu_mem.csv>")
        sys.exit(1)

    try:
        cpu, mem = read_metrics(sys.argv[1])
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not cpu:
        print("No data rows found in CSV.", file=sys.stderr)
        sys.exit(1)

    stats = calculate_stats(cpu, mem)

    print("CPU")
    print(f"  Average: {stats['avg_cpu']:.2f}%")
    print(f"  Median:  {stats['median_cpu']:.2f}%")
    print(f"  Minimum: {stats['min_cpu']:.2f}%")
    print(f"  Maximum: {stats['max_cpu']:.2f}%")

    print()
    print("Memory")
    print(f"  Average: {stats['avg_memory']:.2f} MB")
    print(f"  Median:  {stats['median_memory']:.2f} MB")
    print(f"  Minimum: {stats['min_memory']:.2f} MB")
    print(f"  Maximum: {stats['max_memory']:.2f} MB")

    print()
    print(f"Samples: {stats['samples']}")


if __name__ == "__main__":
    main()
