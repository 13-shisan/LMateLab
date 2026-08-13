# VASP INCAR 模板库调用说明

本文档用于把 `vasp-incar-library` 交给其他 AI 模型、Agent 或自动化程序调用。推荐把 `AGENT_PROMPT.md` 作为 system prompt，把下面的请求 JSON 和用户任务一起作为 user message。

## 一、调用目标

模型应根据“具体体系 + 计算任务”检索库内最接近的体系记录和任务模板，合成完整工作流，并解释关键参数来源。模型不能只输出一份看似合理的 INCAR，也不能把论文中相同元素的参数直接移植到不同结构或任务。

## 二、建议输入格式

```json
{
  "system": {
    "name": "体系名称",
    "composition": "化学式",
    "phase_or_structure": "晶型、表面、缺陷、吸附构型或分子构型",
    "dimensionality": "0d|1d|2d|3d|surface|interface",
    "periodic_axes": ["a", "b", "c"],
    "elements_in_poscar_order": ["..."],
    "charge_state": 0,
    "electronic_character": "metal|semiconductor|insulator|unknown",
    "magnetism": "nonmagnetic|FM|AFM|ferrimagnetic|noncollinear|unknown",
    "oxidation_states_or_spin_hint": "可为空"
  },
  "task": {
    "type": "relax|static|adsorption|dos|bands|neb|vibration|aimd|defect|soc|magnetic_anisotropy",
    "observable": "最终需要比较或输出的物理量",
    "accuracy_target": "screening|production|high_precision",
    "workflow_stage": "new|restart|postprocess"
  },
  "method": {
    "vasp_version": "未知时写 unknown",
    "xc_functional": "PBE|r2SCAN|HSE06|...",
    "potcar_family": "PBE_54/Ti_pv 等；未知时写 unknown",
    "potcar_enmax_ev": {"Element": 0},
    "dft_u": null,
    "dispersion": null,
    "soc": false,
    "solvation": null
  },
  "model": {
    "cell_description": "晶胞/超胞/层数/真空",
    "vacuum_axis": "c|null",
    "fixed_atoms": "无或具体说明",
    "kpoints_known": null
  },
  "restart_files": {
    "wavecar": false,
    "chgcar": false
  },
  "resources": {
    "cores": null,
    "memory_gb": null
  }
}
```

自然语言输入也可以，但调用模型必须先映射到以上字段；未知项必须保留为 unknown，不能静默补造。

## 三、检索顺序

1. `index.json`：按 `dimensions`、`tasks`、`methods`、`magnetism` 找基础模板。
2. `SYSTEM_DOI_INDEX.md`：确认库内是否有同一具体体系，以及它的 DOI 真实性状态。
3. `materials/*/PROFILE.md`：同体系时读取结构、POTCAR、磁性、k 点和收敛约束。
4. `literature/records.json`：只继承与当前“体系 + 任务阶段 + 方法”兼容的已核验参数。
5. `literature/candidates.json`：禁止用于生成参数，只能报告存在待核验论文。
6. `templates/*.INCAR`：补齐工作流骨架。
7. `PARAMETER_GUIDE.md`、`KPOINTS_GUIDE.md`、`MAGNETISM_GUIDE.md`：检查参数含义、相互作用和适用条件。

## 四、模板选择表

| 用户任务 | 主要模板/链路 |
|---|---|
| 3D 体相优化 | `bulk_relax` |
| 2D 材料优化 | `2d_relax`，固定真空；面内晶格需单独受控优化 |
| 1D 线/链优化 | `1d_relax` |
| 分子优化 | `molecule_relax` |
| 表面吸附优化 | `slab_adsorption_relax` |
| 缺陷优化 | `defect_relax`，另做有限尺寸/电荷修正方案 |
| 最终静态能 | 已优化结构 -> `static_energy` |
| DOS/PDOS | 收敛 SCF/静态计算 -> `dos` |
| 能带 | 优化 -> `band_scf`（均匀网格）-> `band_nscf`（线模式路径） |
| DFT+U 优化 | `dftu_relax`，U/J 必须有来源或由用户提供 |
| HSE06 | `hse06_static`，能带需专门 hybrid k 点工作流 |
| SOC | 标量相对论基态 -> `soc_static` |
| 非共线磁性优化 | `noncollinear_relax` |
| CI-NEB | 初末态优化 -> `cineb` -> 鞍点优化/振动验证 |
| 振动 | 严格优化结构 -> `vibrations` |
| NVT AIMD | `aimd_nvt`，时间步长和恒温器必须验证 |

