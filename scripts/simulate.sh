#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
arch="${1:-}"
target="${2:-add_mmad_add}"
if [[ ! "${arch}" =~ ^(dav-2201|dav-3510)$ ]]; then
    printf 'Usage: %s {dav-2201|dav-3510} [vector_add|direct_mmad|add_mmad_add]\n' "$0" >&2
    exit 2
fi

if [[ "${arch}" == "dav-2201" ]]; then
    default_soc=Ascend910B1
else
    default_soc=Ascend950PR_9599
fi
soc="${SOC_VERSION:-${default_soc}}"
"${root}/scripts/build.sh" sim "${arch}"
output="${root}/out/simulator/${arch#dav-}/${target}-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${output}"
env -u ASCEND_DUMP_PATH -u ASCEND_WORK_PATH \
    msprof op simulator --soc-version="${soc}" --output="${output}" \
    "${root}/build/sim-${arch#dav-}/${target}"

shopt -s nullglob globstar
traces=("${output}"/**/trace.json)
if (( ${#traces[@]} == 0 )); then
    printf 'msprof generated no trace.json under %s\n' "${output}" >&2
    exit 1
fi
printf 'Simulator artifacts: %s\n' "${output}"
printf '%s\n' 'Load trace.json in chrome://tracing; visualize_data.bin requires MindStudio Insight.'
