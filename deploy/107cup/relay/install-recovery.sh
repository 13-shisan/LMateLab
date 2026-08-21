#!/bin/bash
set -euo pipefail
umask 077

test "$(id -un)" = Pwjb

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config=/home/Pwjb/.config/lmatelab-107cup-proxy
bin="$config/bin"
state="$config/state"
log="$config/log"
cron_begin='# BEGIN LMATELAB 107CUP RELAY RECOVERY'
cron_end='# END LMATELAB 107CUP RELAY RECOVERY'

for source in ensure_forward.py ensure-forward.sh reauth-control-master.sh; do
  test -f "$source_dir/$source"
done
test -f "$config/conf/nginx.conf"

mkdir -p "$bin" "$state" "$log"
chmod 700 "$config" "$bin" "$state" "$log"
install -m 700 "$source_dir/ensure_forward.py" "$bin/ensure_forward.py"
install -m 700 "$source_dir/ensure-forward.sh" "$bin/ensure-forward.sh"
install -m 700 "$source_dir/reauth-control-master.sh" "$bin/reauth-control-master.sh"
/usr/bin/python3 "$bin/ensure_forward.py" --adopt-current

current=$(mktemp)
updated=$(mktemp)
cleanup() {
  rm -f -- "$current" "$updated"
}
trap cleanup EXIT INT TERM

crontab -l > "$current" 2>/dev/null || :
awk -v begin="$cron_begin" -v end="$cron_end" '
  $0 == begin {
    if (inside || seen_begin) exit 40
    inside = 1
    seen_begin = 1
    next
  }
  $0 == end {
    if (!inside || seen_end) exit 41
    inside = 0
    seen_end = 1
    next
  }
  END {
    if (inside || seen_begin != seen_end) exit 42
  }
' "$current"
awk -v begin="$cron_begin" -v end="$cron_end" '
  $0 == begin { skipping = 1; next }
  $0 == end { skipping = 0; next }
  !skipping { print }
' "$current" > "$updated"
cat >> "$updated" <<'CRON'
# BEGIN LMATELAB 107CUP RELAY RECOVERY
@reboot umask 077; /bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh >> /home/Pwjb/.config/lmatelab-107cup-proxy/log/recovery.log 2>&1
* * * * * umask 077; /bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh >> /home/Pwjb/.config/lmatelab-107cup-proxy/log/recovery.log 2>&1
# END LMATELAB 107CUP RELAY RECOVERY
CRON

crontab "$updated"
printf 'relay recovery installed; reauthenticate with %s\n' \
  "$bin/reauth-control-master.sh"
