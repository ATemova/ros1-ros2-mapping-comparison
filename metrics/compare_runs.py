#!/usr/bin/env python3

import sys
from metrics_utils import read_metrics, calculate_stats

def print_comparison(ros1, ros2):
    print("ROS1 vs ROS2")
    print()

    print("CPU")
    print(f"{'':12}{'ROS1':10}{'ROS2':10}")

    print(f"{'Average':12}{ros1['avg_cpu']:>8.2f}% {ros2['avg_cpu']:>8.2f}%")
    print(f"{'Median':12}{ros1['median_cpu']:>8.2f}% {ros2['median_cpu']:>8.2f}%")
    print(f"{'Minimum':12}{ros1['min_cpu']:>8.2f}% {ros2['min_cpu']:>8.2f}%")
    print(f"{'Maximum':12}{ros1['max_cpu']:>8.2f}% {ros2['max_cpu']:>8.2f}%")
    print()

    print("Memory")
    print(f"{'':12}{'ROS1':10}{'ROS2':10}")

    print(f"{'Average':12}{ros1['avg_memory']:>8.2f} MB {ros2['avg_memory']:>8.2f} MB")
    print(f"{'Median':12}{ros1['median_memory']:>8.2f} MB {ros2['median_memory']:>8.2f} MB")
    print(f"{'Minimum':12}{ros1['min_memory']:>8.2f} MB {ros2['min_memory']:>8.2f} MB")
    print(f"{'Maximum':12}{ros1['max_memory']:>8.2f} MB {ros2['max_memory']:>8.2f} MB")
    print()

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
        print("One or both csv files contain invalid data")
        sys.exit(1)

    ros1_stats = calculate_stats(ros1_cpu, ros1_mem)
    ros2_stats = calculate_stats(ros2_cpu, ros2_mem)

    print_comparison(ros1_stats, ros2_stats)

if __name__ == "__main__":
    main()