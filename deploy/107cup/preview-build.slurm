#!/bin/bash
#SBATCH --job-name=lmatelab-preview-build
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=00:45:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/preview-build-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/preview-build-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?preview-build.slurm must run through Slurm}"
: "${LMATELAB_PREVIEW_COMMIT:?fixed merge commit is required}"
[[ "$LMATELAB_PREVIEW_COMMIT" =~ ^[0-9a-f]{40}$ ]]

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup
commit="$LMATELAB_PREVIEW_COMMIT"
release="$root/previews/$commit"
staging="$root/previews/.$commit.$SLURM_JOB_ID"
python_env="$root/preview-envs/python/$commit"
source_tree="$staging/source"
node_version=v22.14.0
node_name="node-$node_version-linux-x64"
node_root="$root/envs/$node_name"

test -d "$project/.git"
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
git -C "$project" merge-base --is-ancestor "$commit" origin/main

mkdir -p "$root/previews" "$root/preview-envs/python" "$root/envs" "$root/logs"

if test -d "$release"; then
  cd "$release"
  test "$(<commit.txt)" = "$commit"
  test "$(<release-kind.txt)" = preview
  test "$(<data-mode.txt)" = demo
  sha256sum -c manifest.sha256
  sha256sum -c manifest.txt
  exit 0
fi

test ! -e "$staging"
mkdir -p "$source_tree"
git -C "$project" archive "$commit" | tar -C "$source_tree" -xf -

source /etc/profile.d/modules.sh
module load miniconda/py312

if ! test -x "$node_root/bin/node"; then
  tmp_root="${SLURM_TMPDIR:-/tmp}"
  archive="$tmp_root/$node_name.tar.xz"
  checksums="$tmp_root/node-$node_version-SHASUMS256.txt"
  node_staging="$root/envs/.$node_name.$SLURM_JOB_ID"

  curl --fail --location --silent --show-error \
    "https://nodejs.org/dist/$node_version/$node_name.tar.xz" \
    --output "$archive"
  curl --fail --location --silent --show-error \
    "https://nodejs.org/dist/$node_version/SHASUMS256.txt" \
    --output "$checksums"
  (cd "$tmp_root" && grep "  $node_name.tar.xz$" "$(basename "$checksums")" | sha256sum -c -)
  test ! -e "$node_staging"
  mkdir -p "$node_staging"
  tar -xJf "$archive" -C "$node_staging" --strip-components=1
  mv "$node_staging" "$node_root"
fi
export PATH="$node_root/bin:$PATH"

if ! test -x "$python_env/bin/python"; then
  python -m venv "$python_env"
fi
source "$python_env/bin/activate"
python -m pip install --upgrade pip
python -m pip install --requirement "$source_tree/backend/requirements-107cup.txt"

cd "$source_tree/backend"
python -m unittest \
  tests.test_107cup_authz \
  tests.test_107cup_runtime \
  tests.test_107cup_deploy_contract \
  tests.test_107cup_preview_deploy_contract \
  tests.test_health_readiness \
  -v

cd "$source_tree/frontend"
npm ci
npm test
VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build

mkdir -p "$staging/frontend-dist"
cp -a "$source_tree/frontend/dist/." "$staging/frontend-dist/"
rm -rf "$source_tree/frontend/node_modules" "$source_tree/frontend/dist"

cd "$staging"
printf '%s\n' "$commit" > commit.txt
printf '%s\n' preview > release-kind.txt
printf '%s\n' demo > data-mode.txt
find source frontend-dist commit.txt release-kind.txt data-mode.txt -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > manifest.txt
sha256sum manifest.txt > manifest.sha256
sha256sum -c manifest.sha256
sha256sum -c manifest.txt

mv "$staging" "$release"
