#!/usr/bin/env python3
"""Record timing events from a running SLAM pipeline (ROS1 rospy or ROS2 rclpy).

The logger only records raw events; metrics/latency_analysis.py turns them into
latency, rate, jitter and drop figures, and metrics/trajectory.py into a trajectory.

Usage:
    ros_latency_logger.py --ros 1|2 --output latency_events.csv [--use-sim-time]
                          [--scan-topic /scan] [--map-topic /map]
                          [--map-frame map] [--odom-frame odom] [--base-frame base_link]

Subscriptions use the same QoS as the SLAM node (ROS2: sensor-data QoS for scans,
reliable + transient-local for the map), so drops the logger sees are the drops a
subscriber like SLAM sees.

CSV columns (one row per event):
    event   scan | map | tf
    wall    wall-clock receive time [s]
    ros     ROS-clock receive time [s] (simulated time in replay)
    stamp   message header stamp [s]
    parent, child, x, y, yaw   for tf events (map->odom and odom->base only)
    width, height              for map events
Stops cleanly on SIGINT / SIGTERM.
"""

import argparse
import csv
import math
import signal
import sys
import threading
import time

COLUMNS = ["event", "wall", "ros", "stamp", "parent", "child", "x", "y", "yaw", "width", "height"]


def yaw_from_quat(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def strip(frame):
    return frame.lstrip("/")


class EventWriter:
    def __init__(self, path, frames):
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(COLUMNS)
        self.last_flush = time.time()
        self.edges = {
            (frames["map"], frames["odom"]),
            (frames["odom"], frames["base"]),
        }
        self.counts = {"scan": 0, "map": 0, "tf": 0}
        self.lock = threading.Lock()  # rospy runs each subscriber callback in its own thread

    def _row(self, event, ros_now, stamp, parent="", child="", x="", y="", yaw="", width="", height=""):
        wall = time.time()
        with self.lock:
            self.w.writerow([event, f"{wall:.6f}", f"{ros_now:.6f}", f"{stamp:.6f}",
                             parent, child, x, y, yaw, width, height])
            self.counts[event] += 1
            if wall - self.last_flush > 1.0:
                self.f.flush()
                self.last_flush = wall

    def scan(self, ros_now, stamp):
        self._row("scan", ros_now, stamp)

    def map(self, ros_now, stamp, width, height):
        self._row("map", ros_now, stamp, width=width, height=height)

    def tf(self, ros_now, transforms):
        for parent, child, stamp, t, q in transforms:
            parent, child = strip(parent), strip(child)
            if (parent, child) in self.edges:
                self._row("tf", ros_now, stamp, parent, child,
                          f"{t.x:.6f}", f"{t.y:.6f}", f"{yaw_from_quat(q):.6f}")

    def close(self):
        with self.lock:
            self.f.flush()
            self.f.close()


def run_ros1(args, writer, running):
    import rospy
    from nav_msgs.msg import OccupancyGrid
    from sensor_msgs.msg import LaserScan
    from tf2_msgs.msg import TFMessage

    rospy.init_node("latency_logger", anonymous=True, disable_signals=True)

    def now():
        return rospy.get_rostime().to_sec()

    rospy.Subscriber(args.scan_topic, LaserScan,
                     lambda m: writer.scan(now(), m.header.stamp.to_sec()),
                     queue_size=100, tcp_nodelay=True)
    rospy.Subscriber(args.map_topic, OccupancyGrid,
                     lambda m: writer.map(now(), m.header.stamp.to_sec(), m.info.width, m.info.height),
                     queue_size=5)
    rospy.Subscriber("/tf", TFMessage,
                     lambda m: writer.tf(now(), [(t.header.frame_id, t.child_frame_id,
                                                  t.header.stamp.to_sec(), t.transform.translation,
                                                  t.transform.rotation) for t in m.transforms]),
                     queue_size=1000, tcp_nodelay=True)

    while running["flag"] and not rospy.is_shutdown():
        time.sleep(0.2)
    rospy.signal_shutdown("done")


def run_ros2(args, writer, running):
    import rclpy
    from nav_msgs.msg import OccupancyGrid
    from rclpy.parameter import Parameter
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy,
                           qos_profile_sensor_data)
    from sensor_msgs.msg import LaserScan
    from tf2_msgs.msg import TFMessage

    try:
        from rclpy.signals import SignalHandlerOptions
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    except (ImportError, TypeError):
        rclpy.init()
        signal.signal(signal.SIGINT, lambda *_: running.__setitem__("flag", False))
        signal.signal(signal.SIGTERM, lambda *_: running.__setitem__("flag", False))

    node = rclpy.create_node(
        "latency_logger",
        parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, args.use_sim_time)],
    )

    def now():
        return node.get_clock().now().nanoseconds / 1e9

    def sec(stamp):
        return stamp.sec + stamp.nanosec / 1e9

    map_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=1,
                         reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
    tf_qos = QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=100,
                        reliability=ReliabilityPolicy.RELIABLE,
                        durability=DurabilityPolicy.VOLATILE)

    node.create_subscription(LaserScan, args.scan_topic,
                             lambda m: writer.scan(now(), sec(m.header.stamp)),
                             qos_profile_sensor_data)
    node.create_subscription(OccupancyGrid, args.map_topic,
                             lambda m: writer.map(now(), sec(m.header.stamp), m.info.width, m.info.height),
                             map_qos)
    node.create_subscription(TFMessage, "/tf",
                             lambda m: writer.tf(now(), [(t.header.frame_id, t.child_frame_id,
                                                          sec(t.header.stamp), t.transform.translation,
                                                          t.transform.rotation) for t in m.transforms]),
                             tf_qos)

    try:
        while running["flag"] and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.2)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    ap = argparse.ArgumentParser(description="Record SLAM timing events to CSV.")
    ap.add_argument("--ros", required=True, choices=["1", "2"])
    ap.add_argument("--output", required=True)
    ap.add_argument("--use-sim-time", action="store_true")
    ap.add_argument("--scan-topic", default="/scan")
    ap.add_argument("--map-topic", default="/map")
    ap.add_argument("--map-frame", default="map")
    ap.add_argument("--odom-frame", default="odom")
    ap.add_argument("--base-frame", default="base_link")
    args = ap.parse_args()

    running = {"flag": True}

    def stop(*_):
        running["flag"] = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    frames = {"map": strip(args.map_frame), "odom": strip(args.odom_frame), "base": strip(args.base_frame)}
    writer = EventWriter(args.output, frames)
    try:
        if args.ros == "1":
            run_ros1(args, writer, running)
        else:
            run_ros2(args, writer, running)
    finally:
        writer.close()
    print(f"Latency logging stopped: {writer.counts}", file=sys.stderr)


if __name__ == "__main__":
    main()
