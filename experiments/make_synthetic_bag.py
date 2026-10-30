#!/usr/bin/env python3
"""Generate a deterministic synthetic ROS1 bag for pipeline tests (CI, no robot).

A differential-drive robot drives an L-shaped path through a 12 m x 8 m room with
two box obstacles. A 360-beam 2D LiDAR is ray-cast analytically.

Topics: /scan (10 Hz), /odom and /tf odom->base_link (50 Hz), /tf_static base_link->laser.

Also writes the ground truth next to the bag, in the SLAM map frame (= odom frame at
start), which analyze_run.py picks up automatically:
  <name>.groundtruth.tum     true base_link trajectory, 10 Hz (TUM format)
  <name>.reference.yaml/.pgm floor plan as an occupancy grid (walls occupied, room free,
                             box interiors and outside unknown)

Usage: make_synthetic_bag.py [--out data/bags/synthetic.bag]
       make_synthetic_bag.py --out data/bags/long30.bag --path loop --duration 1800
       make_synthetic_bag.py --out data/bags/fast40.bag --scan-hz 40 --beams 1080
Convert to ROS2 with experiments/convert_bag.sh. Needs `rosbags` and `numpy`.
"""

import argparse
import math
import os
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


PATH = "l"
LAP = [("line", 9.3), ("turn", math.pi / 2), ("line", 4.0), ("turn", math.pi / 2),
       ("line", 9.3), ("turn", math.pi / 2), ("line", 4.0), ("turn", math.pi / 2)]


def pose_at(t):
    return pose_loop(t) if PATH == "loop" else pose_l(t)


def pose_loop(t):
    """Laps of a 9.3 m x 4 m rectangle clear of both boxes; loop closure every lap."""
    v, w = 0.3, math.radians(18.0)
    lap_t = sum(d / v if k == "line" else d / w for k, d in LAP)
    t = t % lap_t
    x, y, yaw = -4.5, -1.0, 0.0
    for kind, amount in LAP:
        dur = amount / v if kind == "line" else amount / w
        step = min(t, dur)
        if kind == "line":
            x += v * step * math.cos(yaw)
            y += v * step * math.sin(yaw)
        else:
            yaw += w * step
        if t <= dur:
            return x, y, math.atan2(math.sin(yaw), math.cos(yaw)), (v if kind == "line" else 0.0), \
                (w if kind == "turn" else 0.0)
        t -= dur
    return x, y, 0.0, 0.0, 0.0


def pose_l(t):
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


def write_groundtruth(path, duration, x0, y0, yaw0, rate_hz=10.0):
    with open(path, "w") as f:
        n = int(duration * rate_hz)
        for i in range(n):
            t = i / rate_hz
            x, y, yaw, _, _ = pose_at(t)
            # map frame == odom frame at start == robot start pose
            c, s = math.cos(-yaw0), math.sin(-yaw0)
            mx, my = c * (x - x0) - s * (y - y0), s * (x - x0) + c * (y - y0)
            myaw = yaw - yaw0
            stamp = (T0_NS + int(t * 1e9)) / 1e9
            f.write(f"{stamp:.6f} {mx:.6f} {my:.6f} 0.0 0.0 0.0 {math.sin(myaw / 2):.9f} {math.cos(myaw / 2):.9f}\n")


def write_reference_map(stem, x0, y0, res=0.05, margin=1.0):
    """Floor plan in the map frame (walls shifted by the start pose; start yaw is 0)."""
    xs = [p[0] for w in WALLS for p in w]
    ys = [p[1] for w in WALLS for p in w]
    ox, oy = min(xs) - margin - x0, min(ys) - margin - y0
    W = int(math.ceil((max(xs) - min(xs) + 2 * margin) / res))
    H = int(math.ceil((max(ys) - min(ys) + 2 * margin) / res))
    img = np.full((H, W), 205, dtype=np.uint8)

    rr, cc = np.mgrid[0:H, 0:W]
    wx = ox + (cc + 0.5) * res + x0
    wy = oy + (H - 1 - rr + 0.5) * res + y0
    room = (wx > -6.0) & (wx < 6.0) & (wy > -4.0) & (wy < 4.0)
    boxes = ((wx > -1.0) & (wx < 0.5) & (wy > 0.5) & (wy < 1.5)) | \
            ((wx > 2.5) & (wx < 3.5) & (wy > -3.0) & (wy < -2.0))
    img[room & ~boxes] = 254

    for (ax, ay), (bx, by) in WALLS:
        n = int(math.hypot(bx - ax, by - ay) / res * 4) + 1
        for t in np.linspace(0.0, 1.0, n):
            px, py = ax + t * (bx - ax) - x0, ay + t * (by - ay) - y0
            c = int((px - ox) / res)
            r = H - 1 - int((py - oy) / res)
            if 0 <= r < H and 0 <= c < W:
                img[r, c] = 0

    with open(f"{stem}.reference.pgm", "wb") as f:
        f.write(f"P5\n{W} {H}\n255\n".encode())
        f.write(img.tobytes())
    with open(f"{stem}.reference.yaml", "w") as f:
        f.write(f"image: {os.path.basename(stem)}.reference.pgm\nresolution: {res}\n"
                f"origin: [{ox:.6f}, {oy:.6f}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")


def main():
    ap = argparse.ArgumentParser(description="Generate a synthetic ROS1 bag.")
    ap.add_argument("--out", type=Path, default=Path("data/bags/synthetic.bag"))
    ap.add_argument("--duration", type=float, default=40.0, help="seconds (default 40)")
    ap.add_argument("--path", choices=["l", "loop"], default="l",
                    help="l: one L-shaped drive (default); loop: repeated laps for long runs")
    ap.add_argument("--scan-hz", type=float, default=10.0, help="LiDAR rate (default 10)")
    ap.add_argument("--beams", type=int, default=360, help="beams per scan (default 360)")
    args = ap.parse_args()

    global PATH, SCAN_HZ, N_BEAMS
    PATH, SCAN_HZ, N_BEAMS = args.path, args.scan_hz, args.beams

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

    stem = str(args.out)[:-4] if str(args.out).endswith(".bag") else str(args.out)
    write_groundtruth(f"{stem}.groundtruth.tum", args.duration, x0, y0, yaw0)
    write_reference_map(stem, x0, y0)
    print(args.out)


if __name__ == "__main__":
    main()
