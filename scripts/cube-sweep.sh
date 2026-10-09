#!/usr/bin/env bash
set -euo pipefail

# Run the cube_peak MMAD sweep for one architecture + dtype.
#
# The CA-model simulator models the full multi-AIC chip by default, so each run
# is slow.  This patches config_stars.json to a single AIC (num_aic=1) inside a
# throwaway root container, runs the sweep there, and chowns the output back to
# the host user.  The image is immutable, so the patch is automatically "reset"
# by every fresh container -- there is nothing to restore.
#
# Usage:
#   scripts/cube-sweep.sh <dav-2201|dav-3510> <half|float|int8|bf16> [--limit N] ...
#
# Extra arguments are forwarded to scripts/cube_sweep.py (e.g. --limit, --workers).

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

arch="${1:?usage: cube-sweep.sh <dav-2201|dav-3510> <dtype> [extra...]}"
dtype="${2:?usage: cube-sweep.sh <arch> <dtype> [extra...]}"
shift 2 || true

case "${arch}" in
    dav-2201|2201) s=2201 ;;
    dav-3510|3510) s=3510 ;;
    *) printf 'unknown arch: %s (want dav-2201 or dav-3510)\n' "${arch}" >&2; exit 1 ;;
esac

case "${dtype}" in
    half|float|int8|bf16) ;;
    *) printf 'unknown dtype: %s (want half|float|int8|bf16)\n' "${dtype}" >&2; exit 1 ;;
esac

# Forward extra args to the inner python with shell-safe quoting.
extra=()
for a in "$@"; do
    extra+=("$(printf '%q' "$a")")
done

host_uid="$(id -u)"
host_gid="$(id -g)"

docker run --rm \
    --user 0:0 \
    --volume "${root}:/workspace" \
    --workdir /workspace \
    "ascendc-low-level:${CANN_VERSION}" bash -lc "
set -e
cfg=\"\${ASCEND_HOME_PATH}/tools/simulator/dav_${s}/lib/config_stars.json\"
python3 - \"\$cfg\" <<'PY'
import json, sys
cfg = sys.argv[1]
d = json.load(open(cfg))
d['model_top']['num_aic'] = 1
d['model_top']['num_aiv'] = 2
json.dump(d, open(cfg, 'w'), indent=2)
print('patched', cfg, '-> num_aic=1 num_aiv=2')
PY
python3 scripts/cube_sweep.py --arch ${s} --dtype ${dtype} ${extra[*]}
chown -R ${host_uid}:${host_gid} /workspace/out/cube-sweep 2>/dev/null || true
"
