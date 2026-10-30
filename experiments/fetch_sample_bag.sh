#!/usr/bin/env bash
# Download the sample bag (a GitHub release asset or any URL) into data/bags/ and verify it.
#
# Usage: experiments/fetch_sample_bag.sh [URL] [SHA256]
#   Defaults: SAMPLE_BAG_URL / SAMPLE_BAG_SHA256 (CI sets them from repository variables).
#   The asset may be a .bag, or a .zip / .tar.gz holding sample.bag plus its companions
#   (sample.groundtruth.tum, sample.reference.yaml/.pgm). See docs/dataset.md.
set -euo pipefail

URL="${1:-${SAMPLE_BAG_URL:-}}"
SHA="${2:-${SAMPLE_BAG_SHA256:-}}"
[ -n "${URL}" ] || { echo "ERROR: no URL (argument or SAMPLE_BAG_URL)" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SCRIPT_DIR}/../data/bags"
mkdir -p "${DEST}"
NAME="$(basename "${URL%%\?*}")"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

echo "Downloading ${URL}"
curl -fL --retry 3 -o "${TMP}/${NAME}" "${URL}"

if [ -n "${SHA}" ]; then
  echo "${SHA}  ${TMP}/${NAME}" | sha256sum -c - || { echo "ERROR: checksum mismatch" >&2; exit 1; }
else
  echo "WARNING: no SHA256 given; not verified. sha256: $(sha256sum "${TMP}/${NAME}" | cut -d' ' -f1)" >&2
fi

case "${NAME}" in
  *.zip) unzip -o -q "${TMP}/${NAME}" -d "${DEST}" ;;
  *.tar.gz|*.tgz) tar -xzf "${TMP}/${NAME}" -C "${DEST}" ;;
  *.bag) cp "${TMP}/${NAME}" "${DEST}/sample.bag" ;;
  *) echo "ERROR: unsupported asset type: ${NAME}" >&2; exit 1 ;;
esac
[ -f "${DEST}/sample.bag" ] || { echo "ERROR: no sample.bag after extracting ${NAME}" >&2; exit 1; }
echo "Sample bag ready: data/bags/sample.bag"
