#!/bin/bash
#SBATCH --job-name=lmatelab-generic-vaspkit-preflight
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/generic-vaspkit-preflight-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/generic-vaspkit-preflight-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?generic-vaspkit-preflight.slurm must run through Slurm}"
[[ "$SLURM_JOB_ID" =~ ^[1-9][0-9]*$ ]] || exit 64

root=/home/scc/pb23030683/lmatelab-107cup
evidence="$root/evidence/stage7/generic-vaspkit-preflight-$SLURM_JOB_ID"
test ! -e "$evidence"
test ! -L "$evidence"
mkdir -m 700 -- "$evidence"
cd -- "$evidence"

cat > POSCAR <<'EOF'
WS2 generic preflight
1.0
3.180000000000000 0.000000000000000 0.000000000000000
-1.590000000000000 2.753960784034515 0.000000000000000
0.000000000000000 0.000000000000000 20.000000000000000
W S
1 2
Direct
0.000000000000000 0.000000000000000 0.500000000000000
0.333333333333333 0.666666666666667 0.579000000000000
0.333333333333333 0.666666666666667 0.421000000000000
EOF
printf '%s\n' W S > POTCAR.spec

vaspkit=/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit
"$vaspkit" -task 103 2>&1 | tee vaspkit-potcar-output.txt
vaspkit_banner='VASPKIT Standard Edition 1.5.1'
read_vaspkit_markers() {
  local output=$1
  sed -En 's/^[[:space:]]*\|[[:space:]]+VASPKIT[[:space:]]+Standard[[:space:]]+Edition[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+)[[:space:]]+\([0-9]{2}[[:space:]][[:alpha:]]{3}\.[[:space:]][0-9]{4}\)[[:space:]]+\|[[:space:]]*$/VASPKIT Standard Edition \1/p' "$output"
}
mapfile -t potcar_markers < <(read_vaspkit_markers vaspkit-potcar-output.txt)
test "${#potcar_markers[@]}" -eq 1
test "${potcar_markers[0]}" = "$vaspkit_banner"
printf '%s\n' "$vaspkit_banner" > vaspkit-version.txt

mapfile -t potcar_titles < <(sed -n 's/^[[:space:]]*TITEL[[:space:]]*=[[:space:]]*//p' POTCAR)
test "${#potcar_titles[@]}" -eq 2
potcar_root=/home/scc/pb23030683/POTCAR/PBE
: > POTCAR.resolved
: > potcar-source-sha256.txt
: > expected-POTCAR
poscar_elements=(W S)
for index in "${!potcar_titles[@]}"; do
  title=${potcar_titles[$index]}
  read -r potential_family resolved_symbol title_suffix <<< "$title"
  test "$potential_family" = PAW_PBE
  [[ "$resolved_symbol" =~ ^[A-Z][a-z]?(_[A-Za-z0-9]+)?$ ]] || exit 64
  test -n "$title_suffix"
  test "${resolved_symbol%%_*}" = "${poscar_elements[$index]}"
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
rm -- expected-POTCAR vaspkit-potcar-output.txt

test ! -e KPATH.in
"$vaspkit" -task 302 2>&1 | tee vaspkit-band-output.txt
mapfile -t band_markers < <(read_vaspkit_markers vaspkit-band-output.txt)
test "${#band_markers[@]}" -eq 1
test "${band_markers[0]}" = "$vaspkit_banner"
rm -- vaspkit-band-output.txt
test -s KPATH.in
test ! -L KPATH.in
test "$(wc -c < KPATH.in)" -le 8192
sed -n '3p' KPATH.in | grep -Eiq '^[[:space:]]*Line-mode[[:space:]]*$'
sed -n '4p' KPATH.in | grep -Eiq '^[[:space:]]*Reciprocal[[:space:]]*$'
printf '%s\n' '{"generator":"vaspkit","task":302,"vaspkit_version":"1.5.1"}' \
  > band-path-generator.txt
/usr/bin/scontrol --oneliner show job "$SLURM_JOB_ID" > slurm-job.txt

find . -maxdepth 1 -type f ! -name manifest.txt ! -name manifest.sha256 \
  -printf '%P\0' | LC_ALL=C sort -z | xargs -0 sha256sum -- > manifest.txt
sha256sum -c manifest.txt
sha256sum manifest.txt > manifest.sha256
sha256sum -c manifest.sha256
find . -maxdepth 1 -type f -exec chmod 600 -- {} +

printf '%s\n' GENERIC_VASPKIT_PREFLIGHT_OK
