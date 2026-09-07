#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

if (( $# == 0 )); then
    set -- bash
fi

terminal=()
if [[ -t 0 && -t 1 ]]; then
    terminal=(-it)
fi

docker run --rm "${terminal[@]}" \
    --user "$(id -u):$(id -g)" \
    --volume "${root}:/workspace" \
    --workdir /workspace \
    "ascendc-low-level:${CANN_VERSION}" "$@"
