#!/bin/bash
set -euo pipefail
umask 077

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup

test "$(id -un)" = pb23030683
test -L "$root/current"
test -f "$project/deploy/107cup/service.slurm"
test -f "$project/deploy/107cup/service_recovery.py"

exec /usr/bin/python3 "$project/deploy/107cup/service_recovery.py" recover
