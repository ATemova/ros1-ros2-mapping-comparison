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
#   REQUIRE_MAP   1 = fail unless a /map was received and saved (default: 1 replay, 0 live)
#   REQUIRE_PARAMS 1 = fail if the node holds a parameter value that differs from the
#                 config file, or its parameters cannot be read (default 1)
#   RUN_TAG       free-form label stored in run_meta.json (used to group repeated runs)
#   ROS_DISTRO    override the ROS distribution to source
#   LOG_LATENCY   1 = run metrics/ros_latency_logger.py (default 1). It subscribes to
#                 /scan, /map and /tf like any other client; set 0 for CPU-only runs.
#   REFERENCE_TRAJ / REFERENCE_MAP   reference trajectory (TUM) / map (.yaml) for ATE and
#                 map accuracy (default: data/bags/<bag>.groundtruth.tum / .reference.yaml)
#
# Two machines (network/IPC overhead): run the bag on one machine and SLAM on the other.
#   ROLE=all      (default) everything on this machine
#   ROLE=slam     SLAM, loggers and map saving here; waits for /clock from the player,
#                 stops CLOCK_IDLE seconds after it goes silent. BAG is optional (used for
#                 the bag id and the expected scan count).
#   ROLE=player   only plays BAG (ROS1: against the remote ROS_MASTER_URI) and logs this
#                 machine's CPU and network. Start it after the slam side reports ready.
#   CLOCK_WAIT    seconds the slam side waits for the player to start (default 600)
#
# Middleware and conditions:
#   RMW           ROS2 middleware: fastrtps (default), cyclonedds, zenoh, or a full
#                 rmw_* name. zenoh starts its router (rmw_zenohd) automatically.
#   CPU_SET       pin the whole run to these CPUs (taskset list, e.g. "0,1")
#   CONDITION     label for the run condition (default: derived from applied CPU/memory
#                 limits, "default" when unconstrained). Runs with different conditions
#                 are never pooled.
#   IMAGE_ID / IMAGE_TAG / GIT_DIRTY   set by the Makefile / run_matrix.sh for run_manifest.json

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

ROLE="${ROLE:-all}"
LOG_LATENCY="${LOG_LATENCY:-1}"
CLOCK_WAIT="${CLOCK_WAIT:-600}"
CLOCK_IDLE="${CLOCK_IDLE:-5}"
case "${ROLE}" in
  all|slam|player) ;;
  *) echo "ERROR: ROLE must be all, slam or player (got '${ROLE}')" >&2; exit 1 ;;
esac
[ "${ROLE}" = "player" ] && [ -z "${BAG}" ] && { echo "ERROR: ROLE=player needs BAG" >&2; exit 1; }

if [ -n "${BAG}" ] || [ "${ROLE}" = "slam" ]; then MODE="replay"; else MODE="live"; fi
if [ "${MODE}" = "replay" ]; then USE_SIM_TIME=true; else USE_SIM_TIME=false; fi
REQUIRE_MAP="${REQUIRE_MAP:-$([ "${MODE}" = "replay" ] && echo 1 || echo 0)}"
REQUIRE_PARAMS="${REQUIRE_PARAMS:-1}"
RMW="${RMW:-${RMW_IMPLEMENTATION:-}}"
CPU_SET="${CPU_SET:-}"
CONDITION="${CONDITION:-}"

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
    command -v ros2 >/dev/null 2>&1 || die "ROS2 not found on PATH. Run inside a ros2-mapping container or source /opt/ros/<distro>/setup.bash."
    ros2 pkg prefix "${SLAM_PKG}" >/dev/null 2>&1 || die "package '${SLAM_PKG}' is not installed (apt-get install ros-${ROS_DISTRO}-${SLAM_PKG//_/-})."
  fi
  select_rmw
}

