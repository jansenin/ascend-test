#!/usr/bin/env bash
set -euo pipefail

# Keep CANN's version-specific environment setup authoritative.
set +u
source /usr/local/Ascend/cann/set_env.sh
set -u
mkdir -p "${ASCEND_CACHE_PATH}"
exec "$@"
