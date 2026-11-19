#!/usr/bin/env python3
"""Turn a floor-plan image into an occupancy grid (map_server .yaml + .pgm).

    floorplan_to_map.py plan.png --meters-per-pixel 0.02 --out data/floorplan/office
    floorplan_to_map.py plan.png --scale 120,340,1720,340,16.0 --crop 100,80,1800,900 --out ...

Dark pixels (below --wall-threshold) are walls. The plan is resampled to --resolution
(default 0.05 m, the SLAM resolution); a cell is a wall if any of its pixels is. Free
space is the largest area enclosed by walls (one that does not touch the image border),
or the areas containing --seed points: give one seed per room the robot drove through
or could see into. Everything else is unknown.

By default only wall cells that face free space are kept (--keep-thick keeps all):
a LiDAR sees wall surfaces, so thick walls drawn on a plan would otherwise count as
structure the robot "missed".

Scale, one of:
  --meters-per-pixel M          if the plan's scale is known
  --scale x1,y1,x2,y2,METERS    two pixel positions and their real distance, e.g. the
                                ends of a corridor wall you measured

The result is in the plan's own frame. Place it in a bag's SLAM map frame with
    python3 metrics/map_quality.py register <out>.yaml <a run's map.yaml> --out data/bags/<bag>.reference.yaml
Needs numpy and Pillow (pip install pillow); PDF plans: export a page to PNG first.
"""

import argparse
import math
import os
import sys
from collections import deque

import numpy as np

UNKNOWN, FREE, WALL = 205, 254, 0


def load_gray(path):
    if path.lower().endswith((".pgm", ".pnm")):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "metrics"))
        from map_quality import read_pgm
        return read_pgm(path).astype(np.float64)
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is needed to read this image: pip install pillow")
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return np.asarray(img.convert("L"), dtype=np.float64)


def parse_ints(text, n, name):
    try:
        v = [float(x) for x in text.split(",")]
    except ValueError:
        sys.exit(f"--{name}: expected {n} comma-separated numbers")
    if len(v) != n:
        sys.exit(f"--{name}: expected {n} comma-separated numbers, got {len(v)}")
    return v


def block_any(mask, res_px):
    """Resample a boolean pixel mask to cells of res_px pixels: True if any pixel is True."""
    h, w = mask.shape
    rows = int(math.ceil(h / res_px))
    cols = int(math.ceil(w / res_px))
    integral = np.zeros((h + 1, w + 1), dtype=np.int64)
    integral[1:, 1:] = np.cumsum(np.cumsum(mask.astype(np.int64), axis=0), axis=1)
    r0 = np.floor(np.arange(rows) * res_px).astype(int)
    r1 = np.minimum(h, np.maximum(r0 + 1, np.ceil((np.arange(rows) + 1) * res_px).astype(int)))
    c0 = np.floor(np.arange(cols) * res_px).astype(int)
    c1 = np.minimum(w, np.maximum(c0 + 1, np.ceil((np.arange(cols) + 1) * res_px).astype(int)))
    total = (integral[r1][:, c1] - integral[r0][:, c1] - integral[r1][:, c0] + integral[r0][:, c0])
    return total > 0


def components(open_mask):
    """4-connected components of open cells. Returns (labels, list of (touches_border, size))."""
    h, w = open_mask.shape
    labels = np.full((h, w), -1, dtype=np.int32)
    info = []
    for r0 in range(h):
        for c0 in np.nonzero(open_mask[r0] & (labels[r0] < 0))[0]:
            if labels[r0, c0] >= 0:
                continue
            lab = len(info)
            border = False
            size = 0
            q = deque([(r0, c0)])
            labels[r0, c0] = lab
            while q:
                r, c = q.popleft()
                size += 1
                if r == 0 or c == 0 or r == h - 1 or c == w - 1:
                    border = True
                for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= rr < h and 0 <= cc < w and open_mask[rr, cc] and labels[rr, cc] < 0:
                        labels[rr, cc] = lab
                        q.append((rr, cc))
            info.append((border, size))
    return labels, info


