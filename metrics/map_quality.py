#!/usr/bin/env python3
"""Quantitative occupancy-grid comparison (numpy only).

    map_quality.py compare test.yaml reference.yaml [--max-angle 10] [--no-align]
    map_quality.py consistency [--results results/raw] --tag T [--group-by variant] [--json f] [--markdown f]

`compare` aligns the test map to the reference (2D rotation + translation search on
occupied cells, FFT cross-correlation per angle) and reports, on the reference grid:

  occ_iou              occupied-cell IoU, exact cells
  occ_precision_Nc     share of test walls within N cells of a reference wall
  occ_recall_Nc        share of reference walls within N cells of a test wall
  occ_f1_Nc            harmonic mean of the two (N = 1, 2)
  cell_accuracy        share of cells known in both maps with the same class (free/occupied)
  wall_error_m         mean distance from test walls to the nearest reference wall
                       (alignment / sharpness; capped at --max-dist)
  completeness_m       mean distance from reference walls to the nearest test wall
                       (missing structure; capped at --max-dist)
  known_area_ratio     known area of the test map / known area of the reference

With a floor plan or ground-truth map as the reference this is map accuracy; with
another run's map it is cross-run consistency. `consistency` compares all pairs of
runs selected by tag (comma-separated tags allowed), within each group (default: variant,
e.g. ros1-noetic, ros2-humble-zenoh) and across groups.

Maps are map_server format (.yaml + .pgm). Classes follow map_server trinary mode:
p = (255 - v) / 255 (or v / 255 if negate); occupied if p > occupied_thresh,
free if p < free_thresh, unknown otherwise.
"""

import argparse
import glob
import itertools
import json
import math
import os
import sys

import numpy as np

UNKNOWN, FREE, OCC = -1, 0, 1


# ---------------------------------------------------------------- io
def read_pgm(path):
    with open(path, "rb") as f:
        data = f.read()
    tokens = []
    pos = 0
    while len(tokens) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while data[pos:pos + 1] not in (b"\n", b""):
                pos += 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    magic, w, h, maxval = tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3])
    pos += 1
    if magic == b"P5":
        dtype = np.uint8 if maxval < 256 else np.dtype(">u2")
        img = np.frombuffer(data, dtype=dtype, count=w * h, offset=pos).reshape(h, w)
    elif magic == b"P2":
        img = np.array(data[pos:].split()[: w * h], dtype=np.int32).reshape(h, w)
    else:
        raise ValueError(f"{path}: unsupported image type {magic!r} (need P5/P2 PGM)")
    if maxval != 255:
        img = (img.astype(np.float64) * 255.0 / maxval).round()
    return img.astype(np.uint8)


def _parse_yaml(path):
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        out = {}
        with open(path) as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if ":" not in line:
                    continue
                k, v = (s.strip() for s in line.split(":", 1))
                if v.startswith("["):
                    out[k] = [float(x) for x in v.strip("[]").split(",")]
                else:
                    try:
                        out[k] = float(v) if any(c in v for c in ".eE") else int(v)
                    except ValueError:
                        out[k] = v
        return out


def load_map(yaml_path):
    meta = _parse_yaml(yaml_path)
    img_path = str(meta["image"])
    here = os.path.dirname(os.path.abspath(yaml_path))
    if not os.path.isabs(img_path):
        img_path = os.path.join(here, img_path)
    elif not os.path.exists(img_path):
        # ROS1 map_saver writes an absolute path; the run folder may have moved since
        # (another machine, a CI artifact, a container mount), so look next to the yaml
        img_path = os.path.join(here, os.path.basename(img_path))
    img = read_pgm(img_path).astype(np.float64)
    p = img / 255.0 if int(meta.get("negate", 0)) else (255.0 - img) / 255.0
    cls = np.full(img.shape, UNKNOWN, dtype=np.int8)
    cls[p > float(meta.get("occupied_thresh", 0.65))] = OCC
    cls[p < float(meta.get("free_thresh", 0.196))] = FREE
    origin = [float(x) for x in meta.get("origin", [0.0, 0.0, 0.0])]
    return {"cls": cls, "res": float(meta["resolution"]), "origin": origin, "path": yaml_path}


# ---------------------------------------------------------------- geometry
def cell_to_world(m, rows, cols):
    h = m["cls"].shape[0]
    lx = (cols + 0.5) * m["res"]
    ly = (h - 1 - rows + 0.5) * m["res"]
    ox, oy, oyaw = m["origin"]
    c, s = math.cos(oyaw), math.sin(oyaw)
    return np.stack([ox + c * lx - s * ly, oy + s * lx + c * ly], axis=1)


