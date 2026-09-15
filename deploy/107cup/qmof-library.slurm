#!/usr/bin/env bash
#SBATCH --job-name=lmatelab-qmof
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/qmof-library-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/qmof-library-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?qmof-library.slurm must run through Slurm}"
: "${LMATELAB_QMOF_SOURCE_COMMIT:?source commit was not supplied}"

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup
data_root="$root/data/qmof"
downloads="$data_root/downloads"
archive="$downloads/qmof_database-v18.zip"
default_download_url='https://huggingface.co/datasets/StructureCloud/QMOF/resolve/24fc459339583e2f7b876296b6daec8d6d0a22a5/raw/qmof_database.zip?download=true'
temporary_relay_url='http://222.195.94.37:18757/qmof_database-v18.zip'
download_url="${LMATELAB_QMOF_TRANSFER_URL:-$default_download_url}"
case "$download_url" in
  "$default_download_url") curl_protocol='=https'; curl_tls=(--tlsv1.2) ;;
  "$temporary_relay_url") curl_protocol='=http'; curl_tls=() ;;
  *) printf 'unapproved QMOF transfer URL\n' >&2; exit 2 ;;
esac

chmod 600 "$root/logs/qmof-library-$SLURM_JOB_ID.out" \
  "$root/logs/qmof-library-$SLURM_JOB_ID.err"
test -L "$root/current"
release=$(readlink -f "$root/current")
commit=$(<"$release/commit.txt")
test "$commit" = "$LMATELAB_QMOF_SOURCE_COMMIT"
test "$commit" = "$(git -C "$project" rev-parse HEAD)"
installer="$release/source/backend/scripts/install_qmof_dataset.py"
python_env="$root/envs/python"
test -f "$installer"
test -x "$python_env/bin/python"

mkdir -p "$downloads" "$root/runtime"
chmod 700 "$data_root" "$downloads"
temporary="$downloads/.qmof_database-v18.$SLURM_JOB_ID.zip"
cleanup() {
  rm -f "$temporary"
}
trap cleanup EXIT

if ! test -f "$archive"; then
  test ! -e "$temporary"
  curl --fail --location --silent --show-error \
    --retry 3 --retry-all-errors --connect-timeout 30 \
    --proto "$curl_protocol" "${curl_tls[@]}" \
    --user-agent 'LMateLab-107Cup-QMOF-v18/1.0' \
    "$download_url" --output "$temporary"
  chmod 600 "$temporary"
  "$python_env/bin/python" "$installer" \
    --archive "$temporary" --verify-archive-only
  mv "$temporary" "$archive"
fi
chmod 600 "$archive"

exec 9>"$data_root/.install.lock"
chmod 600 "$data_root/.install.lock"
flock -n 9
"$python_env/bin/python" "$installer" \
  --archive "$archive" \
  --data-root "$data_root" \
  --source-commit "$commit" \
  --transport-url-used "$download_url"
"$python_env/bin/python" "$installer" \
  --archive "$archive" \
  --data-root "$data_root" \
  --verify-installed
printf '%s\n' "$SLURM_JOB_ID" > "$root/runtime/qmof-library-job-id"
printf 'QMOF_INSTALL_OK version=v18 commit=%s\n' "$commit"
