#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
binary="${1:-}"
if [[ -z "${binary}" || ! -f "${binary}" ]]; then
    printf 'Usage: %s path/to/executable\n' "$0" >&2
    exit 2
fi

output="${2:-${root}/out/device-elf/$(basename "${binary}")}"
mkdir -p "${output}"
msobjdump --list-elf "${binary}"
msobjdump --dump-elf "${binary}" --verbose
msobjdump --extract-elf "${binary}" --out-dir "${output}"
printf 'Extracted device ELF files: %s\n' "${output}"
