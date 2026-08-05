# LMateLab 107 Cup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 107 平台独立交付一个围绕固定 MoS2 `relax -> SCF -> BAND -> DOS` 闭环的 LMateLab 竞赛版本，并提供可追溯、可恢复、可只读演示的真实 Slurm/VASP 证据链。

**Architecture:** 源码由私有 Gitea 管理，107 只读拉取固定提交；构建、网页服务和 VASP 作业全部通过 Slurm 运行在 107 计算节点。4090 仅作为可替换的网络转发与 IP 白名单入口，不保存竞赛业务数据，也不执行 LMateLab 或 VASP 业务逻辑。

**Tech Stack:** React/Vite, FastAPI, SQLAlchemy/Alembic, SQLite, Slurm, VASP 6.4.2 GPU, VASPKIT 1.5.1, user-scoped Nginx, Gitea.

---

## 1. 文档地位与更新规则

本文件是 107 杯项目唯一的实施路线和状态账本。不得再创建内容重叠的第二份总路线。

每次修改必须遵守以下同步规则：

- [ ] 修改前确认本文件中的当前阶段、范围和门禁。
- [ ] 修改源码、测试、部署脚本、远端运行配置或验收状态时，在同一个 Git 提交中更新本文件。
- [ ] 本地测试通过只能记录为“本地已验证”，不能记录为“107 已部署”。
- [ ] 107 构建、服务或 VASP 作业实际完成后，记录提交、Job ID、节点、退出状态、关键输出路径和哈希。
- [ ] 每个功能分支推送到 Gitea 后，通过 PR 合并；107 仅拉取合并后的固定提交，不从 107 推送源码。
- [ ] 如果改动不改变阶段状态，也要在“变更记录”中写明改动和验证边界。
- [ ] 失败证据不得删除。保留失败 attempt、Slurm 日志和发布目录，再创建新的 attempt 或发布。

同步关系只有一条主线：

```text
本地工作区中的本文件
  -> 与源码一起提交到个人分支
  -> 推送 Gitea 并通过 PR 合并 main
  -> 107 只读拉取合并提交
  -> 107 运行证据回写本文件并再次走 PR
```

## 2. 固定范围

第一版只实现以下主线：

```text
固定 MoS2 模板
  -> 输入生成与校验
  -> Slurm 受控执行
  -> relax
  -> SCF
  -> BAND
  -> DOS
  -> 解析、图表、导出和证据包
```

明确不进入第一版：

- Agent、聊天、RAG、Ollama 和 `vasp-wiki`。
- 机器学习、主动学习和跨服务器迁移。
- QE、EPW、Gaussian、DeepMD、LASP 和 CP2K 工作流。
- 将原 4090 LMateLab 生产数据库、上传文件、日志或密钥复制到 107。
- 泛化材料模板、任意命令执行、任意 Slurm 脚本和任意路径浏览。
- 为了“看起来完整”而扩展实验记录、学术报告、文献和服务器监控功能。

不再单独安排人工 SCF 基线。VASP、VASPKIT 和现有提交脚本视为可用；第一次真实 VASP 验收合并到阶段 7，失败时保留证据并就地处理。

## 3. 不可违反的运行约束

- 登录节点 `tradmin-02` 只执行短时检查、Git 拉取、`sbatch`、`squeue`、`sacct` 和配置操作。
- 依赖安装、前端构建、测试、FastAPI 服务和 VASP 计算必须通过 Slurm 运行。
- 竞赛根目录固定为 `/home/scc/pb23030683/lmatelab-107cup`。
- 竞赛源码检出固定为 `/home/scc/pb23030683/projects/LMateLab-107Cup`。
- 4090 `222.195.94.37` 只能转发网络流量并执行入口白名单，不能成为竞赛运行依赖或数据源。
- 共享 Unix 账号 `pb23030683` 不能作为成员身份依据；Git 提交身份和 LMateLab 应用身份必须分别记录。
- 同一 107 Unix 账号下的非 LMateLab 作业不得查询敏感内容、取消或修改。
- 页面显示、静态测试和队列名称不能替代真实作业、输出、完成标记和文件哈希。

