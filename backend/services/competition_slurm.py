from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None


FIXED_STEPS = frozenset({"relax", "scf", "band", "dos"})
PROBE_MODES = frozenset({"success", "fail", "cancel"})
RUNNER_MODES = {
    "probe": PROBE_MODES,
    "vasp": FIXED_STEPS,
}
_JOB_ID_RE = re.compile(r"^([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?$")
_LOG_NAMES = {"stdout": "stdout.log", "stderr": "stderr.log"}
_MAX_SUBMISSION_SCRIPT_BYTES = 1024 * 1024
_SCRIPT_READ_CHUNK_BYTES = 64 * 1024
_IS_LINUX = sys.platform.startswith("linux")


class SlurmError(RuntimeError):
    pass


class SlurmCommandError(SlurmError):
    pass


class SlurmCommandTimeout(SlurmError):
    pass


class SlurmOutputTooLarge(SlurmError):
    pass


def _script_stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _hash_script_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > _MAX_SUBMISSION_SCRIPT_BYTES
        ):
            raise ValueError("submission script is invalid")
        os.lseek(descriptor, 0, os.SEEK_SET)
        total = 0
        while chunk := os.read(descriptor, _SCRIPT_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > _MAX_SUBMISSION_SCRIPT_BYTES:
                raise ValueError("submission script is invalid")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            total != before.st_size
            or _script_stat_signature(before) != _script_stat_signature(after)
        ):
            raise ValueError("submission script changed while hashing")
        os.lseek(descriptor, 0, os.SEEK_SET)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("submission script is unavailable") from exc
    return digest.hexdigest()


def _open_hashed_script(path: Path) -> tuple[int, str]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("submission script is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(candidate, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("submission script is unavailable") from exc
    try:
        return descriptor, _hash_script_descriptor(descriptor)
    except BaseException:
        os.close(descriptor)
        raise


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written < 1:
            raise OSError("submission script snapshot write failed")
        remaining = remaining[written:]


def _copy_script_descriptor(source: int, destination: int) -> str:
    digest = hashlib.sha256()
    try:
        before = os.fstat(source)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > _MAX_SUBMISSION_SCRIPT_BYTES
        ):
            raise ValueError("submission script is invalid")
        os.lseek(source, 0, os.SEEK_SET)
        os.lseek(destination, 0, os.SEEK_SET)
        os.ftruncate(destination, 0)
        total = 0
        while chunk := os.read(source, _SCRIPT_READ_CHUNK_BYTES):
            total += len(chunk)
            if total > _MAX_SUBMISSION_SCRIPT_BYTES:
                raise ValueError("submission script is invalid")
            _write_all(destination, chunk)
            digest.update(chunk)
        after = os.fstat(source)
        if total != before.st_size or _script_stat_signature(before) != _script_stat_signature(after):
            raise ValueError("submission script changed while copying")

        snapshot = os.fstat(destination)
        if not stat.S_ISREG(snapshot.st_mode) or snapshot.st_size != total:
            raise ValueError("submission script snapshot is invalid")
        os.lseek(destination, 0, os.SEEK_SET)
        if _hash_script_descriptor(destination) != digest.hexdigest():
            raise ValueError("submission script snapshot identity changed")
        os.lseek(destination, 0, os.SEEK_SET)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("submission script snapshot is unavailable") from exc
    return digest.hexdigest()


