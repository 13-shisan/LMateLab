#!/bin/bash
#SBATCH --job-name=lmatelab-workflow-preview-web
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=08:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-service-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-service-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?workflow-preview-service.slurm must run through Slurm}"
: "${LMATELAB_WORKFLOW_PREVIEW_COMMIT:?fixed merge commit is required}"
[[ "$LMATELAB_WORKFLOW_PREVIEW_COMMIT" =~ ^[0-9a-f]{40}$ ]]

root=/home/scc/pb23030683/lmatelab-107cup
commit="$LMATELAB_WORKFLOW_PREVIEW_COMMIT"
release="$root/workflow-previews/$commit"
python_env="$root/workflow-preview-envs/python/$commit"
runtime_env="$root/config/runtime.env"
runtime_parent="$root/workflow-preview-runtime/$commit"
runtime="$runtime_parent/$SLURM_JOB_ID"
data="$runtime/data"
source_root="$release/source"
frontend_root="$release/frontend-dist"

test -d "$release"
test -x "$python_env/bin/python"
test -f "$runtime_env"
test -f "$source_root/backend/main_107cup.py"
test -f "$frontend_root/index.html"
(cd "$release" && sha256sum -c manifest.sha256 && sha256sum -c manifest.txt)
test "$(<"$release/commit.txt")" = "$commit"
test "$(<"$release/release-kind.txt")" = preview
test "$(<"$release/data-mode.txt")" = live

test ! -e "$runtime"
mkdir -p "$runtime_parent"
chmod 700 "$root/workflow-preview-runtime" "$runtime_parent"
mkdir -p "$data/db" "$data/workflows" "$runtime/cache/matplotlib" \
  "$runtime/cache/vasp-elements"
chmod 700 "$runtime" "$data" "$data/db" "$data/workflows" \
  "$runtime/cache" "$runtime/cache/matplotlib" "$runtime/cache/vasp-elements"

"$python_env/bin/python" - \
  "$root/data/db/eln.db" "$data/db/eln.db" \
  "$root/data/db/digests.db" "$data/db/digests.db" <<'PY'
import sqlite3
import sys

for source_path, target_path in zip(sys.argv[1::2], sys.argv[2::2]):
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"workflow preview database integrity failed: {target_path}")
    finally:
        target.close()
        source.close()
PY

port=$((21000 + SLURM_JOB_ID % 1000))
if ss -ltnH "sport = :$port" | grep -q .; then
  printf 'workflow preview port already in use: %s\n' "$port" >&2
  exit 1
fi

set -a
source "$runtime_env"
set +a
export JWT_SECRET="$("$python_env/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"

export DATABASE_URL="sqlite:///$data/db/eln.db"
export DIGEST_DATABASE_URL="sqlite:///$data/db/digests.db"
export LMATELAB_DATA_DIR="$data"
export LMATELAB_WORKFLOW_ROOT="$data/workflows"
export UPLOADS_ROOT="$data/uploads"
export VASP_UPLOADS_ROOT="$data/uploads"
export VASP_CUSTOM_DB_ROOT="$data/custom/vasp"
export QE_EPW_CUSTOM_DB_ROOT="$data/custom/qe_epw"
export VASP_ELEMENTS_CACHE_DIR="$runtime/cache/vasp-elements"
export ISSUES_DIR="$data/issues"
export CHANGELOG_PATH="$data/changelog.md"
export ACADEMIC_REPORTS_FILE="$data/academic_reports.json"
export MPLCONFIGDIR="$runtime/cache/matplotlib"
export LMATELAB_FRONTEND_DIST="$frontend_root"
export LMATELAB_GIT_COMMIT="$commit"
export LMATELAB_MANIFEST_SHA256="$(cut -d ' ' -f 1 "$release/manifest.sha256")"
export LMATELAB_STARTED_AT="$(date --iso-8601=seconds)"
export LMATELAB_EDITION=107cup
export LMATELAB_RELEASE_KIND=preview
export LMATELAB_DATA_MODE=live
export LMATELAB_PORT="$port"
export LMATELAB_REGISTRATION_ENABLED=0
export LMATELAB_PASSWORD_RESET_ENABLED=0
export LMATELAB_SLURM_USER=pb23030683
export LMATELAB_SLURM_PROBE_SCRIPT="$source_root/deploy/107cup/slurm/probe.slurm"
export LMATELAB_COORDINATOR_ENABLED=0

mkdir -p "$UPLOADS_ROOT" "$VASP_CUSTOM_DB_ROOT" "$QE_EPW_CUSTOM_DB_ROOT" \
  "$ISSUES_DIR"
chmod 700 "$UPLOADS_ROOT" "$VASP_CUSTOM_DB_ROOT" "$QE_EPW_CUSTOM_DB_ROOT" \
  "$ISSUES_DIR"

printf '%s\n' "$SLURM_JOB_ID" > "$runtime/workflow-preview-service-job-id"
printf '%s\n' "${SLURMD_NODENAME:-$(hostname)}" > "$runtime/workflow-preview-service-node"
printf '%s\n' "$port" > "$runtime/workflow-preview-service-port"
printf '%s\n' "$commit" > "$runtime/workflow-preview-service-commit"
printf '%s\n' "$LMATELAB_MANIFEST_SHA256" > "$runtime/workflow-preview-service-manifest-sha256"
printf '%s\n' "$LMATELAB_STARTED_AT" > "$runtime/workflow-preview-service-started-at"

source "$python_env/bin/activate"
cd "$source_root/backend"
alembic -c alembic.ini upgrade head
alembic -c alembic_digest.ini upgrade head

"$python_env/bin/python" - "$data/db/eln.db" "$runtime/schema-evidence.json" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

database, evidence_path = map(Path, sys.argv[1:])
expected_tables = [
    "workflow_runs",
    "workflow_steps",
    "workflow_attempts",
    "workflow_events",
    "workflow_files",
    "workflow_templates",
]
with sqlite3.connect(database) as connection:
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = sorted(set(expected_tables) - tables)
    workflow_count = connection.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

if revision != "107c0ffee001" or missing or workflow_count != 0 or integrity != "ok":
    raise SystemExit(
        f"workflow schema gate failed: revision={revision}, missing={missing}, "
        f"workflow_count={workflow_count}, integrity={integrity}"
    )
payload = {
    "revision": revision,
    "tables": expected_tables,
    "workflow_count_before_acceptance": workflow_count,
    "integrity_check": integrity,
}
evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
evidence_path.chmod(0o600)
PY

"$python_env/bin/python" - \
  "$data/db/eln.db" "$runtime/acceptance-credentials.json" "$SLURM_JOB_ID" <<'PY'
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from passlib.context import CryptContext

database = Path(sys.argv[1])
credentials_path = Path(sys.argv[2])
job_id = sys.argv[3]
passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")
accounts = []
with sqlite3.connect(database) as connection:
    for role in ("operator", "viewer"):
        email = f"stage5-{role}-{job_id}@matflow.top"
        password = secrets.token_urlsafe(24)
        connection.execute(
            "INSERT INTO users (email, password_hash, name, alias, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                email,
                passwords.hash(password),
                f"Stage5 {role} {job_id}",
                f"stage5-{role}-{job_id}",
                role,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        accounts.append({"email": email, "password": password, "role": role})
    connection.commit()

flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
descriptor = os.open(credentials_path, flags, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump({"accounts": accounts}, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

exec uvicorn main_107cup:app --host 0.0.0.0 --port "$port" --workers 1
