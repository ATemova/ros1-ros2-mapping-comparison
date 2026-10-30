#!/usr/bin/env bash
# Package bags, references and (optionally) results into a zip for Zenodo.
#
# Usage: experiments/package_dataset.sh <name> <bag.bag> [<bag.bag> ...]
#   RESULTS_TAG=<run_tag>[,<tag>]   also include those runs' reports and per-run outputs
# Output: data/release/<name>.zip and data/release/<name>.SHA256SUMS
# Contents: bags (ROS1 .bag + ROS2 directory), ground truth / reference maps when present,
# SHA256SUMS, a README.md describing the data, CITATION.cff and the parameter files used.
set -euo pipefail

NAME="${1:?usage: package_dataset.sh <name> <bag.bag> [...]}"; shift
[ "$#" -ge 1 ] || { echo "ERROR: give at least one bag" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT="${REPO_ROOT}/data/release"
STAGE="$(mktemp -d)/${NAME}"
mkdir -p "${STAGE}/bags" "${STAGE}/config" "${OUT}"
trap 'rm -rf "$(dirname "${STAGE}")"' EXIT

for bag in "$@"; do
  stem="${bag%.bag}"; stem="${stem%/}"
  [ -f "${stem}.bag" ] || { echo "ERROR: ${stem}.bag not found" >&2; exit 1; }
  cp "${stem}.bag" "${STAGE}/bags/"
  [ -d "${stem}" ] && cp -r "${stem}" "${STAGE}/bags/"
  for f in "${stem}".groundtruth.tum "${stem}".reference.yaml "${stem}".reference.pgm; do
    [ -f "${f}" ] && cp "${f}" "${STAGE}/bags/"
  done
  python3 "${SCRIPT_DIR}/inspect_bag.py" "${stem}.bag" > "${STAGE}/bags/$(basename "${stem}").info.txt" 2>&1 || true
done

cp "${REPO_ROOT}"/config/*.yaml "${STAGE}/config/"
cp "${REPO_ROOT}/CITATION.cff" "${STAGE}/" 2>/dev/null || true
cp "${REPO_ROOT}/docs/parameter_mapping.md" "${STAGE}/config/" 2>/dev/null || true

if [ -n "${RESULTS_TAG:-}" ]; then
  mkdir -p "${STAGE}/results"
  IFS=',' read -r -a tags <<< "${RESULTS_TAG}"
  for tag in "${tags[@]}"; do
    [ -d "${REPO_ROOT}/results/reports/${tag}" ] && cp -r "${REPO_ROOT}/results/reports/${tag}" "${STAGE}/results/"
    grep -l "\"run_tag\": \"${tag}\"" "${REPO_ROOT}"/results/raw/*/*/run_meta.json 2>/dev/null | while read -r meta; do
      run="$(dirname "${meta}")"
      mkdir -p "${STAGE}/results/raw/$(basename "$(dirname "${run}")")"
      cp -r "${run}" "${STAGE}/results/raw/$(basename "$(dirname "${run}")")/"
    done
  done
fi

COMMIT="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
cat > "${STAGE}/README.md" <<README
# ${NAME}

Recorded sensor data (and optionally results) for the study
"A Practical Comparison of ROS1 and ROS2 Mapping Pipelines on a Real Mobile Robot".

Code: https://github.com/ATemova/ros1-ros2-mapping-comparison (commit ${COMMIT})

## Contents

- \`bags/<name>.bag\`: ROS1 bag (/scan, /odom, /tf, /tf_static), recorded with SLAM stopped
- \`bags/<name>/\`: the same data as a ROS2 bag (rosbag2, sqlite3), converted with rosbags
- \`bags/<name>.groundtruth.tum\`: reference trajectory, when available (TUM format)
- \`bags/<name>.reference.yaml/.pgm\`: reference map / floor plan, when available
- \`bags/<name>.info.txt\`: topics, rates, frames (experiments/inspect_bag.py)
- \`config/\`: SLAM parameters used by both stacks, and the parameter mapping
- \`results/\` (optional): per-run outputs and generated reports
- \`SHA256SUMS\`: checksums of every file

## Reproduce

Copy \`bags/*\` into \`data/bags/\` of the repository at the commit above, then:

    make images
    make matrix BAG=data/bags/<name>.bag

See docs/metrics.md in the repository for metric definitions.
README

SUMS="$(mktemp)"
(cd "${STAGE}" && find . -type f -print0 | sort -z | xargs -0 sha256sum > "${SUMS}")
mv "${SUMS}" "${STAGE}/SHA256SUMS"
rm -f "${OUT}/${NAME}.zip"
(cd "$(dirname "${STAGE}")" && zip -qr "${OUT}/${NAME}.zip" "${NAME}")
cp "${STAGE}/SHA256SUMS" "${OUT}/${NAME}.SHA256SUMS"
echo "${OUT}/${NAME}.zip ($(du -h "${OUT}/${NAME}.zip" | cut -f1))"
echo "sha256: $(sha256sum "${OUT}/${NAME}.zip" | cut -d' ' -f1)"
