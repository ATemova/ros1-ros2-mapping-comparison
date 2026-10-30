#!/usr/bin/env python3
"""Log CPU, memory and network usage to CSV at a fixed interval.

Outputs:
  --output       cpu_mem.csv        system-wide CPU % (of all cores) and used memory
  --proc-output  proc_metrics.csv   per role: process count, CPU % (of ONE core, can
                                    exceed 100) and RSS, summed over the role's processes
  --net-output   net_io.csv         cumulative bytes/packets per network interface

Roles group processes by command line (first match wins). Defaults:
  slam            sync_slam_toolbox_node, slam_gmapping
  middleware      rosmaster, rosout (ROS1); the ros2 CLI daemon (ROS2 has no master)
  launch          roslaunch, ros2 launch
  bag_player      rosbag play, ros2 bag play
  latency_logger  metrics/ros_latency_logger.py
Override or add with --role name=REGEX (repeatable).
"""

import argparse
import csv
import os
import re
import signal
import sys
import time

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

DEFAULT_ROLES = [
    ("slam", r"sync_slam_toolbox_node|async_slam_toolbox_node|slam_gmapping"),
    ("middleware", r"rosmaster|lib/rosout/rosout|_ros2_daemon"),
    ("launch", r"roslaunch|bin/ros2 launch"),
    ("bag_player", r"rosbag/play|bin/rosbag play|bin/ros2 bag play"),
    ("latency_logger", r"ros_latency_logger\.py"),
]


def parse_args():
    parser = argparse.ArgumentParser(description="CPU, memory and network usage logger")
    parser.add_argument("--output", required=True, help="Path to the system-wide CSV (cpu_mem.csv)")
    parser.add_argument("--ros_version", required=True, choices=["ROS1", "ROS2"],
                        help="ROS version used during the experiment")
    parser.add_argument("--experiment_id", required=True,
                        help="Unique experiment identifier")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Logging interval in seconds (default: 1.0)")
    parser.add_argument("--proc-output", help="Per-role CSV (proc_metrics.csv)")
    parser.add_argument("--net-output", help="Per-interface network CSV (net_io.csv)")
    parser.add_argument("--role", action="append", default=[], metavar="NAME=REGEX",
                        help="Add or override a process role (repeatable)")
    return parser.parse_args()


def build_roles(overrides):
    roles = list(DEFAULT_ROLES)
    for item in overrides:
        if "=" not in item:
            raise SystemExit(f"--role expects NAME=REGEX, got {item!r}")
        name, pattern = item.split("=", 1)
        roles = [(n, p) for n, p in roles if n != name]
        roles.insert(0, (name, pattern))
    return [(n, re.compile(p)) for n, p in roles]


def classify(cmdline, roles):
    for name, rx in roles:
        if rx.search(cmdline):
            return name
    return None


class ProcessTracker:
    """Keeps psutil.Process objects across samples so cpu_percent() is meaningful."""

    def __init__(self, roles):
        self.roles = roles
        self.procs = {}
        self.self_pid = os.getpid()

    def sample(self):
        seen = set()
        totals = {name: [0, 0.0, 0.0] for name, _ in self.roles}
        for p in psutil.process_iter(["pid", "cmdline"]):
            pid = p.info["pid"]
            if pid == self.self_pid:
                continue
            cmd = " ".join(p.info.get("cmdline") or [])
            if not cmd:
                continue
            role = classify(cmd, self.roles)
            if role is None:
                continue
            seen.add(pid)
            tracked = self.procs.get(pid)
            if tracked is None or tracked[1] != role:
                try:
                    p.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                self.procs[pid] = (p, role)
                tracked = self.procs[pid]
                cpu = 0.0
            else:
                try:
                    cpu = tracked[0].cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            try:
                rss = tracked[0].memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            t = totals[role]
            t[0] += 1
            t[1] += cpu
            t[2] += rss
        for pid in list(self.procs):
            if pid not in seen:
                del self.procs[pid]
        return totals


def main():
    args = parse_args()
    roles = build_roles(args.role)

    running = {"flag": True}

    def handle_signal(_sig, _frame):
        running["flag"] = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    start_time = time.time()
    # Prime cpu_percent so the first sample is meaningful rather than 0.0.
    psutil.cpu_percent(interval=None)
    tracker = ProcessTracker(roles) if args.proc_output else None
    if tracker:
        tracker.sample()

    files = []
    try:
        f = open(args.output, "w", newline="")
        files.append(f)
        writer = csv.writer(f)
        writer.writerow([
            "timestamp_unix",
            "elapsed_time_sec",
            "cpu_percent_total",
            "memory_mb",
            "ros_version",
            "experiment_id",
        ])

        proc_writer = None
        if args.proc_output:
            pf = open(args.proc_output, "w", newline="")
            files.append(pf)
            proc_writer = csv.writer(pf)
            proc_writer.writerow(["timestamp_unix", "elapsed_time_sec", "role",
                                  "n_procs", "cpu_percent", "rss_mb"])

        net_writer = None
        if args.net_output:
            nf = open(args.net_output, "w", newline="")
            files.append(nf)
            net_writer = csv.writer(nf)
            net_writer.writerow(["timestamp_unix", "elapsed_time_sec", "iface",
                                 "bytes_sent", "bytes_recv", "packets_sent", "packets_recv"])

        def write_net(now, elapsed):
            for iface, c in sorted(psutil.net_io_counters(pernic=True).items()):
                net_writer.writerow([round(now, 3), round(elapsed, 3), iface,
                                     c.bytes_sent, c.bytes_recv, c.packets_sent, c.packets_recv])

        if net_writer:
            write_net(time.time(), 0.0)

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

            if proc_writer:
                for role, (n, rcpu, rss) in tracker.sample().items():
                    proc_writer.writerow([round(current_time, 3), round(elapsed, 3), role,
                                          n, round(rcpu, 2), round(rss, 2)])
            if net_writer:
                write_net(current_time, elapsed)

            for fh in files:
                fh.flush()

    except IOError as e:
        print(f"Error writing to output file: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        for fh in files:
            fh.close()

    print("CPU and memory logging stopped cleanly.")


if __name__ == "__main__":
    main()
