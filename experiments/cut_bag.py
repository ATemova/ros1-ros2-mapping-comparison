#!/usr/bin/env python3
"""Cut a short window out of a ROS1 bag, e.g. a CI sample or a release asset.

Usage: cut_bag.py data/bags/corridor_01.bag --seconds 30 [--start 10] --out data/bags/sample.bag

Messages keep their original timestamps. /tf_static is always kept (it is latched).
Companion files are trimmed or copied alongside: <name>.groundtruth.tum (window only)
and <name>.reference.yaml/.pgm. For a ROS2 bag, convert it first:
    experiments/convert_bag.sh data/bags/corridor_01 && cut_bag.py data/bags/corridor_01.bag ...
Needs `rosbags`.
"""

import argparse
import os
import shutil
import sys

try:
    from rosbags.rosbag1 import Reader, Writer
except ImportError:
    sys.stderr.write("ERROR: the 'rosbags' package is required (pip install rosbags).\n")
    sys.exit(1)

LATCHED = ("/tf_static",)


def main():
    ap = argparse.ArgumentParser(description="Cut a time window out of a ROS1 bag.")
    ap.add_argument("bag")
    ap.add_argument("--seconds", type=float, required=True, help="window length")
    ap.add_argument("--start", type=float, default=0.0, help="offset from the bag start (s)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if os.path.isdir(args.bag):
        sys.exit(f"{args.bag} is a ROS2 bag; convert it first: experiments/convert_bag.sh {args.bag}")
    if os.path.exists(args.out):
        sys.exit(f"Refusing to overwrite {args.out}")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    with Reader(args.bag) as reader:
        t0 = reader.start_time + int(args.start * 1e9)
        t1 = t0 + int(args.seconds * 1e9)
        written = 0
        with Writer(args.out) as writer:
            conns = {}
            for c in reader.connections:
                conns[c.id] = writer.add_connection(
                    c.topic, c.msgtype, msgdef=c.msgdef.data, md5sum=c.digest,
                    callerid=getattr(c.ext, "callerid", None), latching=getattr(c.ext, "latching", None),
                )
            for c, ts, raw in reader.messages():
                if c.topic in LATCHED and ts < t0:
                    ts = t0
                elif not (t0 <= ts < t1):
                    continue
                writer.write(conns[c.id], ts, raw)
                written += 1

    src_stem, dst_stem = args.bag[:-4], args.out[:-4] if args.out.endswith(".bag") else args.out
    gt = f"{src_stem}.groundtruth.tum"
    if os.path.exists(gt):
        with open(gt) as f, open(f"{dst_stem}.groundtruth.tum", "w") as g:
            for line in f:
                parts = line.split()
                if parts and not line.startswith("#") and t0 / 1e9 <= float(parts[0]) < t1 / 1e9:
                    g.write(line)
    ref = f"{src_stem}.reference.yaml"
    if os.path.exists(ref):
        with open(ref) as f:
            text = f.read()
        old_img = os.path.basename(src_stem) + ".reference.pgm"
        new_img = os.path.basename(dst_stem) + ".reference.pgm"
        with open(f"{dst_stem}.reference.yaml", "w") as f:
            f.write(text.replace(old_img, new_img))
        shutil.copy(f"{src_stem}.reference.pgm", f"{dst_stem}.reference.pgm")
    print(f"{written} messages, {args.seconds:g} s -> {args.out}")


if __name__ == "__main__":
    main()
