#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-}"
arch="${2:-}"

if [[ ! "${mode}" =~ ^(cpu|sim|npu)$ || ! "${arch}" =~ ^(dav-2201|dav-3510)$ ]]; then
    printf 'Usage: %s {cpu|sim|npu} {dav-2201|dav-3510} [additional CMake arguments...]\n' "$0" >&2
    exit 2
fi
shift 2

build_dir="${root}/build/${mode}-${arch#dav-}"
cmake -S "${root}" -B "${build_dir}" -G Ninja \
    -DCMAKE_ASC_RUN_MODE="${mode}" \
    -DCMAKE_ASC_ARCHITECTURES="${arch}" \
    -DCMAKE_BUILD_TYPE=Release \
    "$@"
cmake --build "${build_dir}" --parallel
printf 'Built %s + %s in %s\n' "${mode}" "${arch}" "${build_dir}"
