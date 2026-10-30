#!/usr/bin/env bash
# Repeated, counterbalanced ROS1 vs ROS2 replay runs in Docker, followed by statistics.
#
# Usage: BAG=data/bags/<name>.bag ./experiments/run_matrix.sh
#   BAG may be the ROS1 file or the ROS2 directory; the other form is created with
#   experiments/convert_bag.sh (inside the ros2-mapping image) when missing.
#   The bag must live inside the repository (it is mounted into the containers).
#
# Environment:
#   RUNS         runs per stack (default 5)
#   ALGO         slam_toolbox (default)
#   RATE         bag playback rate (default 1.0)
#   SETTLE       seconds after the bag ends (default 5)
#   RUN_TAG      label for this batch (default matrix_<timestamp>)
#   DOCKER_ARGS  extra docker run args, e.g. "--cpuset-cpus=2,3 --memory=4g" to pin resources
#   BUILD        1 = rebuild both images first (default: build only if missing)
#   COOLDOWN     seconds between runs (default 5)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

BAG="${BAG:-}"
RUNS="${RUNS:-5}"
ALGO="${ALGO:-slam_toolbox}"
RATE="${RATE:-1.0}"
SETTLE="${SETTLE:-5}"
RUN_TAG="${RUN_TAG:-matrix_$(date +%Y%m%d_%H%M%S)}"
DOCKER_ARGS="${DOCKER_ARGS:-}"
BUILD="${BUILD:-0}"
COOLDOWN="${COOLDOWN:-5}"
IMG_ROS1="ros1-mapping"
IMG_ROS2="ros2-mapping"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -n "${BAG}" ] || die "set BAG=data/bags/<name>.bag (or the ROS2 bag directory)."
command -v docker >/dev/null 2>&1 || die "docker not found."

BAG="${BAG%/}"
BAG_ABS="$(cd "$(dirname "${BAG}")" 2>/dev/null && pwd)/$(basename "${BAG}")" || die "bag path not found: ${BAG}"
case "${BAG_ABS}" in
  "${REPO_ROOT}"/*) BAG_REL="${BAG_ABS#"${REPO_ROOT}"/}" ;;
  *) die "the bag must be inside the repository (e.g. data/bags/), it is mounted into the containers." ;;
esac
STEM="${BAG_REL%.bag}"
BAG_ID="$(basename "${STEM}")"

read -r -a EXTRA <<< "${DOCKER_ARGS}"

# docker_run <image> [cmd...]; DOCKER_ENV (array) and DOCKER_ARGS are added to every call.
DOCKER_ENV=()
docker_run() {
  local image="$1"; shift
  docker run --rm \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "${REPO_ROOT}:/work" -w /work \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    ${DOCKER_ENV[@]+"${DOCKER_ENV[@]}"} \
    "${image}" "$@"
}

build_if_needed() {
  local image="$1" file="$2"
  if [ "${BUILD}" = "1" ] || ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Building ${image}..."
    docker build -f "${file}" -t "${image}" . || die "failed to build ${image}"
  fi
}

build_if_needed "${IMG_ROS1}" docker/Dockerfile.ros1
build_if_needed "${IMG_ROS2}" docker/Dockerfile.ros2

if [ ! -f "${STEM}.bag" ] && [ -f "${STEM}/metadata.yaml" ]; then
  docker_run "${IMG_ROS2}" ./experiments/convert_bag.sh "${STEM}" || die "conversion to ROS1 failed"
elif [ -f "${STEM}.bag" ] && [ ! -f "${STEM}/metadata.yaml" ]; then
  docker_run "${IMG_ROS2}" ./experiments/convert_bag.sh "${STEM}.bag" || die "conversion to ROS2 failed"
fi
[ -f "${STEM}.bag" ] && [ -f "${STEM}/metadata.yaml" ] || die "need both ${STEM}.bag and ${STEM}/"

docker_run "${IMG_ROS2}" python3 experiments/inspect_bag.py "${STEM}.bag" || die "bag failed validation"

echo
echo "Batch ${RUN_TAG}: ${RUNS} run(s) per stack, ${ALGO}, bag ${BAG_ID} at ${RATE}x"
echo

FAILED=0
run_one() {
  local stack="$1" image
  [ "${stack}" = "ros1" ] && image="${IMG_ROS1}" || image="${IMG_ROS2}"
  echo "=== ${stack} (round ${ROUND}/${RUNS})"
  DOCKER_ENV=(-e "ALGO=${ALGO}" -e "BAG=${STEM}.bag" -e "RATE=${RATE}" -e "SETTLE=${SETTLE}" -e "RUN_TAG=${RUN_TAG}")
  if ! docker_run "${image}" ./experiments/run_"${stack}".sh; then
    echo "!!! ${stack} run failed (round ${ROUND})" >&2
    FAILED=$((FAILED + 1))
  fi
  DOCKER_ENV=()
  sleep "${COOLDOWN}"
}

for ROUND in $(seq 1 "${RUNS}"); do
  if [ $((ROUND % 2)) -eq 1 ]; then
    run_one ros1; run_one ros2
  else
    run_one ros2; run_one ros1
  fi
done

REPORT_DIR="results/reports/${RUN_TAG}"
mkdir -p "${REPORT_DIR}"
echo
docker_run "${IMG_ROS2}" python3 metrics/compare_groups.py --tag "${RUN_TAG}" \
    --markdown "${REPORT_DIR}/report.md" --json "${REPORT_DIR}/report.json" --csv "${REPORT_DIR}/runs.csv"
echo
docker_run "${IMG_ROS2}" python3 metrics/map_quality.py consistency --tag "${RUN_TAG}" \
    --markdown "${REPORT_DIR}/map_consistency.md" --json "${REPORT_DIR}/map_consistency.json" \
  && { echo; cat "${REPORT_DIR}/map_consistency.md"; } >> "${REPORT_DIR}/report.md"

echo
echo "Report: ${REPORT_DIR}/report.md"
[ "${FAILED}" -eq 0 ] || { echo "${FAILED} run(s) failed; they are excluded from the report." >&2; exit 1; }
