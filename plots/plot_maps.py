#!/usr/bin/env python3
"""Render an occupancy-grid map (map_server .pgm/.png) to a PNG for the paper.

Usage:
    python3 plots/plot_maps.py path/to/map.pgm [--out map.png]
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")  # headless-safe
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.image as mpimg  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Render an occupancy grid map to PNG.")
    ap.add_argument("map_image", help="Path to a map image (.pgm or .png)")
    ap.add_argument("--out", help="Output PNG path (default: alongside the input)")
    args = ap.parse_args()

    if not os.path.exists(args.map_image):
        print(f"Map image not found: {args.map_image}", file=sys.stderr)
        sys.exit(1)

    img = mpimg.imread(args.map_image)

    plt.figure()
    plt.imshow(img, cmap="gray", origin="upper")
    plt.axis("off")
    plt.title(os.path.basename(args.map_image))

    out = args.out or (os.path.splitext(args.map_image)[0] + "_render.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
