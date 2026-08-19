# 107 Cup Stage 8 Results and Evidence Bundle Plan

**Goal:** 在不重新运行 VASP 的前提下，把 Stage 7 已验收的固定 `MoS2` 工作流接入真实结果列表、结构详情、BAND/DOS 图与原始数据下载，并生成可重复、可核验的 JSON 证据包。

**Architecture:** `competition_results.py` 只读取终态工作流账本，并将每个科学结果绑定到最终 attempt、`WorkflowFile`、严格受限的工作流根路径及 SHA-256。它通过现有 VASP BAND/DOS 纯解析函数生成图和数值数据，不复用旧 VASP 数据库的路径映射、数据库或权限逻辑。`competition_bundle.py` 从同一可信账本生成确定性 JSON 证据包；Router 只负责角色可见性、HTTP 状态和固定 artifact kind。任何文件缺失、路径不一致、哈希变化、验收合同不完整或解析异常都返回失败记录，绝不降级为空成功结果。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, ASE 3.23, Pymatgen 2025.10.7, Matplotlib, `unittest`, React 19, Slurm, SHA-256.

---

## Fixed Boundaries

- 起点是已合并 Stage 7 `main` 提交 `fef662d24941c5c5fd08bf75fc10c0a3f8c48547`。
- 不提交新的 VASP 作业；复用成功工作流 `4b566547-961b-4e10-a8d0-99431f2e2229` 和失败工作流 `db9c793d-cf8f-4207-823b-5943d825f21d`。
- 不加入 Agent、机器学习、任意材料、任意命令、新 VASP 模板、跨服务器计算或原 4090 数据。
- 4090 仍只作可替换网络入口；源码、数据库、解析、证据包和真实结果均留在 107。
- 107 登录节点只执行短 Git、`sbatch`、队列和状态命令；构建、测试、解析与服务均在 Slurm 计算节点运行。
- 不重写已经存在的竞赛结果页、VASP 数据库页、3D 结构组件或周期表；只接通 live API，必要的前端改动限于合同修正。

## Real Acceptance Fixtures

| 工作流 | 预期结果 | 真实 Job |
|---|---|---|
| `4b566547-961b-4e10-a8d0-99431f2e2229` | 四步成功，可显示结构、BAND、DOS 并下载证据包 | `40212 / 40250 / 40251 / 40252` |
| `db9c793d-cf8f-4207-823b-5943d825f21d` | SCF `electronic_not_converged`，只显示失败证据 | `40264 / 40265`，BAND/DOS 无 Job |

成功详情必须同时满足：

```text
run.status == succeeded
四步最终 attempt.status == succeeded
四步 scheduler == COMPLETED/0:0 且 stale == false
四步 scientific_acceptance.accepted == true
scientific_acceptance SHA-256 可重算
解析源 WorkflowFile 指向对应 attempt、固定 logical_path 和真实普通文件
文件大小及 SHA-256 与账本一致
结构、BAND、DOS 均可完整解析
```

任一条件失败，结果状态为 `parse-error`，只返回安全的 `failure_evidence`，不返回成功科学区。

## API Contract

| Endpoint | Contract |
|---|---|
| `GET /api/competition/results` | 只列出 `succeeded`、`failed`、`parse-error` 终态结果，支持 query/status |
| `GET /api/competition/results/{workflow_id}` | 成功返回完整四步、结构和电子性质；失败只返回失败证据 |
| `GET /api/competition/results/{workflow_id}/band-plot` | 返回 `{image_base64, data_kind, provenance}` |
| `GET /api/competition/results/{workflow_id}/dos-plot` | 返回 `{image_base64, data_kind, provenance}` |
| `GET /api/competition/results/{workflow_id}/artifacts/{kind}` | kind 仅允许 `structure-cif`、`structure-poscar`、`band-data`、`dos-data`、`evidence-bundle` |
| `GET /api/competition/vasp/records` | 对可信终态结果分页、元素筛选，返回既有只读表格合同 |
| `GET /api/competition/vasp/records/{workflow_id}` | 返回与结果详情相同来源的只读记录 |

