#!/usr/bin/env bash
# Repeated, counterbalanced replay runs of several variants in Docker, then statistics.
#
# Usage: BAG=data/bags/<name>.bag ./experiments/run_matrix.sh
#   BAG may be the ROS1 file or the ROS2 directory; the other form is created with
#   experiments/convert_bag.sh when missing. The bag must live inside the repository
#   (it is mounted into the containers). `make matrix` / `make rmw` wrap this script.
#
# Environment:
#   VARIANTS     space-separated list of stack[:distro[:rmw]] (default "ros1 ros2"), e.g.
#                "ros2:humble:fastrtps ros2:humble:cyclonedds ros2:humble:zenoh"
#                "ros2:humble ros2:jazzy"     "ros1 ros2:humble:cyclonedds"
#   RUNS         runs per variant (default 5). Each round rotates the variant order.
#   ALGO         slam_toolbox (default)
#   RATE         bag playback rate (default 1.0); 2, 4 = higher scan/TF rates
#   SETTLE       seconds after the bag ends (default 5)
#   RUN_TAG      label for this batch (default matrix_<timestamp>)
#   CPUS         container CPU quota, e.g. 1.5 (docker --cpus)        } stress conditions,
#   CPU_SET      container CPUs, e.g. 0,1 (docker --cpuset-cpus)       } recorded per run
#   MEMORY       container memory limit, e.g. 2g (docker --memory)     } as `condition`
#   CONDITION    label overriding the derived condition (e.g. "rpi4-like")
#   GROUP_BY     report grouping (default: stack for "ros1 ros2", else variant)
#   BASELINE     baseline group for the report (default: the first variant)
#   DOCKER_ARGS  extra docker run args
#   BUILD        1 = rebuild images first (default: build only if missing)
#   COOLDOWN     seconds between runs (default 5)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

BAG="${BAG:-}"
VARIANTS="${VARIANTS:-ros1 ros2}"
RUNS="${RUNS:-5}"
ALGO="${ALGO:-slam_toolbox}"
RATE="${RATE:-1.0}"
SETTLE="${SETTLE:-5}"
RUN_TAG="${RUN_TAG:-matrix_$(date +%Y%m%d_%H%M%S)}"
CPUS="${CPUS:-}"
CPU_SET="${CPU_SET:-}"
MEMORY="${MEMORY:-}"
CONDITION="${CONDITION:-}"
DOCKER_ARGS="${DOCKER_ARGS:-}"
BUILD="${BUILD:-0}"
COOLDOWN="${COOLDOWN:-5}"
TOOLS_IMAGE="ros2-mapping:humble"

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

# ---------------------------------------------------------------- variants
# parse "stack[:distro[:rmw]]" into V_STACK V_DISTRO V_RMW V_IMAGE V_LABEL
parse_variant() {
  local spec="$1" rest
  V_STACK="${spec%%:*}"
  rest="${spec#"${V_STACK}"}"; rest="${rest#:}"
  V_DISTRO="${rest%%:*}"
  rest="${rest#"${V_DISTRO}"}"; rest="${rest#:}"
  V_RMW="${rest}"
  case "${V_STACK}" in
    ros1)
      [ -n "${V_RMW}" ] && die "variant '${spec}': ROS1 has no RMW choice"
      V_DISTRO="${V_DISTRO:-noetic}"
      V_IMAGE="ros1-mapping:${V_DISTRO}"; V_FILE="docker/Dockerfile.ros1"
      V_LABEL="ros1-${V_DISTRO}"
      ;;
    ros2)
      V_DISTRO="${V_DISTRO:-humble}"
      V_RMW="${V_RMW:-fastrtps}"
      V_IMAGE="ros2-mapping:${V_DISTRO}"; V_FILE="docker/Dockerfile.ros2"
      local short="${V_RMW#rmw_}"; short="${short%_cpp}"
      case "${short}" in fastdds) short=fastrtps ;; cyclone) short=cyclonedds ;; esac
      V_LABEL="ros2-${V_DISTRO}-${short}"
      ;;
    *) die "variant '${spec}': stack must be ros1 or ros2" ;;
  esac
}

read -r -a VARIANT_LIST <<< "${VARIANTS}"
[ "${#VARIANT_LIST[@]}" -ge 1 ] || die "VARIANTS is empty"
for v in "${VARIANT_LIST[@]}"; do parse_variant "${v}"; done

if [ -z "${GROUP_BY:-}" ]; then
  if [ "${VARIANTS}" = "ros1 ros2" ]; then GROUP_BY=stack; else GROUP_BY=variant; fi
fi
if [ -z "${BASELINE:-}" ]; then
  parse_variant "${VARIANT_LIST[0]}"
  case "${GROUP_BY}" in
    variant) BASELINE="${V_LABEL}" ;;
    stack) BASELINE="${V_STACK}" ;;
    ros_distro) BASELINE="${V_DISTRO}" ;;
    rmw) BASELINE="$( [ "${V_STACK}" = ros1 ] && echo tcpros || echo "rmw_${V_LABEL##*-}_cpp")" ;;
    *) BASELINE="" ;;
  esac
