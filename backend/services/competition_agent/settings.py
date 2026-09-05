from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


def settings_path(environ: Mapping[str, str] | None = None) -> Path | None:
    values = os.environ if environ is None else environ
    value = values.get("LMATELAB_AGENT_SETTINGS_FILE", "").strip()
    return Path(value) if value else None


def read_settings(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if environ is None else environ
    result = {
        "api_url": values.get("LMATELAB_LLM_API_URL", DEFAULT_API_URL),
        "model": values.get("LMATELAB_LLM_MODEL", DEFAULT_MODEL),
    }
    path = settings_path(values)
    if path and path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            result.update({key: value[key] for key in result if isinstance(value.get(key), str)})
    return result


def write_settings(api_url: str, model: str, environ: Mapping[str, str] | None = None) -> None:
    path = settings_path(environ)
    if path is None:
        raise RuntimeError("Agent settings file is not configured")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"api_url": api_url, "model": model}), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def write_api_key(api_key: str, environ: Mapping[str, str] | None = None) -> None:
    values = os.environ if environ is None else environ
    value = values.get("LMATELAB_LLM_API_KEY_FILE", "").strip()
    if not value:
        raise RuntimeError("LLM API key file is not configured")
    path = Path(value)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(api_key.strip(), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)