## 4. 当前可验证基线

记录时间：`2026-08-05`。

### 4.1 源码与仓库

- 初始来源提交：`4d51e5837e62bb8582646f371352eb958af2a9db`。
- 来源清单 SHA-256：`fe35216bb093894e8d7b2edbac67e4fc11939d67af776325e1045e4ccf4aa3f9`。
- Gitea：`ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git`。
- Gitea `main`：`4a311a2cccdefe8b6f30f5414f5a2541c891fab9`。
- PR #2 已将 `codex/107cup-python-runtime` 合并到 `main`。
- 当前工作分支：`codex/107cup-access-control`。
- 当前分支基线提交：`4a311a2cccdefe8b6f30f5414f5a2541c891fab9`。
- 当前访问控制改动仅在本地工作树中验证，尚未提交、合并或部署到 107。

### 4.2 构建与发布

- Slurm 构建 Job：`32642`。
- Python：模块 `miniconda/py312` 创建的 Python 3.12 venv。
- 发布目录：`/home/scc/pb23030683/lmatelab-107cup/releases/196690a6b5dc583bf9e2a6b1b21f52494790244f`。
- `current` 已原子指向该发布目录。
- 发布 manifest SHA-256：`6c4e2452aaf95937517c1a8929ffd35104f24be0d43f762cc968bda09cab86dd`。
- 无效旧 Python 环境保存在 `backups/python-invalid-32642`。

### 4.3 网页服务与数据

- Slurm 服务 Job：`32676`。
- 节点：`anode16`。
- 服务端口：`18731`。
- `/api/health/live` 和 `/api/health/ready` 已实际返回成功。
- 两套 Alembic migration 已运行，两个 SQLite 数据库完整性检查均为 `ok`。
- 当前业务数据为空；仅有 1 个已注册管理员账号。
- VASP 自定义数据库目录和上传目录均为 0 个文件。

### 4.4 网络入口

- 4090 用户态 Nginx：`/home/Pwjb/.config/lmatelab-107cup-proxy/conf/nginx.conf`。
- Nginx 监听：`0.0.0.0:18733`。
- 4090 到 107 的内部 SSH 转发：`127.0.0.1:18734 -> anode16:18731`。
- 公网入口：`http://222.195.94.37:18733`。
- 已验证白名单 IP 返回 `200`，未授权 IP 返回 `403`。
- 当前入口为 HTTP，尚未完成 TLS 和自动恢复。

## 5. 阶段状态总表

状态只允许使用 `DONE`、`PARTIAL`、`PENDING`、`BLOCKED`。

| 阶段 | 状态 | 当前结论 | 下一门禁 |
|---|---|---|---|
| 1. 竞赛仓库初始化 | PARTIAL | 已导入、建立 Gitea，PR #2 已合并 main | 验证 main 保护、三人身份和只读 Deploy Key |
| 2. 无 Docker 构建与发布 | PARTIAL | 真实 Slurm 构建、测试、manifest 和原子切换已完成 | 演练失败构建不替换 current 和上一版回滚 |
| 3. 最小 107 网页服务 | PARTIAL | 真实计算节点服务、迁移、健康和空数据库已完成 | 增加受控恢复并记录服务结束后端口消失证据 |
| 4. 访问与角色控制 | PARTIAL | 本地已实现角色合同、写保护、迁移脚本、只读代理示例和专用前端入口 | 合并部署后预置 Viewer，并完成 Operator/Viewer 浏览器验收 |
| 5. 工作流模型与输入校验 | PENDING | 尚无工作流领域模型 | 所有危险输入在 `sbatch` 前失败 |
| 6. Slurm 适配器 | PENDING | 尚无提交、取消和对账控制链 | 完成普通短作业的全状态真实验收 |
| 7. VASP 四步闭环 | PENDING | 尚未从网页执行真实 VASP | 完成成功和人为失败两条链 |
| 8. 结果解析与证据包 | PENDING | 现有 BAND/DOS 解析能力尚未接入工作流 | 可追溯导出且失败不得显示成功 |
| 9. 恢复、安全和回归 | PENDING | 仅有部署契约和基础安全检查 | 故障、竞态和恶意输入全部失败关闭 |
| 10. 比赛交付验收 | PENDING | 尚无完整演示包 | 六层测试和真实演示复跑全部通过 |