# Resolve RMW to an rmw_* package, export it, and set RMW_EFFECTIVE / VARIANT.
select_rmw() {
  if [ "${STACK}" = "ros1" ]; then
    [ -n "${RMW}" ] && die "RMW applies to ROS2 only (ROS1 always uses TCPROS)."
    RMW_EFFECTIVE="tcpros"
    VARIANT="ros1-${ROS_DISTRO}"
    return
  fi
  case "${RMW}" in
    ""|fastrtps|fastdds|rmw_fastrtps_cpp) RMW_EFFECTIVE="rmw_fastrtps_cpp" ;;
    cyclonedds|cyclone|rmw_cyclonedds_cpp) RMW_EFFECTIVE="rmw_cyclonedds_cpp" ;;
    zenoh|rmw_zenoh_cpp) RMW_EFFECTIVE="rmw_zenoh_cpp" ;;
    rmw_*) RMW_EFFECTIVE="${RMW}" ;;
    *) die "unknown RMW '${RMW}' (fastrtps, cyclonedds, zenoh or an rmw_* package)" ;;
  esac
  ros2 pkg prefix "${RMW_EFFECTIVE}" >/dev/null 2>&1 \
    || die "${RMW_EFFECTIVE} is not installed (apt-get install ros-${ROS_DISTRO}-${RMW_EFFECTIVE//_/-})."
  export RMW_IMPLEMENTATION="${RMW_EFFECTIVE}"
  ros2 daemon stop >/dev/null 2>&1 || true
  local short="${RMW_EFFECTIVE#rmw_}"
  VARIANT="ros2-${ROS_DISTRO}-${short%_cpp}"
}

# rmw_zenoh needs a router; start one for this run unless ZENOH_ROUTER=external.
start_zenoh_router() {
  [ "${RMW_EFFECTIVE:-}" = "rmw_zenoh_cpp" ] || return 0
  [ "${ZENOH_ROUTER:-local}" = "external" ] && return 0
  start_group ros2 run rmw_zenoh_cpp rmw_zenohd
  sleep 2
  group_alive "${LAST_GROUP}" || die "the Zenoh router (rmw_zenohd) did not start."
  log "Zenoh router started."
}

apply_cpu_set() {
  [ -n "${CPU_SET}" ] || return 0
  command -v taskset >/dev/null 2>&1 || die "CPU_SET needs taskset (util-linux)."
  taskset -cp "${CPU_SET}" $$ >/dev/null || die "could not pin to CPUs ${CPU_SET}."
  log "Pinned to CPUs ${CPU_SET}."
}

