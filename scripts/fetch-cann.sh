#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

if [[ "${1:-}" != "--accept-license" ]]; then
    printf '%s\n' "Usage: $0 --accept-license" >&2
    printf '%s\n' "Review the CANN Software User License Agreement 2.0 before downloading:" >&2
    printf '%s\n' "https://www.hiascend.com/legal/cannua-download?isNewCon=true" >&2
    exit 2
fi

destination="${root}/downloads/${CANN_INSTALLER}"
mkdir -p "${root}/downloads"
if [[ -f "${destination}" ]]; then
    printf '%s  %s\n' "${CANN_SHA256}" "${destination}" | sha256sum -c -
    printf 'Already present: %s\n' "${destination}"
    exit 0
fi

temporary="${destination}.partial"
trap 'rm -f "${temporary}"' EXIT
curl --fail --location --continue-at - --output "${temporary}" "${CANN_URL}"
printf '%s  %s\n' "${CANN_SHA256}" "${temporary}" | sha256sum -c -
mv "${temporary}" "${destination}"
trap - EXIT
printf 'Downloaded and verified: %s\n' "${destination}"
