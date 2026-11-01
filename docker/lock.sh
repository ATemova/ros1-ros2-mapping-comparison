#!/usr/bin/env bash
# Pin base images by digest.
#
#   docker/lock.sh update [ros:noetic ros:humble ros:jazzy]   write docker/base-images.lock
#   docker/lock.sh resolve ros:humble                          print the pinned reference
#                                                              (or the tag when not locked)
# The lock stores the multi-arch index digest, so one entry pins amd64 and arm64.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="${SCRIPT_DIR}/base-images.lock"
DEFAULT_BASES="ros:noetic ros:humble ros:jazzy"

index_digest() {
  local ref="$1" d=""
  if docker buildx version >/dev/null 2>&1; then
    d="$(docker buildx imagetools inspect "${ref}" --format '{{json .Manifest}}' 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["digest"])' 2>/dev/null || true)"
  fi
  if [ -z "${d}" ]; then
    docker pull -q "${ref}" >/dev/null
    d="$(docker image inspect -f '{{range .RepoDigests}}{{println .}}{{end}}' "${ref}" | head -1 | cut -d@ -f2)"
  fi
  [ -n "${d}" ] || { echo "ERROR: could not resolve a digest for ${ref}" >&2; return 1; }
  echo "${d}"
}

case "${1:-}" in
  resolve)
    ref="${2:?usage: lock.sh resolve <image:tag>}"
    if [ -f "${LOCK}" ]; then
      pinned="$(awk -v r="${ref}" '$1 == r {print $2; exit}' "${LOCK}")"
      [ -n "${pinned}" ] && { echo "${ref}@${pinned}"; exit 0; }
    fi
    echo "${ref}"
    ;;
  update)
    shift
    bases="${*:-${DEFAULT_BASES}}"
    tmp="$(mktemp)"
    {
      echo "# Base images pinned by multi-arch index digest. Refresh: make lock"
      echo "# Updated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      for ref in ${bases}; do
        echo "${ref} $(index_digest "${ref}")"
      done
    } > "${tmp}"
    mv "${tmp}" "${LOCK}"
    cat "${LOCK}"
    ;;
  *)
    echo "usage: lock.sh update [refs...] | lock.sh resolve <ref>" >&2
    exit 1
    ;;
esac
