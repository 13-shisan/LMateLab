from pathlib import Path


def get_status_file(base_dir: Path, server_name: str) -> Path:
    return base_dir / server_name / "status.json"


def get_history_dir(base_dir: Path, server_name: str) -> Path:
    return base_dir / server_name / "history"


def get_user_limits_file(base_dir: Path, server_name: str) -> Path:
    return base_dir / server_name / "user_limits.json"
