#!/usr/bin/env bash
set -euo pipefail

directory="${1:-}"
if [[ -z "${directory}" || ! -d "${directory}" ]]; then
    printf 'Usage: %s simulator-output-directory\n' "$0" >&2
    exit 2
fi

mapfile -d '' files < <(find "${directory}" -type f -name '*_instr_exe.csv' -print0)
if (( ${#files[@]} == 0 )); then
    printf 'No *_instr_exe.csv files found under %s\n' "${directory}" >&2
    exit 1
fi
printf '%s\n' "${files[@]}"
printf '%s\n' 'These CSVs are the supported AI Core instruction view; import visualize_data.bin for source correlation.'
