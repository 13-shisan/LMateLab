import ast
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "107cup"
VALID_WORKFLOW_ID = "11111111-1111-4111-8111-111111111111"
VALID_ATTEMPT_ID = "22222222-2222-4222-8222-222222222222"
REAL_VASPKIT_BANNER = (
    "|         VASPKIT Standard Edition 1.5.1 "
    "(27 Jan. 2024)         |\n"
)
REAL_VASPKIT_OUTPUT = (
    "VASPKIT startup notice\n"
    f"{REAL_VASPKIT_BANNER}"
    "When using VASPKIT in your research, cite the VASPKIT paper.\n"
)


class VaspStageFixture:
    hashes = {
        "mo": "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
        "s": "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
        "w": "4a6ad4d6ac7d8dd634ed1bdc7b3755ab56459e57fd15fc9eaa2ed7fd83d32b88",
        "combined": "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
        "ws2_combined": "6ae462127454203c2cbeed53f77335e8586603ca4bf34dd3768a936cf4f11f22",
    }
    evidence_names = (
        "POTCAR",
        "potcar-source-sha256.txt",
        "vaspkit-version.txt",
        "vasp-exit-code.txt",
        "runtime-time.txt",
    )
    stage_output_names = (
        "OUTCAR",
        "vasprun.xml",
        "OSZICAR",
        "CONTCAR",
        "CHGCAR",
        "WAVECAR",
        "EIGENVAL",
        "DOSCAR",
    )

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lmatelab-vasp-stage-")
        self.root = Path(self.temporary.name)
        self.bash = shutil.which("bash")
        if self.bash is None:
            self.cleanup()
            raise unittest.SkipTest("bash is unavailable")
        self.bin = self.root / "bin"
        self.markers = self.root / "markers"
        self.workflow_root = self.root / "workflows"
        self.attempt = (
            self.workflow_root
            / VALID_WORKFLOW_ID
            / "attempts"
            / VALID_ATTEMPT_ID
        )
        self.potcar_root = self.root / "PBE"
        for directory in (self.bin, self.markers, self.attempt, self.potcar_root):
            directory.mkdir(parents=True, exist_ok=True)
        (self.attempt / "INCAR").write_text(
            "SYSTEM = fixture\n", encoding="utf-8", newline="\n"
        )
        self.sources = {}
        for symbol in ("Mo_sv", "S", "W"):
            source = self.potcar_root / symbol / "POTCAR"
            source.parent.mkdir(mode=0o700)
            source.write_text(
                f"TITEL  = PAW_PBE {symbol} fixture\n", encoding="utf-8"
            )
            self.sources[symbol] = source
        self._configure_inputs(generic=False, stage="scf")
        self._write_stubs()
        self._rewrite_runner()

    def cleanup(self):
        self.temporary.cleanup()

    def _write_executable(self, name, source):
        path = self.bin / name
        path.write_text(source.lstrip(), encoding="utf-8", newline="\n")
        path.chmod(0o700)
        return path

    def _write_stubs(self):
        self.modules = self._write_executable(
            "modules.sh",
            """
#!/bin/bash
module() {
  test "$*" = 'load mkl/2026.0'
  printf '%s\n' "$*" > "$FIXTURE_MARKERS/modules"
}
""",
        )
        self._write_executable(
            "vaspkit",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >> "$FIXTURE_MARKERS/vaspkit"
case "$*" in
  '-task 103')
    : > POTCAR
    while IFS= read -r symbol; do
      printf 'TITEL  = PAW_PBE %s fixture\n' "$symbol" >> POTCAR
    done < POTCAR.spec
    ;;
  '-task 302')
    cat > KPATH.in <<'EOF'
WS2 generated path
20
Line-mode
Reciprocal
0.000000 0.000000 0.000000 ! G
0.500000 0.000000 0.000000 ! M

0.500000 0.000000 0.000000 ! M
0.333333 0.333333 0.000000 ! K
EOF
    ;;
  *) exit 64 ;;
esac
printf '%s' "$FIXTURE_VASPKIT_OUTPUT"
""",
        )
        self._write_executable(
            "sha256sum",
            f"""
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/sha256sum"
case "$1" in
  "$FIXTURE_MO_SOURCE") printf '%s  %s\n' '{self.hashes["mo"]}' "$1" ;;
  "$FIXTURE_S_SOURCE") printf '%s  %s\n' '{self.hashes["s"]}' "$1" ;;
  "$FIXTURE_W_SOURCE") printf '%s  %s\n' '{self.hashes["w"]}' "$1" ;;
  POTCAR)
    if grep -q 'PAW_PBE W ' POTCAR; then
      printf '%s  POTCAR\n' '{self.hashes["ws2_combined"]}'
    else
      printf '%s  POTCAR\n' '{self.hashes["combined"]}'
    fi
    ;;
  *) exit 64 ;;
esac
""",
        )
        self._write_executable(
            "env-nvhpc.sh",
            """
#!/bin/bash
module load mkl/2026.0
printf '%s\n' sourced > "$FIXTURE_MARKERS/environment"
export PATH="$FIXTURE_BIN:$PATH"
""",
        )
        self._write_executable(
            "scontrol",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/scontrol"
test "$*" = "--oneliner show job $SLURM_JOB_ID"
printf '%s\n' "$FIXTURE_SCONTROL_RECORD"
""",
        )
        self._write_executable(
            "mpirun",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/mpirun"
test "$*" = "--bind-to none -np $SLURM_NTASKS vasp_std"
exec vasp_std
""",
        )
        self._write_executable(
            "vasp_std",
            """
#!/bin/bash
printf '%s\n' invoked > "$FIXTURE_MARKERS/vasp_std"
if test -n "$FIXTURE_PUBLISH_COLLISION"; then
  printf '%s\n' collision > "$FIXTURE_ATTEMPT/$FIXTURE_PUBLISH_COLLISION"
fi
case "$FIXTURE_STAGE" in
  relax) outputs='OUTCAR vasprun.xml OSZICAR CONTCAR' ;;
  scf) outputs='OUTCAR vasprun.xml CHGCAR WAVECAR' ;;
  band) outputs='OUTCAR vasprun.xml EIGENVAL' ;;
  dos) outputs='OUTCAR vasprun.xml DOSCAR' ;;
  *) exit 64 ;;
esac
for output in $outputs; do
  printf '%s\n' "$FIXTURE_STAGE output" > "$output"
