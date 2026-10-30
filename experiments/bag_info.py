#!/usr/bin/env python3
"""Print how many messages a topic has in a bag (ROS1 .bag or rosbag2 directory).

Usage: bag_info.py <bag> [--topic /scan]
Prints the count, or nothing (exit 1) if it cannot be determined. Uses the `rosbag`
Python module for ROS1 bags (available on Noetic) and metadata.yaml for rosbag2.
"""

import argparse
import os
import sys


def count_ros2(path, topic):
    import yaml
    with open(os.path.join(path, "metadata.yaml")) as f:
        meta = yaml.safe_load(f)["rosbag2_bagfile_information"]
    for t in meta.get("topics_with_message_count", []):
        if t["topic_metadata"]["name"] == topic:
            return int(t["message_count"])
    return 0


def count_ros1(path, topic):
    try:
        import rosbag
    except ImportError:
        from rosbags.highlevel import AnyReader
        from pathlib import Path
        with AnyReader([Path(path)]) as reader:
            return sum(c.msgcount for c in reader.connections if c.topic == topic)
    with rosbag.Bag(path) as bag:
        return bag.get_message_count(topic_filters=[topic])


def main():
    ap = argparse.ArgumentParser(description="Message count of a topic in a bag.")
    ap.add_argument("bag")
    ap.add_argument("--topic", default="/scan")
    args = ap.parse_args()
    try:
        if os.path.isdir(args.bag):
            n = count_ros2(args.bag, args.topic)
        else:
            n = count_ros1(args.bag, args.topic)
    except Exception as e:  # noqa: BLE001
        print(f"bag_info: {e}", file=sys.stderr)
        sys.exit(1)
    print(n)


if __name__ == "__main__":
    main()
