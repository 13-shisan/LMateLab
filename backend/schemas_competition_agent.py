from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentRunCreate(BaseModel):
    request_kind: Literal["template_recommendation", "result_analysis"]
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

    @model_validator(mode="after")
    def validate_kind_fields(self):
        if self.prompt != self.prompt.strip() or any(char in self.prompt for char in "\x00\r"):
            raise ValueError("prompt contains unsupported characters")
        if self.request_kind == "template_recommendation":
            if self.material_id is None or self.step_key is None or self.workflow_id is not None:
                raise ValueError("template recommendation requires material and step only")
        elif self.workflow_id is None or self.material_id is not None or self.step_key is not None:
            raise ValueError("result analysis requires workflow only")
        return self


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    request_kind: str
    provider: str
    status: str
    workflow_id: str | None
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
