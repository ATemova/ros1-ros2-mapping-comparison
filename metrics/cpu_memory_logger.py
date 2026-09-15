#!/usr/bin/env python3
"""Log total CPU and memory usage to a CSV at a fixed interval."""

import argparse
import csv
import signal
import sys
import time
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    sys.stderr.write(
        "ERROR: the 'psutil' package is required but not installed.\n"
        "       Install it with one of:\n"
        "         apt-get install -y python3-psutil   (Debian/Ubuntu, ROS images)\n"
        "         pip3 install psutil\n"
    )
    sys.exit(2)


def parse_args():
    parser = argparse.ArgumentParser(description="CPU and memory usage logger")
    parser.add_argument("--output", required=True, help="Path to output CSV file")
    parser.add_argument("--ros_version", required=True, choices=["ROS1", "ROS2"],
                        help="ROS version used during the experiment")
    parser.add_argument("--experiment_id", required=True,
                        help="Unique experiment identifier")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Logging interval in seconds (default: 1.0)")
    return parser.parse_args()


def main():
    args = parse_args()

    running = {"flag": True}

    def handle_signal(_sig, _frame):
        running["flag"] = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    start_time = time.time()
    # Prime cpu_percent so the first sample is meaningful rather than 0.0.
    psutil.cpu_percent(interval=None)

    try:
        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp_unix",
                "elapsed_time_sec",
                "cpu_percent_total",
                "memory_mb",
                "ros_version",
                "experiment_id",
            ])

            while running["flag"]:
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
                    args.experiment_id,
                ])
                f.flush()

    except IOError as e:
        print(f"Error writing to output file: {e}", file=sys.stderr)
        sys.exit(1)

    print("CPU and memory logging stopped cleanly.")


if __name__ == "__main__":
    main()
