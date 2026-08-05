#!/bin/bash
set -euo pipefail

root=/home/scc/pb23030683/lmatelab-107cup
job_id=$(<"$root/runtime/service-job-id")
node=$(<"$root/runtime/service-node")
port=$(<"$root/runtime/service-port")

squeue -j "$job_id" -o '%.18i %.12P %.20j %.10T %.12M %R'
sacct -j "$job_id" --format=JobID,State,ExitCode,Elapsed,NodeList

curl --fail --silent --show-error "http://$node:$port/api/health/live"
printf '\n'
curl --fail --silent --show-error "http://$node:$port/api/health/ready"
printf '\n'

for database in "$root/data/db/eln.db" "$root/data/db/digests.db"; do
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$database" 'PRAGMA integrity_check;'
  else
    python3 -c 'import sqlite3, sys; connection=sqlite3.connect(sys.argv[1]); print(connection.execute("PRAGMA integrity_check").fetchone()[0]); connection.close()' "$database"
  fi
done

if pgrep -u "$USER" -af 'uvicorn main_107cup:app|vite|celery worker|celery beat|redis-server' >/dev/null; then
  printf '%s\n' 'unexpected LMateLab process found on the login node' >&2
  exit 1
fi
