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

: "${SLURM_JOB_ID:?vasp-stage.slurm must run through Slurm}"
: "${SLURMD_NODENAME:?SLURMD_NODENAME is required}"
: "${SLURM_CPUS_PER_TASK:?SLURM_CPUS_PER_TASK is required}"
: "${SLURM_NTASKS:?SLURM_NTASKS is required}"
[[ "$SLURM_JOB_ID" =~ ^[1-9][0-9]*$ ]] || exit 64
[[ "$SLURMD_NODENAME" =~ ^[A-Za-z0-9._-]+$ ]] || exit 64
[[ "$SLURM_CPUS_PER_TASK" =~ ^[1-9][0-9]*$ ]] || exit 64
[[ "$SLURM_NTASKS" =~ ^[1-9][0-9]*$ ]] || exit 64
test "$SLURM_CPUS_PER_TASK" = 16 || exit 64
test "$SLURM_NTASKS" = 1 || exit 64

slurm_record=$(/usr/bin/scontrol --oneliner show job "$SLURM_JOB_ID")
read -r -a slurm_fields <<< "$slurm_record"
for required_field in \
  "JobId=$SLURM_JOB_ID" \
  "Account=competition" \
  "Partition=P107-RTX5090" \
  "QOS=qos_p107-rtx5090" \
  "NumNodes=1" \
  "NumTasks=1" \
  "CPUs/Task=16"; do
  field_found=0
  for field in "${slurm_fields[@]}"; do
    if test "$field" = "$required_field"; then
      field_found=1
      break
    fi
  done
  test "$field_found" = 1 || exit 64
done

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

attempt_directory=$PWD
scratch="$PWD/.vasp-stage-runtime"
common_evidence=(
  POTCAR
  potcar-source-sha256.txt
  vaspkit-version.txt
  vasp-exit-code.txt
  runtime-time.txt
)
case "$stage" in
  relax)
    input_names=(INCAR KPOINTS POSCAR POTCAR.spec)
    stage_outputs=(OUTCAR vasprun.xml OSZICAR CONTCAR)
    ;;
  scf)
    input_names=(INCAR KPOINTS POSCAR POTCAR.spec)
    stage_outputs=(OUTCAR vasprun.xml CHGCAR WAVECAR)
    ;;
  band)
    input_names=(INCAR KPOINTS POSCAR POTCAR.spec CHGCAR)
    stage_outputs=(OUTCAR vasprun.xml EIGENVAL)
    ;;
  dos)
    input_names=(INCAR KPOINTS POSCAR POTCAR.spec CHGCAR)
    stage_outputs=(OUTCAR vasprun.xml DOSCAR)
    ;;
esac
reserved_names=("${common_evidence[@]}" "${stage_outputs[@]}")
for name in "${reserved_names[@]}"; do
  test ! -e "$name" || exit 64
  test ! -L "$name" || exit 64
done
test ! -e "$scratch" || exit 64
test ! -L "$scratch" || exit 64
mkdir -m 700 -- "$scratch"

for name in "${input_names[@]}"; do
  test -f "$attempt_directory/$name"
  test ! -L "$attempt_directory/$name"
  cp -- "$attempt_directory/$name" "$scratch/$name"
  chmod 600 -- "$scratch/$name"
done
cd -- "$scratch"

mo_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/Mo_sv/POTCAR | awk '{print $1}')
s_source_sha=$(sha256sum /home/scc/pb23030683/POTCAR/PBE/S/POTCAR | awk '{print $1}')
test "$mo_source_sha" = 2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa
test "$s_source_sha" = 0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132
printf '%s  Mo_sv\n%s  S\n' "$mo_source_sha" "$s_source_sha" > potcar-source-sha256.txt

/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103 \
  2>&1 | tee vaspkit-version.txt
vaspkit_banner='VASPKIT Standard Edition 1.5.1'
mapfile -t vaspkit_markers < <(
  grep -Eo 'VASPKIT[[:space:]]+Standard[[:space:]]+Edition[[:space:]]+[0-9]+\.[0-9]+\.[0-9]+' vaspkit-version.txt || true
)
test "${#vaspkit_markers[@]}" -eq 1
test "${vaspkit_markers[0]}" = "$vaspkit_banner"
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

publish_fixed_file() {
  local name=$1
  test -f "$scratch/$name" || return 1
  test ! -L "$scratch/$name" || return 1
  ln -- "$scratch/$name" "$attempt_directory/$name"
}

publication_status=0
for name in "${common_evidence[@]}"; do
  if ! publish_fixed_file "$name"; then
    publication_status=74
  fi
done
for name in "${stage_outputs[@]}"; do
  if test -e "$scratch/$name" || test -L "$scratch/$name"; then
    if ! publish_fixed_file "$name"; then
      publication_status=74
    fi
  fi
done
if test "$publication_status" = 74; then
  printf '%s\n' 'fixed evidence publication failed' >&2
  exit 74
fi
exit "$vasp_status"
