#!/usr/bin/env bash
# Record the sensor input for replay experiments on the robot.
#
# Usage: experiments/record_bag.sh <name>
#   Writes data/bags/<name>.bag (ROS1) or data/bags/<name>/ (ROS2), whichever stack is sourced.
#
# Environment:
#   DURATION  seconds to record (default 300)
#   TOPICS    topics to record (default "/scan /odom /tf /tf_static")
#
# Record with the SLAM node STOPPED: a bag that already contains map->odom on /tf
# would fight the SLAM node under test. experiments/inspect_bag.py checks for this.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

NAME="${1:-}"
[ -n "${NAME}" ] || { echo "Usage: $0 <name>" >&2; exit 1; }
DURATION="${DURATION:-300}"
TOPICS="${TOPICS:-/scan /odom /tf /tf_static}"
OUT_DIR="data/bags"
mkdir -p "${OUT_DIR}"

read -r -a TOPIC_ARRAY <<< "${TOPICS}"

case "${ROS_VERSION:-}" in
  1)
    OUT="${OUT_DIR}/${NAME}.bag"
    [ -e "${OUT}" ] && { echo "ERROR: ${OUT} already exists" >&2; exit 1; }
    if rosnode list 2>/dev/null | grep -qE '^/(slam_toolbox|slam_gmapping)$'; then
      echo "ERROR: a SLAM node is running. Stop it before recording." >&2; exit 1
    fi
    echo "Recording ${TOPICS} for ${DURATION}s -> ${OUT}"
    rosbag record --duration="${DURATION}" -O "${OUT}" "${TOPIC_ARRAY[@]}"
    ;;
  2)
    OUT="${OUT_DIR}/${NAME}"
    [ -e "${OUT}" ] && { echo "ERROR: ${OUT} already exists" >&2; exit 1; }
    if ros2 node list 2>/dev/null | grep -qx '/slam_toolbox'; then
      echo "ERROR: a SLAM node is running. Stop it before recording." >&2; exit 1
    fi
    echo "Recording ${TOPICS} for ${DURATION}s -> ${OUT}"
    timeout -s INT "${DURATION}" ros2 bag record -o "${OUT}" "${TOPIC_ARRAY[@]}"
    rc=$?
    [ "${rc}" -eq 0 ] || [ "${rc}" -eq 124 ] || exit "${rc}"
    ;;
  *)
    echo "ERROR: source a ROS1 or ROS2 setup.bash first (ROS_VERSION is unset)." >&2
    exit 1
    ;;
esac

if python3 -c "import rosbags" 2>/dev/null; then
  python3 experiments/inspect_bag.py "${OUT}"
else
  echo "Recorded ${OUT}. Run experiments/inspect_bag.py on a machine with 'rosbags' installed to validate it."
fi
