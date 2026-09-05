#!/usr/bin/env python3
"""Import an authenticated 18755 Agent history export into the 107 database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path


EXPORT_FORMAT = "lmatelab-competition-agent-history-v1"
TERMINAL_STATUSES = {"succeeded", "failed"}
REQUEST_KINDS = {
    "auto",
    "calculation_planning",
    "general_qa",
    "file_analysis",
    "template_recommendation",
    "result_analysis",
}
PROVIDERS = {"mock", "qoder", "llm"}
REQUIRED_TABLES = {"users", "workflow_runs", "competition_agent_runs"}


class AgentHistoryMigrationError(RuntimeError):
    pass


def _regular_file(path: Path, *, maximum_bytes: int, private: bool) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise AgentHistoryMigrationError(f"file is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AgentHistoryMigrationError(f"file must be regular and not a symlink: {path}")
    if not 0 < metadata.st_size <= maximum_bytes:
        raise AgentHistoryMigrationError(f"file size is outside the allowed range: {path}")
    if private and os.name == "posix":
        if metadata.st_uid != os.getuid():
            raise AgentHistoryMigrationError(f"file is not owned by the current user: {path}")
        if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise AgentHistoryMigrationError(f"file permissions must be 0600 or stricter: {path}")
    return path.resolve()


def _canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AgentHistoryMigrationError(f"{field} must be a UUID string")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise AgentHistoryMigrationError(f"{field} is not a valid UUID") from exc
    if parsed != value:
        raise AgentHistoryMigrationError(f"{field} must use canonical lowercase UUID form")
    return parsed


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AgentHistoryMigrationError(f"{field} must be an ISO timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AgentHistoryMigrationError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AgentHistoryMigrationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(sep=" ")


def _json_text(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, dict):
        raise AgentHistoryMigrationError(f"{field} must be an object")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validated_run(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise AgentHistoryMigrationError("every Agent history item must be an object")
    run_id = _canonical_uuid(item.get("id"), "run.id")
    request_kind = item.get("request_kind")
    provider = item.get("provider")
    status_value = item.get("status")
    if request_kind not in REQUEST_KINDS:
        raise AgentHistoryMigrationError(f"run {run_id} has an unsupported request kind")
    if provider not in PROVIDERS:
        raise AgentHistoryMigrationError(f"run {run_id} has an unsupported provider")
    if status_value not in TERMINAL_STATUSES:
        raise AgentHistoryMigrationError(f"run {run_id} is not terminal")
    prompt = item.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 2000 or "\x00" in prompt or "\r" in prompt:
        raise AgentHistoryMigrationError(f"run {run_id} has an invalid prompt")
    input_value = item.get("input")
    if not isinstance(input_value, dict):
        raise AgentHistoryMigrationError(f"run {run_id} input must be an object")
    input_value = dict(input_value)
    conversation_id = item.get("conversation_id")
    if conversation_id is not None:
        conversation_id = _canonical_uuid(conversation_id, "run.conversation_id")
        embedded = input_value.get("conversation_id")
        if embedded is not None and embedded != conversation_id:
            raise AgentHistoryMigrationError(f"run {run_id} conversation identity is inconsistent")
        input_value["conversation_id"] = conversation_id
    workflow_id = item.get("workflow_id")
    if workflow_id is not None:
        workflow_id = _canonical_uuid(workflow_id, "run.workflow_id")
    error_code = item.get("error_code")
    if error_code is not None and (not isinstance(error_code, str) or len(error_code) > 100):
        raise AgentHistoryMigrationError(f"run {run_id} has an invalid error code")
    approved = item.get("approved")
    if type(approved) is not bool:
        raise AgentHistoryMigrationError(f"run {run_id} approved must be boolean")
    created_at = _timestamp(item.get("created_at"), "run.created_at")
    updated_at = _timestamp(item.get("updated_at"), "run.updated_at")
    if datetime.fromisoformat(updated_at) < datetime.fromisoformat(created_at):
        raise AgentHistoryMigrationError(f"run {run_id} is updated before it was created")
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "request_kind": request_kind,
        "provider": provider,
        "status": status_value,
        "prompt_text": prompt,
        "input_json": _json_text(input_value, "run.input"),
        "output_json": _json_text(item.get("output"), "run.output", nullable=True),
        "error_code": error_code,
        "approved": approved,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def load_export(path: Path, owner_email: str) -> tuple[list[dict[str, object]], str]:
    source = _regular_file(path, maximum_bytes=64 * 1024 * 1024, private=True)
    payload_bytes = source.read_bytes()
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentHistoryMigrationError("source export is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
        raise AgentHistoryMigrationError("source export format is unsupported")
    if payload.get("complete") is not True:
        raise AgentHistoryMigrationError("source export is not proven complete")
    source_user = payload.get("source_user")
    source_email = source_user.get("email") if isinstance(source_user, dict) else None
    if not isinstance(source_email, str) or source_email.casefold() != owner_email.casefold():
        raise AgentHistoryMigrationError("source user does not match the target owner email")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > 1000:
        raise AgentHistoryMigrationError("source export items must be a list of at most 1000 runs")
    runs = [_validated_run(item) for item in items]
    ids = [str(item["id"]) for item in runs]
    if len(ids) != len(set(ids)):
        raise AgentHistoryMigrationError("source export contains duplicate run IDs")
    return runs, hashlib.sha256(payload_bytes).hexdigest()


def _connect_target(path: Path) -> sqlite3.Connection:
    target = _regular_file(
        path,
        maximum_bytes=16 * 1024 * 1024 * 1024,
        private=False,
    )
    connection = sqlite3.connect(target, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        connection.close()
        raise AgentHistoryMigrationError("target database integrity check failed")
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not REQUIRED_TABLES.issubset(tables):
        connection.close()
        raise AgentHistoryMigrationError("target database is missing required tables")
    return connection


def _existing_matches(row: sqlite3.Row, run: dict[str, object], owner_id: int) -> bool:
    def decoded(value: object) -> object:
        return None if value is None else json.loads(str(value))

    return all((
        row["owner_id"] == owner_id,
        row["workflow_id"] == run["workflow_id"],
        row["request_kind"] == run["request_kind"],
        row["provider"] == run["provider"],
        row["status"] == run["status"],
        row["prompt_text"] == run["prompt_text"],
        decoded(row["input_json"]) == decoded(run["input_json"]),
        decoded(row["output_json"]) == decoded(run["output_json"]),
        row["error_code"] == run["error_code"],
        (row["approved_at"] is not None) == run["approved"],
        _timestamp(str(row["created_at"]), "existing.created_at") == run["created_at"],
        _timestamp(str(row["updated_at"]), "existing.updated_at") == run["updated_at"],
    ))


def _backup(connection: sqlite3.Connection, backup_dir: Path, label: str) -> Path:
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    destination = backup_dir / f"eln.db.before-agent-history-{label}.sqlite"
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        backup = sqlite3.connect(destination)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        destination.chmod(0o600)
        verify = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
        try:
            if verify.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AgentHistoryMigrationError("backup database integrity check failed")
        finally:
            verify.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def migrate(
    *,
    source_export: Path,
    target_database: Path,
    owner_email: str,
    backup_dir: Path,
    label: str,
    apply: bool,
) -> dict[str, object]:
    runs, source_sha256 = load_export(source_export, owner_email)
    connection = _connect_target(target_database)
    try:
        users = connection.execute(
            "SELECT id FROM users WHERE lower(email)=lower(?)", (owner_email,)
        ).fetchall()
        if len(users) != 1:
            raise AgentHistoryMigrationError("target owner email must match exactly one user")
        owner_id = int(users[0]["id"])
        workflow_ids = {
            row[0] for row in connection.execute("SELECT id FROM workflow_runs")
        }
        detached_workflows: list[dict[str, str]] = []
        skipped_ids: list[str] = []
        pending: list[dict[str, object]] = []
        for run in runs:
            run = dict(run)
            if run["workflow_id"] is not None and run["workflow_id"] not in workflow_ids:
                detached_workflows.append({
                    "run_id": str(run["id"]),
                    "source_workflow_id": str(run["workflow_id"]),
                })
                run["workflow_id"] = None
            existing = connection.execute(
                "SELECT * FROM competition_agent_runs WHERE id=?", (run["id"],)
            ).fetchone()
            if existing is not None:
                if not _existing_matches(existing, run, owner_id):
                    raise AgentHistoryMigrationError(
                        f"target run ID conflicts with different content: {run['id']}"
                    )
                skipped_ids.append(str(run["id"]))
                continue
            pending.append(run)

        backup_path = None
        inserted_ids: list[str] = []
        if apply and pending:
            backup_path = _backup(connection, backup_dir, label)
            connection.execute("BEGIN IMMEDIATE")
            try:
                for run in pending:
                    approved_by = owner_id if run["approved"] else None
                    approved_at = run["updated_at"] if run["approved"] else None
                    connection.execute(
                        """
                        INSERT INTO competition_agent_runs (
                          id, owner_id, workflow_id, request_kind, provider, status,
                          prompt_text, input_json, output_json, error_code,
                          approved_by_id, approved_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run["id"], owner_id, run["workflow_id"], run["request_kind"],
                            run["provider"], run["status"], run["prompt_text"],
                            run["input_json"], run["output_json"], run["error_code"],
                            approved_by, approved_at, run["created_at"], run["updated_at"],
                        ),
                    )
                    inserted_ids.append(str(run["id"]))
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise AgentHistoryMigrationError("target foreign key check failed before commit")
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise AgentHistoryMigrationError("target integrity check failed before commit")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AgentHistoryMigrationError("target integrity check failed after import")
        return {
            "format": EXPORT_FORMAT,
            "mode": "apply" if apply else "dry-run",
            "source_sha256": source_sha256,
            "owner_email": owner_email,
            "source_count": len(runs),
            "inserted_count": len(inserted_ids),
            "skipped_identical_count": len(skipped_ids),
            "pending_count": len(pending) if not apply else 0,
            "detached_workflows": detached_workflows,
            "inserted_ids": inserted_ids,
            "skipped_identical_ids": skipped_ids,
            "backup_path": str(backup_path) if backup_path else None,
        }
    finally:
        connection.close()


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-export", type=Path, required=True)
    parser.add_argument("--target-database", type=Path, required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.owner_email or len(args.owner_email) > 320 or "@" not in args.owner_email:
        raise AgentHistoryMigrationError("owner email is invalid")
    if not args.label.isdigit() or not 1 <= len(args.label) <= 20:
        raise AgentHistoryMigrationError("label must be a numeric Slurm job ID")
    report = migrate(
        source_export=args.source_export,
        target_database=args.target_database,
        owner_email=args.owner_email,
        backup_dir=args.backup_dir,
        label=args.label,
        apply=args.apply,
    )
    _write_report(args.report, report)
    print(json.dumps({
        "mode": report["mode"],
        "source_count": report["source_count"],
        "inserted_count": report["inserted_count"],
        "skipped_identical_count": report["skipped_identical_count"],
        "detached_workflow_count": len(report["detached_workflows"]),
        "report": str(args.report),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