## 6. 阶段 1：竞赛仓库初始化

**Files:**

- Maintain: `docs/107cup/source-provenance.md`
- Maintain: `docs/107cup/implementation-plan.md`
- Create: `.gitea/pull_request_template.md`
- Verify: local Git config, Gitea branch protection, 107 remote configuration

- [x] 导入不含 `.git`、密钥、数据库、日志、上传和运行数据的源码快照。
- [x] 记录来源提交、文件清单、字节数和 SHA-256。
- [x] 建立私有 Gitea 仓库和 `main`。
- [x] 建立个人功能分支并以 `Pwjb (jbwu@mail.ustc.edu.cn)` 推送。
- [ ] 为另外两名成员分别验证个人 Gitea 账号、SSH key 和提交邮箱。
- [ ] 验证 `main` 禁止直接推送且必须通过 PR。
- [ ] 在 107 验证 Deploy Key 可以 `fetch`，但尝试 `push --dry-run` 被拒绝。
- [x] 创建并合并 `codex/107cup-python-runtime` PR #2；合并提交为 `4a311a2cccdefe8b6f30f5414f5a2541c891fab9`。

验收命令：

```bash
git log --format='%H|%an|%ae|%G?' main
git ls-remote origin refs/heads/main
git remote -v
```

验收证据必须包含三名成员各自的提交哈希、作者邮箱和对应 PR，不以共享 Unix 用户名代替。

## 7. 阶段 2：无 Docker 构建与发布

**Files:**

- Maintain: `deploy/107cup/build.slurm`
- Maintain: `deploy/107cup/submit-build.sh`
- Maintain: `deploy/107cup/runtime.env.example`
- Test: `backend/tests/test_107cup_deploy_contract.py`

- [x] Slurm 作业创建项目专用 Python 和 Node 环境。
- [x] 构建作业运行后端专项测试、前端测试和 Vite 生产构建。
- [x] 发布内容写入 `releases/{git_commit}` 并生成 `manifest.txt` 与 `manifest.sha256`。
- [x] 只有完整校验通过后才原子替换 `current`。
- [x] 无效旧环境采用非覆盖备份。
- [ ] 用一个故意失败的构建提交验证 `current` 仍指向上一成功版本。
- [ ] 验证上一成功发布可在不重建依赖的情况下回滚并启动。

验收命令：

```bash
build_job_id=$(sbatch --parsable deploy/107cup/build.slurm)
squeue -j "$build_job_id"
sacct -j "$build_job_id" --format=JobID,State,ExitCode,Elapsed,NodeList
cd /home/scc/pb23030683/lmatelab-107cup/current
sha256sum -c manifest.sha256
sha256sum -c manifest.txt
```

## 8. 阶段 3：最小 107 网页服务

**Files:**

- Maintain: `backend/main_107cup.py`
- Maintain: `backend/competition_runtime.py`
- Maintain: `backend/routers/health.py`
- Maintain: `deploy/107cup/service.slurm`
- Maintain: `deploy/107cup/verify-runtime.sh`
- Test: `backend/tests/test_107cup_runtime.py`
- Test: `backend/tests/test_health_readiness.py`

- [x] 单进程 Uvicorn 仅通过 Slurm 运行。
- [x] 前端静态文件由同一个 FastAPI 服务提供。
- [x] 使用独立空 SQLite 数据库和独立数据目录。
- [x] 记录 Job ID、节点、端口、提交和 manifest 哈希。
- [x] 登录节点不存在 Uvicorn、Vite、Celery 或 Redis 常驻进程。
- [ ] 在受控窗口让服务作业正常结束，验证 `anodeXX:18731` 和转发入口随之不可达。
- [ ] 提交新服务作业并根据新节点安全更新 4090 内部转发。
- [ ] 编写不依赖管理员权限的启动、检查、停止和恢复运行手册。

