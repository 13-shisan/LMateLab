# 107 Cup Stage 5 Workflow Models and Input Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不调用 Slurm/VASP 的前提下，为 107 竞赛版建立可追溯的 MoS2 四步工作流草稿、固定模板、结构上传和提交前校验闭环。

**Architecture:** 在现有主 SQLite 中增加六张工作流表，文件内容保存到 `LMATELAB_WORKFLOW_ROOT`，数据库只记录相对路径、大小、SHA-256、来源和归属。FastAPI 提供结构暂存、草稿保存、确认校验以及 Dashboard/工作流只读接口；确认成功只进入 `validated`，不创建 attempt、执行目录或 Job ID。React 继续使用现有 live provider，只补齐真实上传、草稿 ID 和确认状态。

**Tech Stack:** FastAPI 0.115、Pydantic 2.8、SQLAlchemy 2、Alembic、ASE/pymatgen、SQLite、React 19、Node test runner。

---

### Task 1: 工作流模型与 Alembic 迁移

**Files:**
- Create: `backend/models_workflow.py`
- Create: `backend/alembic/versions/107c0ffee001_add_competition_workflows.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/test_competition_workflow_models.py`

- [ ] 写失败测试，断言新库和从当前 head 升级的库均包含 `workflow_runs`、`workflow_steps`、`workflow_attempts`、`workflow_events`、`workflow_files`、`workflow_templates`，并验证外键、唯一约束和 cascade。
- [ ] 运行 `..\.venv\Scripts\python.exe -m unittest tests.test_competition_workflow_models -v`，确认因模型和 revision 不存在而 RED。
- [ ] 建立六个 SQLAlchemy 模型。`workflow_runs.id`、`workflow_attempts.id`、`workflow_files.id` 使用服务端 UUID 字符串；时间使用 UTC；JSON 以 canonical JSON 文本保存；attempt 在阶段 5 不创建记录。
- [ ] 新增 Alembic revision `107c0ffee001`，`down_revision` 指向 `2f694f47e108`；迁移只建表和索引，不读取运行目录、不创建示例工作流。
- [ ] 在 Alembic env 中显式导入 `models_workflow`，重跑聚焦测试直到 GREEN。

### Task 2: 固定 `mos2_v1` 模板和结构校验

**Files:**
- Create: `backend/competition_templates/mos2_v1/POSCAR`
- Create: `backend/competition_templates/mos2_v1/INCAR.relax`
- Create: `backend/competition_templates/mos2_v1/INCAR.scf`
- Create: `backend/competition_templates/mos2_v1/INCAR.band`
- Create: `backend/competition_templates/mos2_v1/INCAR.dos`
- Create: `backend/competition_templates/mos2_v1/template.json`
- Create: `backend/services/competition_inputs.py`
- Test: `backend/tests/test_competition_inputs.py`

- [ ] 写失败测试覆盖：超过 `1 MiB`、空文件、二进制/NUL、路径穿越名、POSCAR/CIF 均无法解析、超过 `200` 原子、非 Mo/S、化学计量非 `1:2`、POSCAR 元素顺序不是 `Mo S`、未知 INCAR 键、布尔/非有限数冒充数值、参数越界和命令注入字符串。
- [ ] 写成功测试覆盖内置 MoS2、合法 POSCAR、合法 CIF、canonical JSON、固定四步依赖 `relax -> scf -> band/dos`、生成 KPOINTS 以及每个输入文件的 SHA-256。
- [ ] 运行 `..\.venv\Scripts\python.exe -m unittest tests.test_competition_inputs -v`，确认因服务不存在而 RED。
- [ ] 实现 `parse_structure_bytes(content, filename)`：文件名仅用于审计和拒绝路径字符，实际格式由 ASE 依次尝试 `vasp`、`cif`；POSCAR 使用解析结果核对有序元素组，CIF 按 Mo/S 化学计量 canonicalize。
- [ ] 实现 `load_template('mos2_v1')` 和 `validate_draft_payload(payload)`；只允许固定模板、`builtin/upload`、四步固定顺序以及定义的数值键和值域，额外字段失败关闭。
- [ ] 实现 `materialize_inputs(...)`：只在服务生成的 UUID 目录写入，目录/文件目标权限为 `0700/0600`；相对路径必须仍位于 workflow root；不写 POTCAR，只保存 `Mo_sv`、`S` 标识，POTCAR 哈希留待阶段 7 运行时记录。
- [ ] 重跑聚焦测试直到 GREEN。

### Task 3: 工作流 schema、存储服务与失败事件

**Files:**
- Create: `backend/schemas_workflow.py`
- Create: `backend/services/competition_workflows.py`
- Test: `backend/tests/test_competition_workflow_service.py`

- [ ] 写失败测试覆盖结构暂存归属、草稿创建、四个 waiting step、文件记录、重复确认幂等、非 owner 修改拒绝、校验失败事件、缺失/篡改文件哈希拒绝，以及确认后 attempt/Job ID/attempt 目录仍为零。
- [ ] 运行聚焦测试并确认 RED。
- [ ] 实现结构暂存记录：合法上传保存到 `incoming/<owner_id>/<file_uuid>`，`workflow_files.workflow_id` 和 `attempt_id` 为空，owner 固定为当前用户。
- [ ] 实现草稿事务：创建 run、四个 step、复制/生成固定输入、记录文件和 `draft_created` 事件；上传暂存文件只能由 owner 消费一次。
- [ ] 实现确认事务：重新读取文件并核对大小/SHA-256、模板版本和四步定义；成功更新为 `validated` 并写 `workflow_validated`，失败保持不可调度并写 `validation_failed`。该函数不得 import subprocess、不得调用 Slurm、不得创建 attempt。
- [ ] 重跑聚焦测试直到 GREEN。

