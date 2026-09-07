#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

if [[ "${1:-}" != "--accept-eula" ]]; then
    printf '%s\n' "Usage: $0 --accept-eula" >&2
    printf '%s\n' "The flag confirms acceptance of CANN Software User License Agreement 2.0." >&2
    exit 2
fi

installer="${root}/downloads/${CANN_INSTALLER}"
if [[ ! -f "${installer}" ]]; then
    printf 'Missing %s; run ./scripts/fetch-cann.sh --accept-license first.\n' "${installer}" >&2
    exit 1
fi
printf '%s  %s\n' "${CANN_SHA256}" "${installer}" | sha256sum -c -

docker build \
    --file "${root}/docker/Dockerfile" \
    --build-arg "BASE_IMAGE=${UBUNTU_IMAGE}" \
    --build-arg "CANN_INSTALLER=${CANN_INSTALLER}" \
    --build-arg "CANN_SHA256=${CANN_SHA256}" \
    --build-arg ACCEPT_CANN_EULA=yes \
    --tag "ascendc-low-level:${CANN_VERSION}" \
    "${root}"
