#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-}"
arch="${2:-}"

if [[ ! "${mode}" =~ ^(cpu|sim|npu)$ || ! "${arch}" =~ ^(dav-2201|dav-3510)$ ]]; then
    printf 'Usage: %s {cpu|sim|npu} {dav-2201|dav-3510}\n' "$0" >&2
    exit 2
fi

"${root}/scripts/build.sh" "${mode}" "${arch}"
ctest --test-dir "${root}/build/${mode}-${arch#dav-}" --output-on-failure