def convert(gray, mpp, resolution, threshold=128.0, seeds=None, keep_thick=False, min_room_m2=1.0):
    res_px = resolution / mpp
    wall = block_any(gray < threshold, res_px)
    open_cells = ~wall
    labels, info = components(open_cells)
    cell_area = resolution ** 2
    if seeds:
        chosen = set()
        for x, y in seeds:
            r, c = int(y / res_px), int(x / res_px)
            if not (0 <= r < labels.shape[0] and 0 <= c < labels.shape[1]) or labels[r, c] < 0:
                sys.exit(f"--seed {x:g},{y:g} is on a wall or outside the image")
            chosen.add(int(labels[r, c]))
    else:
        enclosed = [(size, i) for i, (border, size) in enumerate(info)
                    if not border and size * cell_area >= min_room_m2]
        chosen = {max(enclosed)[1]} if enclosed else set()
        if not chosen:
            sys.exit("No enclosed area found (every open region touches the image border). "
                     "Close the outline or give --seed x,y inside the mapped area.")
    free = np.isin(labels, list(chosen))
    if not keep_thick:
        near_free = free.copy()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                near_free |= np.roll(np.roll(free, dr, axis=0), dc, axis=1)
        wall = wall & near_free
    img = np.full(wall.shape, UNKNOWN, dtype=np.uint8)
    img[free] = FREE
    img[wall] = WALL
    return img, {"rooms": len(chosen), "free_m2": float(free.sum() * cell_area),
                 "wall_cells": int(wall.sum()), "shape": list(img.shape)}


def write_map(stem, img, resolution, origin=(0.0, 0.0, 0.0)):
    os.makedirs(os.path.dirname(os.path.abspath(stem)) or ".", exist_ok=True)
    h, w = img.shape
    with open(stem + ".pgm", "wb") as f:
        f.write(f"P5\n{w} {h}\n255\n".encode())
        f.write(img.tobytes())
    with open(stem + ".yaml", "w") as f:
        f.write(f"image: {os.path.basename(stem)}.pgm\nresolution: {resolution}\n"
                f"origin: [{origin[0]:.6f}, {origin[1]:.6f}, {origin[2]:.9f}]\n"
                "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")


def main():
    ap = argparse.ArgumentParser(description="Floor-plan image to occupancy grid.")
    ap.add_argument("image")
    ap.add_argument("--out", required=True, help="output stem, writes <out>.yaml and <out>.pgm")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--meters-per-pixel", type=float)
    g.add_argument("--scale", help="x1,y1,x2,y2,METERS: two pixel positions and their real distance")
    ap.add_argument("--resolution", type=float, default=0.05, help="cell size in m (default 0.05)")
    ap.add_argument("--wall-threshold", type=float, default=128.0, help="gray level below which a pixel is wall")
    ap.add_argument("--crop", help="x0,y0,x1,y1 in pixels: keep only this part of the plan")
    ap.add_argument("--seed", action="append", default=[], help="x,y pixel inside the mapped area (repeatable)")
    ap.add_argument("--keep-thick", action="store_true", help="keep full wall thickness")
    ap.add_argument("--min-room", type=float, default=1.0, help="smallest enclosed area considered in auto mode [m²]")
    args = ap.parse_args()

    gray = load_gray(args.image)
    x_off = y_off = 0.0
    if args.crop:
        x0, y0, x1, y1 = (int(round(v)) for v in parse_ints(args.crop, 4, "crop"))
        gray = gray[y0:y1, x0:x1]
        x_off, y_off = x0, y0
        if gray.size == 0:
            sys.exit("--crop selects nothing")
    if args.meters_per_pixel:
        mpp = args.meters_per_pixel
    else:
        x1, y1, x2, y2, meters = parse_ints(args.scale, 5, "scale")
        px = math.hypot(x2 - x1, y2 - y1)
        if px == 0 or meters <= 0:
            sys.exit("--scale: the two points must differ and the distance must be positive")
        mpp = meters / px
    seeds = [(x - x_off, y - y_off) for x, y in (parse_ints(s, 2, "seed") for s in args.seed)]

    img, info = convert(gray, mpp, args.resolution, args.wall_threshold, seeds, args.keep_thick, args.min_room)
    write_map(args.out, img, args.resolution)
    print(f"{args.out}.yaml: {info['shape'][1]}x{info['shape'][0]} cells at {args.resolution} m "
          f"({mpp:.4f} m/px), {info['rooms']} enclosed area(s), {info['free_m2']:.1f} m² free, "
          f"{info['wall_cells']} wall cells")


if __name__ == "__main__":
    main()