验收命令：

```bash
bash deploy/107cup/verify-runtime.sh
service_job_id=$(cat /home/scc/pb23030683/lmatelab-107cup/runtime/service-job-id)
sacct -j "$service_job_id" --format=JobID,State,ExitCode,Elapsed,NodeList
```

## 9. 阶段 4：访问与角色控制

**Files:**

- Create: `backend/competition_authz.py`
- Create: `backend/tests/test_107cup_authz.py`
- Create: `frontend/tests/competitionRoles107Cup.test.mjs`
- Create: `frontend/src/App107Cup.jsx`
- Create: `frontend/src/config/competitionAccess.js`
- Create: `frontend/src/pages/CompetitionDashboard.jsx`
- Create: `deploy/107cup/relay/nginx.conf.example`
- Create: `deploy/107cup/migrate-competition-roles.py`
- Modify: `backend/auth.py`
- Modify: `backend/main_107cup.py`
- Modify: `backend/competition_runtime.py`
- Modify: `frontend/src/config/appNavigation.js`
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/routes/RequireAuth.jsx`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/vite.config.js`
- Modify: `deploy/107cup/allowed_users.example.json`

角色固定为：

```text
operator: 可以创建和控制属于 LMateLab 的工作流，不能操作其他 Slurm 作业
viewer:   只能读取演示工作流、状态、日志摘要和结果
```

后端依赖合同固定为：

```python
def require_roles(*allowed_roles: str): ...
def require_operator(current_user = Depends(get_current_user)): ...
def require_viewer_or_operator(current_user = Depends(get_current_user)): ...
```

- [x] 4090 公开入口配置 IP 白名单并验证 `200/403`。
- [x] 本地实现 `operator/viewer` 授权合同；旧 `root/user` 在 107 竞赛入口登录时失败关闭。
- [ ] 迁移脚本已通过本地备份、原子更新、密码哈希不变和重复运行测试；尚未在 107 数据库执行。
- [ ] 为三名成员配置独立应用身份；共享 Unix 账号不共享应用密码。
- [ ] 后端和专用前端已关闭注册与密码重置；Viewer 尚未在 107 受控预置。
- [ ] 已新增 Nginx 只读配置示例，只允许 `/api/auth/login` 的 POST 和其他 GET；尚未替换 4090 当前运行配置。
- [x] 后端角色依赖对 Viewer 的业务 `POST/PUT/PATCH/DELETE` 返回 `403`，Operator 通过。
- [ ] Operator 写接口同时验证角色、资源归属和请求路径。
- [x] 107 杯专用构建仅包含登录、竞赛 Dashboard 和认证壳；导航移除所有非主线入口。
- [x] 107 后端只注册认证和健康路由，无关业务 API 未挂载；专用前端未注册隐藏页面 URL。
- [ ] 本机 SSH 隧道和公开 Viewer 入口分别完成浏览器验收。

阶段门禁：

```text
Viewer 登录成功 + GET 成功 + 任一业务写请求 403
Operator 登录成功 + 仅允许竞赛资源写操作
无登录请求 401
非白名单网络请求 403
```

阶段 4 不要求已有真实 VASP 演示数据。Viewer 对真实演示数据的验收在阶段 8 和阶段 10 重复执行。

本地 TDD 证据（`2026-08-05`）：

- RED：新增后端授权/迁移/部署契约后出现 11 个预期失败；新增前端角色与裁剪契约后出现 3 个预期失败；专用构建入口测试先出现 1 个预期失败。
- GREEN：后端阶段 4 专项测试 `24/24` 通过，其中未登录请求为 `401`、角色拒绝和 Viewer 写拒绝为 `403`；完整前端测试 `21/21` 通过。
- BUILD：`VITE_LMATELAB_EDITION=107cup npm run build` 通过，产物只生成登录、Dashboard 和主入口 JS 分块。
- ROUTES：本地导入 `main_107cup` 后仅注册 `login`、`me`、只读密码策略、健康和 SPA 路由；注册、密码重置以及项目、实验记录、文件、VASP 数据库、报告、Issue 和 Agent API 均未挂载。
- 边界：Windows 全仓库后端基线仍有 6 个既存环境错误（Docker、`fcntl`、生产密钥、`pytest` 和 GBK 子进程解码相关），不能记录为全仓库后端通过，也不能替代 107 Slurm 构建验收。
- LINT：本次 107 前端相关文件的定向 ESLint 检查通过；全仓库 ESLint 仍有 36 个旧模块错误，不在本批次扩大修复。

