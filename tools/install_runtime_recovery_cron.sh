#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CANONICAL_PROJECT_DIR="$(cd "${LMATELAB_PROJECT_DIR:-/home/software/LMateLab}" && pwd -P)"

if [[ "$SCRIPT_PROJECT_DIR" != "$CANONICAL_PROJECT_DIR" ]]; then
    echo "install_runtime_recovery_cron.sh must run from canonical production checkout: $CANONICAL_PROJECT_DIR" >&2
    exit 2
fi

PROJECT_DIR="$CANONICAL_PROJECT_DIR"
RECOVERY_SCRIPT="$PROJECT_DIR/tools/ensure_runtime_running.sh"
LOG_DIR="${LMATELAB_RUNTIME_LOG_DIR:-$PROJECT_DIR/var/log}"
LOG_FILE="$LOG_DIR/runtime-recovery.log"
CRONTAB_BIN="${LMATELAB_CRONTAB_BIN:-crontab}"
BEGIN_MARKER="# BEGIN LMATELAB RUNTIME RECOVERY"
END_MARKER="# END LMATELAB RUNTIME RECOVERY"
LEGACY_BEGIN_MARKER="# BEGIN LMATELAB NGINX RECOVERY"
LEGACY_END_MARKER="# END LMATELAB NGINX RECOVERY"

if [[ ! -f "$RECOVERY_SCRIPT" ]]; then
    echo "recovery script is missing: $RECOVERY_SCRIPT" >&2
    exit 2
fi
if ! command -v "$CRONTAB_BIN" >/dev/null 2>&1; then
    echo "crontab command is unavailable: $CRONTAB_BIN" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"
existing_file="$(mktemp)"
cleaned_file="$(mktemp)"
new_file="$(mktemp)"
error_file="$(mktemp)"
trap 'rm -f "$existing_file" "$cleaned_file" "$new_file" "$error_file"' EXIT

set +e
"$CRONTAB_BIN" -l >"$existing_file" 2>"$error_file"
read_status=$?
set -e
if ((read_status != 0)); then
    if grep -qi "no crontab" "$error_file"; then
        : >"$existing_file"
    else
        cat "$error_file" >&2
        exit "$read_status"
    fi
fi

awk \
    -v begin="$BEGIN_MARKER" \
    -v end="$END_MARKER" \
    -v legacy_begin="$LEGACY_BEGIN_MARKER" \
    -v legacy_end="$LEGACY_END_MARKER" '
    $0 == begin || $0 == legacy_begin {
        if (managed) {
            failure = 42
            exit
        }
        managed = 1
        expected_end = ($0 == begin ? end : legacy_end)
        next
    }
    $0 == end || $0 == legacy_end {
        if (!managed || $0 != expected_end) {
            failure = 43
            exit
        }
        managed = 0
        expected_end = ""
        next
    }
    !managed { lines[++line_count] = $0 }
    END {
        if (failure) exit failure
        if (managed) exit 44
        while (line_count > 0 && lines[line_count] == "") line_count--
        for (line_number = 1; line_number <= line_count; line_number++) {
            print lines[line_number]
        }
    }
' "$existing_file" >"$cleaned_file"

printf -v recovery_script_q '%q' "$RECOVERY_SCRIPT"
printf -v log_file_q '%q' "$LOG_FILE"
{
    cat "$cleaned_file"
    if [[ -s "$cleaned_file" ]]; then
        printf '\n'
    fi
    printf '%s\n' "$BEGIN_MARKER"
    printf '@reboot umask 077; /bin/bash %s >> %s 2>&1\n' "$recovery_script_q" "$log_file_q"
    printf '*/5 * * * * umask 077; /bin/bash %s >> %s 2>&1\n' "$recovery_script_q" "$log_file_q"
    printf '%s\n' "$END_MARKER"
} >"$new_file"

"$CRONTAB_BIN" "$new_file"
echo "production runtime recovery cron installed; log=$LOG_FILE"
