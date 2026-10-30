#!/usr/bin/env bash
# Shared experiment runner. Sourced by run_ros1.sh / run_ros2.sh after they set STACK.
#
# Environment:
#   ALGO          slam_toolbox (default) | gmapping (ROS1 only)
#   BAG           replay this bag instead of live sensors. Accepts the ROS1 file
#                 (data/bags/x.bag) or the ROS2 directory (data/bags/x); the matching
#                 form for this stack is resolved automatically.
#   RATE          bag playback rate (default 1.0)
#   DURATION      live-mode run length in seconds (default 300); ignored for replay
#   SETTLE        seconds to keep SLAM running after the bag ends (default 5)
#   STARTUP_WAIT  seconds to wait for the SLAM node to appear (default 15)
#   REQUIRE_MAP   1 = fail if no /map was received (default: 1 for replay, 0 for live)
#   RUN_TAG       free-form label stored in run_meta.json (used to group repeated runs)
#   ROS_DISTRO    override the ROS distribution to source

# shellcheck disable=SC2034
set -uo pipefail

: "${STACK:?STACK must be set to ros1 or ros2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

ALGO="${ALGO:-slam_toolbox}"
BAG="${BAG:-}"
RATE="${RATE:-1.0}"
DURATION="${DURATION:-300}"
SETTLE="${SETTLE:-5}"
STARTUP_WAIT="${STARTUP_WAIT:-15}"
RUN_TAG="${RUN_TAG:-}"
QOS_OVERRIDES="${REPO_ROOT}/config/qos_overrides.yaml"

if [ -n "${BAG}" ]; then MODE="replay"; else MODE="live"; fi
if [ "${MODE}" = "replay" ]; then USE_SIM_TIME=true; else USE_SIM_TIME=false; fi
REQUIRE_MAP="${REQUIRE_MAP:-$([ "${MODE}" = "replay" ] && echo 1 || echo 0)}"

case "${STACK}" in
  ros1)
    ROS_LABEL="ROS1"; DEFAULT_DISTRO="noetic"
    LAUNCH_FILE="${REPO_ROOT}/ros1/launch/mapping.launch"
    SUPPORTED_ALGOS="slam_toolbox gmapping"
    ;;
  ros2)
    ROS_LABEL="ROS2"; DEFAULT_DISTRO="humble"
    LAUNCH_FILE="${REPO_ROOT}/ros2/launch/mapping.launch.py"
    SUPPORTED_ALGOS="slam_toolbox"
    ;;
  *)
    echo "ERROR: unknown STACK '${STACK}'" >&2; exit 1 ;;
esac

case " ${SUPPORTED_ALGOS} " in
  *" ${ALGO} "*) ;;
  *) echo "ERROR: ALGO='${ALGO}' not supported on ${ROS_LABEL} (supported: ${SUPPORTED_ALGOS})" >&2; exit 1 ;;
esac

case "${ALGO}" in
  slam_toolbox) SLAM_PKG="slam_toolbox"; SLAM_NODE="/slam_toolbox" ;;
  gmapping)     SLAM_PKG="gmapping";     SLAM_NODE="/slam_gmapping" ;;
esac

log() { echo "[${ROS_LABEL}] $*"; }
die() { echo "[${ROS_LABEL}] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------- process groups
# Every long-running child is started in its own session so the whole tree
# (roslaunch/ros2 launch and their nodes) can be stopped together.
# Bash makes background jobs ignore SIGINT when job control is off, and that
# disposition survives exec; roslaunch / ros2 launch need SIGINT for a clean
# shutdown, so the spawner restores it before exec. stdin is detached so the
# bag players' keyboard controls never block on the terminal.
GROUPS_TO_STOP=()
SPAWN_PY='import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGQUIT, signal.SIG_DFL)
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])'

start_group() {
  python3 -c "${SPAWN_PY}" "$@" </dev/null &
  LAST_GROUP=$!
  GROUPS_TO_STOP+=("${LAST_GROUP}")
}

group_alive() { kill -0 -- "-$1" 2>/dev/null; }

# SIGINT, then SIGTERM, then SIGKILL, waiting on every process in the group,
# not just the leader, so no node outlives the run.
stop_group() {
  local pgid="$1" sig i
  for sig in INT TERM KILL; do
    group_alive "${pgid}" || break
    kill "-${sig}" -- "-${pgid}" 2>/dev/null || true
    for i in $(seq 1 20); do
      group_alive "${pgid}" || break
      sleep 0.5
    done
  done
  wait "${pgid}" 2>/dev/null || true
}