def world_to_cell(m, pts):
    """Fractional (row, col) of world points in map m."""
    h = m["cls"].shape[0]
    ox, oy, oyaw = m["origin"]
    c, s = math.cos(oyaw), math.sin(oyaw)
    dx, dy = pts[:, 0] - ox, pts[:, 1] - oy
    lx = c * dx + s * dy
    ly = -s * dx + c * dy
    return h - 1 - (ly / m["res"] - 0.5), lx / m["res"] - 0.5


def occupied_points(m):
    r, c = np.nonzero(m["cls"] == OCC)
    return cell_to_world(m, r, c)


def rot(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def apply_tf(pts, tf):
    theta, center, d = tf
    return (pts - center) @ rot(theta).T + center + d


def invert_tf(pts, tf):
    theta, center, d = tf
    return (pts - center - d) @ rot(-theta).T + center


def _dilate(mask, k=1):
    out = mask.copy()
    for dr in range(-k, k + 1):
        for dc in range(-k, k + 1):
            if dr == 0 and dc == 0:
                continue
            out |= np.roll(np.roll(mask, dr, axis=0), dc, axis=1)
    return out


def _rasterize(rows, cols, shape):
    r = np.rint(rows).astype(np.int64)
    c = np.rint(cols).astype(np.int64)
    ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
    mask = np.zeros(shape, dtype=bool)
    mask[r[ok], c[ok]] = True
    return mask


# ---------------------------------------------------------------- alignment
def align(test, ref, max_angle_deg=10.0, coarse_step=1.0, fine_step=0.1, pad_m=2.0):
    """Rigid 2D transform taking test-map world coordinates to reference world coordinates."""
    pts = occupied_points(test)
    ref_pts = occupied_points(ref)
    if len(pts) == 0 or len(ref_pts) == 0:
        return (0.0, np.zeros(2), np.zeros(2)), 0.0
    center = ref_pts.mean(axis=0)
    P = int(math.ceil(pad_m / ref["res"]))
    h, w = ref["cls"].shape
    shape = (h + 2 * P, w + 2 * P)
    ref_occ = ref["cls"] == OCC
    # exact walls weigh 2, their 1-cell neighbourhood 1: tolerant to small offsets
    # without a flat plateau that would make the best shift ambiguous
    target = np.zeros(shape, dtype=np.float64)
    target[P:P + h, P:P + w] = ref_occ.astype(np.float64) + _dilate(ref_occ, 1)
    F_target = np.fft.rfft2(target)

    def score(theta):
        moved = apply_tf(pts, (theta, center, np.zeros(2)))
        r, c = world_to_cell(ref, moved)
        canvas = _rasterize(r + P, c + P, shape).astype(np.float64)
        n = canvas.sum()
        if n == 0:
            return -1.0, (0, 0)
        corr = np.fft.irfft2(F_target * np.conj(np.fft.rfft2(canvas)), s=shape)
        # only shifts within +/- P cells are meaningful (no wrap-around)
        corr = np.roll(np.roll(corr, P, axis=0), P, axis=1)[: 2 * P + 1, : 2 * P + 1]
        idx = np.unravel_index(int(np.argmax(corr)), corr.shape)
        return float(corr[idx]) / (2.0 * n), (idx[0] - P, idx[1] - P)

    best = (-1.0, 0.0, (0, 0))
    span = max_angle_deg
    for deg in np.arange(-span, span + 1e-9, coarse_step):
        s, sh = score(math.radians(deg))
        if s > best[0]:
            best = (s, deg, sh)
    base = best[1]
    for deg in np.arange(base - coarse_step, base + coarse_step + 1e-9, fine_step):
        s, sh = score(math.radians(deg))
        if s > best[0]:
            best = (s, deg, sh)

    s, deg, (drow, dcol) = best
    oyaw = ref["origin"][2]
    lx, ly = dcol * ref["res"], -drow * ref["res"]
    d = np.array([math.cos(oyaw) * lx - math.sin(oyaw) * ly, math.sin(oyaw) * lx + math.cos(oyaw) * ly])
    return (math.radians(deg), center, d), s


# ---------------------------------------------------------------- distances
def _offsets(radius):
    r = int(radius)
    dr, dc = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.hypot(dr, dc).ravel()
    keep = d <= radius
    order = np.argsort(d[keep], kind="stable")
    return dr.ravel()[keep][order], dc.ravel()[keep][order], d[keep][order]


def nearest_dist_cells(src, dst, max_cells):
    """For each True cell in src, grid distance (cells) to nearest True cell in dst, capped."""
    sr, sc = np.nonzero(src)
    out = np.full(len(sr), float(max_cells))
    todo = np.arange(len(sr))
    h, w = dst.shape
    for dr, dc, d in zip(*_offsets(max_cells)):
        if todo.size == 0:
            break
        r = sr[todo] + dr
        c = sc[todo] + dc
        ok = (r >= 0) & (r < h) & (c >= 0) & (c < w)
        hit = np.zeros(todo.size, dtype=bool)
        hit[ok] = dst[r[ok], c[ok]]
        out[todo[hit]] = d
        todo = todo[~hit]
    return out


# ---------------------------------------------------------------- comparison
def compare(test, ref, max_angle_deg=10.0, do_align=True, max_dist_m=1.0):
    if do_align:
        tf, score = align(test, ref, max_angle_deg)
    else:
        tf, score = (0.0, np.zeros(2), np.zeros(2)), None

    rc = ref["cls"]
    h, w = rc.shape
    rows, cols = np.mgrid[0:h, 0:w]
    q = cell_to_world(ref, rows.ravel(), cols.ravel())
    tr, tcol = world_to_cell(test, invert_tf(q, tf))
    tr, tcol = np.rint(tr).astype(np.int64), np.rint(tcol).astype(np.int64)
    th, tw = test["cls"].shape
    inside = (tr >= 0) & (tr < th) & (tcol >= 0) & (tcol < tw)
    tc = np.full(h * w, UNKNOWN, dtype=np.int8)
    tc[inside] = test["cls"][tr[inside], tcol[inside]]
    tc = tc.reshape(h, w)

    known_both = (tc != UNKNOWN) & (rc != UNKNOWN)
    t_occ_cells = tc == OCC
    r_occ = rc == OCC

    # walls as point sets on the reference grid (padded so nothing is clipped)
    P = int(math.ceil(max_dist_m / ref["res"])) + 2
    shape = (h + 2 * P, w + 2 * P)
    tp = apply_tf(occupied_points(test), tf)
    r_, c_ = world_to_cell(ref, tp)
    t_mask = _rasterize(r_ + P, c_ + P, shape)
    r_mask = np.zeros(shape, dtype=bool)
    r_mask[P:P + h, P:P + w] = r_occ
    max_cells = max_dist_m / ref["res"]
    d_tr = nearest_dist_cells(t_mask, r_mask, max_cells)
    d_rt = nearest_dist_cells(r_mask, t_mask, max_cells)

    res = {
        "test": test["path"], "reference": ref["path"],
        "resolution": ref["res"],
        "aligned": do_align,
        "align_yaw_deg": math.degrees(tf[0]),
        "align_shift_m": [float(x) for x in tf[2]],
        "align_score": score,
        "cells_known_both": int(known_both.sum()),
        "cell_accuracy": float((tc[known_both] == rc[known_both]).mean()) if known_both.any() else None,
        "occ_iou": float((t_occ_cells & r_occ).sum() / max(1, (t_occ_cells | r_occ).sum())),
        "wall_error_m": float(d_tr.mean() * ref["res"]) if d_tr.size else None,
        "completeness_m": float(d_rt.mean() * ref["res"]) if d_rt.size else None,
        "known_area_test_m2": float((test["cls"] != UNKNOWN).sum() * test["res"] ** 2),
        "known_area_ref_m2": float((rc != UNKNOWN).sum() * ref["res"] ** 2),
    }
    res["known_area_ratio"] = (res["known_area_test_m2"] / res["known_area_ref_m2"]
                               if res["known_area_ref_m2"] else None)
    for n in (1, 2):
        prec = float((d_tr <= n).mean()) if d_tr.size else 0.0
        rec = float((d_rt <= n).mean()) if d_rt.size else 0.0
        res[f"occ_precision_{n}c"] = prec
        res[f"occ_recall_{n}c"] = rec
        res[f"occ_f1_{n}c"] = 2 * prec * rec / (prec + rec) if prec + rec > 0 else 0.0
    return res


# ---------------------------------------------------------------- consistency
PAIR_METRICS = [
    ("occ_f1_1c", "Wall F1 (±1 cell)", ""),
    ("occ_iou", "Occupied IoU", ""),
    ("cell_accuracy", "Cell agreement", ""),
    ("wall_error_m", "Wall offset", "m"),
]


def consistency(results_dir, tag, max_angle_deg, group_by="variant"):
    """Pairwise map comparison of all runs with a saved map, grouped by `group_by`."""
    from compare_groups import prop
    from stats_utils import mean_ci95

    tags = tag.split(",") if tag else None
    runs = []
    for meta_path in sorted(glob.glob(os.path.join(results_dir, "*", "*", "run_meta.json"))):
        d = os.path.dirname(meta_path)
        with open(meta_path) as f:
            meta = json.load(f)
        if tags and meta.get("run_tag") not in tags:
            continue
        if meta.get("exit_status") not in (0, None) or prop(meta, "role") == "player":
            continue
        if os.path.exists(os.path.join(d, "map.yaml")):
            runs.append((prop(meta, group_by), d))

    maps = {d: load_map(os.path.join(d, "map.yaml")) for _, d in runs}
    groups = sorted({g for g, _ in runs})
    pairs = {}
    for (ga, da), (gb, db) in itertools.combinations(runs, 2):
        key = " | ".join(sorted([ga, gb]))
        r = compare(maps[da], maps[db], max_angle_deg)
        r.update(a=da, b=db)
        pairs.setdefault(key, []).append(r)

    within = [f"{g} | {g}" for g in groups]
    across = [f"{a} | {b}" for a, b in itertools.combinations(groups, 2)]
    order = [k for k in within + across if k in pairs]
    summary = {}
    for key in order:
        rows = pairs[key]
        summary[key] = {"pairs": len(rows), "within": key in within}
        for m, _, _ in PAIR_METRICS:
            vals = [r[m] for r in rows if r.get(m) is not None]
            mu, sd, ci = mean_ci95(vals)
            summary[key][m] = {"mean": mu, "sd": sd, "ci95": ci}
    return {"tag": tag, "group_by": group_by, "groups": groups, "order": order,
            "runs": [d for _, d in runs], "summary": summary, "pairs": pairs}


def consistency_markdown(rep):
    def f(x, d=3):
        return "n/a" if x is None or x != x else f"{x:.{d}f}"

    lines = [
        "## Map consistency across runs",
        "",
        "Pairwise comparison of saved maps after rigid alignment. Pairs within one group measure "
        "repeatability; pairs across groups measure whether both build the same map.",
        "",
        "| Pairs | n | " + " | ".join(f"{label}{' (' + u + ')' if u else ''}" for _, label, u in PAIR_METRICS) + " |",
        "|---|---|" + "---|" * len(PAIR_METRICS),
    ]
    for key in rep["order"]:
        s = rep["summary"][key]
        name = key.split(" | ")[0] + " (within)" if s["within"] else key.replace(" | ", " ↔ ")
        cells = [f"{f(s[m]['mean'])} ± {f(s[m]['ci95'])}" for m, _, _ in PAIR_METRICS]
        lines.append(f"| {name} | {s['pairs']} | " + " | ".join(cells) + " |")
    if not rep["order"]:
        lines.append("| (no saved maps) | 0 |" + " |" * len(PAIR_METRICS))
    lines += ["", "Pairs share runs, so they are not independent samples; read the CIs as descriptive."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Occupancy-grid map quality")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("test")
    c.add_argument("reference")
    c.add_argument("--max-angle", type=float, default=10.0, help="rotation search range [deg]")
    c.add_argument("--no-align", action="store_true")
    c.add_argument("--max-dist", type=float, default=1.0, help="distance cap for wall errors [m]")
    k = sub.add_parser("consistency")
    k.add_argument("--results", default="results/raw")
    k.add_argument("--tag", required=True)
    k.add_argument("--max-angle", type=float, default=10.0)
    k.add_argument("--group-by", default="variant", help="run property to group by (default variant)")
    k.add_argument("--json")
    k.add_argument("--markdown")
    args = ap.parse_args()

    if args.cmd == "compare":
        res = compare(load_map(args.test), load_map(args.reference), args.max_angle,
                      not args.no_align, args.max_dist)
        json.dump(res, sys.stdout, indent=2)
        print()
    else:
        rep = consistency(args.results, args.tag, args.max_angle, args.group_by)
        md = consistency_markdown(rep)
        print(md, end="")
        if args.json:
            with open(args.json, "w") as f:
                json.dump(rep, f, indent=2)
        if args.markdown:
            with open(args.markdown, "w") as f:
                f.write(md)


if __name__ == "__main__":
    main()
