#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
arch="${1:-}"
target="${2:-add_mmad_add}"
if [[ ! "${arch}" =~ ^(dav-2201|dav-3510)$ ]]; then
    printf 'Usage: %s {dav-2201|dav-3510} [target]\n' "$0" >&2
    printf '  SIMD: vector_add direct_mmad add_mmad_add arith_simd gather_simd scatter_simd\n' >&2
    printf '        arith_simd_half gather_simd_half scatter_simd_half\n' >&2
    printf '  SIMT: simt_add arith_simt gather_simt scatter_simt (dav-3510 only)\n' >&2
    printf '        arith_simt_half gather_simt_half scatter_simt_half\n' >&2
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
    case "${target}" in
        simt_add|arith_simt|gather_simt|scatter_simt|arith_simt_half|gather_simt_half|scatter_simt_half)
            printf '%s\n' 'SIMT kernels are not profiled by msprof op simulator (empty output).' >&2
            printf '%s\n' 'Run the sim binary directly to emit core*.veccore*.instr_log.dump instead.' >&2
            ;;
    esac
    exit 1
fi
printf 'Simulator artifacts: %s\n' "${output}"
printf '%s\n' 'Load trace.json in chrome://tracing; visualize_data.bin requires MindStudio Insight.'
