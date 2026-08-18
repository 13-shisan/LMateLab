#!/bin/bash
#SBATCH --job-name=lmatelab-stage7-vasp
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:RTX5090:1
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/vasp-stage-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/vasp-stage-%j.err

set -euo pipefail
umask 077

test "$#" -eq 3
stage=$1
workflow_id=$2
attempt_id=$3
case "$stage" in relax|scf|band|dos) ;; *) exit 64 ;; esac

uuid_re='^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
[[ "$workflow_id" =~ $uuid_re ]] || exit 64
[[ "$attempt_id" =~ $uuid_re ]] || exit 64
: "${LMATELAB_WORKFLOW_ROOT:?LMATELAB_WORKFLOW_ROOT is required}"
test "$PWD" = "$LMATELAB_WORKFLOW_ROOT/$workflow_id/attempts/$attempt_id"
test "$(<POTCAR.spec)" = $'Mo_sv\nS'

mo_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/Mo_sv/POTCAR | awk '{print $1}')
s_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/S/POTCAR | awk '{print $1}')
test "$mo_source_sha" = 2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa
test "$s_source_sha" = 0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132
printf '%s  Mo_sv\n%s  S\n' "$mo_source_sha" "$s_source_sha" > potcar-source-sha256.txt

/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103 \
  2>&1 | tee vaspkit-version.txt
test "$(sha256sum POTCAR | cut -d ' ' -f 1)" = 509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045
mapfile -t potcar_titles < <(sed -n 's/^[[:space:]]*TITEL[[:space:]]*=[[:space:]]*//p' POTCAR)
test "${#potcar_titles[@]}" -eq 2
[[ "${potcar_titles[0]}" == PAW_PBE\ Mo_sv* ]]
[[ "${potcar_titles[1]}" == PAW_PBE\ S\ * ]]

source /home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"
set +e
/usr/bin/time -v -o runtime-time.txt \
  mpirun --bind-to none -np "$SLURM_NTASKS" vasp_std
vasp_status=$?
set -e
printf '%s\n' "$vasp_status" > vasp-exit-code.txt
exit "$vasp_status"