Operator 只能读取自己的工作流；Viewer 可读取竞赛演示工作流。两种角色下载完全相同的字节，不生成角色相关证据包。

## Evidence Bundle Contract

`evidence-bundle` 是 canonical JSON，至少包含：

- schema/version、工作流 ID、材料、创建人、模板版本、输入 SHA-256、工作流创建/完成时间；
- 工作流固定 `release_commit`、对应 release `manifest.sha256` 和 `manifest.txt` 清单；
- 四步及所有 attempt 的状态、Job ID、Slurm 观察、科学验收、资源和时间；
- 模板定义、规范化参数、输入 manifest；
- 所有工作流事件，保持 sequence 顺序；
- 所有 `WorkflowFile` 的 attempt、logical path、role、size、SHA-256；
- 结构、BAND、DOS 解析来源 attempt、相对路径和 SHA-256；
- bundle payload 自身的 canonical SHA-256。

包中不得包含 JWT、密码、绝对路径、日志私有路径、环境变量或未登记文件。证据包不写回历史工作流目录；相同账本和文件应产生相同字节。

## Implementation Tasks

### Task 1: Freeze the result contracts with RED tests

**Files:**
- Create: `backend/tests/test_competition_results.py`

- [x] 建立成功、科学失败、文件缺失、哈希变化、路径逃逸和解析异常 fixtures。
- [x] 固定四步成功详情、失败详情和列表筛选合同。
- [x] 固定结构/BAND/DOS artifact 与 plot 响应合同。
- [x] 固定 Operator/Viewer 可见性及相同证据包字节。
- [x] 先运行定向测试并确认因服务和路由未实现而 RED。

### Task 2: Implement a fail-closed workflow result ledger

**Files:**
- Create: `backend/services/competition_results.py`

- [x] 只接受 terminal run 和固定四步键，选取每步最终 attempt。
- [x] 重算 acceptance canonical SHA-256，并核对 scheduler、状态、Job ID 与 attempt 目录。
- [x] 通过 `WorkflowFile` 定位所需文件，拒绝绝对路径、`..`、错误 attempt、符号链接、非普通文件、size/hash 不一致。
- [x] 提供安全失败原因映射，不向 API 暴露绝对路径或异常内部文本。
- [x] 生成共享的 list/detail/database payload，避免三套状态判断。

### Task 3: Reuse the existing scientific parsers

**Files:**
- Modify: `backend/routers/vasp_db.py` only if a pure parser adapter is required
- Modify: `backend/services/competition_results.py`

- [x] 复用现有 BAND/DOS 图、`band.dat` 和 DOS ZIP 解析函数，不复制解析算法。
- [x] 从已验收 Relax `CONTCAR` 构建 ASE 结构、CIF/POSCAR、晶格、密度、维度和分数坐标。
- [x] 从已验收输出提取总能、带隙、VBM、CBM 和空间群；所有数值必须有限。
- [x] 每次解析前后核对源文件 SHA-256；解析器异常转为 `parse-error`。
- [x] 给每个科学输出附加 source attempt、relative path、size 和 SHA-256 provenance。

### Task 4: Build deterministic evidence bundles

**Files:**
- Create: `backend/services/competition_bundle.py`

- [x] 收集 run、steps、attempts、events、template、file ledger 和解析 provenance。
- [x] 从工作流 `release_commit` 对应 release 读取并核验 `manifest.sha256` 与 `manifest.txt`。
- [x] 核验所有纳入包的文件账本；缺失或变化时不生成 bundle。
- [x] 排序并 canonicalize JSON，计算 payload SHA-256，禁止绝对路径和秘密字段。
- [x] 重复生成及 Viewer/Operator 下载必须字节一致。

### Task 5: Connect the live FastAPI routes

