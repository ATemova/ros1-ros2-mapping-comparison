#!/usr/bin/env python3
"""Trajectory extraction and ATE / RPE (numpy only; same definitions as `evo`).

Estimated trajectory: the pose the SLAM system believed online, map->base =
(latest map->odom received so far) * (odom->base at its stamp), from latency_events.csv.
Written in TUM format (timestamp x y z qx qy qz qw), so it can also be fed to evo:
    evo_ape tum reference.tum trajectory.tum --align --plot

Usage:
    trajectory.py extract latency_events.csv trajectory.tum [--rate HZ]
    trajectory.py error reference.tum trajectory.tum [--max-diff 0.01] [--no-align]

ATE: translation error after SE(3) Umeyama alignment without scale (evo_ape --align).
RPE: relative pose error between consecutive associated poses (evo_rpe, delta 1 frame),
translation [m] and rotation [deg].
Association: as evo: every pose of the shorter trajectory is matched to the nearest
timestamp of the longer one within --max-diff.
"""

import argparse
import json
import math
import sys

import numpy as np


# ---------------------------------------------------------------- SE(3) helpers
def quat_to_rot(qx, qy, qz, qw):
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    x, y, z, w = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def se3(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def se2_to_se3(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return se3(np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]), [x, y, 0.0])


def rot_angle(R):
    return math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0)))


