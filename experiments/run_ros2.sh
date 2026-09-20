#!/usr/bin/env bash
set -uo pipefail

# --- Resolve repo root so the script works from any cwd / Docker mount ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

echo "Starting ROS2 mapping experiment"

# --- Configuration ---
EXPERIMENT_ID="$(date +"%Y%m%d_%H%M%S")"
OUTPUT_DIR="results/raw/ros2/${EXPERIMENT_ID}"
DURATION="${DURATION:-300}"
ROS_LABEL="ROS2"
LAUNCH_FILE="${REPO_ROOT}/ros2/launch/mapping.launch.py"

MAPPING_PID=""
METRICS_PID=""

mkdir -p "${OUTPUT_DIR}"
cp ros2/params/*.yaml "${OUTPUT_DIR}/" 2>/dev/null || true

echo "Experiment ID: ${EXPERIMENT_ID}"
echo "Output directory: ${OUTPUT_DIR}"
echo "Duration: ${DURATION}s"

cleanup() {
  echo "Stopping experiment processes..."
  kill ${METRICS_PID} ${MAPPING_PID} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- Source ROS2 (idempotent; defaults to humble) ---
: "${ROS_DISTRO:=humble}"
# ROS setup scripts reference unset vars; relax nounset while sourcing.
set +u
if [ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
  # shellcheck disable=SC1090
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
fi
# Source a local colcon workspace if one has been built.
[ -f "install/setup.bash" ] && source install/setup.bash
set -u

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ERROR: ROS2 not found on PATH." >&2
  echo "       Run inside the ros:humble container or 'source /opt/ros/humble/setup.bash' first." >&2
  exit 1
fi

# --- Ensure psutil is available for the metrics logger ---
ensure_psutil() {
  python3 -c "import psutil" 2>/dev/null && return 0
  echo "psutil not found; attempting to install python3-psutil..."
  if command -v apt-get >/dev/null 2>&1; then
    { sudo apt-get update -qq && sudo apt-get install -y python3-psutil; } 2>/dev/null \
      || { apt-get update -qq && apt-get install -y python3-psutil; } 2>/dev/null || true
  fi
  python3 -c "import psutil" 2>/dev/null && return 0
  command -v pip3 >/dev/null 2>&1 && pip3 install psutil 2>/dev/null || true
  python3 -c "import psutil" 2>/dev/null
}

# --- Start mapping (launch by absolute path; no ament package required) ---
if [ -f "${LAUNCH_FILE}" ]; then
  ros2 launch "${LAUNCH_FILE}" &
  MAPPING_PID=$!
  sleep 5

  if ! kill -0 "${MAPPING_PID}" 2>/dev/null; then
    echo "ERROR: ROS2 mapping process failed to start." >&2
    exit 1
  fi
else
  echo "WARNING: ${LAUNCH_FILE} not found." >&2
  exit 1
fi

# --- Start metrics logging (non-fatal if psutil unavailable) ---
if ensure_psutil; then
  python3 metrics/cpu_memory_logger.py \
    --output "${OUTPUT_DIR}/cpu_mem.csv" \
    --experiment_id "${EXPERIMENT_ID}" \
    --ros_version "${ROS_LABEL}" &
  METRICS_PID=$!
else
  echo "WARNING: psutil unavailable; skipping CPU/memory logging." >&2
fi

# --- Run for the configured duration ---
sleep "${DURATION}"

echo "ROS2 experiment completed"
