#!/usr/bin/env bash
# Generate a single-core msprof simulator trace for cube_peak at a given size.
#
# The sweep runs cube_peak directly (no msprof), so it produces no trace.json.
# This script runs one size through `msprof op simulator` with the config patched
# to a single AIC (fast, clean timeline) and writes the artifacts under
# out/simulator/<arch>/cube_peak-<M>x<K>x<N>-<dtype>-<ts>/.
#
# Usage: scripts/cube-trace.sh [dav-2201|dav-3510] [M] [K] [N] [dtype]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${root}/dependencies.lock"

arch="${1:-dav-3510}"
M="${2:-256}"
K="${3:-64}"
N="${4:-256}"
dtype="${5:-half}"

case "${arch}" in
    dav-2201) s=2201; soc=Ascend910B1 ;;
    dav-3510) s=3510; soc=Ascend950PR_9599 ;;
    *) printf 'usage: %s <dav-2201|dav-3510> <M> <K> <N> [dtype]\n' "$0" >&2; exit 2 ;;
esac

ts="$(date -u +%Y%m%dT%H%M%SZ)"
out="/workspace/out/simulator/${s}/cube_peak-${M}x${K}x${N}-${dtype}-${ts}"
host_uid="$(id -u)"
host_gid="$(id -g)"

docker run --rm --user 0:0 -v "${root}:/workspace" -w /workspace \
    "ascendc-low-level:${CANN_VERSION}" bash -lc "
set -e
cfg=\"\${ASCEND_HOME_PATH}/tools/simulator/dav_${s}/lib/config_stars.json\"
python3 - \"\$cfg\" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d['model_top']['num_aic'] = 1; d['model_top']['num_aiv'] = 2
json.dump(d, open(sys.argv[1], 'w'), indent=2)
PY
env -u ASCEND_DUMP_PATH -u ASCEND_WORK_PATH \
    msprof op simulator --soc-version=${soc} --output=${out} \
    /workspace/build/sim-${s}/cube_peak ${M} ${K} ${N} ${dtype}
chown -R ${host_uid}:${host_gid} ${out} 2>/dev/null || true
"

printf 'Trace dir: %s\n' "${root}/out/simulator/${s}/cube_peak-${M}x${K}x${N}-${dtype}-${ts}"
printf '%s\n' '  trace.json -> chrome://tracing ; visualize_data.bin -> MindStudio Insight'
