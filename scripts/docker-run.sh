#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

gui=auto
case "${1:-}" in
    --gui)
        gui=yes
        shift
        ;;
    --no-gui)
        gui=no
        shift
        ;;
esac

if (( $# == 0 )); then
    set -- bash
fi

terminal=()
if [[ -t 0 && -t 1 ]]; then
    terminal=(-it)
fi

display=()
if [[ "${gui}" != no ]]; then
    if [[ -n "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
        display+=(--env "DISPLAY=${DISPLAY}")
        display+=(--env QT_X11_NO_MITSHM=1)
        display+=(--volume /tmp/.X11-unix:/tmp/.X11-unix:ro)

        xauthority="${XAUTHORITY:-${HOME}/.Xauthority}"
        if [[ -r "${xauthority}" ]]; then
            display+=(--env XAUTHORITY=/tmp/ascendc.xauth)
            display+=(--volume "${xauthority}:/tmp/ascendc.xauth:ro")
        elif [[ "${gui}" == yes ]]; then
            printf '%s\n' 'Warning: no readable Xauthority file; X11 may require host access configuration.' >&2
        fi
    fi

    if [[ -n "${WAYLAND_DISPLAY:-}" && -n "${XDG_RUNTIME_DIR:-}" && \
          -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
        display+=(--env "WAYLAND_DISPLAY=${WAYLAND_DISPLAY}")
        display+=(--env XDG_RUNTIME_DIR=/tmp/ascendc-runtime)
        display+=(--mount "type=bind,source=${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY},target=/tmp/ascendc-runtime/${WAYLAND_DISPLAY}")
    fi

    if [[ "${gui}" == yes && ${#display[@]} -eq 0 ]]; then
        printf '%s\n' 'No usable X11 or Wayland display was detected on the host.' >&2
        exit 1
    fi
fi

docker run --rm "${terminal[@]}" \
    --user "$(id -u):$(id -g)" \
    "${display[@]}" \
    --volume "${root}:/workspace" \
    --workdir /workspace \
    "ascendc-low-level:${CANN_VERSION}" "$@"
