#!/bin/bash
#SBATCH --job-name=lmatelab-stage7-preflight
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/stage7-preflight-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/stage7-preflight-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?stage7-preflight.slurm must run through Slurm}"
root=/home/scc/pb23030683/lmatelab-107cup
release=$(readlink -f "$root/current")
template="$release/source/backend/competition_templates/mos2_v1"
evidence="$root/evidence/stage7/preflight-$SLURM_JOB_ID"

test -d "$release"
test -f "$template/POSCAR"
test ! -e "$evidence"
mkdir -p "$root/evidence/stage7"
chmod 700 "$root/evidence" "$root/evidence/stage7"
mkdir "$evidence"
chmod 700 "$evidence"
cp -- "$template/POSCAR" "$evidence/POSCAR"
printf 'Mo_sv\nS\n' > "$evidence/POTCAR.spec"
chmod 600 "$evidence/POSCAR" "$evidence/POTCAR.spec"
cd "$evidence"

mo_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/Mo_sv/POTCAR | awk '{print $1}')
s_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/S/POTCAR | awk '{print $1}')
test "$mo_source_sha" = 2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa
test "$s_source_sha" = 0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132
printf '%s  Mo_sv\n%s  S\n' "$mo_source_sha" "$s_source_sha" > potcar-source-sha256.txt

/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103 \
  2>&1 | tee vaspkit-version.txt
vaspkit_banner='VASPKIT Standard Edition 1.5.1'
mapfile -t vaspkit_markers < <(
  grep -E 'VASPKIT[[:space:]]+Standard[[:space:]]+Edition' vaspkit-version.txt || true
)
test "${#vaspkit_markers[@]}" -eq 1
test "${vaspkit_markers[0]}" = "$vaspkit_banner"
test "$(sha256sum POTCAR | cut -d ' ' -f 1)" = 509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045
mapfile -t potcar_titles < <(sed -n 's/^[[:space:]]*TITEL[[:space:]]*=[[:space:]]*//p' POTCAR)
test "${#potcar_titles[@]}" -eq 2
[[ "${potcar_titles[0]}" == PAW_PBE\ Mo_sv* ]]
[[ "${potcar_titles[1]}" == PAW_PBE\ S\ * ]]

source /home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh
command -v vasp_std | tee vasp-std-path.txt
ldd "$(command -v vasp_std)" > vasp-std-ldd.txt
chmod 600 ./*
