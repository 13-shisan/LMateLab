#!/bin/bash
#SBATCH --job-name=lmatelab-build
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=12G
#SBATCH --time=00:45:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/build-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/build-%j.err

set -euo pipefail

: "${SLURM_JOB_ID:?build.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup
runtime_env="$root/config/runtime.env"
python_env="$root/envs/python"
node_version=v22.14.0
node_name="node-$node_version-linux-x64"
node_root="$root/envs/$node_name"

test -f "$runtime_env"
test -d "$project/.git"

set -a
source "$runtime_env"
set +a
: "${JWT_SECRET:?JWT_SECRET must be generated in runtime.env}"

mkdir -p \
  "$root/envs" \
  "$root/releases" \
  "$root/logs" \
  "$root/runtime" \
  "$root/runtime/cache/vasp-elements" \
  "$root/data/db" \
  "$root/data/uploads" \
  "$root/data/custom/vasp" \
  "$root/data/custom/qe_epw" \
  "$root/data/vasp/personal" \
  "$root/data/issues" \
  "$root/backups"

commit=$(git -C "$project" rev-parse HEAD)
release="$root/releases/$commit"
staging="$root/releases/.$commit.$SLURM_JOB_ID"

if test -d "$release"; then
  cd "$release"
  sha256sum -c manifest.sha256
  sha256sum -c manifest.txt
  rm -f "$root/current.next"
  ln -s "$release" "$root/current.next"
  mv -Tf "$root/current.next" "$root/current"
  printf '%s\n' "$commit" > "$root/runtime/build-commit"
  exit 0
fi

if ! test -x "$node_root/bin/node"; then
  tmp_root="${SLURM_TMPDIR:-/tmp}"
  archive="$tmp_root/$node_name.tar.xz"
  checksums="$tmp_root/node-$node_version-SHASUMS256.txt"
  install_staging="$root/envs/.$node_name.$SLURM_JOB_ID"

  curl --fail --location --silent --show-error \
    "https://nodejs.org/dist/$node_version/$node_name.tar.xz" \
    --output "$archive"
  curl --fail --location --silent --show-error \
    "https://nodejs.org/dist/$node_version/SHASUMS256.txt" \
    --output "$checksums"
  cd "$tmp_root"
  grep "  $node_name.tar.xz$" "$checksums" | sha256sum -c -
  rm -rf "$install_staging"
  mkdir -p "$install_staging"
  tar -xJf "$archive" -C "$install_staging" --strip-components=1
  mv "$install_staging" "$node_root"
fi

export PATH="$node_root/bin:$PATH"

if ! test -x "$python_env/bin/python"; then
  python3 -m venv "$python_env"
fi

source "$python_env/bin/activate"
python -m pip install --upgrade pip
python -m pip install --requirement "$project/backend/requirements-107cup.txt"

cd "$project/backend"
python -m unittest \
  tests.test_107cup_runtime \
  tests.test_107cup_deploy_contract \
  tests.test_health_readiness \
  -v

cd "$project/frontend"
npm ci
npm test
VITE_LMATELAB_EDITION=107cup npm run build

export LMATELAB_FRONTEND_DIST="$project/frontend/dist"
cd "$project/backend"
python -c "from main_107cup import app; paths={route.path for route in app.routes}; assert '/api/health/live' in paths; assert '/api/agents' not in paths"

rm -rf "$staging"
mkdir -p "$staging/source" "$staging/frontend-dist"
tar \
  --exclude=.git \
  --exclude=frontend/node_modules \
  --exclude=frontend/dist \
  -C "$project" -cf - . | tar -C "$staging/source" -xf -
cp -a "$project/frontend/dist/." "$staging/frontend-dist/"

cd "$staging"
printf '%s\n' "$commit" > commit.txt
find source frontend-dist -type f -print0 | sort -z | xargs -0 sha256sum > manifest.txt
sha256sum manifest.txt > manifest.sha256
sha256sum -c manifest.sha256
sha256sum -c manifest.txt

mv "$staging" "$release"
rm -f "$root/current.next"
ln -s "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf '%s\n' "$commit" > "$root/runtime/build-commit"
printf '%s\n' "$SLURM_JOB_ID" > "$root/runtime/build-job-id"