## 五、参数证据等级

每个关键标签必须给出以下来源之一：

- `explicit_source`：正文/SI/输入仓库明确给出，记录 DOI 和 evidence location；
- `material_profile`：库内同体系配置的约束或起点；
- `template_choice`：通用工作流的保守设置；
- `official_default`：当前 VASP 官方默认，必须确认版本；
- `system_assumption`：模型基于用户描述作出的假设，必须醒目标注并要求验证。

论文只给 `ENCUT`、k 点、泛函、U、色散或收敛阈值时，可以只继承这些明确字段。没有披露的 `ALGO`、`ISMEAR`、`EDIFF` 等不得伪装成论文参数，应由模板补齐并标记 `template_choice`。

## 六、关键阻断条件

出现以下情况时输出 `draft_needs_decisions`，而不是声称可直接运行：

- 不知道实际 POTCAR/`ENMAX`，却需要给出可靠 `ENCUT`；
- d/f 体系要求 DFT+U，但 U/J 和约定未确定；
- 开壳层、过渡金属、缺陷或磁性材料的磁序/初始磁矩完全未知；
- 带电体系缺少电子数和有限尺寸/电势对齐方案；
- `ISTART=1`/`ICHARG=11` 但没有兼容 `WAVECAR`/`CHGCAR`；
- 表面方向、真空轴、固定层、覆盖度或偶极设置未知；
- SOC、非共线、HSE、溶剂、恒电势或 VTST 功能与 VASP 版本不明确。

## 七、固定输出格式

```text
Status
Classification
Selected library records
Assumptions and unresolved decisions
Workflow

[stage_01/INCAR]
...

[stage_02/INCAR]
...

KPOINTS plan
POTCAR/POSCAR prerequisites
Key-tag provenance
Convergence and validation plan
Warnings
```

能带、DOS、NEB 等多阶段任务必须输出多个目录/阶段，不能只给最后一步 INCAR。

## 八、短版可复制 Prompt

```text
请调用当前工作区的 vasp-incar-library 为我生成 VASP 计算输入。先阅读 AGENT_PROMPT.md 和 CALLING_GUIDE_CN.md，然后按 index.json 检索模板；按 SYSTEM_DOI_INDEX.md、materials/ 和 literature/records.json 检索相同体系与已核验论文参数。严禁使用 literature/candidates.json 中的参数。

先分类体系维度、周期方向、金属性、磁性、泛函/修正和计算阶段。对每个关键 INCAR 标签标注 explicit_source、material_profile、template_choice、official_default 或 system_assumption。不得猜测 POTCAR、ENCUT、U/J、MAGMOM、NELECT、色散、SOC、溶剂、固定原子或重启文件。信息不足时输出 draft_needs_decisions，并列出需要确认的问题；不要声称输入已收敛。

按完整工作流输出：Status、Classification、Selected library records、Assumptions、Workflow、每阶段无占位符的 INCAR、KPOINTS、POTCAR/POSCAR 前提、关键参数来源、收敛计划和警告。能带必须是 SCF+NSCF 两步，DOS 必须有兼容 CHGCAR，NEB 必须包含初末态和鞍点验证。

体系与任务如下：
{{在这里填写体系、结构、任务、VASP版本、POTCAR、磁性、泛函、晶胞/真空、重启文件和目标精度}}
```

## 九、调用示例：单层 MoS2 能带

```text
请为单层 2H-MoS2 生成 PBE 能带工作流。晶胞 c 方向有 20 Angstrom 真空，POSCAR/POTCAR 顺序 Mo S，使用 VASP 6.x PBE PAW；实际 ENMAX 请从 POTCAR 读取。体系非磁性，不加 U、不加色散，先不计算 SOC。需要结构优化、均匀网格 SCF 和高对称路径 NSCF 三阶段。请按 vasp-incar-library 输出，并把 ENCUT 和 k 网格标为待收敛量。
```

正确路由应包括 `2d_relax -> band_scf -> band_nscf`，读取 `materials/MoS2_monolayer/PROFILE.md`，并说明 PBE 能带不包含 SOC 劈裂；不能直接从候选论文复制参数。
