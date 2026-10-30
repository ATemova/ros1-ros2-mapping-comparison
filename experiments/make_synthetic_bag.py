#!/usr/bin/env python3
"""Generate a deterministic synthetic ROS1 bag for pipeline tests (CI, no robot).

A differential-drive robot drives an L-shaped path through a 12 m x 8 m room with
two box obstacles. A 360-beam 2D LiDAR is ray-cast analytically.

Topics: /scan (10 Hz), /odom and /tf odom->base_link (50 Hz), /tf_static base_link->laser.

Usage: make_synthetic_bag.py [--out data/bags/synthetic.bag]
Convert to ROS2 with experiments/convert_bag.sh. Needs `rosbags` and `numpy`.
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np

try:
    from rosbags.rosbag1 import Writer
    from rosbags.typesys import Stores, get_types_from_msg, get_typestore
except ImportError:
    sys.stderr.write("ERROR: the 'rosbags' package is required (pip install rosbags).\n")
    sys.exit(1)

T0_NS = 1_700_000_000 * 1_000_000_000
SCAN_HZ = 10.0
ODOM_HZ = 50.0
N_BEAMS = 360
RANGE_MIN = 0.1
RANGE_MAX = 12.0
LASER_OFFSET = (0.10, 0.0, 0.20)


def rect(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


WALLS = rect(-6.0, -4.0, 6.0, 4.0) + rect(-1.0, 0.5, 0.5, 1.5) + rect(2.5, -3.0, 3.5, -2.0)
SEG_A = np.array([w[0] for w in WALLS])
SEG_B = np.array([w[1] for w in WALLS])


def pose_at(t):
    """Piecewise path: forward 6 m, turn left 90 deg, forward 4 m, then stop."""
    v, w = 0.3, math.radians(18.0)
    x, y, yaw = -4.0, -2.5, 0.0
    leg1 = 6.0 / v
    turn = (math.pi / 2) / w
    leg2 = 4.0 / v

    d = min(t, leg1)
    x += v * d
    if t <= leg1:
        return x, y, yaw, v, 0.0
    d = min(t - leg1, turn)
    yaw += w * d
    if t <= leg1 + turn:
        return x, y, yaw, 0.0, w
    d = min(t - leg1 - turn, leg2)
    y += v * d
    if t <= leg1 + turn + leg2:
        return x, y, yaw, v, 0.0
    return x, y, yaw, 0.0, 0.0


def raycast(x, y, yaw):
    angles = yaw + np.linspace(-math.pi, math.pi, N_BEAMS, endpoint=False)
    d = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    p = np.array([x, y])
    e = SEG_B - SEG_A
    ranges = np.full(N_BEAMS, np.inf)
    for i in range(len(WALLS)):
        denom = d[:, 0] * e[i, 1] - d[:, 1] * e[i, 0]
        diff = SEG_A[i] - p
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (diff[0] * e[i, 1] - diff[1] * e[i, 0]) / denom
            u = (diff[0] * d[:, 1] - diff[1] * d[:, 0]) / denom
        hit = (np.abs(denom) > 1e-12) & (t > 0) & (u >= 0) & (u <= 1)
        ranges = np.where(hit & (t < ranges), t, ranges)
    ranges[~np.isfinite(ranges) | (ranges > RANGE_MAX)] = np.inf
    return ranges.astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description="Generate a synthetic ROS1 bag.")
    ap.add_argument("--out", type=Path, default=Path("data/bags/synthetic.bag"))
    ap.add_argument("--duration", type=float, default=40.0, help="seconds (default 40)")
    args = ap.parse_args()

    if args.out.exists():
        print(f"Refusing to overwrite {args.out}", file=sys.stderr)
        sys.exit(1)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    ts = get_typestore(Stores.ROS1_NOETIC)
    if "tf2_msgs/msg/TFMessage" not in ts.types:
        ts.register(get_types_from_msg(
            "geometry_msgs/TransformStamped[] transforms", "tf2_msgs/msg/TFMessage"
        ))
    T = ts.types
    Time = T["builtin_interfaces/msg/Time"]
    Header = T["std_msgs/msg/Header"]
    Vector3 = T["geometry_msgs/msg/Vector3"]
    Point = T["geometry_msgs/msg/Point"]
    Quaternion = T["geometry_msgs/msg/Quaternion"]
    Transform = T["geometry_msgs/msg/Transform"]
    TransformStamped = T["geometry_msgs/msg/TransformStamped"]
    TFMessage = T["tf2_msgs/msg/TFMessage"]
    Pose = T["geometry_msgs/msg/Pose"]
    PoseWithCovariance = T["geometry_msgs/msg/PoseWithCovariance"]
    Twist = T["geometry_msgs/msg/Twist"]
    TwistWithCovariance = T["geometry_msgs/msg/TwistWithCovariance"]
    Odometry = T["nav_msgs/msg/Odometry"]
    LaserScan = T["sensor_msgs/msg/LaserScan"]

    seq = {"scan": 0, "odom": 0, "tf": 0}

    def stamp(ns):
        return Time(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)

    def header(ns, frame, key):
        seq[key] += 1
        return Header(seq=seq[key], stamp=stamp(ns), frame_id=frame)

    def quat(yaw):
        return Quaternion(x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2))

    def tf_stamped(ns, parent, child, x, y, z, yaw, key="tf"):
        return TransformStamped(
            header=header(ns, parent, key),
            child_frame_id=child,
            transform=Transform(translation=Vector3(x=x, y=y, z=z), rotation=quat(yaw)),
        )

    cov = np.zeros(36, dtype=np.float64)
    cov[[0, 7, 35]] = [0.001, 0.001, 0.001]
    x0, y0, yaw0, _, _ = pose_at(0.0)

    events = []
    dt_odom = int(1e9 / ODOM_HZ)
    dt_scan = int(1e9 / SCAN_HZ)
    end_ns = T0_NS + int(args.duration * 1e9)
    events += [(ns, "odom") for ns in range(T0_NS, end_ns, dt_odom)]
    events += [(ns, "scan") for ns in range(T0_NS + dt_scan // 2, end_ns, dt_scan)]
    events.sort()

    with Writer(args.out) as w:
        c_static = w.add_connection("/tf_static", TFMessage.__msgtype__, typestore=ts, latching=1)
        c_tf = w.add_connection("/tf", TFMessage.__msgtype__, typestore=ts)
        c_odom = w.add_connection("/odom", Odometry.__msgtype__, typestore=ts)
        c_scan = w.add_connection("/scan", LaserScan.__msgtype__, typestore=ts)

        static = TFMessage(transforms=[
            tf_stamped(T0_NS, "base_link", "laser", *LASER_OFFSET, 0.0, key="tf"),
        ])
        w.write(c_static, T0_NS, ts.serialize_ros1(static, TFMessage.__msgtype__))

        for ns, kind in events:
            t = (ns - T0_NS) / 1e9
            x, y, yaw, v, wz = pose_at(t)
            # odom frame starts at the robot's initial pose
            ox, oy, oyaw = x - x0, y - y0, yaw - yaw0
            if kind == "odom":
                tf = TFMessage(transforms=[tf_stamped(ns, "odom", "base_link", ox, oy, 0.0, oyaw)])
                w.write(c_tf, ns, ts.serialize_ros1(tf, TFMessage.__msgtype__))
                odom = Odometry(
                    header=header(ns, "odom", "odom"),
                    child_frame_id="base_link",
                    pose=PoseWithCovariance(
                        pose=Pose(position=Point(x=ox, y=oy, z=0.0), orientation=quat(oyaw)),
                        covariance=cov,
                    ),
                    twist=TwistWithCovariance(
                        twist=Twist(linear=Vector3(x=v, y=0.0, z=0.0), angular=Vector3(x=0.0, y=0.0, z=wz)),
                        covariance=cov,
                    ),
                )
                w.write(c_odom, ns, ts.serialize_ros1(odom, Odometry.__msgtype__))
            else:
                lx = x + LASER_OFFSET[0] * math.cos(yaw)
                ly = y + LASER_OFFSET[0] * math.sin(yaw)
                scan = LaserScan(
                    header=header(ns, "laser", "scan"),
                    angle_min=-math.pi,
                    angle_max=math.pi - 2 * math.pi / N_BEAMS,
                    angle_increment=2 * math.pi / N_BEAMS,
                    time_increment=0.0,
                    scan_time=1.0 / SCAN_HZ,
                    range_min=RANGE_MIN,
                    range_max=RANGE_MAX,
                    ranges=raycast(lx, ly, yaw),
                    intensities=np.zeros(0, dtype=np.float32),
                )
                w.write(c_scan, ns, ts.serialize_ros1(scan, LaserScan.__msgtype__))

    print(args.out)


if __name__ == "__main__":
    main()