done
exit "$FIXTURE_VASP_STATUS"
""",
        )
        self._write_executable(
            "time",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/time"
test "$1" = -v
test "$2" = -o
output=$3
shift 3
printf '%s\n' 'Maximum resident set size (kbytes): 1234' > "$output"
set +e
"$@"
status=$?
set -e
exit "$status"
""",
        )

    def _rewrite_runner(self):
        source_path = DEPLOY_ROOT / "slurm" / "vasp-stage.slurm"
        self.original_source = source_path.read_text(encoding="utf-8")
        dependencies = {
            "/etc/profile.d/modules.sh": self.modules,
            "/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit": self.bin
            / "vaspkit",
            "/home/scc/pb23030683/POTCAR/PBE": self.potcar_root,
            "/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh": self.bin
            / "env-nvhpc.sh",
            "/usr/bin/scontrol": self.bin / "scontrol",
            "/usr/bin/time": self.bin / "time",
        }
        self.rewrites = []
        rewritten = self.original_source
        for original, replacement_path in dependencies.items():
            occurrence_count = rewritten.count(original)
            if occurrence_count < 1:
                raise AssertionError(f"fixed dependency occurrence changed: {original}")
            replacement = shlex.quote(replacement_path.as_posix())
            rewritten = rewritten.replace(original, replacement)
            self.rewrites.append((original, replacement, occurrence_count))
        self.rewritten_source = rewritten
        self.runner = self.root / "vasp-stage.fixture.slurm"
        self.runner.write_text(rewritten, encoding="utf-8", newline="\n")
        self.runner.chmod(0o700)

    def _configure_inputs(self, *, generic, stage):
        if generic:
            title = "WS2 fixture"
            elements = "W S"
            spec = "W\nS\n"
        else:
            title = "MoS2 fixture"
            elements = "Mo S"
            spec = "Mo_sv\nS\n"
        poscar = (
            f"{title}\n"
            "1.0\n"
            "3.2 0.0 0.0\n"
            "-1.6 2.771281292 0.0\n"
            "0.0 0.0 20.0\n"
            f"{elements}\n"
            "1 2\n"
            "Direct\n"
            "0.0 0.0 0.5\n"
            "0.333333 0.666667 0.58\n"
            "0.333333 0.666667 0.42\n"
        )
        (self.attempt / "POSCAR").write_text(
            poscar, encoding="utf-8", newline="\n"
        )
        (self.attempt / "POTCAR.spec").write_text(
            spec, encoding="utf-8", newline="\n"
        )
        if generic and stage == "band":
            (self.attempt / "KPOINTS").unlink(missing_ok=True)
            (self.attempt / "BAND_PATH.policy").write_text(
                '{"generator":"vaspkit","task":302,"version":1}\n',
                encoding="utf-8",
                newline="\n",
            )
        else:
            (self.attempt / "BAND_PATH.policy").unlink(missing_ok=True)
            (self.attempt / "KPOINTS").write_text(
                "fixture mesh\n0\nGamma\n1 1 1\n0 0 0\n",
                encoding="utf-8",
                newline="\n",
            )

    def run(
        self,
        *,
        vaspkit_output=None,
        vasp_status=0,
        publish_collision=None,
        scontrol_record=None,
        slurm_values=None,
        unset=(),
        preserve=(),
        generic=False,
        **arguments,
    ):
        shutil.rmtree(self.attempt / ".vasp-stage-runtime", ignore_errors=True)
        for path in (
            *self.markers.iterdir(),
            *(
                self.attempt / n
                for n in (
                    *self.evidence_names,
                    *self.stage_output_names,
                    "band-path-generator.txt",
                    "KPOINTS",
                )
            ),
        ):
            if path.name not in preserve and (path.exists() or path.is_symlink()):
                path.unlink()
        values = {
            "stage": "scf",
            "workflow_id": VALID_WORKFLOW_ID,
            "attempt_id": VALID_ATTEMPT_ID,
            **arguments,
        }
        self._configure_inputs(generic=generic, stage=values["stage"])
        if values["stage"] in {"band", "dos"}:
            (self.attempt / "CHGCAR").write_bytes(b"fixed SCF charge input\n")
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin}{os.pathsep}{environment.get('PATH', '')}",
                "SLURM_JOB_ID": "12345",
                "SLURMD_NODENAME": "fixture-node",
                "SLURM_CPUS_PER_TASK": "16",
                "SLURM_NTASKS": "1",
                "LMATELAB_WORKFLOW_ROOT": self.workflow_root.as_posix(),
                "FIXTURE_BIN": self.bin.as_posix(),
                "FIXTURE_MARKERS": self.markers.as_posix(),
                "FIXTURE_ATTEMPT": self.attempt.as_posix(),
                "FIXTURE_MO_SOURCE": self.sources["Mo_sv"].as_posix(),
                "FIXTURE_S_SOURCE": self.sources["S"].as_posix(),
                "FIXTURE_W_SOURCE": self.sources["W"].as_posix(),
                "FIXTURE_PUBLISH_COLLISION": publish_collision or "",
                "FIXTURE_VASPKIT_OUTPUT": vaspkit_output
                if vaspkit_output is not None
                else REAL_VASPKIT_OUTPUT,
                "FIXTURE_VASP_STATUS": str(vasp_status),
                "FIXTURE_STAGE": values["stage"],
                "FIXTURE_SCONTROL_RECORD": scontrol_record
                if scontrol_record is not None
                else (
                    "JobId=12345 Account=competition Partition=P107-RTX5090 "
                    "QOS=qos_p107-rtx5090 NumNodes=1 NumTasks=1 CPUs/Task=16"
                ),
            }
        )
        environment.update(slurm_values or {})
        for name in unset:
            environment.pop(name, None)
        return subprocess.run(
            [
                self.bash,
                self.runner,
                values["stage"],
                values["workflow_id"],
                values["attempt_id"],
            ],
            cwd=self.attempt,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def reached(self, name):
        return (self.markers / name).is_file()


class Stage7PreflightFixture:
    evidence_names = {
        "POSCAR",
        "POTCAR.spec",
        "potcar-source-sha256.txt",
        "POTCAR",
        "vaspkit-version.txt",
        "vasp-std-path.txt",
        "vasp-std-ldd.txt",
    }

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lmatelab-stage7-preflight-")
        self.root = Path(self.temporary.name)
        self.bash = shutil.which("bash")
        if self.bash is None:
            self.cleanup()
            raise unittest.SkipTest("bash is unavailable")
        self.bin = self.root / "bin"
        self.markers = self.root / "markers"
        self.competition_root = self.root / "competition"
        self.release = self.competition_root / "releases" / ("a" * 40)
        self.template = (
            self.release / "source" / "backend" / "competition_templates" / "mos2_v1"
        )
        self.dependencies = self.root / "dependencies"
        for directory in (self.bin, self.markers, self.template, self.dependencies):
            directory.mkdir(parents=True, exist_ok=True)
        (self.competition_root / "current").symlink_to(
            self.release, target_is_directory=True
        )
        (self.template / "POSCAR").write_text(
            "MoS2 preflight fixture\n", encoding="utf-8", newline="\n"
        )
        self.mo_source = self.dependencies / "Mo_sv.POTCAR"
        self.s_source = self.dependencies / "S.POTCAR"
        self.mo_source.write_bytes(b"Mo preflight source\n")
        self.s_source.write_bytes(b"S preflight source\n")
        self.potcar_content = (
            b"TITEL  = PAW_PBE Mo_sv 02Feb2006\n"
            b"TITEL  = PAW_PBE S 06Sep2000\n"
        )
        self._write_stubs()
        self._rewrite_runner()
        self.next_job_id = 50000

    def cleanup(self):
        self.temporary.cleanup()

    def _write_executable(self, name, source):
        path = self.bin / name
        path.write_text(source.lstrip(), encoding="utf-8", newline="\n")
        path.chmod(0o700)
        return path

    def _write_stubs(self):
        self.modules = self._write_executable(
            "modules.sh",
            """
#!/bin/bash
module() {
  test "$*" = 'load mkl/2026.0'
  printf '%s\n' "$*" > "$FIXTURE_MARKERS/modules"
}
""",
        )
        self.vaspkit = self._write_executable(
            "vaspkit",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/vaspkit"
printf '%s\n' \
  'TITEL  = PAW_PBE Mo_sv 02Feb2006' \
  'TITEL  = PAW_PBE S 06Sep2000' > POTCAR
printf '%s' "$FIXTURE_VASPKIT_OUTPUT"
""",
        )
        self.environment = self._write_executable(
            "env-nvhpc.sh",
            """
#!/bin/bash
module load mkl/2026.0
printf '%s\n' sourced > "$FIXTURE_MARKERS/environment"
export PATH="$FIXTURE_BIN:$PATH"
""",
        )
        self.vasp_std = self._write_executable(
            "vasp_std",
            """
#!/bin/bash
printf '%s\n' invoked > "$FIXTURE_MARKERS/vasp_std"
exit 99
""",
        )
        self._write_executable(
            "ldd",
            """
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" > "$FIXTURE_MARKERS/ldd"
printf '%s\n' 'fixture dependency resolution'
""",
        )

    def _rewrite_runner(self):
        source = (DEPLOY_ROOT / "slurm" / "stage7-preflight.slurm").read_text(
            encoding="utf-8"
        )
        root_assignment = "root=/home/scc/pb23030683/lmatelab-107cup"
        if source.count(root_assignment) != 1:
            raise AssertionError("fixed competition root assignment changed")
        rewritten = source.replace(
            root_assignment,
            f"root={shlex.quote(self.competition_root.as_posix())}",
        )
        paths = {
            "/etc/profile.d/modules.sh": self.modules,
            "/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit": self.vaspkit,
            "/home/scc/pb23030683/POTCAR/PBE/Mo_sv/POTCAR": self.mo_source,
            "/home/scc/pb23030683/POTCAR/PBE/S/POTCAR": self.s_source,
            "/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh": self.environment,
        }
        for original, replacement_path in paths.items():
            if rewritten.count(original) != 1:
                raise AssertionError(f"fixed preflight dependency changed: {original}")
            rewritten = rewritten.replace(
                original, shlex.quote(replacement_path.as_posix())
            )
        hashes = {
            VaspStageFixture.hashes["mo"]: hashlib.sha256(
                self.mo_source.read_bytes()
            ).hexdigest(),
            VaspStageFixture.hashes["s"]: hashlib.sha256(
                self.s_source.read_bytes()
            ).hexdigest(),
            VaspStageFixture.hashes["combined"]: hashlib.sha256(
                self.potcar_content
            ).hexdigest(),
        }
        for original, replacement in hashes.items():
            if rewritten.count(original) != 1:
                raise AssertionError(f"fixed preflight hash changed: {original}")
            rewritten = rewritten.replace(original, replacement)
        self.runner = self.root / "stage7-preflight.fixture.slurm"
        self.runner.write_text(rewritten, encoding="utf-8", newline="\n")
        self.runner.chmod(0o700)

    def run(self, *, banner=REAL_VASPKIT_OUTPUT):
        for marker in self.markers.iterdir():
            marker.unlink()
        job_id = str(self.next_job_id)
        self.next_job_id += 1
        environment = os.environ.copy()
        environment.update(
            {
                "SLURM_JOB_ID": job_id,
                "FIXTURE_BIN": self.bin.as_posix(),
                "FIXTURE_MARKERS": self.markers.as_posix(),
                "FIXTURE_VASPKIT_OUTPUT": banner,
            }
        )
        result = subprocess.run(
            [self.bash, self.runner],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        evidence = (
            self.competition_root / "evidence" / "stage7" / f"preflight-{job_id}"
        )
        return SimpleNamespace(result=result, evidence=evidence)

    def reached(self, name):
        return (self.markers / name).is_file()


@unittest.skipUnless(os.name == "posix", "runner behavior requires POSIX")
class VaspStageLinuxBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = VaspStageFixture()
        self.addCleanup(self.fixture.cleanup)

    def test_untrusted_environment_and_arguments_stop_before_vaspkit(self):
        for variable in ("SLURM_JOB_ID", "SLURMD_NODENAME", "SLURM_CPUS_PER_TASK", "SLURM_NTASKS"):
            with self.subTest(variable=variable):
                result = self.fixture.run(unset=(variable,))
                self.assertNotEqual(0, result.returncode, result)
                self.assertFalse(self.fixture.reached("vaspkit"))
        sentinel = self.fixture.markers / "injected"
        injection = f"$(touch {sentinel.as_posix()})"
        for arguments in (
            {"stage": f"scf{injection}"},
            {"workflow_id": f"{VALID_WORKFLOW_ID}{injection}"},
            {"attempt_id": f"{VALID_ATTEMPT_ID};touch {sentinel.as_posix()}"},
        ):
            with self.subTest(arguments=arguments):
                result = self.fixture.run(**arguments)
                self.assertEqual(64, result.returncode, result)
                self.assertFalse(sentinel.exists())
                self.assertFalse(self.fixture.reached("vaspkit"))

    def test_wrong_positive_slurm_resources_stop_before_scontrol_and_vaspkit(self):
        for variable, value in (("SLURM_NTASKS", "2"), ("SLURM_CPUS_PER_TASK", "8")):
            with self.subTest(variable=variable, value=value):
                result = self.fixture.run(slurm_values={variable: value})
                self.assertEqual(64, result.returncode, result)
                self.assertFalse(self.fixture.reached("scontrol"))
                self.assertFalse(self.fixture.reached("vaspkit"))

    def test_wrong_scheduler_allocation_stops_before_vaspkit(self):
        valid = {
            "JobId": "12345",
            "Account": "competition",
            "Partition": "P107-RTX5090",
            "QOS": "qos_p107-rtx5090",
            "NumNodes": "1",
            "NumTasks": "1",
            "CPUs/Task": "16",
        }
        for field, value in (
            ("JobId", "54321"),
            ("Account", "stu"),
            ("Partition", "Students"),
            ("QOS", "qos_stu_default"),
            ("NumNodes", "2"),
            ("NumTasks", "2"),
            ("CPUs/Task", "8"),
        ):
            with self.subTest(field=field, value=value):
                record = {**valid, field: value}
                result = self.fixture.run(
                    scontrol_record=" ".join(f"{key}={item}" for key, item in record.items())
                )
                self.assertEqual(64, result.returncode, result)
                self.assertTrue(self.fixture.reached("scontrol"))
                self.assertFalse(self.fixture.reached("vaspkit"))

    def _assert_reserved_symlinks_are_rejected(self, names, *, stage="scf"):
        for name in names:
            with self.subTest(name=name):
                link = self.fixture.attempt / name
                link.unlink(missing_ok=True)
                sentinel = self.fixture.root / f"sentinel-{name.replace('/', '_')}"
                sentinel.write_bytes(b"sentinel\n")
                link.symlink_to(sentinel)
                try:
                    result = self.fixture.run(preserve={name}, stage=stage)
                    self.assertEqual(64, result.returncode, result)
                    self.assertEqual(b"sentinel\n", sentinel.read_bytes())
                    self.assertFalse(self.fixture.reached("vaspkit"))
                    self.assertFalse(self.fixture.reached("vasp_std"))
                finally:
                    link.unlink(missing_ok=True)
                    sentinel.unlink(missing_ok=True)

    def test_common_evidence_symlinks_are_rejected_before_tools_run(self):
        self._assert_reserved_symlinks_are_rejected(self.fixture.evidence_names)

    def test_stage_output_symlinks_are_rejected_before_tools_run(self):
        for stage, names in (
            ("relax", ("OUTCAR", "vasprun.xml", "OSZICAR", "CONTCAR")),
            ("scf", ("OUTCAR", "vasprun.xml", "CHGCAR", "WAVECAR")),
            ("band", ("OUTCAR", "vasprun.xml", "EIGENVAL")),
            ("dos", ("OUTCAR", "vasprun.xml", "DOSCAR")),
        ):
            with self.subTest(stage=stage):
                self._assert_reserved_symlinks_are_rejected(names, stage=stage)

    def test_vaspkit_banner_must_be_exact_and_unique(self):
        wrong_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.0")
        extended_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1.1")
        suffixed_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1rc1")
        prerelease_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1-rc1")
        build_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1+build7")
        underscored_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1_rc1")
        spaced_banner = REAL_VASPKIT_BANNER.replace("1.5.1", "1.5.1 rc1")
        for output in (
            wrong_banner,
            extended_banner,
            suffixed_banner,
            prerelease_banner,
            build_banner,
            underscored_banner,
            spaced_banner,
            REAL_VASPKIT_BANNER + REAL_VASPKIT_BANNER,
        ):
            with self.subTest(output=output):
                result = self.fixture.run(vaspkit_output=output)
                self.assertNotEqual(0, result.returncode, result)
                self.assertTrue(self.fixture.reached("vaspkit"))
                self.assertFalse(self.fixture.reached("environment"))
                self.assertFalse(self.fixture.reached("vasp_std"))

    def test_every_valid_stage_reaches_vasp_and_publishes_only_its_outputs(self):
        expected_outputs = {
            "relax": ("OUTCAR", "vasprun.xml", "OSZICAR", "CONTCAR"),
            "scf": ("OUTCAR", "vasprun.xml", "CHGCAR", "WAVECAR"),
            "band": ("OUTCAR", "vasprun.xml", "EIGENVAL"),
            "dos": ("OUTCAR", "vasprun.xml", "DOSCAR"),
        }
        for stage, outputs in expected_outputs.items():
            with self.subTest(stage=stage):
                result = self.fixture.run(stage=stage)
                self.assertEqual(0, result.returncode, result)
                for phase in (
                    "sha256sum",
                    "vaspkit",
                    "modules",
                    "environment",
                    "time",
                    "mpirun",
                    "vasp_std",
                ):
                    self.assertTrue(self.fixture.reached(phase), phase)
                scratch = self.fixture.attempt / ".vasp-stage-runtime"
                self.assertTrue(scratch.is_dir())
                self.assertEqual(0o700, scratch.stat().st_mode & 0o777)
                for name in self.fixture.evidence_names:
                    path = self.fixture.attempt / name
                    self.assertTrue(path.is_file(), str(path))
                    self.assertEqual(0o600, path.stat().st_mode & 0o777)
                    self.assertTrue(os.path.samefile(path, scratch / name), name)
                self.assertEqual(
                    "VASPKIT Standard Edition 1.5.1\n",
                    (self.fixture.attempt / "vaspkit-version.txt").read_text(
                        encoding="utf-8"
                    ),
                )
                self.assertEqual(
                    ["-task 103"],
                    (self.fixture.markers / "vaspkit")
                    .read_text(encoding="utf-8")
                    .splitlines(),
                )
                self.assertFalse((scratch / "vaspkit-potcar-output.txt").exists())
                self.assertFalse((scratch / "vaspkit-band-output.txt").exists())
                for name in outputs:
                    self.assertTrue((self.fixture.attempt / name).is_file(), name)

    def test_generic_ws2_band_generates_potcar_and_302_path_from_final_poscar(self):
        result = self.fixture.run(stage="band", generic=True)
        self.assertEqual(0, result.returncode, result)

        self.assertEqual(
            ["-task 103", "-task 302"],
            (self.fixture.markers / "vaspkit")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
        self.assertEqual(
            "W\nS\n", (self.fixture.attempt / "POTCAR.spec").read_text()
        )
        self.assertEqual(
            f'{self.fixture.hashes["w"]}  W\n'
            f'{self.fixture.hashes["s"]}  S\n',
            (self.fixture.attempt / "potcar-source-sha256.txt").read_text(),
        )
        self.assertEqual(
            ["TITEL  = PAW_PBE W fixture", "TITEL  = PAW_PBE S fixture"],
            (self.fixture.attempt / "POTCAR").read_text().splitlines(),
        )
        kpoints = (self.fixture.attempt / "KPOINTS").read_text()
        self.assertIn("Line-mode", kpoints)
        self.assertIn("Reciprocal", kpoints)
        self.assertEqual(
            '{"generator":"vaspkit","task":302,'
            '"vaspkit_version":"1.5.1"}\n',
            (self.fixture.attempt / "band-path-generator.txt").read_text(),
        )
        scratch = self.fixture.attempt / ".vasp-stage-runtime"
        self.assertFalse((scratch / "KPATH.in").exists())
        self.assertFalse((scratch / "vaspkit-potcar-output.txt").exists())
        self.assertFalse((scratch / "vaspkit-band-output.txt").exists())

    def test_nonzero_vasp_status_is_preserved(self):
        result = self.fixture.run(vasp_status=37)
        self.assertEqual(37, result.returncode, result)
        self.assertEqual(
            "37\n",
            (self.fixture.attempt / "vasp-exit-code.txt").read_text(encoding="utf-8"),
        )

    def test_publication_collision_returns_infrastructure_status_and_keeps_vasp_status(self):
        result = self.fixture.run(vasp_status=37, publish_collision="POTCAR")
        self.assertEqual(74, result.returncode, result)
        self.assertEqual(
            "collision\n",
            (self.fixture.attempt / "POTCAR").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "37\n",
            (self.fixture.attempt / ".vasp-stage-runtime" / "vasp-exit-code.txt").read_text(
                encoding="utf-8"
            ),
        )
        self.assertTrue((self.fixture.attempt / "runtime-time.txt").is_file())

    def test_fixture_executes_only_the_rewritten_runner(self):
        result = self.fixture.run()
        self.assertEqual(0, result.returncode, result)
        restored = self.fixture.rewritten_source
        for original, replacement, occurrence_count in self.fixture.rewrites:
            self.assertEqual(occurrence_count, restored.count(replacement))
            restored = restored.replace(replacement, original)
        self.assertEqual(self.fixture.original_source, restored)


@unittest.skipUnless(os.name == "posix", "preflight behavior requires POSIX")
class Stage7PreflightLinuxBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Stage7PreflightFixture()
        self.addCleanup(self.fixture.cleanup)

    def test_success_creates_self_checked_private_manifests_without_running_vasp(self):
        run = self.fixture.run()
        self.assertEqual(0, run.result.returncode, run.result)
        self.assertTrue(self.fixture.reached("vaspkit"))
        self.assertTrue(self.fixture.reached("modules"))
        self.assertTrue(self.fixture.reached("environment"))
        self.assertTrue(self.fixture.reached("ldd"))
        self.assertFalse(self.fixture.reached("vasp_std"))

        manifest = run.evidence / "manifest.txt"
        manifest_sha = run.evidence / "manifest.sha256"
        listed_names = {
            line.split(None, 1)[1]
            for line in manifest.read_text(encoding="utf-8").splitlines()
        }
        self.assertEqual(self.fixture.evidence_names, listed_names)
        self.assertNotIn("manifest.txt", listed_names)
        self.assertNotIn("manifest.sha256", listed_names)
        for name in listed_names:
            self.assertFalse(Path(name).is_absolute(), name)
            self.assertNotIn("..", Path(name).parts, name)
            self.assertFalse(name.startswith("./"), name)
        for checksum_file in (manifest, manifest_sha):
            check = subprocess.run(
                ["sha256sum", "-c", checksum_file.name],
                cwd=run.evidence,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, check.returncode, check)

        all_files = {*self.fixture.evidence_names, "manifest.txt", "manifest.sha256"}
        self.assertEqual(all_files, {path.name for path in run.evidence.iterdir()})
        for name in all_files:
            self.assertEqual(0o600, (run.evidence / name).stat().st_mode & 0o777)
        self.assertEqual(
            "VASPKIT Standard Edition 1.5.1\n",
            (run.evidence / "vaspkit-version.txt").read_text(encoding="utf-8"),
        )
        self.assertFalse((run.evidence / "vaspkit-output.txt").exists())
        for directory in (
            self.fixture.competition_root / "evidence",
            self.fixture.competition_root / "evidence" / "stage7",
            run.evidence,
        ):
            self.assertEqual(0o700, directory.stat().st_mode & 0o777)

    def test_version_suffixes_stop_before_vasp_environment(self):
        for suffix in ("-rc1", "+build7", "_rc1", " rc1"):
            with self.subTest(suffix=suffix):
                run = self.fixture.run(
                    banner=REAL_VASPKIT_BANNER.replace("1.5.1", f"1.5.1{suffix}")
                )
                self.assertNotEqual(0, run.result.returncode, run.result)
                self.assertTrue(self.fixture.reached("vaspkit"))
                self.assertFalse(self.fixture.reached("environment"))
                self.assertFalse(self.fixture.reached("vasp_std"))


class CompetitionDeployContractTests(unittest.TestCase):
    def read_required(self, name: str) -> str:
        path = DEPLOY_ROOT / name
        self.assertTrue(path.is_file(), str(path))
        return path.read_text(encoding="utf-8")

    def test_linux_runtime_scripts_are_forced_to_lf_in_git(self):
        attributes_path = REPO_ROOT / ".gitattributes"
        self.assertTrue(attributes_path.is_file(), str(attributes_path))
        attributes = attributes_path.read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attributes)
        self.assertIn("*.slurm text eol=lf", attributes)

    def test_build_job_runs_only_under_slurm_and_creates_validated_release(self):
        source = self.read_required("build.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "SLURM_JOB_ID",
            "requirements-107cup.txt",
            "npm ci",
            "npm run build",
            "VITE_LMATELAB_EDITION=107cup",
            "releases",
            "sha256sum",
            "manifest.sha256",
            "current.next",
            "mv -Tf",
            "tests.test_107cup_authz",
        ):
            self.assertIn(required, source)
        self.assertNotIn("#SBATCH --gres", source)

    def test_stage6_probe_is_fixed_small_private_and_never_runs_vasp(self):
        source = self.read_required("slurm/probe.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            "#SBATCH --cpus-per-task=1",
            "#SBATCH --mem=256M",
            "#SBATCH --time=00:03:00",
            "SLURM_JOB_ID",
            "umask 077",
            "success|fail|cancel",
            "exit 42",
            "sleep 1",
        ):
            self.assertIn(required, source)
        for forbidden in ("vasp", "mpirun", "srun", "eval", "bash -c", "sh -c"):
            self.assertNotIn(forbidden, source.lower())

    def test_stage6_smoke_is_compute_only_isolated_and_hashes_all_evidence(self):
        source = self.read_required("slurm/stage6-smoke.py")
        for required in (
            "SLURM_JOB_ID",
            "sqlite:///",
            "stage6-smoke.sqlite",
            "CompetitionReconciler",
            "SlurmClient",
            "success",
            "fail",
            "cancel",
            "submission_accepted",
            "submission_failed",
            "cancellation_requested",
            "scheduler_state_changed",
            "manifest.sha256",
            "hashlib.sha256",
            "integrity_check",
        ):
            self.assertIn(required, source)
        for forbidden in ("shell=True", "docker", "vasp_std", "vasp_gam", "vasp_ncl"):
            self.assertNotIn(forbidden, source)

    def test_stage6_smoke_test_only_probe_uses_typed_probe_runner(self):
        source = self.read_required("slurm/stage6-smoke.py")
        module = ast.parse(source)
        function = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "test_only_probe"
        )

        class TypedSubmission:
            created: list["TypedSubmission"] = []

            def __init__(
                self,
                *,
                workflow_id: str,
                attempt_id: str,
                step_key: str,
                attempt_number: int,
                attempt_directory: Path,
                script_path: Path,
                runner_kind: str,
                runner_mode: str,
            ) -> None:
                self.runner_kind = runner_kind
                self.runner_mode = runner_mode
                self.job_name = "typed-probe-job"
                self.__class__.created.append(self)

        class Client:
            def prepare_attempt_directory(self, workflow_id: str, attempt_id: str) -> Path:
                return Path("/attempts") / workflow_id / attempt_id

            def test_submission(self, submission: TypedSubmission) -> SimpleNamespace:
                return SimpleNamespace(returncode=0, stderr="", stdout="")

        namespace = {
            "PROBE_SCRIPT": Path("/fixed/probe.slurm"),
            "SlurmSubmission": TypedSubmission,
            "create_client": lambda: Client(),
            "hashlib": hashlib,
            "json": json,
            "run_command": lambda *_args, **_kwargs: {"stdout": '{"jobs": []}'},
            "uuid": SimpleNamespace(uuid4=lambda: "00000000-0000-4000-8000-000000000001"),
        }
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "stage6-smoke.py", "exec"),
            namespace,
        )

        result = namespace["test_only_probe"]()

        self.assertEqual(0, result["returncode"])
        self.assertEqual(1, len(TypedSubmission.created))
        self.assertEqual(
            ("probe", "success"),
            (TypedSubmission.created[0].runner_kind, TypedSubmission.created[0].runner_mode),
        )

    def test_stage6_smoke_resolves_the_pinned_release_when_slurm_spools_the_script(self):
        source = self.read_required("slurm/stage6-smoke.py")

        self.assertNotIn("Path(__file__).resolve()", source)
        for required in (
            'RELEASE_COMMIT = os.environ.get("LMATELAB_GIT_COMMIT", "")',
            'RELEASE_PARENT = Path("/home/scc/pb23030683/lmatelab-107cup/releases")',
            'RELEASE_ROOT = RELEASE_PARENT / RELEASE_COMMIT',
            'BACKEND_ROOT = RELEASE_ROOT / "source" / "backend"',
            'os.environ["LMATELAB_SLURM_PROBE_SCRIPT"] = str(',
            'EVIDENCE_ROOT.mkdir(mode=0o700, parents=True)',
            'EVIDENCE_ROOT / "failure.json"',
        ):
            self.assertIn(required, source)

        evidence_creation = source.index("EVIDENCE_ROOT.mkdir(mode=0o700, parents=True)")
        backend_validation = source.index("competition backend source is unavailable")
        sqlalchemy_import = source.index("from sqlalchemy import")
        self.assertLess(evidence_creation, backend_validation)
        self.assertLess(evidence_creation, sqlalchemy_import)

    def test_formal_build_runs_stage5_and_stage6_workflow_suites(self):
        source = self.read_required("build.slurm")
        for suite in (
            "tests.test_competition_workflow_models",
            "tests.test_competition_inputs",
            "tests.test_competition_workflow_service",
            "tests.test_competition_workflow_routes",
            "tests.test_competition_slurm",
            "tests.test_competition_slurm_linux",
        ):
            self.assertIn(suite, source)

    def test_formal_build_runs_stage3_recovery_suites(self):
        source = self.read_required("build.slurm")
        self.assertIn("tests.test_107cup_service_recovery", source)
        self.assertIn("tests.test_107cup_relay_recovery", source)

    def test_formal_release_materializes_the_fixed_stage6_script_path(self):
        source = self.read_required("build.slurm")
        self.assertIn('"$staging/deploy/107cup"', source)
        self.assertIn(
            'cp -a "$project/deploy/107cup/slurm" "$staging/deploy/107cup/"',
            source,
        )
        self.assertIn("find source frontend-dist deploy -type f", source)

    def test_stage7_vasp_runner_has_only_fixed_resources_identity_and_commands(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            "#SBATCH --cpus-per-task=16",
            "#SBATCH --gres=gpu:RTX5090:1",
            "#SBATCH --mem=32G",
            "#SBATCH --time=06:00:00",
            'test "$#" -eq 3',
            "case \"$stage\" in relax|scf|band|dos)",
            "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            'test "$PWD" = "$LMATELAB_WORKFLOW_ROOT/$workflow_id/attempts/$attempt_id"',
            "mapfile -t potcar_symbols < POTCAR.spec",
            "read -r -a poscar_elements",
            "seen_potcar_symbols",
            'test "${symbol%%_*}" = "${poscar_elements[$index]}"',
            "potcar_root=/home/scc/pb23030683/POTCAR/PBE",
            'source_potcar="$potcar_root/$symbol/POTCAR"',
            'cat -- "$source_potcar" >> expected-POTCAR',
            "cmp --silent -- expected-POTCAR POTCAR",
            "rm -- expected-POTCAR",
            "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
            "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
            "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
            '"PAW_PBE $symbol"',
            "/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103",
            "/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 302",
            "BAND_PATH.policy",
            "KPATH.in",
            "band-path-generator.txt",
            "/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh",
            "/usr/bin/time -v -o runtime-time.txt",
            'mpirun --bind-to none -np "$SLURM_NTASKS" vasp_std',
            "umask 077",
        ):
            self.assertIn(required, source)
        for forbidden in ("eval ", "bash -c", "sh -c", "docker", "singularity", "srun --pty"):
            self.assertNotIn(forbidden, source)

    def test_stage7_vasp_runner_preserves_common_evidence_and_vasp_exit_status(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for evidence_name in (
            "POTCAR",
            "potcar-source-sha256.txt",
            "vaspkit-version.txt",
            "vasp-exit-code.txt",
            "runtime-time.txt",
        ):
            self.assertIn(evidence_name, source)

        allow_nonzero = source.index("set +e")
        execute_vasp = source.index("/usr/bin/time -v -o runtime-time.txt", allow_nonzero)
        capture_status = source.index("vasp_status=$?", execute_vasp)
        restore_errexit = source.index("set -e", capture_status)
        write_status = source.index('> vasp-exit-code.txt', restore_errexit)
        preserve_status = source.index('exit "$vasp_status"', write_status)
        self.assertLess(allow_nonzero, execute_vasp)
        self.assertLess(execute_vasp, capture_status)
        self.assertLess(capture_status, restore_errexit)
        self.assertLess(restore_errexit, write_status)
        self.assertLess(write_status, preserve_status)

    def test_stage7_runner_gates_slurm_and_exact_vaspkit_banner(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for required in (
            ': "${SLURM_JOB_ID:?vasp-stage.slurm must run through Slurm}"',
            ': "${SLURMD_NODENAME:?SLURMD_NODENAME is required}"',
            ': "${SLURM_CPUS_PER_TASK:?SLURM_CPUS_PER_TASK is required}"',
            ': "${SLURM_NTASKS:?SLURM_NTASKS is required}"',
            '[[ "$SLURM_JOB_ID" =~ ^[1-9][0-9]*$ ]]',
            'test "$SLURM_CPUS_PER_TASK" = 16',
            'test "$SLURM_NTASKS" = 1',
            '/usr/bin/scontrol --oneliner show job "$SLURM_JOB_ID"',
            "Account=competition",
            "Partition=P107-RTX5090",
            "QOS=qos_p107-rtx5090",
            "NumNodes=1",
            "NumTasks=1",
            "CPUs/Task=16",
            "mapfile -t vaspkit_markers",
            "VASPKIT Standard Edition 1.5.1",
            'test "${#vaspkit_markers[@]}" -eq 1',
            'test "${vaspkit_markers[0]}" = "$vaspkit_banner"',
        ):
            self.assertIn(required, source)
        self.assertLess(source.index("SLURM_JOB_ID"), source.index('test "$#" -eq 3'))
        self.assertLess(source.index("/usr/bin/scontrol"), source.index('test "$#" -eq 3'))
        self.assertLess(source.index('test "$#" -eq 3'), source.index("POTCAR.spec"))
        self.assertLess(source.index("mapfile -t vaspkit_markers"), source.index("env-nvhpc.sh"))

        preflight = self.read_required("slurm/stage7-preflight.slurm")
        self.assertIn("mapfile -t vaspkit_markers", preflight)
        self.assertIn('test "${#vaspkit_markers[@]}" -eq 1', preflight)
        self.assertIn('test "${vaspkit_markers[0]}" = "$vaspkit_banner"', preflight)
        self.assertLess(preflight.index("mapfile -t vaspkit_markers"), preflight.index("env-nvhpc.sh"))

    def test_stage7_scripts_validate_full_line_vaspkit_banners(self):
        banner_assignment = "vaspkit_banner='VASPKIT Standard Edition 1.5.1'"
        preflight_extractor = (
            "sed -En 's/^[[:space:]]*\\|[[:space:]]+VASPKIT[[:space:]]+"
            "Standard[[:space:]]+Edition[[:space:]]+"
            "([0-9]+\\.[0-9]+\\.[0-9]+)[[:space:]]+\\([0-9]{2}"
            "[[:space:]][[:alpha:]]{3}\\.[[:space:]][0-9]{4}\\)"
            "[[:space:]]+\\|[[:space:]]*$/VASPKIT Standard Edition \\1/p' "
            "vaspkit-output.txt"
        )
        preflight = self.read_required("slurm/stage7-preflight.slurm")
        self.assertEqual(1, preflight.count(banner_assignment))
        self.assertEqual(1, preflight.count(preflight_extractor))
        self.assertIn('test "${#vaspkit_markers[@]}" -eq 1', preflight)
        self.assertIn(
            'test "${vaspkit_markers[0]}" = "$vaspkit_banner"', preflight
        )
        self.assertIn("rm -- vaspkit-output.txt", preflight)

        runner = self.read_required("slurm/vasp-stage.slurm")
        self.assertEqual(1, runner.count(banner_assignment))
        self.assertIn("read_vaspkit_markers()", runner)
        self.assertIn('read_vaspkit_markers vaspkit-potcar-output.txt', runner)
        self.assertIn('read_vaspkit_markers vaspkit-band-output.txt', runner)
        self.assertIn('test "${#vaspkit_markers[@]}" -eq 1', runner)
        self.assertIn('test "${#band_vaspkit_markers[@]}" -eq 1', runner)
        self.assertIn(
            'test "${band_vaspkit_markers[0]}" = "$vaspkit_banner"', runner
        )
        self.assertIn(
            "printf '%s\\n' \"$vaspkit_banner\" > vaspkit-version.txt", runner
        )
        self.assertIn("rm -- vaspkit-potcar-output.txt", runner)
        self.assertIn("rm -- vaspkit-band-output.txt", runner)

    def test_stage7_scripts_initialize_modules_before_vasp_environment(self):
        module_init = "source /etc/profile.d/modules.sh"
        vasp_environment = (
            "source /home/scc/pb23030683/software/"
            "vasp.6.4.2-GPU-Cell/env-nvhpc.sh"
        )
        for script_name in ("slurm/stage7-preflight.slurm", "slurm/vasp-stage.slurm"):
            with self.subTest(script_name=script_name):
                source = self.read_required(script_name)
                self.assertEqual(1, source.count(module_init))
                self.assertEqual(1, source.count(vasp_environment))
                self.assertLess(source.index(module_init), source.index(vasp_environment))

    def test_stage7_preflight_hashes_all_evidence_with_self_checked_manifests(self):
        source = self.read_required("slurm/stage7-preflight.slurm")
        final_evidence = source.index(
            'ldd "$(command -v vasp_std)" > vasp-std-ldd.txt'
        )
        for required in (
            "! -name manifest.txt",
            "! -name manifest.sha256",
            "-printf '%P\\0'",
            "LC_ALL=C sort -z",
        ):
            self.assertIn(required, source)

        manifest = source.index("> manifest.txt", final_evidence)
        check_manifest = source.index("sha256sum -c manifest.txt", manifest)
        manifest_sha = source.index(
            "sha256sum manifest.txt > manifest.sha256", check_manifest
        )
        check_manifest_sha = source.index(
            "sha256sum -c manifest.sha256", manifest_sha
        )
        chmod_evidence = source.index(
            "find . -maxdepth 1 -type f -exec chmod 600 -- {} +",
            check_manifest_sha,
        )
        self.assertLess(final_evidence, manifest)
        self.assertLess(manifest, check_manifest)
        self.assertLess(check_manifest, manifest_sha)
        self.assertLess(manifest_sha, check_manifest_sha)
        self.assertLess(check_manifest_sha, chmod_evidence)

    def test_stage7_runner_uses_private_scratch_and_no_overwrite_publication(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for required in (
            'scratch="$PWD/.vasp-stage-runtime"',
            'mkdir -m 700 -- "$scratch"',
            'test ! -e "$name"',
            'test ! -L "$name"',
            'test -f "$scratch/$name"',
            'test ! -L "$scratch/$name"',
            'ln -- "$scratch/$name" "$attempt_directory/$name"',
            "OUTCAR",
            "vasprun.xml",
            "OSZICAR",
            "CONTCAR",
            "CHGCAR",
            "WAVECAR",
            "EIGENVAL",
            "DOSCAR",
        ):
            self.assertIn(required, source)
        self.assertNotIn("rm -rf", source)
        precheck = source.index('test ! -e "$name"')
        scratch = source.index('mkdir -m 700 -- "$scratch"', precheck)
        vaspkit = source.index("vaspkit -task 103", scratch)
        publish = source.index('ln -- "$scratch/$name"', vaspkit)
        self.assertLess(precheck, scratch)
        self.assertLess(scratch, vaspkit)
        self.assertLess(vaspkit, publish)

    def test_stage7_preflight_is_short_private_fixed_and_never_executes_vasp(self):
        source = self.read_required("slurm/stage7-preflight.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "umask 077",
            'evidence/stage7/preflight-$SLURM_JOB_ID',
            "competition_templates/mos2_v1",
            '"$template/POSCAR"',
            "POTCAR.spec",
            "vaspkit -task 103",
            "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
            "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
            "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
            "PAW_PBE\\ Mo_sv*",
            "PAW_PBE\\ S\\ *",
            "env-nvhpc.sh",
            "command -v vasp_std",
            'ldd "$(command -v vasp_std)"',
        ):
            self.assertIn(required, source)
        for forbidden in ("mpirun", "/usr/bin/time", "srun "):
            self.assertNotIn(forbidden, source)

    def test_generic_vaspkit_preflight_is_short_fixed_and_never_runs_vasp(self):
        source = self.read_required("slurm/generic-vaspkit-preflight.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --cpus-per-task=1",
            "#SBATCH --mem=2G",
            "#SBATCH --time=00:05:00",
            "generic-vaspkit-preflight-$SLURM_JOB_ID",
            "W S",
            "POTCAR.spec",
            '"$vaspkit" -task 103',
            '"$vaspkit" -task 302',
            "cmp --silent -- expected-POTCAR POTCAR",
            "KPATH.in",
            "Line-mode",
            "Reciprocal",
            "band-path-generator.txt",
            "manifest.txt",
            "manifest.sha256",
            "GENERIC_VASPKIT_PREFLIGHT_OK",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "vasp_std",
            "vasp_gam",
            "vasp_ncl",
            "mpirun",
            "/usr/bin/time",
            "srun ",
            "eval ",
            "bash -c",
            "sh -c",
        ):
            self.assertNotIn(forbidden, source)

        submit = self.read_required("submit-generic-vaspkit-preflight.sh")
        self.assertIn("test -z \"$(git status --porcelain)\"", submit)
        self.assertIn(
            "sbatch --parsable \"$project/deploy/107cup/slurm/"
            "generic-vaspkit-preflight.slurm\"",
            submit,
        )

    def test_stage7_internal_acceptance_creator_is_fixed_short_and_nonpublic(self):
        python_source = self.read_required("slurm/stage7-acceptance.py")
        slurm_source = self.read_required("slurm/stage7-acceptance.slurm")
        for required in (
            'parser.add_argument("--profile", choices=("scf_nonconvergence_v1",), required=True)',
            'parser.add_argument("--operator-alias", default="pb23030683")',
            "DraftCreateRequest",
            "create_internal_acceptance_draft",
            "confirm_workflow",
            "build_production_coordinator",
            "coordinator.start",
        ):
            self.assertIn(required, python_source)
        for forbidden in (
            "shell=True",
            "subprocess",
            "os.system",
            "/home/scc/pb23030683/POTCAR",
            "TITEL  =",
            "apply_internal_profile",
            "render_acceptance_scf_incar",
            "WorkflowFile",
            "WorkflowRun",
            "append_workflow_event",
        ):
            self.assertNotIn(forbidden, python_source)

        create = python_source.index("create_internal_acceptance_draft(")
        confirm = python_source.index("confirm_workflow(", create)
        coordinator = python_source.index("coordinator.start(", confirm)
        self.assertLess(create, confirm)
        self.assertLess(confirm, coordinator)

        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "runtime.env",
            "envs/python",
            "stage7-acceptance.py",
            "--profile scf_nonconvergence_v1",
            'export PYTHONPATH="$release/source/backend"',
        ):
            self.assertIn(required, slurm_source)
        self.assertLess(
            slurm_source.index('export PYTHONPATH="$release/source/backend"'),
            slurm_source.index('exec "$python_env/bin/python"'),
        )
        for forbidden in ("vasp_std", "vasp_gam", "vasp_ncl", "mpirun", "vaspkit"):
            self.assertNotIn(forbidden, slurm_source.lower())

    def test_formal_build_runs_stage7_backend_suites(self):
        source = self.read_required("build.slurm")
        for suite in (
            "tests.test_competition_attempt_inputs",
            "tests.test_competition_vasp",
            "tests.test_competition_coordinator",
            "tests.test_competition_lifespan",
        ):
            self.assertIn(suite, source)

    def test_formal_build_runs_stage9_recovery_and_security_suites(self):
        source = self.read_required("build.slurm")
        for suite in (
            "tests.test_competition_recovery",
            "tests.test_competition_security",
        ):
            self.assertIn(suite, source)

    def test_build_job_uses_module_python_with_a_valid_pip_environment(self):
        source = self.read_required("build.slurm")
        module_init = "source /etc/profile.d/modules.sh"
        module_load = "module load miniconda/py312"
        backups_directory = '"$root/backups"'
        module_python_base = (
            "module_python_base=$(python -c "
            "'import os, sys; print(os.path.realpath(sys.base_prefix))')"
        )
        validation_condition = "\n".join(
            (
                'if ! test -x "$python_env/bin/python" \\',
                '  || ! test "$("$python_env/bin/python" -c '
                "'import os, sys; print(os.path.realpath(sys.base_prefix))')\" "
                '= "$module_python_base" \\',
                '  || ! "$python_env/bin/python" -m pip --version '
                ">/dev/null 2>&1; then",
            )
        )
        backup_recovery = "\n".join(
            (
                '  if test -e "$python_env" || test -L "$python_env"; then',
                '    invalid_python_env="$root/backups/'
                'python-invalid-$SLURM_JOB_ID"',
                '    test ! -e "$invalid_python_env"',
                '    test ! -L "$invalid_python_env"',
                '    mv "$python_env" "$invalid_python_env"',
                "  fi",
                '  python -m venv "$python_env"',
                "fi",
            )
        )
        pip_gate = '"$python_env/bin/python" -m pip --version'
        activation = 'source "$python_env/bin/activate"'
        pip_upgrade = "python -m pip install --upgrade pip"
        requirements_install = (
            'python -m pip install --requirement '
            '"$project/backend/requirements-107cup.txt"'
        )
        postcondition_install = "\n".join(
            (pip_gate, activation, pip_upgrade, requirements_install)
        )

        module_loads = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("module load ")
        ]
        self.assertEqual([module_load], module_loads)
        for required in (
            module_init,
            backups_directory,
            module_python_base,
            validation_condition,
            backup_recovery,
            postcondition_install,
        ):
            self.assertIn(required, source)

        positions = [
            source.index(module_init),
            source.index(module_load),
            source.index(backups_directory),
            source.index(module_python_base),
            source.index(validation_condition),
            source.index(backup_recovery),
            source.index(postcondition_install),
        ]
        self.assertEqual(sorted(positions), positions)

    def test_service_job_runs_single_uvicorn_and_applies_both_migrations(self):
        source = self.read_required("service.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=4-00:00:00",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
            "uvicorn main_107cup:app",
            "--workers 1",
            "service_recovery.py",
            "publish",
            "/api/health/live",
            "/api/health/ready",
            "trap shutdown_server TERM INT",
            'wait "$server_pid"',
            "migrate-competition-roles.py",
            "--operator-alias",
        ):
            self.assertIn(required, source)
        for forbidden in ("celery worker", "celery beat", "redis-server", "gunicorn"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("#SBATCH --time=7-00:00:00", source)
        self.assertNotIn("exec uvicorn", source)
        self.assertLess(source.index("uvicorn main_107cup:app"), source.index(" publish "))

    def test_service_recovery_is_bounded_owned_and_single_candidate(self):
        source = self.read_required("service_recovery.py")
        wrapper = self.read_required("recover-service.sh")
        for required in (
            "/home/scc/pb23030683/lmatelab-107cup",
            "/home/scc/pb23030683/projects/LMateLab-107Cup",
            "/usr/bin/scontrol",
            "/usr/bin/sbatch",
            "service-recovery.lock",
            "service-state.json",
            "service-recovery-state.json",
            "candidate_job_id",
            "retry_budget_exhausted",
            "candidate_ownership_mismatch",
            "--parsable",
        ):
            self.assertIn(required, source)
        self.assertIn("max_attempts: int = 3", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("scancel", source)
        self.assertIn("service_recovery.py\" recover", wrapper)
        for forbidden in ("uvicorn", "npm ", "pip install", "while true"):
            self.assertNotIn(forbidden, wrapper)

    def test_relay_recovery_probes_candidate_before_switch_and_preserves_crontab(self):
        relay = self.read_required("relay/ensure_forward.py")
        installer = self.read_required("relay/install-recovery.sh")
        reauth = self.read_required("relay/reauth-control-master.sh")
        for required in (
            "CONTROL_SOCKET",
            "cm-107cup",
            "MAIN_PORT = 18740",
            "PROBE_PORT = 18742",
            "node_to_target",
            "unknown_existing_forward",
            "forward_rollback_failed",
            "maintenance_marker_unsafe",
            "BatchMode=yes",
            "--adopt-current",
        ):
            self.assertIn(required, relay)
        self.assertNotIn("shell=True", relay)
        self.assertNotIn("password", relay.lower())
        self.assertLess(
            relay.index("self.control.forward(PROBE_PORT"),
            relay.index("self.control.cancel(MAIN_PORT"),
        )
        for required in (
            "BEGIN LMATELAB 107CUP RELAY RECOVERY",
            "crontab -l",
            'crontab "$updated"',
            "* * * * *",
            "@reboot",
            "--adopt-current",
            "seen_begin != seen_end",
        ):
            self.assertIn(required, installer)
        self.assertIn("1048576", self.read_required("relay/ensure-forward.sh"))
        self.assertIn("ControlPersist=96h", reauth)
        self.assertIn("IdentitiesOnly=yes", reauth)
        self.assertIn("id_ed25519_107cup", reauth)

    def test_rollback_smoke_is_isolated_and_exits_after_self_check(self):
        source = self.read_required("rollback-smoke.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=00:10:00",
            "LMATELAB_ROLLBACK_RELEASE",
            '[[ "$LMATELAB_ROLLBACK_RELEASE" =~ ^[0-9a-f]{40}$ ]]',
            "umask 077",
            "sha256sum -c manifest.sha256",
            "rollback-current.next",
            "mv -Tf",
            "production_current_before",
            "production_current_after",
            'test "$production_current_before" = "$production_current_after"',
            "DATABASE_URL",
            "DIGEST_DATABASE_URL",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
            "rollback-smoke@example.invalid",
            "rollback-smoke-placeholder",
            "uvicorn main_107cup:app",
            "/api/health/live",
            "/api/health/ready",
            "kill -TERM",
            "wait",
            "set +e",
            "server_status=$?",
            "server-exit-status.txt",
            "Application shutdown complete",
            "Finished server process",
            "integrity_check",
        ):
            self.assertIn(required, source)

        for forbidden in (
            '"$root/current"',
            '"$root/data',
            '"$root/runtime/service-',
            "npm ",
            "pip install",
            "build.slurm",
        ):
            self.assertNotIn(forbidden, source)

        primary_migration = source.index("alembic -c alembic.ini upgrade head")
        synthetic_operator = source.index("rollback-smoke@example.invalid")
        role_migration = source.index("migrate-competition-roles.py")
        self.assertLess(primary_migration, synthetic_operator)
        self.assertLess(synthetic_operator, role_migration)

        controlled_shutdown = source.index('kill -TERM "$server_pid"')
        allow_expected_signal = source.index("set +e", controlled_shutdown)
        wait_for_server = source.index('wait "$server_pid"', allow_expected_signal)
        capture_status = source.index("server_status=$?", wait_for_server)
        restore_errexit = source.index("set -e", capture_status)
        self.assertLess(controlled_shutdown, allow_expected_signal)
        self.assertLess(allow_expected_signal, wait_for_server)
        self.assertLess(wait_for_server, capture_status)
        self.assertLess(capture_status, restore_errexit)

    def test_viewer_provision_job_is_short_private_and_has_no_service_process(self):
        source = self.read_required("provision-viewer.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "umask 077",
            "demo-viewer.password",
            "demo-viewer@matflow.top",
            "secrets.token_urlsafe",
            "os.O_EXCL",
            "provision-competition-viewer.py",
            "evidence/access",
            "integrity_check",
        ):
            self.assertIn(required, source)
        for forbidden in ("uvicorn", "npm ", "pip install", "celery", "redis-server"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("@lmatelab.invalid", source)

    def test_login_node_helpers_only_submit_or_verify(self):
        build_submit = self.read_required("submit-build.sh")
        service_submit = self.read_required("submit-service.sh")
        service_recover = self.read_required("recover-service.sh")
        verifier = self.read_required("verify-runtime.sh")

        self.assertIn("sbatch --parsable", build_submit)
        self.assertIn("recover-service.sh", service_submit)
        self.assertIn("service_recovery.py", service_recover)
        for source in (build_submit, service_submit, service_recover):
            self.assertNotIn("uvicorn", source)
            self.assertNotIn("npm ", source)
            self.assertNotIn("pip install", source)

        for required in (
            "squeue",
            "sacct",
            "/api/health/live",
            "/api/health/ready",
            "sqlite3",
            "integrity_check",
        ):
            self.assertIn(required, verifier)

    def test_runtime_example_keeps_every_writable_path_under_107_root(self):
        source = self.read_required("runtime.env.example")
        root = "/home/scc/pb23030683/lmatelab-107cup"
        for variable in (
            "LMATELAB_ROOT",
            "DATABASE_URL",
            "DIGEST_DATABASE_URL",
            "LMATELAB_DATA_DIR",
            "UPLOADS_ROOT",
            "ALLOWED_USERS_PATH",
            "SECURITY_POLICY_PATH",
            "ISSUES_DIR",
            "CHANGELOG_PATH",
            "ACADEMIC_REPORTS_FILE",
            "VASP_CUSTOM_DB_ROOT",
            "QE_EPW_CUSTOM_DB_ROOT",
        ):
            line = next((item for item in source.splitlines() if item.startswith(f"{variable}=")), "")
            self.assertTrue(line, variable)
            self.assertIn(root, line, line)
        self.assertIn("LMATELAB_SLURM_USER=pb23030683", source)
        self.assertIn(
            "LMATELAB_SLURM_PROBE_SCRIPT=/home/scc/pb23030683/lmatelab-107cup/current/deploy/107cup/slurm/probe.slurm",
            source,
        )

    def test_allowed_users_example_is_fresh_competition_identity(self):
        source = self.read_required("allowed_users.example.json")
        data = json.loads(source)
        self.assertEqual(1, len(data["users"]))
        user = data["users"][0]
        self.assertEqual("107杯管理员", user["nameCN"])
        self.assertEqual("pb23030683", user["aliasEN"])
        self.assertEqual("operator", user["role"])
        self.assertTrue(user["enabled"])
        self.assertTrue(user["asedbdir"].startswith("/home/scc/pb23030683/lmatelab-107cup/"))

    def test_security_policy_is_deployable_without_production_config(self):
        source = self.read_required("security_policy.json")
        policy = json.loads(source)["password"]
        self.assertGreaterEqual(policy["minLength"], 10)
        self.assertTrue(policy["requireUpper"])
        self.assertTrue(policy["requireLower"])
        self.assertTrue(policy["allowedPattern"])

    def test_competition_runtime_disables_public_account_changes(self):
        source = self.read_required("runtime.env.example")
        self.assertIn("LMATELAB_REGISTRATION_ENABLED=0", source)
        self.assertIn("LMATELAB_PASSWORD_RESET_ENABLED=0", source)

    def test_public_relay_allows_login_but_rejects_business_writes(self):
        relay = self.read_required("relay/nginx.conf.example")
        self.assertIn("listen 18733", relay)
        self.assertIn("client_body_temp_path /home/Pwjb/.config/lmatelab-107cup-proxy/client-body", relay)
        self.assertIn("proxy_temp_path /home/Pwjb/.config/lmatelab-107cup-proxy/proxy-temp", relay)
        self.assertIn("proxy_http_version 1.1", relay)
        self.assertIn("proxy_buffering off", relay)
        self.assertIn("location = /api/auth/login", relay)
        self.assertIn("location = /api/auth/change-password", relay)
        change_password = relay.split("location = /api/auth/change-password", 1)[1].split(
            "location /api/", 1
        )[0]
        self.assertIn("limit_except POST", change_password)
        self.assertIn("deny all", change_password)
        self.assertIn("proxy_pass http://127.0.0.1:18734", change_password)
        self.assertIn("limit_except POST", relay)
        self.assertIn("location /api/", relay)
        self.assertIn("limit_except GET", relay)
        self.assertIn("deny all", relay)
        self.assertIn("allow 114.214.203.210", relay)
        self.assertIn("proxy_pass http://127.0.0.1:18734", relay)


if __name__ == "__main__":
    unittest.main()