def _create_private_snapshot_descriptor() -> int:
    if _IS_LINUX:
        memfd_create = getattr(os, "memfd_create", None)
        allow_sealing = getattr(os, "MFD_ALLOW_SEALING", None)
        close_on_exec = getattr(os, "MFD_CLOEXEC", None)
        if memfd_create is None or allow_sealing is None or close_on_exec is None:
            raise ValueError("submission script snapshot is unavailable")
        try:
            return memfd_create(
                "lmatelab-slurm-script",
                allow_sealing | close_on_exec,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError("submission script snapshot is unavailable") from exc

    raise ValueError("submission script snapshot is unavailable")


def _seal_linux_snapshot(descriptor: int) -> None:
    if _fcntl is None:
        raise ValueError("submission script snapshot is unavailable")
    required_names = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_WRITE",
        "F_SEAL_GROW",
        "F_SEAL_SHRINK",
        "F_SEAL_SEAL",
    )
    if any(not hasattr(_fcntl, name) for name in required_names):
        raise ValueError("submission script snapshot is unavailable")
    required_seals = (
        _fcntl.F_SEAL_WRITE
        | _fcntl.F_SEAL_GROW
        | _fcntl.F_SEAL_SHRINK
        | _fcntl.F_SEAL_SEAL
    )
    try:
        _fcntl.fcntl(descriptor, _fcntl.F_ADD_SEALS, required_seals)
        applied_seals = _fcntl.fcntl(descriptor, _fcntl.F_GET_SEALS)
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("submission script snapshot is unavailable") from exc
    if applied_seals & required_seals != required_seals:
        raise ValueError("submission script snapshot is unavailable")


def _snapshot_script_descriptor(
    source: int,
) -> tuple[int, str]:
    snapshot = _create_private_snapshot_descriptor()
    try:
        digest = _copy_script_descriptor(source, snapshot)
        if _IS_LINUX:
            _seal_linux_snapshot(snapshot)
            if _hash_script_descriptor(snapshot) != digest:
                raise ValueError("submission script snapshot identity changed")
        os.lseek(snapshot, 0, os.SEEK_SET)
        return snapshot, digest
    except BaseException:
        os.close(snapshot)
        raise


def calculate_script_sha256(path: Path) -> str:
    descriptor, digest = _open_hashed_script(path)
    try:
        return digest
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class SlurmBinaries:
    sbatch: str = "/usr/bin/sbatch"
    squeue: str = "/usr/bin/squeue"
    scontrol: str = "/usr/bin/scontrol"
    sacct: str = "/usr/bin/sacct"
    scancel: str = "/usr/bin/scancel"

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            path = PurePosixPath(value)
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError(f"{field.name} must be a fixed absolute POSIX path")


@dataclass(frozen=True)
class SlurmCommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class SlurmSubmission:
    workflow_id: str
    attempt_id: str
    step_key: str
    attempt_number: int
    attempt_directory: Path
    script_path: Path
    runner_kind: str
    runner_mode: str
    script_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_canonical_uuid("workflow_id", self.workflow_id)
        _validate_canonical_uuid("attempt_id", self.attempt_id)
        if self.step_key not in FIXED_STEPS:
            raise ValueError("step_key is not part of the fixed workflow")
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("attempt_number must be a positive integer")
        if self.runner_mode not in RUNNER_MODES.get(self.runner_kind, frozenset()):
            raise ValueError("runner mode is not allowed")
        object.__setattr__(
            self,
            "script_sha256",
            calculate_script_sha256(self.script_path),
        )

    @property
    def job_name(self) -> str:
        return f"lmatelab-{self.workflow_id[:8]}-{self.step_key}-a{self.attempt_number}"

    @property
    def comment(self) -> str:
        return (
            f"lmatelab:workflow={self.workflow_id};attempt={self.attempt_id};"
            f"runner={self.runner_kind};mode={self.runner_mode};"
            f"script_sha256={self.script_sha256}"
        )