**Files:**
- Modify: `backend/routers/competition_workflows.py`
- Modify: `backend/tests/test_competition_workflow_routes.py`

- [x] 实现结果列表、结果详情、VASP 记录列表和记录详情。
- [x] 实现 BAND/DOS plot 与五种固定 artifact 下载。
- [x] 路由复用现有 `_visible_runs_statement`，不得绕过 Operator 所有权边界。
- [x] 固定下载 filename、media type、`Content-Disposition` 和 `Cache-Control: no-store`。
- [x] 对未知 kind、非终态工作流和不可信文件返回 4xx/安全错误码。

### Task 6: Verify the existing frontend contract

**Files:**
- Modify only if tests expose a contract defect:
  - `frontend/src/pages/competition/CompetitionResultDetail.jsx`
  - `frontend/src/pages/competition/CompetitionResults.jsx`
  - `frontend/src/pages/competition/CompetitionVaspDatabase.jsx`
  - `frontend/src/features/competition/data/apiCompetitionDataProvider.js`

- [x] 保持同一页面同时服务 demo/live，不复制页面。
- [x] 成功详情显示 3D 结构、晶体参数、BAND/DOS tab 和导出。
- [x] 失败或解析错误只显示 `failure_evidence`，不挂载成功科学组件。
- [x] 运行现有前端测试、定向 ESLint 和 107cup live build。

### Task 7: Run local regression and repository checks

- [x] 运行 Stage 8 定向后端测试。
- [x] 运行完整后端测试集并记录 pass/skip 数。
- [x] 运行完整前端测试、定向 ESLint 和 live build。
- [x] 运行 `python -m compileall`、`git diff --check` 和仓库秘密/大文件检查。
- [x] 只有全部通过后才推送 `codex/107cup-stage8-results`。

### Task 8: Merge through the authorized Gitea API

- [x] 使用本机已保存 Token，仅为本代理的 `codex/107cup-stage8-results` 创建 PR。
- [x] 检查 PR 无冲突且测试通过后合并到受保护 `main`。
- [x] 同步 Windows `main`、Gitea `main` 和 107 只读 checkout 到同一合并提交。

### Task 9: Validate on a Slurm compute node without rerunning VASP

- [x] 提交 Stage 8 短时验收 Job，在计算节点运行完整构建/测试和真实解析。
- [x] 对成功工作流验证详情、BAND/DOS plot、四种科学 artifact 和证据包。
- [x] 对失败工作流验证只显示 SCF 失败，BAND/DOS 无 attempt/Job 且无科学成功区。
- [x] 重复下载并比较 Viewer/Operator 证据包 SHA-256。
- [x] 保存 Job ID、节点、ExitCode、测试输出和验收 manifest。

### Task 10: Deploy and record Stage 8 evidence

**Files:**
- Modify: `docs/107cup/implementation-plan.md`
- Create: `docs/107cup/stage8-results-evidence.md`

- [x] 从合并后的 `main` 构建新 release 并原子切换稳定服务。
- [x] 核对公网、Windows Operator 和 107 内部入口指向同一 Job/commit/manifest。
- [ ] 以 Viewer 和 Operator 浏览器验收结果列表、成功详情、失败详情、数据库和下载。
- [x] 记录原始证据路径和 SHA-256。
- [ ] 完成全部门禁后才把 Stage 8 改为 `DONE`。

## Completion Gate

只有以下条件同时成立，Stage 8 才能标记为 `DONE`：

```text
真实成功工作流可显示结构、BAND 和 DOS
真实失败工作流绝不显示科学成功区
缺失/篡改/越界/解析异常全部失败关闭
BAND/DOS 图和原始数据均可下载
Viewer 与 Operator 得到同一不可变证据包
证据包可追溯到 Git、release manifest、模板、Job、事件和原始文件哈希
本地与 107 计算节点测试通过
稳定服务部署并完成浏览器验收
```