## 10. 阶段 5：工作流数据模型与输入校验

**Files:**

- Create: `backend/models_workflow.py`
- Create: `backend/schemas_workflow.py`
- Create: `backend/routers/competition_workflows.py`
- Create: `backend/services/competition_inputs.py`
- Create: `backend/competition_templates/mos2_v1/POSCAR`
- Create: `backend/competition_templates/mos2_v1/INCAR.relax`
- Create: `backend/competition_templates/mos2_v1/INCAR.scf`
- Create: `backend/competition_templates/mos2_v1/INCAR.band`
- Create: `backend/competition_templates/mos2_v1/INCAR.dos`
- Create: `backend/competition_templates/mos2_v1/template.json`
- Create: `backend/alembic/versions/107c0ffee001_add_competition_workflows.py`
- Create: `backend/tests/test_competition_inputs.py`
- Create: `backend/tests/test_competition_workflow_models.py`

数据库实体固定为：

```text
workflow_runs
workflow_steps
workflow_attempts
workflow_events
workflow_files
workflow_templates
```

每个文件记录相对路径、大小、SHA-256、生成来源和所属 attempt。POTCAR 不进入 Git；只记录元素顺序、赝势标识和运行时文件哈希。

- [ ] 先写失败测试覆盖缺文件、路径穿越、命令注入、错误元素顺序和参数越界。
- [ ] 创建 Alembic migration，并在全新数据库和升级数据库各运行一次。
- [ ] 固定 MoS2 模板版本为 `mos2_v1`，不接受任意模板上传。
- [ ] 使用结构解析器核对 POSCAR 元素顺序，不使用字符串猜测。
- [ ] INCAR 只允许阶段定义的键和值域。
- [ ] KPOINTS 由固定模板或受控生成器产生。
- [ ] 所有校验在创建 Slurm 作业前完成。
- [ ] 校验失败写入事件表，但不得产生 Job ID 或 attempt 执行目录。

## 11. 阶段 6：Slurm 适配器

**Files:**

- Create: `backend/services/competition_slurm.py`
- Create: `backend/services/competition_reconcile.py`
- Create: `backend/tests/test_competition_slurm.py`
- Create: `backend/tests/fixtures/fake_slurm/`
- Create: `deploy/107cup/slurm/probe.slurm`
- Modify: `backend/routers/competition_workflows.py`

适配器只能使用参数数组调用固定二进制，不使用 `shell=True`。LMateLab 作业必须同时满足以下归属证据：

```text
JobName 前缀为 lmatelab-
WorkDir 位于 /home/scc/pb23030683/lmatelab-107cup/workflows
Slurm comment 含 workflow_id 和 attempt_id
数据库 ledger 中存在相同 Job ID
```

- [ ] 从服务计算节点验证 `sbatch --test-only`、`squeue`、`sacct` 和 `scancel`。
- [ ] 假 Slurm 测试覆盖提交、排队、运行、完成、失败、取消和命令超时。
- [ ] 状态映射保留原始 Slurm state、exit code、reason 和时间戳。
- [ ] 日志读取限制在 attempt 目录并限制单次读取字节数。
- [ ] `scancel` 前验证四项归属证据，任一不符即拒绝。
- [ ] 服务重启后从数据库和 `sacct` 对账，不把陈旧状态显示为运行中。
- [ ] 真实提交一个短时普通作业并完成取消、失败和重启对账验收。
- [ ] 创建一个非 LMateLab 作业并验证平台无法取消它。

