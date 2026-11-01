#!/usr/bin/env bash
# Build one experiment image for the host architecture.
#
# Usage: docker/build.sh <ros1|ros2> <distro> [extra docker build args]
#   ros1 noetic -> ros1-mapping:noetic     ros2 humble -> ros2-mapping:humble
# The base image is pinned by digest when docker/base-images.lock has an entry for it
# (create or refresh with `make lock`); otherwise the moving tag (ros:<distro>) is used.
set -euo pipefail

STACK="${1:?usage: docker/build.sh <ros1|ros2> <distro>}"
DISTRO="${2:?usage: docker/build.sh <ros1|ros2> <distro>}"
shift 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

case "${STACK}" in
  ros1) FILE=docker/Dockerfile.ros1 ;;
  ros2) FILE=docker/Dockerfile.ros2 ;;
  *) echo "ERROR: stack must be ros1 or ros2" >&2; exit 1 ;;
esac

BASE="ros:${DISTRO}"
PINNED="$("${SCRIPT_DIR}/lock.sh" resolve "${BASE}")"
if [ "${PINNED}" = "${BASE}" ]; then
  echo "Base ${BASE} (not pinned; run 'make lock' to pin by digest)"
else
  echo "Base ${PINNED}"
fi

docker build -f "${FILE}" \
  --build-arg "ROS_DISTRO=${DISTRO}" \
  --build-arg "BASE_IMAGE=${PINNED}" \
  -t "${STACK}-mapping:${DISTRO}" "$@" .
