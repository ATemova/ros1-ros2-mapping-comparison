#!/usr/bin/env bash
# Convert a bag to the other ROS format so both stacks replay identical data.
#
# Usage: experiments/convert_bag.sh <data/bags/name.bag | data/bags/name>
#   name.bag -> name/      (ROS1 -> ROS2, rosbag2 sqlite3, metadata version 8 for Humble)
#   name/    -> name.bag   (ROS2 -> ROS1)
#
# Needs `rosbags-convert` (pip install rosbags; Python >= 3.10). The ros2-mapping
# Docker image ships it.
set -euo pipefail

SRC="${1:-}"
[ -n "${SRC}" ] || { echo "Usage: $0 <bag.bag | bag_dir>" >&2; exit 1; }
SRC="${SRC%/}"

command -v rosbags-convert >/dev/null 2>&1 || {
  echo "ERROR: rosbags-convert not found. pip install rosbags, or run inside the ros2-mapping image." >&2
  exit 1
}

if [ -f "${SRC}" ] && [ "${SRC##*.}" = "bag" ]; then
  DST="${SRC%.bag}"
  [ -e "${DST}" ] && { echo "Already converted: ${DST}"; exit 0; }
  rosbags-convert --src "${SRC}" --dst "${DST}" --dst-storage sqlite3 --dst-version 8
elif [ -f "${SRC}/metadata.yaml" ]; then
  DST="${SRC}.bag"
  [ -e "${DST}" ] && { echo "Already converted: ${DST}"; exit 0; }
  rosbags-convert --src "${SRC}" --dst "${DST}"
else
  echo "ERROR: ${SRC} is neither a .bag file nor a rosbag2 directory." >&2
  exit 1
fi

echo "Converted ${SRC} -> ${DST}"
