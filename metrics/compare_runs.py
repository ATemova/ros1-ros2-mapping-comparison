#!/usr/bin/env python3

import csv
import sys
from statistics import median

def read_metrics(filename):
    cpu = []
    mem = []

    with open(filename, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                cpu.append(float(row["cpu_percent_total"]))
                mem.append(float(row["memory_mb"]))
            except (KeyError, ValueError):
                continue
        return cpu, mem

def caclulate_stats(cpu, mem):
    return{
        "avg_cpu": sum(cpu) /len(cpu),
        "median_cpu": median(cpu),
        "min_cpu": min(cpu),
        "max_cpu": max(cpu),

        "avg_memory": sum(mem) / len(mem),
        "median_memory": median(mem),
        "min_memory": min(mem),
        "max_memory": max(mem),
        
        "samples": len(cpu),
    }


def print_comarison(ros1, ros2):
    print("ROS1 vs ROS2")

    print("CPU")
    print(f"{'':12}{'ROS1':10}{'ROS2':10}")

    print(f"{'Average':12}{ros1['avg_cpu']:>8.2f}% {ros2['avg_cpu']:>8.2f}%")
    print(f"{'Median':12}{ros1['median_cpu']:>8.2f}% {ros2['median_cpu']:>8.2f}%")
    print(f"{'Minimum':12}{ros1['min_cpu']:>8.2f}% {ros2['min_cpu']:>8.2f}%")
    print(f"{'Maximum':12}{ros1['max_cpu']:>8.2f}% {ros2['max_cpu']:>8.2f}%")

    print("Memory")
    print(f"{'':12}{'ROS1':10}{'ROS2':10}")

    print(f"{'Average':12}{ros1['avg_memory']:>8.2f}MB {ros2['avg_memory']:>8.2f}MB")
    print(f"{'Median':12}{ros1['median_memory']:>8.2f}MB {ros2['median_memory']:>8.2f}MB")
    print(f"{'Minimum':12}{ros1['min_memory']:>8.2f}MB {ros2['min_memory']:>8.2f}MB")
    print(f"{'Maximum':12}{ros1['max_memory']:>8.2f}MB {ros2['max_memory']:>8.2f}MB")

    print(f"Samples: ROS1={ros1['samples']}, ROS2={ros2['samples']}")

def main():
    if len(sys.argv) != 3:
        print ("Usage: compare_runs.py <ros1_csv> <ros2_csv>")
        sys.exit(1)

    ros1_file = sys.argv[1]
    ros2_file = sys.argv[2]

    ros1_cpu, ros1_mem = read_metrics(ros1_file)
    ros2_cpu, ros2_mem = read_metrics(ros2_file)

    if not ros1_cpu or not ros2_cpu:
        print("One or bith csv files contain invalid data")
        sys.exit(1)

    ros1_stats = caclulate_stats(ros1_cpu, ros1_mem)
    ros2_stats = caclulate_stats(ros2_cpu, ros2_mem)

    print_comarison(ros1_stats, ros2_stats)

if __name__ == "__main__":
    main()