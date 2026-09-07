#!/usr/bin/env bash
set -euo pipefail

printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-unset}"
for command in bisheng cmake msobjdump msprof mssanitizer; do
    if path="$(command -v "${command}" 2>/dev/null)"; then
        printf '%-12s %s\n' "${command}" "${path}"
    else
        printf '%-12s %s\n' "${command}" missing
    fi
done

if [[ -n "${ASCEND_HOME_PATH:-}" ]]; then
    for model in dav_2201 dav_3510 Ascend910B1 Ascend950PR_9599; do
        [[ -d "${ASCEND_HOME_PATH}/tools/simulator/${model}" ]] && printf 'simulator    %s\n' "${model}"
    done
fi