write_manifest() {
  local extra=()
  [ -n "${BAG_PATH:-}" ] && extra+=(--bag "${BAG_PATH}")
  [ "${STACK}" = "ros2" ] && [ "${MODE}" = "replay" ] && extra+=(--qos "${QOS_OVERRIDES}")
  python3 experiments/write_manifest.py "${OUTPUT_DIR}" \
    --params "config/${ALGO}.yaml" --launch "${LAUNCH_FILE}" ${extra[@]+"${extra[@]}"} \
    || log "WARNING: could not write run_manifest.json"
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

# Dump the parameters the running node actually holds and compare them with the
# config file (writes params_dump.yaml and effective_params.json).
dump_params() {
  local raw="${OUTPUT_DIR}/params_dump.yaml" i
  for i in 1 2 3; do
    if [ "${STACK}" = "ros1" ]; then
      timeout 15 rosparam get "${SLAM_NODE}" > "${raw}" 2>/dev/null
    else
      timeout 30 ros2 param dump "${SLAM_NODE}" > "${raw}" 2>/dev/null
    fi
    [ -s "${raw}" ] && break
    sleep 2
  done
  python3 experiments/dump_params.py "${STACK}" "${raw}" "config/${ALGO}.yaml" \
    "${OUTPUT_DIR}/effective_params.json"
}

# Save the occupancy grid (map.pgm + map.yaml) and, for slam_toolbox, the serialized
# pose graph (pose_graph.posegraph + pose_graph.data) into the run directory.
save_map() {
  local abs="${REPO_ROOT}/${OUTPUT_DIR}"
  if [ "${STACK}" = "ros1" ]; then
    timeout 30 rosrun map_server map_saver -f "${abs}/map" >/dev/null 2>&1
    if [ "${ALGO}" = "slam_toolbox" ]; then
      timeout 30 rosservice call /slam_toolbox/serialize_map "filename: '${abs}/pose_graph'" >/dev/null 2>&1
    fi
  else
    timeout 60 ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
      "{name: {data: '${abs}/map'}}" >/dev/null 2>&1
    # slam_toolbox's save_map runs nav2's map_saver_cli with its 2 s default timeout, which
    # can expire before discovery completes (seen with Fast DDS on Jazzy); retry directly
    # with a longer timeout and a transient-local subscription to the latched map
    if [ ! -s "${abs}/map.pgm" ]; then
      log "save_map service did not write the map; retrying with map_saver_cli."
      timeout 60 ros2 run nav2_map_server map_saver_cli -f "${abs}/map" --ros-args \
        -p save_map_timeout:=10.0 -p map_subscribe_transient_local:=true >/dev/null 2>&1
    fi
    timeout 60 ros2 service call /slam_toolbox/serialize_map slam_toolbox/srv/SerializePoseGraph \
      "{filename: '${abs}/pose_graph'}" >/dev/null 2>&1
  fi
  [ -s "${abs}/map.pgm" ] && [ -s "${abs}/map.yaml" ]
}

csv_rows() {
  [ -f "$1" ] || { echo 0; return; }
  echo $(( $(wc -l < "$1") - 1 ))
}

clock_alive() {
  if [ "${STACK}" = "ros1" ]; then
    timeout 3 rostopic echo -n 1 /clock >/dev/null 2>&1
  else
    timeout "${CLOCK_IDLE}" ros2 topic echo --once /clock rosgraph_msgs/msg/Clock >/dev/null 2>&1
  fi
}

# ROLE=slam: block until the remote player has started and finished publishing /clock.
wait_for_remote_bag() {
  local deadline=$(( SECONDS + CLOCK_WAIT ))
  log "Ready. Waiting up to ${CLOCK_WAIT}s for the player to start (/clock)..."
  until clock_alive; do
    [ "${SECONDS}" -lt "${deadline}" ] || return 1
    sleep 1
  done
  log "Player started; waiting for /clock to stop."
  while clock_alive; do sleep 1; done
  return 0
}

config_value() {
  python3 -c "import sys, yaml; print((yaml.safe_load(open(sys.argv[1])) or {}).get(sys.argv[2], sys.argv[3]))" \
    "config/${ALGO}.yaml" "$1" "$2" 2>/dev/null || echo "$2"
}

new_output_dir() {
  local base_id i=1
  base_id="$(date +"%Y%m%d_%H%M%S")_${VARIANT:-${STACK}}"
  EXPERIMENT_ID="${base_id}"
  while [ -e "results/raw/${STACK}/${EXPERIMENT_ID}" ]; do
    EXPERIMENT_ID="${base_id}_${i}"; i=$((i + 1))
  done
  OUTPUT_DIR="results/raw/${STACK}/${EXPERIMENT_ID}"
  mkdir -p "${OUTPUT_DIR}"
}

start_resource_logger() {
  start_group python3 metrics/cpu_memory_logger.py \
    --output "${OUTPUT_DIR}/cpu_mem.csv" \
    --proc-output "${OUTPUT_DIR}/proc_metrics.csv" \
    --net-output "${OUTPUT_DIR}/net_io.csv" \
    --experiment_id "${EXPERIMENT_ID}" \
    --ros_version "${ROS_LABEL}"
  METRICS_PID="${LAST_GROUP}"
}

start_bag_player() {
  if [ "${STACK}" = "ros1" ]; then
    start_group rosbag play --clock --quiet -r "${RATE}" "${BAG_PATH}"
  else
    start_group ros2 bag play --clock -r "${RATE}" \
      --qos-profile-overrides-path "${QOS_OVERRIDES}" "${BAG_PATH}"
  fi
}

# ---------------------------------------------------------------- ROLE=player
run_player() {
  local bag_rc status=0 started_at finished_at samples

  source_ros
  apply_cpu_set
  ensure_psutil || die "psutil is required (apt-get install python3-psutil)."
  resolve_bag "${BAG}"
  if [ "${STACK}" = "ros1" ]; then
    wait_for_master || die "no ROS master at ${ROS_MASTER_URI:-unset}. Start ROLE=slam first and set ROS_MASTER_URI / ROS_IP."
  fi

  new_output_dir
  log "Player run ${EXPERIMENT_ID}: ${BAG_PATH} at ${RATE}x -> ${OUTPUT_DIR}"
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start_zenoh_router
  start_resource_logger
  sleep 1
  start_bag_player
  wait "${LAST_GROUP}"; bag_rc=$?
  stop_group "${METRICS_PID}"
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  samples="$(csv_rows "${OUTPUT_DIR}/cpu_mem.csv")"
  [ "${bag_rc}" = "0" ] || { log "ERROR: bag playback failed (exit ${bag_rc})."; status=1; }

  python3 experiments/write_meta.py "${OUTPUT_DIR}/run_meta.json" \
    experiment_id="${EXPERIMENT_ID}" stack="${STACK}" ros_distro="${ROS_DISTRO}" role=player \
    rmw="${RMW_EFFECTIVE}" variant="${VARIANT}" condition="${CONDITION}" cpu_set="${CPU_SET}" \
    mode=replay bag_id="${BAG_ID}" bag_path="${BAG_PATH}" rate="${RATE}" run_tag="${RUN_TAG}" \
    bag_exit_code="${bag_rc}" metrics_samples="${samples}" exit_status="${status}" \
    started_at="${started_at}" finished_at="${finished_at}" \
    ros_master_uri="${ROS_MASTER_URI:-}" ros_domain_id="${ROS_DOMAIN_ID:-}" \
    rmw_implementation="${RMW_IMPLEMENTATION:-}" \
    || log "WARNING: could not write run_meta.json"
  write_manifest
  python3 metrics/analyze_run.py "${OUTPUT_DIR}" --quiet || log "WARNING: analysis failed."
  log "Player completed (status ${status})."
  return "${status}"
}

# ---------------------------------------------------------------- main
run_experiment() {
  [ "${ROLE}" = "player" ] && { run_player; return $?; }

  local bag_rc="" map_received=false map_saved=false pose_graph_saved=false
  local params_ok=false metrics_samples=0 started_at finished_at status=0
  local scans_expected="" latency_pid="" latency_events=0

  source_ros
  apply_cpu_set
  ensure_psutil || die "psutil is required for CPU/memory logging (apt-get install python3-psutil)."

  BAG_ID=""; BAG_PATH=""
  [ -n "${BAG}" ] && resolve_bag "${BAG}"
  [ -n "${BAG_PATH}" ] && scans_expected="$(python3 experiments/bag_info.py "${BAG_PATH}" --topic "$(config_value scan_topic /scan)" 2>/dev/null)"

  new_output_dir
  cp "config/${ALGO}.yaml" "${OUTPUT_DIR}/"
  [ "${MODE}" = "replay" ] && [ "${STACK}" = "ros2" ] && cp "${QOS_OVERRIDES}" "${OUTPUT_DIR}/"

  log "Experiment ID: ${EXPERIMENT_ID}"
  log "Output:        ${OUTPUT_DIR}"
  log "Algorithm:     ${ALGO}"
  log "Variant:       ${VARIANT}${CONDITION:+ (${CONDITION})}"
  if [ "${ROLE}" = "slam" ]; then
    log "Mode:          replay from a remote player${BAG_PATH:+ (${BAG_PATH})}"
  elif [ "${MODE}" = "replay" ]; then
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
    start_zenoh_router
    start_group ros2 launch "${LAUNCH_FILE}" "algo:=${ALGO}" "use_sim_time:=${USE_SIM_TIME}"
  fi
  MAPPING_PID="${LAST_GROUP}"

  wait_for_node || die "SLAM node ${SLAM_NODE} did not start within ${STARTUP_WAIT}s."
  log "SLAM node ${SLAM_NODE} is up."

  if dump_params; then
    params_ok=true
    log "Node parameters match config/${ALGO}.yaml."
  else
    log "WARNING: node parameters do not match config/${ALGO}.yaml (see effective_params.json)."
  fi

  start_resource_logger

  if [ "${LOG_LATENCY}" = "1" ]; then
    local sim_flag=()
    [ "${USE_SIM_TIME}" = "true" ] && sim_flag=(--use-sim-time)
    start_group python3 metrics/ros_latency_logger.py --ros "${STACK#ros}" \
      --output "${OUTPUT_DIR}/latency_events.csv" ${sim_flag[@]+"${sim_flag[@]}"} \
      --scan-topic "$(config_value scan_topic /scan)" \
      --map-frame "$(config_value map_frame map)" \
      --odom-frame "$(config_value odom_frame odom)" \
      --base-frame "$(config_value base_frame base_link)"
    latency_pid="${LAST_GROUP}"
    sleep 3
    group_alive "${latency_pid}" || log "WARNING: the latency logger exited at startup."
  fi

  if [ "${ROLE}" = "slam" ]; then
    if wait_for_remote_bag; then bag_rc=0; else bag_rc=124; log "ERROR: no /clock from a player within ${CLOCK_WAIT}s."; fi
    sleep "${SETTLE}"
  elif [ "${MODE}" = "replay" ]; then
    start_bag_player
    wait "${LAST_GROUP}"; bag_rc=$?
    log "Bag playback finished (exit ${bag_rc}); settling ${SETTLE}s."
    sleep "${SETTLE}"
  else
    sleep "${DURATION}"
  fi

  if ! group_alive "${METRICS_PID}"; then
    log "ERROR: the CPU/memory logger exited early."; status=1
  fi
  stop_group "${METRICS_PID}"
  [ -n "${latency_pid}" ] && stop_group "${latency_pid}"
  metrics_samples="$(csv_rows "${OUTPUT_DIR}/cpu_mem.csv")"
  if [ "${metrics_samples}" -lt 1 ]; then
    log "ERROR: cpu_mem.csv has no samples."; status=1
  fi
  [ -n "${latency_pid}" ] && latency_events="$(csv_rows "${OUTPUT_DIR}/latency_events.csv")"

  if probe_map; then
    map_received=true
    log "/map received."
    if save_map; then
      map_saved=true
      log "Map saved to ${OUTPUT_DIR}/map.pgm"
      if python3 -c "import matplotlib" 2>/dev/null; then
        python3 plots/plot_maps.py "${OUTPUT_DIR}/map.pgm" --out "${OUTPUT_DIR}/map.png" >/dev/null 2>&1 || true
      fi
    else
      log "WARNING: map could not be saved."
    fi
    [ -s "${OUTPUT_DIR}/pose_graph.posegraph" ] && pose_graph_saved=true
  else
    log "WARNING: no /map message received."
  fi

  kill -0 "${MAPPING_PID}" 2>/dev/null || { log "ERROR: SLAM process exited during the run."; status=1; }
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "${MODE}" = "replay" ] && [ "${bag_rc}" != "0" ]; then
    log "ERROR: bag playback failed."; status=1
  fi
  if [ "${REQUIRE_MAP}" = "1" ] && { [ "${map_received}" != "true" ] || [ "${map_saved}" != "true" ]; }; then
    log "ERROR: REQUIRE_MAP=1 but no map was produced and saved."; status=1
  fi
  if [ "${REQUIRE_PARAMS}" = "1" ] && [ "${params_ok}" != "true" ]; then
    log "ERROR: REQUIRE_PARAMS=1 but the node parameters differ from config/${ALGO}.yaml."; status=1
  fi

  python3 experiments/write_meta.py "${OUTPUT_DIR}/run_meta.json" \
    experiment_id="${EXPERIMENT_ID}" stack="${STACK}" ros_distro="${ROS_DISTRO}" role="${ROLE}" \
    rmw="${RMW_EFFECTIVE}" variant="${VARIANT}" condition="${CONDITION}" cpu_set="${CPU_SET}" \
    algo="${ALGO}" mode="${MODE}" bag_id="${BAG_ID}" bag_path="${BAG_PATH}" \
    rate="$([ "${ROLE}" = "slam" ] || echo "${RATE}")" \
    duration_s="$([ "${MODE}" = "live" ] && echo "${DURATION}")" \
    settle_s="${SETTLE}" use_sim_time="${USE_SIM_TIME}" run_tag="${RUN_TAG}" \
    bag_exit_code="${bag_rc}" scans_expected="${scans_expected}" \
    map_received="${map_received}" map_saved="${map_saved}" \
    pose_graph_saved="${pose_graph_saved}" params_ok="${params_ok}" \
    metrics_samples="${metrics_samples}" latency_events="${latency_events}" exit_status="${status}" \
    started_at="${started_at}" finished_at="${finished_at}" \
    params_file="${ALGO}.yaml" rmw_implementation="${RMW_IMPLEMENTATION:-}" \
    ros_master_uri="${ROS_MASTER_URI:-}" ros_domain_id="${ROS_DOMAIN_ID:-}" \
    || log "WARNING: could not write run_meta.json"
  write_manifest

  local ref_args=()
  [ -n "${REFERENCE_TRAJ:-}" ] && ref_args+=(--reference-traj "${REFERENCE_TRAJ}")
  [ -n "${REFERENCE_MAP:-}" ] && ref_args+=(--reference-map "${REFERENCE_MAP}")
  if python3 metrics/analyze_run.py "${OUTPUT_DIR}" ${ref_args[@]+"${ref_args[@]}"}; then
    log "Analysis written to ${OUTPUT_DIR}/run_metrics.json"
  else
    log "WARNING: analysis failed; raw data is still in ${OUTPUT_DIR}."
  fi

  log "Experiment completed (status ${status})."
  return "${status}"
}