cleanup() {
  local i
  for (( i=${#GROUPS_TO_STOP[@]}-1; i>=0; i-- )); do
    stop_group "${GROUPS_TO_STOP[i]}"
  done
  GROUPS_TO_STOP=()
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------- ROS environment
source_ros() {
  : "${ROS_DISTRO:=${DEFAULT_DISTRO}}"
  set +u
  if [ "${STACK}" = "ros1" ]; then
    if [ -z "${ROS_ROOT:-}" ] && [ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
      # shellcheck disable=SC1090
      source "/opt/ros/${ROS_DISTRO}/setup.bash"
    fi
    # shellcheck disable=SC1091
    [ -f "devel/setup.bash" ] && source devel/setup.bash
  else
    if [ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
      # shellcheck disable=SC1090
      source "/opt/ros/${ROS_DISTRO}/setup.bash"
    fi
    # shellcheck disable=SC1091
    [ -f "install/setup.bash" ] && source install/setup.bash
  fi
  set -u

  if [ "${STACK}" = "ros1" ]; then
    command -v roscore >/dev/null 2>&1 || die "ROS1 not found on PATH. Run inside the ros:noetic container or source /opt/ros/noetic/setup.bash."
    rospack find "${SLAM_PKG}" >/dev/null 2>&1 || die "package '${SLAM_PKG}' is not installed (apt-get install ros-noetic-${SLAM_PKG//_/-})."
  else
    command -v ros2 >/dev/null 2>&1 || die "ROS2 not found on PATH. Run inside the ros:humble container or source /opt/ros/humble/setup.bash."
    ros2 pkg prefix "${SLAM_PKG}" >/dev/null 2>&1 || die "package '${SLAM_PKG}' is not installed (apt-get install ros-humble-${SLAM_PKG//_/-})."
  fi
}

ensure_psutil() {
  python3 -c "import psutil" 2>/dev/null && return 0
  log "psutil not found; attempting to install python3-psutil..."
  if command -v apt-get >/dev/null 2>&1; then
    { sudo apt-get update -qq && sudo apt-get install -y python3-psutil; } 2>/dev/null \
      || { apt-get update -qq && apt-get install -y python3-psutil; } 2>/dev/null || true
  fi
  python3 -c "import psutil" 2>/dev/null && return 0
  if command -v pip3 >/dev/null 2>&1; then pip3 install psutil 2>/dev/null || true; fi
  python3 -c "import psutil" 2>/dev/null
}

# ---------------------------------------------------------------- bag resolution
resolve_bag() {
  local in="$1" stem
  case "${in}" in
    */) in="${in%/}" ;;
  esac
  stem="${in%.bag}"
  BAG_ID="$(basename "${stem}")"
  if [ "${STACK}" = "ros1" ]; then
    BAG_PATH="${stem}.bag"
    [ -f "${BAG_PATH}" ] || die "ROS1 bag not found: ${BAG_PATH} (convert with experiments/convert_bag.sh ${stem})"
  else
    BAG_PATH="${stem}"
    [ -f "${BAG_PATH}/metadata.yaml" ] || die "ROS2 bag not found: ${BAG_PATH}/metadata.yaml (convert with experiments/convert_bag.sh ${stem}.bag)"
  fi
}

# ---------------------------------------------------------------- ROS helpers
wait_for_master() {
  local i
  for i in $(seq 1 30); do
    rostopic list >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

node_present() {
  if [ "${STACK}" = "ros1" ]; then
    rosnode list 2>/dev/null | grep -qx "${SLAM_NODE}"
  else
    ros2 node list --no-daemon 2>/dev/null | grep -qx "${SLAM_NODE}"
  fi
}

wait_for_node() {
  local deadline=$(( SECONDS + STARTUP_WAIT ))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    kill -0 "${MAPPING_PID}" 2>/dev/null || return 1
    node_present && return 0
    sleep 1
  done
  return 1
}

probe_map() {
  if [ "${STACK}" = "ros1" ]; then
    timeout 15 rostopic echo -n 1 /map >/dev/null 2>&1
  else
    timeout 20 ros2 topic echo --once /map nav_msgs/msg/OccupancyGrid >/dev/null 2>&1
  fi
}

# ---------------------------------------------------------------- main
run_experiment() {
  local base_id i=1 bag_rc="" map_received=false started_at finished_at status=0

  source_ros

  BAG_ID=""; BAG_PATH=""
  [ "${MODE}" = "replay" ] && resolve_bag "${BAG}"

  base_id="$(date +"%Y%m%d_%H%M%S")"
  EXPERIMENT_ID="${base_id}"
  while [ -e "results/raw/${STACK}/${EXPERIMENT_ID}" ]; do
    EXPERIMENT_ID="${base_id}_${i}"; i=$((i + 1))
  done
  OUTPUT_DIR="results/raw/${STACK}/${EXPERIMENT_ID}"
  mkdir -p "${OUTPUT_DIR}"
  cp "config/${ALGO}.yaml" "${OUTPUT_DIR}/"
  [ "${MODE}" = "replay" ] && [ "${STACK}" = "ros2" ] && cp "${QOS_OVERRIDES}" "${OUTPUT_DIR}/"

  log "Experiment ID: ${EXPERIMENT_ID}"
  log "Output:        ${OUTPUT_DIR}"
  log "Algorithm:     ${ALGO}"
  if [ "${MODE}" = "replay" ]; then
    log "Mode:          replay ${BAG_PATH} at ${RATE}x"
  else
    log "Mode:          live, ${DURATION}s"
  fi

  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "${STACK}" = "ros1" ]; then
    start_group roscore
    wait_for_master || die "roscore did not come up."
    start_group roslaunch "${LAUNCH_FILE}" "algo:=${ALGO}" "use_sim_time:=${USE_SIM_TIME}"
  else
    start_group ros2 launch "${LAUNCH_FILE}" "algo:=${ALGO}" "use_sim_time:=${USE_SIM_TIME}"
  fi
  MAPPING_PID="${LAST_GROUP}"

  wait_for_node || die "SLAM node ${SLAM_NODE} did not start within ${STARTUP_WAIT}s."
  log "SLAM node ${SLAM_NODE} is up."

  if ensure_psutil; then
    start_group python3 metrics/cpu_memory_logger.py \
      --output "${OUTPUT_DIR}/cpu_mem.csv" \
      --experiment_id "${EXPERIMENT_ID}" \
      --ros_version "${ROS_LABEL}"
    METRICS_PID="${LAST_GROUP}"
  else
    METRICS_PID=""
    log "WARNING: psutil unavailable; skipping CPU/memory logging."
  fi

  if [ "${MODE}" = "replay" ]; then
    if [ "${STACK}" = "ros1" ]; then
      start_group rosbag play --clock --quiet -r "${RATE}" "${BAG_PATH}"
    else
      start_group ros2 bag play --clock -r "${RATE}" \
        --qos-profile-overrides-path "${QOS_OVERRIDES}" "${BAG_PATH}"
    fi
    wait "${LAST_GROUP}"; bag_rc=$?
    log "Bag playback finished (exit ${bag_rc}); settling ${SETTLE}s."
    sleep "${SETTLE}"
  else
    sleep "${DURATION}"
  fi

  if probe_map; then
    map_received=true
    log "/map received."
  else
    log "WARNING: no /map message received."
  fi

  kill -0 "${MAPPING_PID}" 2>/dev/null || { log "ERROR: SLAM process exited during the run."; status=1; }

  [ -n "${METRICS_PID}" ] && stop_group "${METRICS_PID}"
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "${MODE}" = "replay" ] && [ "${bag_rc}" != "0" ]; then
    log "ERROR: bag playback failed."; status=1
  fi
  if [ "${REQUIRE_MAP}" = "1" ] && [ "${map_received}" != "true" ]; then
    log "ERROR: REQUIRE_MAP=1 but no map was produced."; status=1
  fi

  python3 experiments/write_meta.py "${OUTPUT_DIR}/run_meta.json" \
    experiment_id="${EXPERIMENT_ID}" stack="${STACK}" ros_distro="${ROS_DISTRO}" \
    algo="${ALGO}" mode="${MODE}" bag_id="${BAG_ID}" bag_path="${BAG_PATH}" \
    rate="${RATE}" duration_s="$([ "${MODE}" = "live" ] && echo "${DURATION}")" \
    settle_s="${SETTLE}" use_sim_time="${USE_SIM_TIME}" run_tag="${RUN_TAG}" \
    bag_exit_code="${bag_rc}" map_received="${map_received}" exit_status="${status}" \
    started_at="${started_at}" finished_at="${finished_at}" \
    params_file="${ALGO}.yaml" rmw_implementation="${RMW_IMPLEMENTATION:-}" \
    || log "WARNING: could not write run_meta.json"

  log "Experiment completed (status ${status})."
  return "${status}"
}
