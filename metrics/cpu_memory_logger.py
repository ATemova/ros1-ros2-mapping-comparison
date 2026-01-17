#!/usr/bin/env python3

import psutil
import time
import csv
import argparse
import signal
import sys
from datetime import datetime

# Argument parsing
parser = argparse.ArgumentParser(description="CPU and memory usage logger")
parser.add_argument("--output", required=True, help="Path to output CSV file")
parser.add_argument("--ros_version", required=True, choices=["ROS1", "ROS2"],
                    help="ROS version used during the experiment")
parser.add_argument("--experiment_id", required=True,
                    help="Unique experiment identifier")
parser.add_argument("--interval", type=float, default=1.0,
                    help="Logging interval in seconds (default: 1.0)")
args = parser.parse_args()

# Graceful shutdown handling
running = True

def handle_signal(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# CSV initialization
start_time = time.time()
start_time_iso = datetime.utcnow().isoformat()

try:
    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp_unix",
            "elapsed_time_sec",
            "cpu_percent_total",
            "memory_mb",
            "ros_version",
            "experiment_id"
        ])

        # Logging loop
        while running:
            cpu = psutil.cpu_percent(interval=args.interval)
            mem = psutil.virtual_memory().used / (1024 * 1024)

            current_time = time.time()
            elapsed = current_time - start_time

            writer.writerow([
                round(current_time, 3),
                round(elapsed, 3),
                round(cpu, 2),
                round(mem, 2),
                args.ros_version,
                args.experiment_id
            ])

            f.flush()

except IOError as e:
    print(f"Error writing to output file: {e}", file=sys.stderr)
    sys.exit(1)

print("CPU and memory logging stopped cleanly.")