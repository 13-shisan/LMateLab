from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    template_version: Literal["mos2_v1"]
    source_kind: Literal["builtin", "upload"]
    steps: list[str]
    parameters: dict[str, dict[str, int | float]]
    structure_upload_id: str | None = None


class StructureUploadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    relative_path: str
    size_bytes: int
    sha256: str
    source_format: str
    summary: dict[str, Any]


class WorkflowMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    input_sha256: str
    template_version: str
    source_kind: str
    structure_summary: dict[str, Any] = Field(default_factory=dict)


class LogTailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Literal["stdout", "stderr"]
    content: str
