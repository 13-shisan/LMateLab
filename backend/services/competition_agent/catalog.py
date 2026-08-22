from __future__ import annotations

from types import MappingProxyType


APPLICABLE_TEMPLATE_IDS = frozenset({"2d_relax", "band_scf", "band_nscf", "dos"})

_TEMPLATES = (
    {
        "id": "2d_relax",
        "name": "二维结构优化",
        "material_id": "MoS2_monolayer",
        "workflow_step": "relax",
        "applicable": True,
        "summary": "固定真空层与面内采样的二维离子和晶格优化。",
        "parameters": {"ENCUT": 520, "EDIFF": 1e-6, "EDIFFG": -0.01, "NSW": 120},
    },
    {
        "id": "band_scf",
        "name": "能带自洽基态",
        "material_id": "MoS2_monolayer",
        "workflow_step": "scf",
        "applicable": True,
        "summary": "为后续能带与态密度生成已验收的自洽电荷密度。",
        "parameters": {"ENCUT": 520, "EDIFF": 1e-7, "NELM": 120},
    },
    {
        "id": "band_nscf",
        "name": "能带非自洽计算",
        "material_id": "MoS2_monolayer",
        "workflow_step": "band",
        "applicable": True,
        "summary": "仅复用已验收 SCF 产物并沿固定高对称路径计算。",
        "parameters": {"ENCUT": 520, "EDIFF": 1e-7, "NELM": 120},
    },
    {
        "id": "dos",
        "name": "态密度计算",
        "material_id": "MoS2_monolayer",
        "workflow_step": "dos",
        "applicable": True,
        "summary": "仅复用已验收 SCF 产物并使用固定致密网格。",
        "parameters": {"ENCUT": 520, "EDIFF": 1e-7, "NEDOS": 3000},
    },
    {
        "id": "hybrid_hse06",
        "name": "HSE06 混合泛函",
        "material_id": "reference_only",
        "workflow_step": None,
        "applicable": False,
        "summary": "仅供浏览、解释和导出，当前竞赛流程不可执行。",
        "parameters": {"LHFCALC": True, "HFSCREEN": 0.2},
    },
    {
        "id": "phonon_static",
        "name": "声子静态力计算",
        "material_id": "reference_only",
        "workflow_step": None,
        "applicable": False,
        "summary": "仅供浏览、解释和导出，当前竞赛流程不可执行。",
        "parameters": {"IBRION": -1, "NSW": 0},
    },
)


def _public_copy(template: dict[str, object]) -> dict[str, object]:
    return {
        **template,
        "parameters": dict(template["parameters"]),
    }


def list_templates() -> tuple[dict[str, object], ...]:
    return tuple(_public_copy(item) for item in _TEMPLATES)


_BY_ID = MappingProxyType({item["id"]: item for item in _TEMPLATES})


def get_template(template_id: str) -> dict[str, object]:
    try:
        return _public_copy(_BY_ID[template_id])
    except (KeyError, TypeError) as exc:
        raise KeyError("template is unavailable") from exc
