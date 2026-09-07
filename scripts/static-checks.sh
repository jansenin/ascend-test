#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash -n "${root}"/scripts/*.sh "${root}/docker/entrypoint.sh"
if command -v shellcheck >/dev/null; then
    shellcheck "${root}"/scripts/*.sh "${root}/docker/entrypoint.sh"
fi
if grep -R -E 'AscendC::Matmul|IterateAll|REGIST_MATMUL_OBJ' "${root}/apps" "${root}/include"; then
    printf '%s\n' 'Forbidden high-level Matmul API found.' >&2
    exit 1
fi
grep -q 'AscendC::Mmad' "${root}/include/device_kernels.h"
grep -q '__mix__(1, 2)' "${root}/include/device_kernels.h"
grep -q 'AscendC::Reg::Add' "${root}/include/device_kernels.h"
grep -q 'AscendC::Add' "${root}/include/device_kernels.h"
printf '%s\n' 'Static checks passed.'
