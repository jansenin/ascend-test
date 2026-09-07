#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
arch="${1:-}"
target="${2:-add_mmad_add}"
if [[ ! "${arch}" =~ ^(dav-2201|dav-3510)$ ]]; then
    printf 'Usage: %s {dav-2201|dav-3510} [vector_add|direct_mmad|add_mmad_add]\n' "$0" >&2
    exit 2
fi

"${root}/scripts/build.sh" cpu "${arch}"
exec gdb -ex "set follow-fork-mode child" --args "${root}/build/cpu-${arch#dav-}/${target}"
