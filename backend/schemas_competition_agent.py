from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentRunCreate(BaseModel):
    request_kind: Literal[
        "auto", "calculation_planning", "general_qa", "file_analysis", "template_recommendation", "result_analysis"
    ]
    prompt: str = Field(min_length=1, max_length=2000)
    material_id: Literal[
        "MoS2_monolayer",
        "WS2_monolayer",
        "MoSe2_monolayer",
        "WSe2_monolayer",
        "graphene",
        "hBN",
    ] | None = None
    step_key: Literal["relax", "scf", "band", "dos"] | None = None
    workflow_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    file_ids: list[str] = Field(default_factory=list, max_length=12)
    calculation_ids: list[str] = Field(default_factory=list, max_length=6)
    structure_ids: list[str] = Field(default_factory=list, max_length=12)
    literature_ids: list[str] = Field(default_factory=list, max_length=12)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    search_literature: bool = False

    @model_validator(mode="after")
    def validate_kind_fields(self):
        if self.prompt != self.prompt.strip() or any(char in self.prompt for char in "\x00\r"):
            raise ValueError("prompt contains unsupported characters")
        if self.request_kind == "template_recommendation":
            if (
                self.material_id is None
                or self.step_key is None
                or self.workflow_id is not None
                or self.file_ids
                or self.calculation_ids
                or self.structure_ids
                or self.literature_ids
            ):
                raise ValueError("template recommendation requires material and step only")
        elif self.request_kind == "result_analysis" and (
            (self.workflow_id is None and not self.file_ids and not self.calculation_ids)
            or self.material_id is not None
            or self.step_key is not None
        ):
            raise ValueError("result analysis requires a workflow or calculation directory")
        elif self.request_kind in {"auto", "calculation_planning", "general_qa", "file_analysis"}:
            if self.material_id is not None or self.step_key is not None or (
                self.workflow_id is not None and self.request_kind != "auto"
            ):
                raise ValueError("question analysis accepts files only")
            if self.request_kind == "file_analysis" and not (
                self.file_ids or self.calculation_ids or self.structure_ids
            ):
                raise ValueError("file analysis requires at least one file")
        if any(not re.fullmatch(r"[0-9a-f-]{36}", item) for item in self.file_ids):
            raise ValueError("invalid file id")
        if any(not re.fullmatch(r"[A-Za-z0-9:._-]{1,160}", item) for item in self.calculation_ids):
            raise ValueError("invalid calculation id")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item) for item in self.structure_ids):
            raise ValueError("invalid structure id")
        if any(not re.fullmatch(r"[A-Za-z0-9:._-]{1,160}", item) for item in self.literature_ids):
            raise ValueError("invalid literature id")
        return self


class LiteratureIndexRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9:._/-]+$")
    title: str = Field(min_length=1, max_length=1000)
    abstract: str = Field(default="", max_length=30000)
    authors: list[str] = Field(default_factory=list, max_length=100)
    year: int | None = Field(default=None, ge=1800, le=2200)
    doi: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    library_name: str = Field(default="我的文献库", min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_external_url(self):
        if self.url is not None and not self.url.startswith("https://"):
            raise ValueError("literature URL must use HTTPS")
        return self


class AgentSettingsUpdate(BaseModel):
    api_url: str = Field(min_length=10, max_length=500)
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:/-]+$")
    api_key: str | None = Field(default=None, min_length=8, max_length=500)

    @model_validator(mode="after")
    def validate_url(self):
        if not self.api_url.startswith("https://"):
            raise ValueError("API URL must use HTTPS")
        return self


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_kind: str
    provider: str
    status: str
    workflow_id: str | None
    conversation_id: str | None
    prompt: str
    input: dict[str, object]
    output: dict[str, object] | None
    error_code: str | None
    approved: bool
    created_at: datetime
    updated_at: datetime


class CuratedStructureBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    material_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    repeat_a: int = Field(default=1, ge=1, le=6)
    repeat_b: int = Field(default=1, ge=1, le=6)
    layers: int = Field(default=1, ge=1, le=8)
    vacuum_angstrom: float = Field(default=15.0, ge=8.0, le=40.0)
    interlayer_spacing_angstrom: float = Field(default=6.2, ge=3.0, le=10.0)
    strain_percent: float = Field(default=0.0, ge=-5.0, le=5.0)
    kpoints_source: Literal["manual", "mock_qoder"] = "mock_qoder"
    kpoints_mesh: list[int] | None = None

    @model_validator(mode="after")
    def validate_kpoints(self):
        if self.kpoints_source == "manual" and self.kpoints_mesh is None:
            raise ValueError("manual KPOINTS requires a mesh")
        if self.kpoints_mesh is not None:
            if len(self.kpoints_mesh) != 3:
                raise ValueError("KPOINTS mesh must contain three values")
            if not all(type(value) is int and 1 <= value <= 60 for value in self.kpoints_mesh):
                raise ValueError("KPOINTS mesh values must be between 1 and 60")
        return self
