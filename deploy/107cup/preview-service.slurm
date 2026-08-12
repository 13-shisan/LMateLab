#!/bin/bash
#SBATCH --job-name=lmatelab-preview-web
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=2-00:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/preview-service-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/preview-service-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?preview-service.slurm must run through Slurm}"
: "${LMATELAB_PREVIEW_COMMIT:?fixed merge commit is required}"
[[ "$LMATELAB_PREVIEW_COMMIT" =~ ^[0-9a-f]{40}$ ]]

root=/home/scc/pb23030683/lmatelab-107cup
commit="$LMATELAB_PREVIEW_COMMIT"
release="$root/previews/$commit"
python_env="$root/preview-envs/python/$commit"
runtime_env="$root/config/runtime.env"
runtime="$root/preview-runtime/$commit/$SLURM_JOB_ID"
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
test "$(<"$release/data-mode.txt")" = demo

test ! -e "$runtime"
mkdir -p "$data/db" "$runtime/cache/matplotlib" "$runtime/cache/vasp-elements"
chmod 700 "$runtime" "$data" "$data/db" "$runtime/cache" \
  "$runtime/cache/matplotlib" "$runtime/cache/vasp-elements"

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
            raise RuntimeError(f"preview database integrity failed: {target_path}")
    finally:
        target.close()
        source.close()
PY

port=$((20000 + SLURM_JOB_ID % 1000))
if ss -ltnH "sport = :$port" | grep -q .; then
  printf 'preview port already in use: %s\n' "$port" >&2
  exit 1
fi

set -a
source "$runtime_env"
set +a
: "${JWT_SECRET:?JWT_SECRET must be configured}"

export DATABASE_URL="sqlite:///$data/db/eln.db"
export DIGEST_DATABASE_URL="sqlite:///$data/db/digests.db"
export LMATELAB_DATA_DIR="$data"
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
export LMATELAB_RELEASE_KIND=preview
export LMATELAB_DATA_MODE=demo
export LMATELAB_PORT="$port"

mkdir -p \
  "$UPLOADS_ROOT" \
  "$VASP_CUSTOM_DB_ROOT" \
  "$QE_EPW_CUSTOM_DB_ROOT" \
  "$ISSUES_DIR"
chmod 700 \
  "$UPLOADS_ROOT" \
  "$VASP_CUSTOM_DB_ROOT" \
  "$QE_EPW_CUSTOM_DB_ROOT" \
  "$ISSUES_DIR"

printf '%s\n' "$SLURM_JOB_ID" > "$runtime/preview-service-job-id"
printf '%s\n' "${SLURMD_NODENAME:-$(hostname)}" > "$runtime/preview-service-node"
printf '%s\n' "$port" > "$runtime/preview-service-port"
printf '%s\n' "$commit" > "$runtime/preview-service-commit"
printf '%s\n' "$LMATELAB_MANIFEST_SHA256" > "$runtime/preview-service-manifest-sha256"
printf '%s\n' "$LMATELAB_STARTED_AT" > "$runtime/preview-service-started-at"

source "$python_env/bin/activate"
cd "$source_root/backend"
alembic -c alembic.ini upgrade head
alembic -c alembic_digest.ini upgrade head

exec uvicorn main_107cup:app --host 0.0.0.0 --port "$port" --workers 1
