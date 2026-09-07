#!/usr/bin/env bash
set -euo pipefail

tool="${1:-}"
binary="${2:-}"
if [[ ! "${tool}" =~ ^(memcheck|racecheck|initcheck|synccheck)$ || -z "${binary}" || ! -x "${binary}" ]]; then
    printf 'Usage: %s {memcheck|racecheck|initcheck|synccheck} path/to/instrumented-executable\n' "$0" >&2
    exit 2
fi
if [[ ! -e /dev/davinci_manager ]]; then
    printf '%s\n' 'msSanitizer requires an Ascend NPU and mounted driver devices; CPU/simulator mode is unsupported.' >&2
    exit 1
fi
exec mssanitizer --tool="${tool}" "${binary}"
