#!/bin/bash
set -euo pipefail
umask 077

socket=/home/Pwjb/.ssh/cm-107cup
key=/home/Pwjb/.ssh/id_ed25519_107cup
remote=pb23030683@107.ustc.edu.cn
recovery=/home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh

test "$(id -un)" = Pwjb
test -f "$key"
test -x "$recovery"

if ! /usr/bin/ssh -S "$socket" -O check "$remote" >/dev/null 2>&1; then
  if test -e "$socket" || test -L "$socket"; then
    test -S "$socket"
    unlink -- "$socket"
  fi
  /usr/bin/ssh -MNf \
    -S "$socket" \
    -o ControlPersist=96h \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o IdentitiesOnly=yes \
    -i "$key" \
    "$remote"
fi

test -S "$socket"
chmod 600 "$socket"
exec /bin/bash "$recovery"
