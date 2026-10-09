#!/usr/bin/env bash
# Run the full cube_peak MMAD sweep: all dtypes x both architectures, sequentially.
# Each combo runs in its own throwaway root container (config patched to 1 AIC).
# Progress is appended to out/cube-sweep/sweep.log and per-combo CSVs.
#
# Usage: scripts/cube-sweep-all.sh   (launch under nohup for a long run)
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log="${root}/out/cube-sweep/sweep.log"
mkdir -p "${root}/out/cube-sweep"

for arch in dav-2201 dav-3510; do
    for dtype in half float int8 bf16; do
        stamp="$(date -u +%FT%TZ)"
        printf '=== %s START %s %s ===\n' "${stamp}" "${arch}" "${dtype}" | tee -a "${log}"
        if "${root}/scripts/cube-sweep.sh" "${arch}" "${dtype}" >> "${log}" 2>&1; then
            printf '=== %s DONE  %s %s ===\n' "$(date -u +%FT%TZ)" "${arch}" "${dtype}" | tee -a "${log}"
        else
            printf '=== %s FAIL  %s %s (exit %d) ===\n' "$(date -u +%FT%TZ)" "${arch}" "${dtype}" "$?" | tee -a "${log}"
        fi
    done
done

printf 'ALL SWEEPS DONE %s\n' "$(date -u +%FT%TZ)" | tee -a "${log}"