# ---------------------------------------------------------------- TUM io
def read_tum(path):
    stamps, poses = [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            v = [float(x) for x in line.replace(",", " ").split()]
            if len(v) != 8:
                raise ValueError(f"{path}: expected 8 columns in TUM format, got {len(v)}")
            stamps.append(v[0])
            poses.append(se3(quat_to_rot(*v[4:8]), v[1:4]))
    order = np.argsort(stamps, kind="stable")
    return np.array(stamps)[order], [poses[i] for i in order]


def write_tum(path, rows):
    with open(path, "w") as f:
        for t, x, y, yaw in rows:
            f.write(f"{t:.6f} {x:.6f} {y:.6f} 0.000000 0.000000 0.000000 "
                    f"{math.sin(yaw / 2):.9f} {math.cos(yaw / 2):.9f}\n")


# ---------------------------------------------------------------- extraction
def extract(events, map_frame="map", odom_frame="odom", base_frame="base_link", rate_hz=0.0):
    """events: dicts from latency_analysis.load_events (sorted by receive time).

    rate_hz > 0 subsamples; the default keeps every odom pose so that a reference at any
    rate associates within the default 10 ms.
    """
    map_odom = (0.0, 0.0, 0.0)
    have_correction = False
    out = []
    last_t = -math.inf
    period = 1.0 / rate_hz if rate_hz > 0 else 0.0
    for e in events:
        if e["event"] != "tf":
            continue
        if e["parent"] == map_frame and e["child"] == odom_frame:
            map_odom = (e["x"], e["y"], e["yaw"])
            have_correction = True
        elif e["parent"] == odom_frame and e["child"] == base_frame:
            if not have_correction or e["stamp"] < last_t + period - 1e-9:
                continue
            mx, my, myaw = map_odom
            c, s = math.cos(myaw), math.sin(myaw)
            x = mx + c * e["x"] - s * e["y"]
            y = my + s * e["x"] + c * e["y"]
            yaw = math.atan2(math.sin(myaw + e["yaw"]), math.cos(myaw + e["yaw"]))
            out.append((e["stamp"], x, y, yaw))
            last_t = e["stamp"]
    return out


# ---------------------------------------------------------------- association / alignment
def associate(stamps_ref, stamps_est, max_diff=0.01):
    """Indices (i_ref, i_est) of matched poses, evo nearest-time semantics."""
    ref_shorter = len(stamps_ref) <= len(stamps_est)
    short, long_ = (stamps_ref, stamps_est) if ref_shorter else (stamps_est, stamps_ref)
    pairs = []
    if len(long_) == 0:
        return pairs
    for i, t in enumerate(short):
        j = int(np.searchsorted(long_, t))
        cands = [k for k in (j - 1, j) if 0 <= k < len(long_)]
        k = min(cands, key=lambda k: abs(long_[k] - t))
        if abs(long_[k] - t) <= max_diff:
            pairs.append((i, k) if ref_shorter else (k, i))
    return pairs


def umeyama(src, dst):
    """Rotation R and translation t minimizing ||dst - (R src + t)|| (no scale). src, dst: 3xN."""
    mu_s = src.mean(axis=1, keepdims=True)
    mu_d = dst.mean(axis=1, keepdims=True)
    cov = (dst - mu_d) @ (src - mu_s).T / src.shape[1]
    U, _, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    t = mu_d - R @ mu_s
    return R, t.ravel()


def _summary(values, prefix):
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {}
    return {
        f"{prefix}rmse": float(np.sqrt(np.mean(v ** 2))),
        f"{prefix}mean": float(np.mean(v)),
        f"{prefix}median": float(np.median(v)),
        f"{prefix}std": float(np.std(v)),
        f"{prefix}min": float(np.min(v)),
        f"{prefix}max": float(np.max(v)),
    }


def errors(ref_stamps, ref_poses, est_stamps, est_poses, max_diff=0.01, align=True):
    pairs = associate(ref_stamps, est_stamps, max_diff)
    res = {"poses_ref": len(ref_poses), "poses_est": len(est_poses), "pairs": len(pairs), "aligned": align}
    if len(pairs) < 3:
        res["error"] = "fewer than 3 associated poses"
        return res
    P = [ref_poses[i] for i, _ in pairs]
    Q = [est_poses[j] for _, j in pairs]

    if align:
        src = np.array([q[:3, 3] for q in Q]).T
        dst = np.array([p[:3, 3] for p in P]).T
        R, t = umeyama(src, dst)
        A = se3(R, t)
        Q = [A @ q for q in Q]
        res["alignment"] = {"yaw_deg": math.degrees(math.atan2(R[1, 0], R[0, 0])),
                            "translation": [float(x) for x in t]}

    ate = [np.linalg.norm(p[:3, 3] - q[:3, 3]) for p, q in zip(P, Q)]
    res.update(_summary(ate, "ate_"))

    rpe_t, rpe_r = [], []
    for k in range(len(P) - 1):
        dp = np.linalg.inv(P[k]) @ P[k + 1]
        dq = np.linalg.inv(Q[k]) @ Q[k + 1]
        E = np.linalg.inv(dp) @ dq
        rpe_t.append(np.linalg.norm(E[:3, 3]))
        rpe_r.append(math.degrees(rot_angle(E[:3, :3])))
    res.update(_summary(rpe_t, "rpe_trans_"))
    res.update(_summary(rpe_r, "rpe_rot_deg_"))
    res["duration_s"] = float(ref_stamps[pairs[-1][0]] - ref_stamps[pairs[0][0]])
    path = sum(np.linalg.norm(P[k + 1][:3, 3] - P[k][:3, 3]) for k in range(len(P) - 1))
    res["path_length_m"] = float(path)
    return res


def main():
    ap = argparse.ArgumentParser(description="Trajectory extraction and ATE/RPE")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("events")
    e.add_argument("out")
    e.add_argument("--rate", type=float, default=0.0, help="subsample to this rate (default: keep all)")
    e.add_argument("--map-frame", default="map")
    e.add_argument("--odom-frame", default="odom")
    e.add_argument("--base-frame", default="base_link")
    r = sub.add_parser("error")
    r.add_argument("reference")
    r.add_argument("estimate")
    r.add_argument("--max-diff", type=float, default=0.01)
    r.add_argument("--no-align", action="store_true")
    args = ap.parse_args()

    if args.cmd == "extract":
        from latency_analysis import load_events
        rows = extract(load_events(args.events), args.map_frame, args.odom_frame, args.base_frame, args.rate)
        write_tum(args.out, rows)
        print(f"{len(rows)} poses -> {args.out}", file=sys.stderr)
    else:
        rs, rp = read_tum(args.reference)
        es, ep = read_tum(args.estimate)
        json.dump(errors(rs, rp, es, ep, args.max_diff, not args.no_align), sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