### Task 4: 阶段 5 FastAPI 路由与角色边界

**Files:**
- Create: `backend/routers/competition_workflows.py`
- Modify: `backend/competition_runtime.py`
- Modify: `backend/routers/health.py`
- Test: `backend/tests/test_competition_workflow_routes.py`
- Modify: `backend/tests/test_107cup_runtime.py`

- [ ] 写失败 API 测试覆盖 Operator 上传/保存/确认、Viewer 所有 POST 为 `403`、未认证 `401`、列表筛选、详情 `404`、Dashboard 真实计数、results/database 真实空 envelope，以及响应不包含绝对路径或文件内容。
- [ ] 运行聚焦测试并确认路由不存在的 RED。
- [ ] 挂载唯一业务 router `routers.competition_workflows`。实现：`POST /competition/structures`、`POST /competition/drafts`、`POST /competition/workflows/{id}/submit`、`GET /competition/dashboard`、`GET /competition/workflows`、`GET /competition/workflows/{id}`、`GET /competition/results`、`GET /competition/vasp/records`。
- [ ] 列表和详情使用现有前端合同字段；草稿/已校验步骤始终没有 Job ID 和 attempt。阶段 5 的 results/database 只返回 `data_kind=live` 的空集合。
- [ ] 107 readiness 在竞赛版额外检查 `workflow_runs`，让漏迁移发布返回 `503`。
- [ ] 重跑 API、authz、runtime 和 readiness 测试直到 GREEN。

### Task 5: React 新建计算接入真实草稿

**Files:**
- Modify: `frontend/src/pages/competition/CompetitionNewCalculation.jsx`
- Modify: `frontend/src/pages/competition/CompetitionPages.css`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`
- Modify: `frontend/tests/competitionDataProvider.test.mjs`

- [ ] 先写失败测试：live Operator 选择文件后只调用一次 `uploadStructure`，草稿 payload 使用 `template_version=mos2_v1` 和服务返回的 upload ID；保存成功后使用服务返回 workflow ID；修改来源会清除旧 ID；确认前不能调用 submit；demo/Viewer 继续零写请求。
- [ ] 运行 `npm test -- --test-name-pattern="new calculation|live structure|draft"` 并确认 RED。
- [ ] 增加受控文件 input、上传/保存/确认 pending 状态和服务端错误展示。保存成功显示草稿 ID、输入 SHA-256 和 `draft`；确认成功显示“已校验，等待 Slurm 适配器”，不得显示排队或 Job ID。
- [ ] 保留内置结构的 3D viewer；上传结构只显示后端解析摘要，不用浏览器自行信任 MIME/扩展名。
- [ ] 重跑前端聚焦测试直到 GREEN。

### Task 6: 全量本地门禁和方案同步

**Files:**
- Modify: `docs/107cup/implementation-plan.md`

- [ ] 运行后端阶段 5 聚焦测试和既有 107 专项测试，要求 0 failure/0 error。
- [ ] 在全新临时 SQLite 与当前 schema 副本上分别执行 `alembic upgrade head`，检查六张表和 `PRAGMA integrity_check=ok`。
- [ ] 运行 `npm test`、定向 ESLint、`VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=live npm run build` 和 `git diff --check`。
- [ ] 更新总方案：阶段 5 只有本地实现和门禁通过时仍保持 `PARTIAL`；不得把阶段 6 至 8 标成完成。
- [ ] 提交并推送 `codex/107cup-stage5-workflows`，通过 PR 合并后再在 107 用 Slurm 构建独立预览进行 migration、API 和浏览器验收。

### Task 7: 合并后 107 隔离验收

**Files:**
- Maintain: `docs/107cup/implementation-plan.md`
- Create after runtime acceptance: `docs/107cup/stage5-workflow-evidence.md`

- [ ] 107 只读检出固定 `main` 合并提交；先运行稳定状态快照，不修改 `current` 和正式 SQLite。
- [ ] 通过 Slurm 构建不晋升 preview，后端/前端测试及 manifest 全部通过。
- [ ] 使用正式数据库的私有副本启动独立 preview；执行 migration，验证六张表、readiness 和空工作流页面。
- [ ] 使用隔离测试 Operator 创建内置草稿和上传草稿，确认合法输入进入 `validated`；恶意路径、命令字符串、错元素顺序和越界参数均在无 attempt、无 Job ID 条件下失败。
- [ ] 浏览器验证工作台、新建计算、工作流列表和详情；results/database 显示真实空状态而不是 demo。
- [ ] 停止 preview 并确认端口消失；后快照证明稳定 `current`、Job、端口和正式数据库未变。
- [ ] 固化 Job、节点、提交、manifest、SQLite、API、浏览器和 SHA-256 证据，再通过独立文档 PR 合并；只有这一闭环通过后阶段 5 才可改为 `DONE`。