## 12. 阶段 7：VASP 四步真实闭环

**Files:**

- Create: `backend/services/competition_vasp.py`
- Create: `backend/competition_templates/mos2_v1/run-stage.slurm`
- Create: `backend/tests/test_competition_vasp.py`
- Modify: `backend/routers/competition_workflows.py`

阶段顺序固定为：

```text
relax -> SCF -> BAND -> DOS
```

- [ ] 每一步创建独立 attempt 目录和独立 Slurm Job ID。
- [ ] 前一步只有通过阶段验收函数后，下一步才允许提交。
- [ ] relax 验收结构输出、电子收敛、离子收敛和正常结束标记。
- [ ] SCF 验收 CHGCAR、WAVECAR、费米能级和正常结束标记。
- [ ] BAND 只复用已验收 SCF 产物并记录输入文件哈希。
- [ ] DOS 只复用已验收 SCF 产物并记录输入文件哈希。
- [ ] 记录 VASP 版本、VASPKIT 版本、GPU/CPU、峰值内存、耗时和 Slurm ExitCode。
- [ ] 执行一个完整成功工作流。
- [ ] 执行一个人为失败工作流并验证后续步骤没有 Job ID。

真实 VASP 完成必须同时具备 Slurm `COMPLETED/0:0`、VASP 正常结束标记、阶段文件集合和哈希；缺一项都不能显示成功。

## 13. 阶段 8：结果解析与证据包

**Files:**

