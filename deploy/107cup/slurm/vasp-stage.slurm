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

mapfile -t potcar_symbols < POTCAR.spec
test "${#potcar_symbols[@]}" -ge 1
test "${#potcar_symbols[@]}" -le 16
read -r -a poscar_elements <<< "$(sed -n '6p' POSCAR)"
test "${#poscar_elements[@]}" -eq "${#potcar_symbols[@]}"
declare -A seen_potcar_symbols=()
for index in "${!potcar_symbols[@]}"; do
  symbol=${potcar_symbols[$index]}
  [[ "$symbol" =~ ^[A-Z][a-z]?(_[A-Za-z0-9]+)?$ ]] || exit 64
  test -z "${seen_potcar_symbols[$symbol]+present}" || exit 64
  seen_potcar_symbols[$symbol]=1
  test "${symbol%%_*}" = "${poscar_elements[$index]}" || exit 64
done

attempt_directory=$PWD
scratch="$PWD/.vasp-stage-runtime"
common_evidence=(
  POTCAR
  POTCAR.resolved
  potcar-source-sha256.txt
  vaspkit-version.txt
  vasp-exit-code.txt
  runtime-time.txt
)
generated_band_path=0
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
    if test -f BAND_PATH.policy && test ! -e KPOINTS; then
      test "$(<BAND_PATH.policy)" = '{"generator":"vaspkit","task":302,"version":1}'
      input_names=(INCAR BAND_PATH.policy POSCAR POTCAR.spec CHGCAR)
      common_evidence+=(KPOINTS band-path-generator.txt)
      generated_band_path=1
    else
      input_names=(INCAR KPOINTS POSCAR POTCAR.spec CHGCAR)
    fi
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

/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103 \
  2>&1 | tee vaspkit-potcar-output.txt
vaspkit_banner='VASPKIT Standard Edition 1.5.1'
read_vaspkit_markers() {
  local output=$1
  sed -En 's/^[[:space:]]*\|[[:space:]]+VASPKIT[[:space:]]+Standard[[:space:]]+Edition[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+)[[:space:]]+\([0-9]{2}[[:space:]][[:alpha:]]{3}\.[[:space:]][0-9]{4}\)[[:space:]]+\|[[:space:]]*$/VASPKIT Standard Edition \1/p' "$output"
}
mapfile -t vaspkit_markers < <(read_vaspkit_markers vaspkit-potcar-output.txt)
test "${#vaspkit_markers[@]}" -eq 1
test "${vaspkit_markers[0]}" = "$vaspkit_banner"
printf '%s\n' "$vaspkit_banner" > vaspkit-version.txt
rm -- vaspkit-potcar-output.txt
mapfile -t potcar_titles < <(sed -n 's/^[[:space:]]*TITEL[[:space:]]*=[[:space:]]*//p' POTCAR)
test "${#potcar_titles[@]}" -eq "${#potcar_symbols[@]}"

potcar_root=/home/scc/pb23030683/POTCAR/PBE
: > POTCAR.resolved
: > potcar-source-sha256.txt
: > expected-POTCAR
resolved_symbols=()
for index in "${!potcar_symbols[@]}"; do
  title=${potcar_titles[$index]}
  requested_symbol=${potcar_symbols[$index]}
  read -r potential_family resolved_symbol title_suffix <<< "$title"
  test "$potential_family" = PAW_PBE
  [[ "$resolved_symbol" =~ ^[A-Z][a-z]?(_[A-Za-z0-9]+)?$ ]] || exit 64
  test -n "$title_suffix"
  test "${resolved_symbol%%_*}" = "${poscar_elements[$index]}"
  test "${requested_symbol%%_*}" = "${resolved_symbol%%_*}"
  resolved_symbols+=("$resolved_symbol")
  printf '%s\n' "$resolved_symbol" >> POTCAR.resolved

  source_potcar="$potcar_root/$resolved_symbol/POTCAR"
  test -f "$source_potcar"
  test ! -L "$source_potcar"
  source_sha=$(sha256sum "$source_potcar" | awk '{print $1}')
  [[ "$source_sha" =~ ^[0-9a-f]{64}$ ]]
  printf '%s  %s\n' "$source_sha" "$resolved_symbol" >> potcar-source-sha256.txt
  cat -- "$source_potcar" >> expected-POTCAR
done

cmp --silent -- expected-POTCAR POTCAR
rm -- expected-POTCAR
potcar_sha=$(sha256sum POTCAR | cut -d ' ' -f 1)
[[ "$potcar_sha" =~ ^[0-9a-f]{64}$ ]]

if test "${potcar_symbols[*]}" = 'Mo_sv S'; then
  test "${resolved_symbols[*]}" = 'Mo_sv S'
  test "$(sed -n '1s/ .*//p' potcar-source-sha256.txt)" = 2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa
  test "$(sed -n '2s/ .*//p' potcar-source-sha256.txt)" = 0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132
  test "$potcar_sha" = 509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045
fi

if test "$generated_band_path" = 1; then
  test ! -e KPATH.in
  /home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 302 \
    2>&1 | tee vaspkit-band-output.txt
  mapfile -t band_vaspkit_markers < <(read_vaspkit_markers vaspkit-band-output.txt)
  test "${#band_vaspkit_markers[@]}" -eq 1
  test "${band_vaspkit_markers[0]}" = "$vaspkit_banner"
  rm -- vaspkit-band-output.txt
  test -s KPATH.in
  test ! -L KPATH.in
  test "$(wc -c < KPATH.in)" -le 8192
  sed -n '3p' KPATH.in | grep -Eiq '^[[:space:]]*Line-mode[[:space:]]*$'
  sed -n '4p' KPATH.in | grep -Eiq '^[[:space:]]*Reciprocal[[:space:]]*$'
  mv -- KPATH.in KPOINTS
  printf '%s\n' '{"generator":"vaspkit","task":302,"vaspkit_version":"1.5.1"}' \
    > band-path-generator.txt
fi

source /etc/profile.d/modules.sh
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