@dataclass(frozen=True)
class SlurmJobObservation:
    job_id: str
    raw_state: str | None
    state: str
    exit_code: str | None
    reason: str | None
    source: str
    job_name: str | None
    working_directory: str | None
    comment: str | None
    user_name: str | None
    node_list: str | None
    observed_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stale: bool = False
    error_code: str | None = None
    payload_sha256: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_canonical_uuid(name: str, value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID")
    return value


class SlurmClient:
    def __init__(
        self,
        *,
        binaries: SlurmBinaries | None = None,
        executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        timeout_seconds: float = 5.0,
        max_output_bytes: int = 1024 * 1024,
        allowed_scripts: Iterable[Path] = (),
        clock: Callable[[], datetime] = _utc_now,
        workflow_root: Path | None = None,
        max_log_tail_bytes: int = 64 * 1024,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        if max_log_tail_bytes < 1:
            raise ValueError("max_log_tail_bytes must be positive")
        self.binaries = binaries or SlurmBinaries()
        self._executor = executor
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = int(max_output_bytes)
        self._allowed_scripts = frozenset(Path(path).resolve() for path in allowed_scripts)
        self._clock = clock
        self.workflow_root = Path(workflow_root).resolve() if workflow_root is not None else None
        self.max_log_tail_bytes = int(max_log_tail_bytes)

    @staticmethod
    def _decode(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip()
        return str(value).strip()

    @staticmethod
    def _byte_length(value: bytes | str | None) -> int:
        if value is None:
            return 0
        if isinstance(value, bytes):
            return len(value)
        return len(value.encode("utf-8", errors="replace"))

    def _run(
        self,
        argv: list[str],
        *,
        pass_fds: tuple[int, ...] = (),
    ) -> SlurmCommandResult:
        command_name = PurePosixPath(argv[0]).name
        run_kwargs = {
            "shell": False,
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": self.timeout_seconds,
        }
        if pass_fds:
            run_kwargs["pass_fds"] = pass_fds
        try:
            completed = self._executor(
                argv,
                **run_kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            raise SlurmCommandTimeout(f"{command_name} timed out") from exc
        if (
            self._byte_length(completed.stdout) > self.max_output_bytes
            or self._byte_length(completed.stderr) > self.max_output_bytes
        ):
            raise SlurmOutputTooLarge(f"{command_name} output exceeded the configured limit")
        result = SlurmCommandResult(
            stdout=self._decode(completed.stdout),
            stderr=self._decode(completed.stderr),
            returncode=int(completed.returncode),
        )
        if result.returncode != 0:
            raise SlurmCommandError(f"{command_name} failed")
        return result

    def _open_submission_script(self, submission: SlurmSubmission) -> int:
        candidate = Path(submission.script_path)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("submission script is unavailable") from exc
        if resolved not in self._allowed_scripts:
            raise ValueError("submission script is not allowlisted")
        source, source_digest = _open_hashed_script(candidate)
        snapshot = None
        try:
            if source_digest != submission.script_sha256:
                raise ValueError("submission script identity changed")
            snapshot, snapshot_digest = _snapshot_script_descriptor(source)
            if snapshot_digest != submission.script_sha256:
                raise ValueError("submission script identity changed")
            return snapshot
        except BaseException:
            if snapshot is not None:
                os.close(snapshot)
            raise
        finally:
            os.close(source)

    def _submission_argv(
        self,
        submission: SlurmSubmission,
        *,
        test_only: bool,
        script_argument: str,
    ) -> list[str]:
        attempt_directory = self._attempt_directory(
            submission.workflow_id,
            submission.attempt_id,
            create=False,
        )
        if submission.attempt_directory.is_symlink():
            raise ValueError("submission attempt directory cannot be a symlink")
        if submission.attempt_directory.resolve() != attempt_directory:
            raise ValueError("submission attempt directory does not match the ledger path")
        argv = [self.binaries.sbatch]
        if test_only:
            argv.append("--test-only")
        argv.extend(
            [
                "--parsable",
                f"--job-name={submission.job_name}",
                f"--comment={submission.comment}",
                f"--chdir={attempt_directory}",
                f"--output={attempt_directory / 'stdout.log'}",
                f"--error={attempt_directory / 'stderr.log'}",
                script_argument,
                submission.runner_mode,
                submission.workflow_id,
                submission.attempt_id,
            ]
        )
        return argv

    def _run_submission(
        self,
        submission: SlurmSubmission,
        *,
        test_only: bool,
    ) -> SlurmCommandResult:
        descriptor = self._open_submission_script(submission)
        try:
            return self._run(
                self._submission_argv(
                    submission,
                    test_only=test_only,
                    script_argument=f"/proc/self/fd/{descriptor}",
                ),
                pass_fds=(descriptor,),
            )
        finally:
            os.close(descriptor)

    def test_submission(self, submission: SlurmSubmission) -> SlurmCommandResult:
        return self._run_submission(submission, test_only=True)

    def submit(self, submission: SlurmSubmission) -> str:
        result = self._run_submission(submission, test_only=False)
        match = _JOB_ID_RE.fullmatch(result.stdout)
        if match is None:
            raise ValueError("sbatch returned an invalid job id")
        return match.group(1)

    def _require_workflow_root(self) -> Path:
        if self.workflow_root is None:
            raise ValueError("workflow_root is required for filesystem operations")
        return self.workflow_root

    @staticmethod
    def _set_private_mode(path: Path, mode: int) -> None:
        path.chmod(mode)

    def _attempt_directory(
        self,
        workflow_id: str,
        attempt_id: str,
        *,
        create: bool,
    ) -> Path:
        workflow_id = _validate_canonical_uuid("workflow_id", workflow_id)
        attempt_id = _validate_canonical_uuid("attempt_id", attempt_id)
        root = self._require_workflow_root()
        candidate = root / workflow_id / "attempts" / attempt_id
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("attempt directory escapes the workflow root")
        if candidate.is_symlink():
            raise ValueError("attempt directory cannot be a symlink")

        if create:
            directories = (root, root / workflow_id, root / workflow_id / "attempts", candidate)
            for directory in directories:
                if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
                    raise ValueError("attempt directory path is not a real directory")
                directory.mkdir(exist_ok=True)
                self._set_private_mode(directory, 0o700)
        elif not candidate.is_dir():
            raise ValueError("attempt directory does not exist")

        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved != candidate.absolute():
            raise ValueError("attempt directory is not the exact ledger path")
        return candidate

    def prepare_attempt_directory(self, workflow_id: str, attempt_id: str) -> Path:
        return self._attempt_directory(workflow_id, attempt_id, create=True)

    def write_job_receipt(self, workflow_id: str, attempt_id: str, job_id: str) -> Path:
        job_id = self._validate_job_id(job_id)
        attempt_directory = self._attempt_directory(workflow_id, attempt_id, create=False)
        receipt = attempt_directory / "job-id.receipt"
        if receipt.is_symlink():
            raise ValueError("job receipt cannot be a symlink")
        if receipt.exists():
            existing = receipt.read_text(encoding="ascii").strip()
            if existing == job_id:
                return receipt
            raise ValueError("job receipt already contains a different job id")
        temporary = attempt_directory / f".job-id.receipt.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
                descriptor = None
                handle.write(f"{job_id}\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, receipt, follow_symlinks=False)
            except FileExistsError:
                if receipt.is_symlink() or receipt.read_text(encoding="ascii").strip() != job_id:
                    raise ValueError("job receipt already contains a different job id")
            self._set_private_mode(receipt, 0o600)
            return receipt
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def read_job_receipt(self, workflow_id: str, attempt_id: str) -> str:
        attempt_directory = self._attempt_directory(workflow_id, attempt_id, create=False)
        receipt = attempt_directory / "job-id.receipt"
        if receipt.is_symlink():
            raise ValueError("job receipt cannot be a symlink")
        try:
            receipt_stat = receipt.stat()
        except OSError as exc:
            raise ValueError("job receipt is unavailable") from exc
        if not stat.S_ISREG(receipt_stat.st_mode) or receipt_stat.st_size > 128:
            raise ValueError("job receipt is invalid")
        try:
            value = receipt.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError("job receipt is invalid") from exc
        return self._validate_job_id(value)

    def read_log_tail(
        self,
        workflow_id: str,
        attempt_id: str,
        stream: str,
    ) -> str:
        if stream not in _LOG_NAMES:
            raise ValueError("stream must be stdout or stderr")
        attempt_directory = self._attempt_directory(workflow_id, attempt_id, create=False)
        path = attempt_directory / _LOG_NAMES[stream]
        if path.is_symlink():
            raise ValueError("log file cannot be a symlink")
        if not path.exists():
            return ""

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValueError("log file could not be opened safely") from exc
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("log path is not a regular file")
            os.lseek(descriptor, max(0, file_stat.st_size - self.max_log_tail_bytes), os.SEEK_SET)
            payload = os.read(descriptor, self.max_log_tail_bytes)
        finally:
            os.close(descriptor)
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        if not isinstance(job_id, str) or re.fullmatch(r"[1-9][0-9]*", job_id) is None:
            raise ValueError("job_id must contain positive decimal digits")
        return job_id

    @staticmethod
    def map_state(raw_state: str, exit_code: str | None) -> str:
        normalized = raw_state.strip().upper().split("+", 1)[0].split(None, 1)[0]
        if normalized in {
            "PENDING",
            "CONFIGURING",
            "REQUEUED",
            "REQUEUE_FED",
            "RESV_DEL_HOLD",
        }:
            return "queued"
        if normalized in {"RUNNING", "COMPLETING", "SIGNALING", "STAGE_OUT"}:
            return "running"
        if normalized == "COMPLETED":
            return "succeeded" if exit_code == "0:0" else "failed"
        if normalized == "CANCELLED":
            return "cancelled"
        if normalized in {
            "BOOT_FAIL",
            "DEADLINE",
            "FAILED",
            "NODE_FAIL",
            "OUT_OF_MEMORY",
            "PREEMPTED",
            "REVOKED",
            "SPECIAL_EXIT",
            "TIMEOUT",
        }:
            return "failed"
        return "unknown"

    @staticmethod
    def _nested_number(value: Any, *keys: str) -> int | None:
        current = value
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        if isinstance(current, bool) or not isinstance(current, int):
            return None
        return current

    @classmethod
    def _exit_code(cls, record: dict[str, Any]) -> str | None:
        value = record.get("exit_code")
        if isinstance(value, str):
            return value
        return_code = cls._nested_number(value, "return_code", "number")
        signal = cls._nested_number(value, "signal", "id", "number")
        if return_code is None or signal is None:
            return None
        return f"{return_code}:{signal}"

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if not isinstance(value, dict) or value.get("set") is not True:
            return None
        number = value.get("number")
        if isinstance(number, bool) or not isinstance(number, (int, float)) or number <= 0:
            return None
        return datetime.fromtimestamp(number, tz=timezone.utc)

    @staticmethod
    def _raw_state(record: dict[str, Any]) -> str | None:
        value = record.get("job_state", record.get("state"))
        if isinstance(value, dict):
            value = value.get("current")
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    @staticmethod
    def _string_field(record: dict[str, Any], *names: str) -> str | None:
        for name in names:
            value = record.get(name)
            if isinstance(value, str):
                return value
        return None

    @classmethod
    def _reason(cls, record: dict[str, Any]) -> str | None:
        direct = cls._string_field(record, "state_reason")
        if direct is not None:
            return direct
        state = record.get("state")
        if isinstance(state, dict) and isinstance(state.get("reason"), str):
            return state["reason"]
        return None

    @classmethod
    def _record_timestamp(
        cls,
        record: dict[str, Any],
        direct_name: str,
        nested_name: str,
    ) -> datetime | None:
        direct = cls._timestamp(record.get(direct_name))
        if direct is not None:
            return direct
        time_fields = record.get("time")
        if not isinstance(time_fields, dict):
            return None
        return cls._timestamp(time_fields.get(nested_name))

    @staticmethod
    def _matching_record(payload: str, job_id: str) -> dict[str, Any] | None:
        parsed = json.loads(payload)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("jobs"), list):
            raise ValueError("Slurm JSON payload does not contain a jobs list")
        for record in parsed["jobs"]:
            if isinstance(record, dict) and str(record.get("job_id")) == job_id:
                return record
        return None

    def _observation_from_record(
        self,
        *,
        job_id: str,
        source: str,
        record: dict[str, Any],
        observed_at: datetime,
        payload_sha256: str,
    ) -> SlurmJobObservation:
        raw_state = self._raw_state(record)
        exit_code = self._exit_code(record)
        state = self.map_state(raw_state, exit_code) if raw_state is not None else "unknown"
        return SlurmJobObservation(
            job_id=job_id,
            raw_state=raw_state,
            state=state,
            exit_code=exit_code,
            reason=self._reason(record),
            source=source,
            job_name=self._string_field(record, "name"),
            working_directory=self._string_field(
                record, "current_working_directory", "working_directory"
            ),
            comment=self._string_field(record, "comment"),
            user_name=self._string_field(record, "user_name", "user"),
            node_list=self._string_field(record, "nodes"),
            observed_at=observed_at,
            started_at=self._record_timestamp(record, "start_time", "start"),
            finished_at=self._record_timestamp(record, "end_time", "end"),
            error_code="scheduler_state_unknown" if state == "unknown" else None,
            payload_sha256=payload_sha256,
        )

    def observe(self, job_id: str) -> SlurmJobObservation:
        job_id = self._validate_job_id(job_id)
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")

        commands = (
            ("squeue", [self.binaries.squeue, "--json", f"--jobs={job_id}"]),
            ("scontrol", [self.binaries.scontrol, "--json", "show", "job", job_id]),
            ("sacct", [self.binaries.sacct, "--json", f"--jobs={job_id}"]),
        )
        invalid_payload_sha256: str | None = None
        for source, argv in commands:
            try:
                result = self._run(argv)
            except SlurmError:
                continue
            payload_sha256 = hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
            try:
                record = self._matching_record(result.stdout, job_id)
            except (json.JSONDecodeError, ValueError):
                if invalid_payload_sha256 is None:
                    invalid_payload_sha256 = payload_sha256
                continue
            if record is not None:
                return self._observation_from_record(
                    job_id=job_id,
                    source=source,
                    record=record,
                    observed_at=observed_at,
                    payload_sha256=payload_sha256,
                )

        return SlurmJobObservation(
            job_id=job_id,
            raw_state=None,
            state="unknown",
            exit_code=None,
            reason=None,
            source="unavailable",
            job_name=None,
            working_directory=None,
            comment=None,
            user_name=None,
            node_list=None,
            observed_at=observed_at,
            stale=True,
            error_code=(
                "scheduler_payload_invalid"
                if invalid_payload_sha256 is not None
                else "scheduler_record_unavailable"
            ),
            payload_sha256=invalid_payload_sha256,
        )

    def inspect_job(self, job_id: str) -> SlurmJobObservation:
        job_id = self._validate_job_id(job_id)
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        result = self._run(
            [self.binaries.scontrol, "--json", "show", "job", job_id]
        )
        payload_sha256 = hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        try:
            record = self._matching_record(result.stdout, job_id)
        except (json.JSONDecodeError, ValueError):
            return SlurmJobObservation(
                job_id=job_id,
                raw_state=None,
                state="unknown",
                exit_code=None,
                reason=None,
                source="scontrol",
                job_name=None,
                working_directory=None,
                comment=None,
                user_name=None,
                node_list=None,
                observed_at=observed_at,
                stale=True,
                error_code="scheduler_payload_invalid",
                payload_sha256=payload_sha256,
            )
        if record is None:
            return SlurmJobObservation(
                job_id=job_id,
                raw_state=None,
                state="unknown",
                exit_code=None,
                reason=None,
                source="scontrol",
                job_name=None,
                working_directory=None,
                comment=None,
                user_name=None,
                node_list=None,
                observed_at=observed_at,
                stale=True,
                error_code="scheduler_record_unavailable",
                payload_sha256=payload_sha256,
            )
        return self._observation_from_record(
            job_id=job_id,
            source="scontrol",
            record=record,
            observed_at=observed_at,
            payload_sha256=payload_sha256,
        )

    def cancel(self, job_id: str) -> SlurmCommandResult:
        job_id = self._validate_job_id(job_id)
        return self._run([self.binaries.scancel, job_id])