fi

# ---------------------------------------------------------------- docker
read -r -a EXTRA <<< "${DOCKER_ARGS}"
LIMITS=()
[ -n "${CPUS}" ] && LIMITS+=(--cpus "${CPUS}")
[ -n "${CPU_SET}" ] && LIMITS+=(--cpuset-cpus "${CPU_SET}")
[ -n "${MEMORY}" ] && LIMITS+=(--memory "${MEMORY}" --memory-swap "${MEMORY}")

GIT_DIRTY=false
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] && GIT_DIRTY=true
fi

# docker_run <image> [cmd...]; DOCKER_ENV (array) is added when set.
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
  local image="$1" file="$2" distro="$3"
  if [ "${BUILD}" = "1" ] || ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Building ${image}..."
    docker build -f "${file}" --build-arg "ROS_DISTRO=${distro}" -t "${image}" . || die "failed to build ${image}"
  fi
}

build_if_needed "${TOOLS_IMAGE}" docker/Dockerfile.ros2 humble
for v in "${VARIANT_LIST[@]}"; do
  parse_variant "${v}"
  build_if_needed "${V_IMAGE}" "${V_FILE}" "${V_DISTRO}"
done

if [ ! -f "${STEM}.bag" ] && [ -f "${STEM}/metadata.yaml" ]; then
  docker_run "${TOOLS_IMAGE}" ./experiments/convert_bag.sh "${STEM}" || die "conversion to ROS1 failed"
elif [ -f "${STEM}.bag" ] && [ ! -f "${STEM}/metadata.yaml" ]; then
  docker_run "${TOOLS_IMAGE}" ./experiments/convert_bag.sh "${STEM}.bag" || die "conversion to ROS2 failed"
fi
[ -f "${STEM}.bag" ] && [ -f "${STEM}/metadata.yaml" ] || die "need both ${STEM}.bag and ${STEM}/"

docker_run "${TOOLS_IMAGE}" python3 experiments/inspect_bag.py "${STEM}.bag" || die "bag failed validation"

echo
echo "Batch ${RUN_TAG}: ${RUNS} run(s) x [${VARIANTS}], ${ALGO}, bag ${BAG_ID} at ${RATE}x"
[ "${#LIMITS[@]}" -gt 0 ] && echo "Limits: ${LIMITS[*]}"
echo

FAILED=0
run_one() {
  parse_variant "$1"
  local image_id
  image_id="$(docker image inspect -f '{{.Id}}' "${V_IMAGE}" 2>/dev/null)"
  echo "=== ${V_LABEL} (round ${ROUND}/${RUNS})"
  DOCKER_ENV=(-e "ALGO=${ALGO}" -e "BAG=${STEM}.bag" -e "RATE=${RATE}" -e "SETTLE=${SETTLE}"
              -e "RUN_TAG=${RUN_TAG}" -e "IMAGE_TAG=${V_IMAGE}" -e "IMAGE_ID=${image_id}"
              -e "GIT_DIRTY=${GIT_DIRTY}" ${LIMITS[@]+"${LIMITS[@]}"})
  [ "${V_STACK}" = "ros2" ] && DOCKER_ENV+=(-e "RMW=${V_RMW}")
  [ -n "${CONDITION}" ] && DOCKER_ENV+=(-e "CONDITION=${CONDITION}")
  if ! docker_run "${V_IMAGE}" ./experiments/run_"${V_STACK}".sh; then
    echo "!!! ${V_LABEL} run failed (round ${ROUND})" >&2
    FAILED=$((FAILED + 1))
  fi
  DOCKER_ENV=()
  sleep "${COOLDOWN}"
}

K="${#VARIANT_LIST[@]}"
for ROUND in $(seq 1 "${RUNS}"); do
  # rotate the order every round so no variant always runs first (or last)
  for j in $(seq 0 $((K - 1))); do
    run_one "${VARIANT_LIST[$(( (j + ROUND - 1) % K ))]}"
  done
done

REPORT_DIR="results/reports/${RUN_TAG}"
mkdir -p "${REPORT_DIR}"
echo
REPORT_ARGS=(--tag "${RUN_TAG}" --group-by "${GROUP_BY}")
[ -n "${BASELINE}" ] && REPORT_ARGS+=(--baseline "${BASELINE}")
docker_run "${TOOLS_IMAGE}" python3 metrics/make_report.py "${REPORT_ARGS[@]}" \
    --out "${REPORT_DIR}" --latest results/report.md \
  || echo "WARNING: report generation failed; raw results are in results/raw/" >&2

echo
echo "Report: ${REPORT_DIR}/report.md (also results/report.md)"
[ "${FAILED}" -eq 0 ] || { echo "${FAILED} run(s) failed; they are excluded from the report." >&2; exit 1; }