- Create: `backend/services/competition_results.py`
- Create: `backend/services/competition_bundle.py`
- Create: `backend/tests/test_competition_results.py`
- Create: `frontend/src/pages/workflows/WorkflowList.jsx`
- Create: `frontend/src/pages/workflows/WorkflowDetail.jsx`
- Create: `frontend/src/pages/workflows/WorkflowResults.jsx`
- Create: `frontend/tests/competitionWorkflowResults.test.mjs`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/config/appNavigation.js`

- [ ] 复用现有结构、BAND 和 DOS 解析能力，不复制第二套解析器。
- [ ] 解析结果携带来源 attempt、原始文件路径和 SHA-256。
- [ ] 缺文件、不收敛和解析异常映射为明确失败，不能返回空成功图。
- [ ] 工作流详情显示步骤时间线、Job ID、状态、资源和关键日志摘要。
- [ ] BAND/DOS 图同时提供原始数值下载。
- [ ] 结果包包含 Git 提交、发布 manifest、模板版本、输入、输出、事件和哈希清单。
- [ ] Operator 与 Viewer 下载同一不可变证据包。
- [ ] Viewer 通过公开入口查看真实成功和失败工作流，所有写请求仍为 `403`。

## 14. 阶段 9：恢复、安全和回归

**Files:**

- Create: `backend/tests/test_competition_recovery.py`
- Create: `backend/tests/test_competition_security.py`
- Create: `frontend/tests/competitionWorkflowE2E.test.mjs`
- Create: `docs/107cup/recovery-runbook.md`
- Modify: `deploy/107cup/verify-runtime.sh`

- [ ] 服务重启时恢复未完成工作流并与 Slurm 对账。
- [ ] Slurm 暂时不可用时保留最后可信状态并标记陈旧时间，不伪造失败或成功。
- [ ] 数据库写入失败时不提交下一阶段。
- [ ] 取消与完成竞态以 `sacct` 最终状态和事件序列收敛。
- [ ] 网关目标变化时公开入口失败关闭，不改为生产 4090 LMateLab。
- [ ] 发布回滚不修改历史 attempt 和证据包。
- [ ] 路径穿越、符号链接逃逸、参数注入、超大日志和非法文件名全部拒绝。
- [ ] 验证平台不能查看或控制同一账号下的非 LMateLab 作业。
- [ ] 重跑后端、前端、假 Slurm、107 真实 Slurm、真实 VASP 和浏览器六层测试。

## 15. 阶段 10：比赛交付验收

**Files:**

- Create: `docs/107cup/deployment.md`
- Create: `docs/107cup/data-and-provenance.md`
- Create: `docs/107cup/demo-script.md`
- Create: `docs/107cup/final-acceptance.md`
- Create: `docs/107cup/artifacts/manifest.sha256`

- [ ] 从合并后的 `main` 固定提交重新构建发布。
- [ ] 在全新浏览器会话分别复跑 Operator 和 Viewer 演示。
- [ ] 复跑真实成功工作流和人为失败工作流。
- [ ] 导出桌面、移动页面截图和演示视频素材。
- [ ] 验证原 4090 LMateLab 停止时竞赛项目仍能运行；只允许网络转发依赖 4090。
- [ ] 验证源码、环境、数据库、服务、VASP 任务和结果全部位于 107。
- [ ] 验证 Agent、机器学习、跨服务器迁移和其他旁支未进入发布。
- [ ] 生成最终 SHA-256 清单并由三名成员复核。

最终完成条件：

```text
三人个人 Gitea 身份可追溯
Operator 完成真实 relax -> SCF -> BAND -> DOS
Viewer 只读查看真实状态、日志和 BAND/DOS 结果
成功和失败都具有完整证据包
六层测试全部通过
任何失败层不能被更高层成功替代
```

## 16. 六层测试门禁

| 层级 | 命令或入口 | 通过标准 |
|---|---|---|
| 1. 单元测试 | `python -m unittest discover -s backend/tests -p 'test_*.py'` | 相关测试 0 failure、0 error |
| 2. 假 Slurm 集成 | `python -m unittest backend.tests.test_competition_slurm -v` | 全状态和归属测试通过 |
| 3. 107 真实 Slurm | `sbatch`、`squeue`、`sacct`、`scancel` 证据 | 真实 Job ID 与最终状态一致 |
| 4. 真实 VASP | 阶段验收器与原始 OUTCAR/vasprun.xml | 四步成功链和失败阻断链均通过 |
| 5. 浏览器端到端 | Operator/Viewer 两个新会话 | 页面、API、角色和下载行为一致 |
| 6. 最终演示复跑 | `docs/107cup/demo-script.md` | 从登录到证据包完整复现 |

## 17. 下一执行批次

下一批次只完成阶段 1 至阶段 4 的收尾，不进入阶段 5：

- [x] 创建并合并运行时修复 PR #2。
- [ ] 演练失败构建不替换 `current`，再演练上一成功发布回滚。
- [ ] 在受控时间验证服务结束后端口消失，并提交新服务作业恢复入口。
- [x] 写 Operator/Viewer 后端失败测试。
- [x] 实现最小角色依赖并通过本地测试。
- [x] 新增公开入口只读 Nginx 配置示例；实际替换与验证仍待 107 部署后执行。
- [x] 通过专用构建入口裁剪 107 杯导航、首页和无关页面分块。
- [ ] 在本机和公开入口分别完成浏览器权限验收。
- [ ] 将真实 107 证据和状态更新回本文件并提交 PR。

## 18. 变更记录

### 2026-08-05

- 建立本文件作为唯一实施路线。
- 记录阶段 1 至阶段 4 的真实部署状态。
- 确认取消独立人工 SCF 基线，第一次真实 VASP 验收进入阶段 7。
- 将下一执行批次限定为仓库收尾和访问角色控制，不扩展 LMateLab 旁支功能。
- PR #2 合并后将本地与 Gitea `main` 同步到 `4a311a2cccdefe8b6f30f5414f5a2541c891fab9`，并创建 `codex/107cup-access-control` 隔离工作树。
- 按 TDD 实现阶段 4 的 `operator/viewer` 合同、Viewer 写拒绝、竞赛账号变更关闭和 `root -> operator` 幂等备份迁移。
- 新增 4090 用户态 Nginx 只读配置示例；当前在线代理尚未替换，因此公开入口方法限制仍未完成真实验收。
- 新增 `App107Cup.jsx` 专用构建入口，107 前端产物不再包含实验记录、报告、数据库、Agent 等无关页面分块。
- 本批次未进入工作流模型、Slurm 控制或 VASP 功能。
