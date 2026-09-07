#!/usr/bin/env bash
set -euo pipefail

binary="${1:-}"
if [[ -z "${binary}" || ! -x "${binary}" ]]; then
    printf 'Usage: %s path/to/npu-executable [msprof options...]\n' "$0" >&2
    exit 2
fi
shift
if [[ ! -e /dev/davinci_manager ]]; then
    printf '%s\n' 'Real-device profiling requires an Ascend NPU and mounted driver devices.' >&2
    exit 1
fi
exec msprof op "$@" "${binary}"
