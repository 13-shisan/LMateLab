# LMateLab 107 Cup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 107 平台独立交付一个围绕固定 MoS2 `relax -> SCF -> BAND -> DOS` 闭环的 LMateLab 竞赛版本，并提供可追溯、可恢复、可只读演示的真实 Slurm/VASP 证据链。

**Architecture:** 源码由私有 Gitea 管理，107 只读拉取固定提交；构建、网页服务和 VASP 作业全部通过 Slurm 运行在 107 计算节点。4090 仅作为可替换的网络转发与 IP 白名单入口，不保存竞赛业务数据，也不执行 LMateLab 或 VASP 业务逻辑。

**Tech Stack:** React/Vite, FastAPI, SQLAlchemy/Alembic, SQLite, Slurm, VASP 6.4.2 GPU, VASPKIT 1.5.1, user-scoped Nginx, Gitea.

---

## 1. 文档地位与更新规则

本文件是 107 杯项目唯一的实施路线和状态账本。不得再创建内容重叠的第二份总路线。

已确认的专项设计可以保存在 `docs/superpowers/specs/`，但不得另立阶段状态或改变本文件的主路线。当前前端完整形态预览设计为 `docs/superpowers/specs/2026-08-10-107cup-frontend-preview-design.md`。

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
固定 MoS2 模板或 Operator 上传一个受限的小型 POSCAR/CIF
  -> 输入生成与校验
  -> 可追溯工作流草稿
  -> Slurm 受控执行
  -> relax
  -> SCF
  -> BAND
  -> DOS
  -> 解析、周期表驱动的 VASP 数据库、图表、导出和证据包
```

上传结构只扩展输入来源，不扩展模板和命令范围：单文件最大 `1 MiB`、最多 `200` 个原子，只接受文本 POSCAR/CIF，不接受压缩包、目录、任意模板或任意路径。

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

记录时间：`2026-08-10`。

### 4.1 源码与仓库

- 初始来源提交：`4d51e5837e62bb8582646f371352eb958af2a9db`。
- 来源清单 SHA-256：`fe35216bb093894e8d7b2edbac67e4fc11939d67af776325e1045e4ccf4aa3f9`。
- Gitea：`ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git`。
- Gitea `main`：`f8aee97e4367fa45befab77c3a248d99dd3e36ae`，Windows 于 `2026-08-11` 重新 fetch 后确认。
- PR #11 已将 `codex/107cup-frontend-preview-design` 合并到 `main`，包含已批准设计和 14 项实施计划。
- 107 源码检出最后一次已记录同步仍为 PR #10 的合并提交 `11bac230cb9cd714596c4a460512699db76e0aca`；本次本地前端实现尚未合并或部署，下一次远端操作前必须重新现场核验 detached HEAD 和工作树状态。
- 当前生产仍为 Job `33852`、节点 `anode16` 和发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，本次仓库收尾未重建或重启服务。

### 4.2 构建与发布

- 最新 Slurm 构建 Job：`33839`。为避开 competition 长时间排队，本次提交仅在命令行覆盖为账号 `stu`、分区 `Students`、QOS `qos_stu_default`；构建仍在 107 Slurm 计算节点执行，资源为 4 CPU、12 GiB、45 分钟上限，仓库默认 competition 配置未修改。
- Python：模块 `miniconda/py312` 创建的 Python 3.12 venv。
- 发布目录：`/home/scc/pb23030683/lmatelab-107cup/releases/1bba72d0ade2bb7024081d384584524a9c9d1c69`。
- `current` 已原子指向该发布目录。
- 发布 manifest SHA-256：`fe94381217de7f07c5bfbef61902e755bc567920e3a43d2a50506a51796b1265`；`manifest.txt` 中 340 个文件全部通过作业内复核。
- 构建日志：`logs/build-33839.out` 为 37882 字节，SHA-256 为 `9f88bc5770975afed9f263d32a359dd32f3607cb75cfc7ee4ae21fbf743d60be`；`logs/build-33839.err` 为 5812 字节，SHA-256 为 `dd5d939acaf78dddda1337b89a58cfbbda1d4ee0174eaee8da980357ba5eeb98`。
- 构建内后端专项测试 `31/31` 通过，前端测试 `21/21` 通过；107 专用 Vite 构建完成 1826 个模块，构建日志记录耗时 4.98 秒。
- `squeue` 已无 Job `33839`，`scontrol` 已返回 `Invalid job id specified`，`sacct` 仍返回 0 条数据；构建节点和最终 Slurm 状态不可恢复，不得写成 `COMPLETED/0:0`。成功边界仅由完整日志、作业内 manifest 复核、发布目录和原子 `current` 切换共同证明。
- 故意失败构建 Job `33979` 在 `Students/anode18` 以 `FAILED`、`ExitCode=1:0`、`Reason=NonZeroExitCode` 结束，直接错误为缺失 `manifest.sha256`。演练前后 `current` 均保持 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，在线 Job `33852` 和网页入口未受影响。失败目录保留在 `releases/a33366702f2e62ff9c0012bbc625fbec92fda790`，证据位于 `evidence/build/20260808T162810+0800-build-33979-failed/`，其中清单复核通过且文件均为 `0600`。
- 隔离回滚 Job `34005` 在 `P107-A100/anode16` 使用既有发布 `30a18e1b7000d93a2cca39849a25edb0ff957e28`、独立 SQLite 和端口 `18732` 启动，未执行构建或依赖安装；live 元数据返回旧提交，ready 和两库完整性均通过，随后正常关闭。保存的 `scontrol` 记录 `COMPLETED`、`ExitCode=0:0`、耗时 3 秒；`sacct` 仍为空，不用其替代 `scontrol` 证据。生产 `current` 演练前后均保持 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，临时端口随后关闭。
- 回滚演练的两次失败 Job `33998` 和 `34001` 均保留：前者暴露空数据库缺少待迁移 operator，后者完成 live/ready 后把受控 TERM 的子进程状态 143 传播为批作业失败。最终脚本只接受带完整 Uvicorn shutdown 标记的受控 `0/143` 子进程状态，并让 Slurm 批作业自身零退出。三次证据分别位于 `evidence/rollback/{33998,34001,34005}/`，文件均为 `0600`，对应 SHA-256 清单位于 `rollback-smoke/{job_id}/evidence-manifest.sha256` 并已复核。
- 无效旧 Python 环境保存在 `backups/python-invalid-32642`。

### 4.3 网页服务与数据

- 当前 Slurm 服务 Job：`33852`，账号 `competition`、分区 `P107-A100`、QOS `qos_p107-a100`，时限为 4 天，计划结束时间 `2026-08-12T11:46:52+08:00`。
- 节点：`anode16`。
- 服务端口：`18731`。
- `/api/health/live` 和 `/api/health/ready` 已实际返回成功。
- 两套 Alembic migration 已运行，两个 SQLite 数据库完整性检查均为 `ok`。
- 当前业务数据为空；唯一账号 `pb23030683` 已由 `root` 迁移为 `operator`，迁移前后密码哈希一致。
- 迁移备份：`backups/competition-roles/eln.db.before-competition-roles.20260805T170654166520Z.sqlite`，SHA-256 为 `8b2318b9d6c6fbc8c042a6a15a78c7f539db3635e2a1689a05cc3ed5dd0c57ce`；首次创建权限为 `0644`，发现后已将目录收紧为 `0700`、文件收紧为 `0600`。PR #4 的源码修正现已部署，后续新备份使用 `O_EXCL|0600` 创建且同名不覆盖。
- 新服务上线快照位于 `evidence/runtime/20260808T115141+0800-service-33852-post-deploy/`：`service-33852.out` 为 539 字节，SHA-256 为 `4a46550387c8430c1e4630be3744427e590c57588f58b017fd2cafb5a13e494c`；`service-33852.err` 为 455 字节，SHA-256 为 `b321cbd0ec52eb1431f0b63a842e5ca6b6a5bf70cc801281b13ba31e30c867b1`。快照目录权限为 `0700`，文件和哈希清单权限为 `0600`；活动日志继续增长。
- 被替换的 Job `32769` 于 `2026-08-08T11:49:47+08:00` 经归属核对后由 `scancel` 受控停止；Uvicorn 日志记录完整 shutdown，随后 `anode01:18731` 实测不可达。最终快照位于 `evidence/runtime/20260808T114947+0800-service-32769-controlled-cancel/`：stdout SHA-256 为 `e7cf0e647a9a97132c74aa8a8bff7fb2e1ddf51bc64ca4762de7d2337cbadbf3`，stderr 为 `2efe3681da0a134a0f5e6637ebe89a7bae78f8c823469fec437d6e8a2fac857a`，终止元数据为 `e8059a61b62d6b40284305653f9e339f08abb0b5833c207d165864c989a4cd88`；`sacct` 仍无记录，因此该证据不能写成正常零退出。
- 旧 Job `32676` 于 `2026-08-06T01:24:19+08:00` 因 Students 时限被 Slurm 取消，Uvicorn 正常关闭，随后 `anode16:18731` 实测不可达；因 `sacct` 空表，最终状态只能以保留的 `service-32676.err` 原始标记为证据。
- VASP 自定义数据库目录和上传目录均为 0 个文件。

### 4.4 网络入口

- 4090 用户态 Nginx：`/home/Pwjb/.config/lmatelab-107cup-proxy/conf/nginx.conf`。
- Nginx 监听：`0.0.0.0:18733`。
- 4090 到 107 的内部 SSH 转发：`127.0.0.1:18734 -> anode16:18731`。
- 4090 上的 107 SSH 复用主连接使用 `/home/Pwjb/.ssh/cm-107cup`，socket 权限为 `0600`，配置 96 小时 `ControlPersist` 和 30 秒保活；它减少重复二次验证，但不是永久自动恢复机制。
- 公网入口：`http://222.195.94.37:18733`。
- 已验证白名单 IP 返回 `200`，未授权 IP 返回 `403`。
- 运行中的 Nginx 已替换为只读公开入口：登录端点只允许 POST，其余页面和 API 只允许 GET；注册 POST、非登录 POST 和登录端点 PUT 实测均为 `403`。
- 4090 代理、Windows 本地入口 `http://127.0.0.1:18733` 与校园网直连入口均返回 Job `33852`、节点 `anode16` 和提交 `1bba72d`；注册 POST 仍为 `403`。运行配置 SHA-256 为 `0c011ea9442733daf5d3277d4632a662264083ff0432b9abdfaad5b5828c99c8`，权限为 `0600`；Nginx 自动创建的 `client-body` 和 `proxy-temp` 目录权限均为 `0700`。
- 当前入口为 HTTP，尚未完成 TLS 和自动恢复。

## 5. 阶段状态总表

状态只允许使用 `DONE`、`PARTIAL`、`PENDING`、`BLOCKED`。

| 阶段 | 状态 | 当前结论 | 下一门禁 |
|---|---|---|---|
| 1. 竞赛仓库初始化 | PARTIAL | Gitea `main` 已由 PR #11 更新到 `f8aee97`，本地前端功能检查点为 `ab6064d`，107 检出最后记录仍为 `11bac23` 且本批次未刷新；107 Deploy Key 只读和 `main` 保护均已完成 | 取得另外两名成员的个人 Git 身份证据；实现 PR 合并后再核验并刷新 107 detached checkout |
| 2. 无 Docker 构建与发布 | DONE | Job 33839 完成构建和原子切换；Job 33979 证明失败不切换；Job 34005 证明旧发布无需重建即可隔离启动 | 保持证据和发布不可变；平台 `sacct` 空表作为已知限制保留 |
| 3. 最小 107 网页服务 | PARTIAL | Job 33852 在 anode16 运行；Job 34005 完成旧发布启动、健康检查、优雅关闭和 Slurm 零退出 | 增加服务与 4090 转发自动恢复 |
| 4. 访问与角色控制 | PARTIAL | Viewer 已通过公开入口验收；Operator 已通过独立隧道完成认证、身份和桌面/移动界面验收；当前尚无业务写接口 | 配置三名成员独立应用身份；阶段 5/6 提供写接口后验收资源归属边界 |
| 5. 工作流模型与输入校验 | PENDING | 前端交互和草稿输入范围已确认，尚无工作流领域模型 | 所有危险输入在 `sbatch` 前失败 |
| 6. Slurm 适配器 | PENDING | 尚无提交、取消和对账控制链 | 完成普通短作业的全状态真实验收 |
| 7. VASP 四步闭环 | PENDING | 尚未从网页执行真实 VASP | 完成成功和人为失败两条链 |
| 8. 结果解析与证据包 | PENDING | 前端结果/数据库形态和复用边界已确认，现有 BAND/DOS 解析能力尚未接入工作流 | 可追溯导出且失败不得显示成功 |
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
- [x] 验证 `main` 禁止直接推送且必须通过 PR。
- [x] 在 107 验证 Deploy Key 可以 `fetch`，但尝试 `push --dry-run` 被拒绝。
- [x] 创建并合并 `codex/107cup-python-runtime` PR #2；合并提交为 `4a311a2cccdefe8b6f30f5414f5a2541c891fab9`。
- [x] 创建并合并 `codex/107cup-access-control` PR #3；合并提交为 `30a18e1b7000d93a2cca39849a25edb0ff957e28`。
- [x] 创建并合并 `codex/107cup-runtime-evidence` PR #4；合并提交为 `1bba72d0ade2bb7024081d384584524a9c9d1c69`。
- [x] 创建并合并 `codex/107cup-rollback-evidence` PR #6；合并提交为 `2c92ff2c1770f09ca697adaf11eaf495a14875b1`。
- [x] 创建并合并 `codex/107cup-viewer-acceptance` PR #7；合并提交为 `0ea0354ec893f9ac9c4095fe19977b38a0e66456`。
- [x] 创建并合并 `codex/107cup-operator-acceptance` PR #8；合并提交为 `1ba1661c4c114fc271cf5bd7dd4e1dddc51845e1`。
- [x] 创建并合并 `codex/107cup-repository-gates` PR #9；合并提交为 `79fa22cd932c6d60d8002c433fa851ba8ef90fa3`。
- [x] 创建并合并 `codex/107cup-main-protection-evidence` PR #10；合并提交为 `11bac230cb9cd714596c4a460512699db76e0aca`。

验收命令：

```bash
git log --format='%H|%an|%ae|%G?' main
git ls-remote origin refs/heads/main
git remote -v
```

验收证据必须包含三名成员各自的提交哈希、作者邮箱和对应 PR，不以共享 Unix 用户名代替。

107 Deploy Key 只读证据（`2026-08-09`）：

- FETCH：107 detached checkout 使用远端 `ssh://wugroup-lmatelab/107-team/LMateLab.git` 成功读取 `main`，取得合并提交 `1ba1661c4c114fc271cf5bd7dd4e1dddc51845e1`。
- WRITE：对独立探测引用执行 `git push --dry-run`，Gitea 明确返回 `Deploy Key: 4:107-LMateLab-107Cup is not authorized to write to 107-team/LMateLab`，退出码为 `128`。
- ABSENCE：拒绝后再次查询远端，`refs/heads/codex/deploy-key-probe-20260809` 不存在，未创建任何分支。
- EVIDENCE：原始输出位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/repository/deploy-key-readonly-1ba1661`；目录为 `0700`，文件和 SHA-256 清单为 `0600`，清单复核全部通过。

Gitea `main` 保护证据（`2026-08-09`）：

- 受保护分支表达式严格为 `main`；直接推送禁用，强制推送禁用；PR 合并启用。
- 拒绝审核阻止合并，官方审核请求更改阻止合并，过时 PR 阻止合并；管理员也必须遵守保护规则。
- 当前所需批准数为 `0`，因此没有最低批准人数门禁；状态检查因仓库当前没有 CI 检查而禁用，因此没有 CI 状态门禁；签名提交为可选。这些设置不得表述为已经具备审批阈值、CI 检查或强制签名保证。
- 截图保存在 `D:\Documents\matflow项目\LMateLab-107Cup-evidence\repository-protection-20260809`：
  - `before-no-protected-branch.png`：SHA-256 `90c682e0f33cbaa7b780b0522cf08731b161cb7535927edcce9d0dc7e29a9eaa`
  - `rule-created.png`：SHA-256 `91eff3325e9600fbdd7e05c3295e75ce61befaa290c3cc87ed431051af021b41`
  - `main-disable-push.png`：SHA-256 `dade0b51c9fae8534947dc594268b84d9f22fb3a6159f57c633845313a1a149a`
  - `main-merge-enforcement.png`：SHA-256 `cd4b89c33a1182fada5e5374932ef091640be33d80e3b58cef5c28cae5d8fb6b`

## 7. 阶段 2：无 Docker 构建与发布

**Files:**

- Maintain: `deploy/107cup/build.slurm`
- Maintain: `deploy/107cup/submit-build.sh`
- Maintain: `deploy/107cup/runtime.env.example`
- Maintain: `deploy/107cup/rollback-smoke.slurm`
- Test: `backend/tests/test_107cup_deploy_contract.py`

- [x] Slurm 作业创建项目专用 Python 和 Node 环境。
- [x] 构建作业运行后端专项测试、前端测试和 Vite 生产构建。
- [x] 发布内容写入 `releases/{git_commit}` 并生成 `manifest.txt` 与 `manifest.sha256`。
- [x] 只有完整校验通过后才原子替换 `current`。
- [x] 无效旧环境采用非覆盖备份。
- [x] 用故意失败的构建 Job `33979` 验证 `current` 仍指向上一成功版本。
- [x] 用隔离回滚 Job `34005` 验证上一成功发布可在不重建依赖的情况下启动并正常退出。

回滚自检不切换生产 `current`，而是在 Job 私有目录中原子切换 `rollback-current`，并使用独立数据库和端口验证旧发布。这样能够验证发布可回滚性，同时不与 Job `33852` 共享 SQLite、runtime 指针或服务端口。

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
- [x] 提交新服务作业并根据新节点安全更新 4090 内部转发。
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
- Create: `deploy/107cup/provision-competition-viewer.py`
- Create: `deploy/107cup/provision-viewer.slurm`
- Create: `backend/tests/test_107cup_viewer_provision.py`
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
- [x] 迁移脚本已在 107 执行，`root -> operator`、数据库完整性、备份和密码哈希不变均已验证；备份权限缺口已运行时收紧，PR #4 的源码修正已部署。
- [ ] 为三名成员配置独立应用身份；共享 Unix 账号不共享应用密码。
- [x] 后端和专用前端已关闭注册与密码重置，运行配置显式设置两个开关为 `0`。
- [x] 专用 `demo-viewer` 已通过短时 Slurm Job `34041` 受控创建，Job `34046` 在密码哈希不变的条件下将不可登录的保留域名邮箱迁移为 `demo-viewer@matflow.top`；两次变更均先生成 `0600` SQLite 备份。
- [x] 4090 Nginx 已替换为只读配置，只允许 `/api/auth/login` 的 POST 和其他 GET；活动配置及备份权限均为 `0600`。
- [x] 后端角色依赖对 Viewer 的业务 `POST/PUT/PATCH/DELETE` 返回 `403`，Operator 通过。
- [ ] Operator 写接口同时验证角色、资源归属和请求路径。
- [x] 107 杯专用构建仅包含登录、竞赛 Dashboard 和认证壳；导航移除所有非主线入口。
- [x] 107 后端只注册认证和健康路由，无关业务 API 未挂载；专用前端未注册隐藏页面 URL。
- [x] 独立 Chrome 已完成匿名桌面和移动登录页验收：无令牌重定向、注册/找回入口隐藏、错误凭据反馈和移动端无横向溢出均通过。
- [x] Windows 本地入口 `http://127.0.0.1:18733` 已完成公开 Viewer 浏览器验收：登录和 `/api/auth/me` 均为 `200`，业务 POST 为 `403`，桌面/移动页面均显示“只读访客 / 只读演示权限”。
- [x] Operator 通过独立本机 SSH 隧道完成登录、`/api/auth/me`、身份显示和桌面/移动浏览器验收。
- [ ] 阶段 5/6 提供真实工作流写接口后，验证 Operator 写权限、资源归属和请求路径；当前认证壳不能替代该验收。

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

Viewer 预置与验收证据（`2026-08-08`）：

- RED/GREEN：Linux 符号链接数据库拒绝测试先失败、修复后通过；真实浏览器首次登录因 `viewer@lmatelab.invalid` 被 `EmailStr` 拒绝而返回 `422`，随后为唯一允许的旧邮箱迁移补失败测试并修复。
- TEST：Slurm Job `34040` 对初版提交运行 Linux 专项测试 `23/23`；修正后 Job `34045` 对提交 `eab70688259a9a85ae2007143eafed2b72aadacd` 运行 `24/24`，两者均为 `COMPLETED/0:0`。
- PROVISION：Job `34041` 创建 Viewer；Job `34046` 复用原 `0600` 密码文件，仅迁移邮箱，验证迁移前后密码哈希一致、凭据仍可验证、数据库完整性为 `ok`，且当前服务 Job `33852` 未重启。
- EVIDENCE：最终证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/access/viewer-34046`，目录为 `0700`、文件和清单为 `0600`；数据库备份为 `/home/scc/pb23030683/lmatelab-107cup/backups/competition-viewer/eln.db.before-viewer.20260808T114852712450Z.sqlite`，权限为 `0600`。
- BROWSER：全新 Viewer 会话的登录和 `/api/auth/me` 网络记录均为 `200`，控制台 0 error/0 warning；桌面与 `390x844` 截图本地保存为 `LMateLab-107Cup-evidence/viewer-34041/viewer-desktop.png` 和 `viewer-mobile.png`。
- BOUNDARY：Viewer 是团队演示和自动验收共用的只读应用账号，不替代三名成员的个人 Operator 身份；密码只保存在 107 的 `config/credentials/demo-viewer.password`，不进入 Git 或方案文件。Operator 认证与身份界面验收已完成，但业务写权限和资源归属仍待阶段 5/6，阶段 4 保持 `PARTIAL`。

Operator 浏览器验收证据（`2026-08-08`）：

- ROUTE：独立入口为 `Windows:18734 -> 4090:18734 -> anode16:18731`；验收期间 107 服务继续由 Slurm Job `33852` 运行，未重建、重启或修改生产数据库。
- AUTH：显式退出残留 Viewer 会话后，Operator 登录 `POST /api/auth/login` 和 `GET /api/auth/me` 均为 `200`；页面显示 `107杯管理员 / 操作员 / 受控操作权限`，没有读取、恢复或重置 Operator 密码。
- TEST：Slurm Job `34062` 在 `Students/anode20` 对合并提交 `0ea0354` 运行认证与 Viewer 预置专项测试 `12/12`，以 `COMPLETED/0:0` 结束，耗时 12 秒；证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/access/operator-34062`，目录为 `0700`、文件和 SHA-256 清单为 `0600` 且复核全部通过。
- BROWSER：登录后的控制台为 0 error/0 warning；`1440x900` 与 `390x844` 页面均通过人工检查，无文字重叠。截图与不含凭据的验收记录保存在本地 `LMateLab-107Cup-evidence/operator-0ea0354/`；桌面截图 SHA-256 为 `680f42d07b0483a2e5bdce03f36f4d245bcbeead791d8acb17fcb783d77d3d76`，移动截图为 `5c47c4dbc1418ad57cf9425e800ea38e26678f0ce09dc9b16fc33114062bdc13`。
- RUNTIME：验收后只读复核确认 107 源码为 `0ea0354ec893f9ac9c4095fe19977b38a0e66456`、工作树干净、Job `33852` 为 `RUNNING` 且节点为 `anode16`，`/api/health/ready` 返回 `200`。
- BOUNDARY：当前 `main_107cup` 只挂载认证、健康检查和 SPA 路由，不存在可用于真实工作流的业务写接口。因此本次只通过 Operator 认证与身份 UI 验收；写权限、请求路径和“只能操作 LMateLab 自有资源”的验收等待阶段 5/6，阶段 4 保持 `PARTIAL`。

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
- Create: `frontend/src/pages/competition/NewCalculation.jsx`
- Create: `frontend/tests/competitionNewCalculation.test.mjs`

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
- [ ] Operator 可以上传一个最大 `1 MiB`、最多 `200` 原子的文本 POSCAR/CIF；Viewer 和预览模式不能上传。
- [ ] 上传文件先使用结构解析器读取并记录 SHA-256，不依赖扩展名、MIME 字符串或用户提供的路径决定可信格式。
- [ ] 合法输入先保存为可追溯草稿；只有 Operator 明确确认后才进入 Slurm 提交路径。
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
- Create: `frontend/src/pages/competition/CompetitionDashboard.jsx`
- Create: `frontend/src/pages/competition/WorkflowList.jsx`
- Create: `frontend/src/pages/competition/WorkflowDetail.jsx`
- Create: `frontend/src/pages/competition/WorkflowResults.jsx`
- Create: `frontend/src/pages/competition/VaspDatabase.jsx`
- Create: `frontend/src/competition/data/demoCompetitionDataProvider.js`
- Create: `frontend/src/competition/data/apiCompetitionDataProvider.js`
- Create: `frontend/src/components/vasp/PeriodicTableFilter.jsx`
- Create: `frontend/src/components/vasp/VaspRecordTable.jsx`
- Create: `frontend/tests/competitionWorkflowResults.test.mjs`
- Modify: `frontend/src/App107Cup.jsx`
- Modify: `frontend/src/config/appNavigation.js`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`
- Modify: `frontend/src/pages/db/VaspDataTable.jsx`

- [ ] 复用现有结构、BAND 和 DOS 解析能力，不复制第二套解析器。
- [ ] 复用现有 3Dmol、结构详情、BAND/DOS 标签页、元素颜色、周期表数据和表格格式化能力；竞赛页面不得依赖旧库上传、收藏或删除动作。
- [ ] 从原 VASP 数据库提取受控 `PeriodicTableFilter` 和只读 `VaspRecordTable`，原页面通过兼容包装器保持现有行为。
- [ ] 预览构建固定使用 demo 数据提供器并持续显示演示标识；所有 mutation 失败关闭且不发送网络写请求。
- [ ] 正式构建使用 API 数据提供器；同一套页面和组件不得因 demo/live 模式复制两份。
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

下一批次先交付经确认的“前端完整形态预览”，再进入阶段 5 的真实模型和写接口。该批次横跨阶段 5 至 8 的展示层，但不得把任何相关阶段更新为 `DONE` 或把演示数据记为真实验收。

专项设计：`docs/superpowers/specs/2026-08-10-107cup-frontend-preview-design.md`。

- [x] 按 `superpowers:writing-plans` 生成可执行实施计划并经用户复核。
- [x] 建立独立功能工作树和分支，不在受保护 `main` 直接修改。
- [x] 优先复用现有结构、晶体详情、BAND/DOS、元素颜色和导出组件。
- [x] 从原 VASP 数据库提取完整周期表筛选和只读表格核心，保持原页面兼容。
- [x] 为工作台、新建计算、工作流、结果和 VASP 数据库增加 107 专用路由。
- [x] 实现 demo/live 数据提供器；预览模式的全部 mutation 失败关闭且不伪造成功。
- [x] 使用内置 MoS2 演示成功、运行中和人为失败状态；不导入 4090 生产数据。
- [x] 在本地完成针对性测试、构建和代码检查，只记录为本地预检。
- [ ] 将功能分支推送 Gitea 并通过 PR 合并；107 只拉取固定合并提交，不直接检出未合并功能分支。
- [ ] 通过 107 Slurm 构建不晋升的 `previews/<commit>` 发布和独立 manifest。
- [ ] 启动独立 Slurm 预览 Job，使用独立数据库、runtime 目录和未占用端口；不得切换 `current` 或修改稳定数据库。
- [ ] 从 Windows 浏览器完成 `1440x900`、`1024x768` 和 `390x844` 验收，包括 3D Canvas 非空检查。
- [ ] 记录预览 Job、节点、提交、端口、manifest、健康检查和结束后端口消失证据。
- [ ] 对比预览前后的稳定 `current`、正式数据库和稳定服务 Job，证明未受影响。
- [ ] 用户确认前端预览后，再为阶段 5 工作流模型与输入校验创建下一份实施计划。

另外两名成员的 Git 和应用身份仍是阶段 1/4 的剩余门禁；按用户决定暂不处理，不阻塞本次前端预览，但必须在比赛交付前完成。

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

### 2026-08-06

- PR #3 合并后，本地、Gitea `main` 和 107 固定检出同步到 `30a18e1b7000d93a2cca39849a25edb0ff957e28`。
- Slurm 构建 Job `32757` 生成并原子启用 340 文件的新发布；专项后端 `29/29`、前端 `21/21` 和 107 专用构建通过。
- 服务 Job `32769` 在 `anode01` 启动，健康检查、两套数据库完整性和实际路由状态通过；运行时角色迁移保持密码哈希不变。
- 4090 转发切换到 `anode01`，运行中的 Nginx 收紧为白名单加只读方法入口；Windows 本地和校园网直连均指向新提交。
- 独立 Chrome 在桌面和移动视口完成匿名登录页烟雾测试；该结果不替代尚未执行的 Operator/Viewer 身份验收。
- 旧 Job `32676` 因 Students 时限结束，原始 Slurm 错误日志保留，旧节点端口实测不可达；`sacct` 对相关作业仍为空表。
- 发现并运行时修复迁移备份 `0644` 和 Nginx 配置 `0664` 权限；按 TDD 在 `codex/107cup-runtime-evidence` 修正私有备份创建、Nginx 用户态临时路径和 4 天 QOS 时限。
- 质量审查后新增备份碰撞不覆盖、更新失败回滚和 `O_EXCL|0600` 创建参数测试；两个安全 mutation 均被测试拦截。Nginx 临时目录改为代理根目录直接子目录，干净候选 `nginx -t` 已自动创建两个 `0700` 目录。
- Viewer 身份、Operator/Viewer 浏览器验收、正常服务结束复跑、失败构建和回滚演练仍未完成；阶段 4 保持 `PARTIAL`，不进入阶段 5。

### 2026-08-08

- PR #4 合并后构建并部署运行提交 `1bba72d0ade2bb7024081d384584524a9c9d1c69`；随后 PR #5 只更新方案，本地主检出、Gitea `main` 和 107 detached HEAD 同步到 `a33366702f2e62ff9c0012bbc625fbec92fda790`，运行发布未重建。
- Slurm Build Job `33839` 通过 107 Linux 后端专项测试 `31/31`、前端测试 `21/21`、Vite 构建和 340 文件 manifest 复核，原子启用发布 `releases/1bba72d0ade2bb7024081d384584524a9c9d1c69`。由于 `scontrol` 已清除且 `sacct` 空表，不记录构建节点或 `COMPLETED/0:0`。
- Service Job `33852` 在 `P107-A100/anode16` 启动，live/ready、两套 SQLite 完整性和登录节点无业务常驻进程均通过；计划结束时间为 `2026-08-12T11:46:52+08:00`。
- 4090 SSH 复用主连接和 `127.0.0.1:18734 -> anode16:18731` 转发建立后，4090 代理、Windows 本地入口和校园网直连入口均返回新 Job、节点和提交；注册 POST 继续返回 `403`。
- 在确认新入口健康后，精确取消被替换的 Job `32769`；Uvicorn 完整 shutdown，`anode01:18731` 随后不可达，最终日志与终止元数据已按 `0600` 保存并生成 SHA-256。该结果本身是受控取消，正常零退出后来由 Job `34005` 补齐。
- 故意失败构建 Job `33979` 以 `FAILED/1:0` 结束且没有替换 `current`；失败目录、Slurm 元数据和 SHA-256 证据均保留。
- 新增 `rollback-smoke.slurm`，通过 Job `33998` 和 `34001` 的保留失败证据修正空库 operator 初始化与受控 TERM 状态传播；最终 Job `34005` 从旧发布 `30a18e1` 完成独立迁移、live/ready、SQLite 完整性、优雅关闭和 `COMPLETED/0:0`，生产 Job `33852`、数据库、端口和 `current` 全程不变。
- 阶段 2 更新为 `DONE`。在该检查点，Viewer 预置与 Operator/Viewer 浏览器验收、自动恢复和 Slurm `sacct` 空表限制仍未解决；阶段 1、3、4 保持 `PARTIAL`，未进入阶段 5。
- PR #6 合并后，本地、Gitea `main` 和 107 detached HEAD 同步到 `2c92ff2c1770f09ca697adaf11eaf495a14875b1`；运行发布继续保持 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，未重建或重启。
- 在 `codex/107cup-viewer-acceptance` 分支提交 Viewer 受控预置能力；Job `34040` 和修正后的 Job `34045` 分别通过 Linux 专项测试 `23/23`、`24/24`。
- Job `34041` 创建专用 Viewer 后，真实浏览器暴露 `.invalid` 邮箱被 `EmailStr` 拒绝的 `422`；按 TDD 增加唯一旧邮箱迁移，Job `34046` 保持密码哈希不变并迁移到 `demo-viewer@matflow.top`。
- Viewer API 与浏览器验收完成：登录和 `/api/auth/me` 为 `200`，业务 POST 为 `403`，桌面/移动均显示只读身份，控制台 0 error/0 warning。
- PR #7 合并后，本地、Gitea `main` 和 107 detached HEAD 同步到 `0ea0354ec893f9ac9c4095fe19977b38a0e66456`；运行发布继续保持 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，未重建或重启。
- Operator 通过独立 SSH 隧道完成认证和身份界面验收：登录与 `/api/auth/me` 为 `200`，桌面/移动均显示“操作员 / 受控操作权限”，登录后的控制台 0 error/0 warning。
- Slurm Job `34062` 在 `Students/anode20` 对当前合并提交完成认证与 Viewer 预置专项测试 `12/12`，以 `COMPLETED/0:0` 结束；日志、调度元数据和 SHA-256 清单已按 `0700/0600` 保存。
- 当前竞赛后端没有真实业务写接口，因此未把身份 UI 误记为写权限或资源归属验收；该门禁等待阶段 5/6。三名成员独立应用身份和自动恢复仍未完成，阶段 1、3、4 继续保持 `PARTIAL`，未进入阶段 5。

### 2026-08-09

- PR #8 合并后，本地主检出、Gitea `main` 和 107 detached HEAD 同步到 `1ba1661c4c114fc271cf5bd7dd4e1dddc51845e1`；运行中的 Job `33852`、节点 `anode16` 和发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69` 保持不变。
- 107 Deploy Key 成功读取 `main`，但对独立探测引用的 `git push --dry-run` 被 Gitea 以只读权限明确拒绝，退出码为 `128`；拒绝后探测引用不存在，证据已按 `0700/0600` 固化并复核 SHA-256 清单。
- PR #9 合并后，本地 `main`、Gitea `main` 和 107 detached HEAD 同步到 `79fa22cd932c6d60d8002c433fa851ba8ef90fa3`；运行中的 Job `33852`、节点 `anode16` 和发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69` 保持不变，未重建或重启。
- Gitea 已为严格匹配 `main` 的保护规则禁用直接推送和强制推送，并启用 PR 合并及拒绝审核、官方审核请求更改、过时 PR、管理员同样受约束的合并限制；截图及其 SHA-256 已保存在 `D:\Documents\matflow项目\LMateLab-107Cup-evidence\repository-protection-20260809`。当前所需批准数仍为 `0`，因没有 CI 检查而未启用状态检查，签名提交为可选。
- 阶段 1 继续保持 `PARTIAL`；唯一剩余门禁是取得另外两名成员各自的 Gitea 账号、SSH key、提交邮箱、提交哈希和 PR 证据。阶段 3/4 状态不变，仍未进入阶段 5。

### 2026-08-10

- PR #10 合并后，本地 `main`、Gitea `main` 和 107 detached checkout 同步到 `11bac230cb9cd714596c4a460512699db76e0aca`；阶段状态未改变。
- 用户决定暂不处理另外两名成员身份，当前批次转为先展示最终前端形态；该决定不取消比赛交付前的成员身份门禁。
- 经逐段确认，前端预览固定为工作台、新建计算、工作流、结果和周期表驱动的 VASP 数据库五个入口。
- 输入范围由仅内置 MoS2 明确扩展为“内置 MoS2 或 Operator 上传一个受限的小型 POSCAR/CIF”，但仍不允许任意模板、命令、脚本或路径。
- 复用边界固定：直接复用现有 3D 结构、晶体详情、BAND/DOS 和解析服务；提取周期表与只读表格；不得挂载完整旧 VASP router 或旧库写操作。
- 预览采用 demo/live 双数据提供器和独立 107 Slurm 预览发布，不切换 `current`、不修改正式数据库或稳定服务。
- 本次提交只增加设计文档并更新总实施方案；未修改功能源码，未运行 107 构建，未启动预览 Job，也未改变阶段 5 至 8 的 `PENDING` 状态。
- 已生成专项实施计划 `docs/superpowers/plans/2026-08-10-107cup-frontend-preview.md`，按 TDD 拆分数据提供器、周期表与只读表格提取、五页前端、浏览器验收和独立 Slurm 预览链路；当前仍只是计划文档，尚未实现、构建、合并或部署，相关执行清单保持未勾选。

### 2026-08-11

- 在隔离工作树和分支 `codex/107cup-frontend-preview` 开始执行前端预览计划；该分支将随本次团队指南提交推送到 Gitea，但尚未合并或部署到 107，阶段 5 至 8 继续保持 `PENDING`。
- Task 1 已在本地实现 demo/live 数据提供器、MoS2 成功/运行/失败 fixture、BAND/DOS 演示数据和预览只读 mutation；规格与质量复审已通过。
- Task 2 已从旧 VASP 页面提取 118 元素周期表和受控筛选组件，保留旧页面兼容；规格与质量复审已通过。旧数组的视觉顺序与实施计划中的 `Z=1..118` 验收测试冲突，实际采用按 `Z` 机械重排、对象字段完全不变、由 `row/col` 保持视觉布局的澄清。
- Task 3 曾在源码修改前暂停，先新增 `docs/107cup/team-guide.md` 作为三名成员的统一仓库入口，记录阅读顺序、固定范围、分工建议、个人 Gitea 身份、PR、107/Slurm、安全和证据规则；README 同步增加入口。
- 根据队友也将使用 AI 的协作方式，新增仓库根目录 `TEAMMATE_AI_START.md` 作为唯一可直接转发文件：AI 先帮助队友检测并复用个人 Gitea key、克隆仓库、只读查看功能分支并提交接手报告，再在负责人明确分配 Task、文件范围和起点提交后进入 TDD 实施；文件同时提供前端、科学计算和发布证据三个方向的只读准备提示词，避免共享文件和 107 登录节点上的并行误操作。
- Task 3 恢复后已提取无旧收藏/移除 mutation 的 `VaspRecordTable` 只读核心，原 `VaspDataTable` 保持兼容包装、详情路由和操作列；新增移动端横向表格模式、行/卡片选择及可访问键盘行为。代码质量复审发现嵌套详情链接或操作按钮会冒泡触发行选择，已通过可执行回归测试隔离交互目标，并补齐 Enter/Space 与可见焦点；规格和质量复审最终均通过。
- 当前功能实现检查点为 `7b74a78e4084235bcf2a2263566bc71c89370bee`（不含本次方案状态提交），前端测试 `46/46`、聚焦 ESLint、生产构建和 `git diff --check` 通过；这些仍仅是 Windows 本地事实，不能表述为已合并、107 preview 或真实 VASP 验收。
- Task 4 已增加独立且深度冻结的 107 杯五入口导航数据，没有污染完整版导航，也没有提前注册 Task 10 才允许接入的页面路由；新增 `CompetitionDataProvider`、`useCompetitionData` 和带卸载/loader 切换保护的 `useCompetitionResource`，并仅包裹现有受保护 Dashboard 壳。规格与质量复审均通过，异步生命周期仍缺少渲染级回归测试，暂以代码审查和后续页面集成验收覆盖。
- 当前功能实现检查点更新为 `ab961b9b83e4b5ab79d5f2f65e7c4b16dbe2f53f`（不含本次方案状态提交）；导航/Provider/角色聚焦测试 `20/20`、前端全套 `46/46`、聚焦 ESLint、生产构建和 `git diff --check` 通过，仍未合并或部署到 107。
- Task 5 已新增显式 demo/loading/empty/forbidden/stale/parse-error/render-error/error 状态、固定 `relax -> SCF -> BAND/DOS` 分叉时间线和紧凑横向只读表格；现有 3Dmol 查看器增加视角重置，BAND/DOS 图保持 base64 兼容并支持 provider URL。质量复审发现并已修复数值 `exit_code=0` 丢失、异常步骤集合崩溃、旧绘图请求覆盖新记录、viewer 切换状态和 disabled hover；规格与质量复审最终均通过。绘图竞态已有可执行判定 helper 与三分支 guard 合同，但完整 deferred-Promise 组件生命周期仍留待 Task 11 浏览器/组件验收补强。
- 当前功能实现检查点更新为 `0bd9eaa482192a55d362788deb50ccfabf3f8a34`（不含本次方案状态提交）；Task 5 聚焦测试 `16/16`、前端全套 `56/56`、定向 ESLint、demo/live/标准三种 Vite 构建和 `git diff --check` 通过。这些仍仅是 Windows 本地实现事实，尚未合并、部署到 107 或执行真实 Slurm/VASP 验收，阶段 5 至 8 继续保持 `PENDING`。
- Task 6 已将硬编码零值和空工作流占位 Dashboard 替换为 provider 驱动的运营预览，包含持续 demo 标记、四项工作流摘要、最近工作流表、当前四步分叉时间线和最小 Slurm 演示快照。质量复审发现并已修复损坏 ready payload 引发的渲染崩溃、竞赛 grid 污染完整版 Dashboard 以及窄侧栏丢失 `SCF -> BAND/DOS` 分叉；规格与质量复审最终均通过。
- 当前功能实现检查点更新为 `0f3c6e1b7ab62f2108de9c98622b7ac4a6f80b80`（不含本次方案状态提交）；Task 6 聚焦测试 `11/11`、前端全套 `60/60`、定向 ESLint、demo/live/标准三种 Vite 构建和 `git diff --check` 通过。Browser 插件不可用时使用 Playwright fallback 完成 `1440x900` 与 `390x844` 本地 smoke，未见控制台错误、页面级溢出或重叠；详情链接已产生目标 URL，但 Task 10 前仍由现有 catch-all 返回 Dashboard。该结果不是 Task 11 的正式三视口验收，仍未合并或部署到 107。
- Task 7 已新增单页新建计算预览工作区：内置 MoS2 与受限上传占位、直接复用的 3D 结构查看器、固定 `relax -> SCF -> BAND/DOS` 双分支、逐步演示参数、Slurm 资源审阅和草稿/提交控制。规格复审发现并已修复只有 SCF 竖线而没有 BAND/DOS 双分支的问题；质量复审发现并已修复上传占位仍显示 MoS2 晶格数值、写门禁缺少可执行回归和来源切换残留错误。上传态现在明确显示待选择、未解析和不可提交；demo、Viewer 与上传占位均在 provider 调用前失败关闭，仅 live Operator 加内置结构允许写调用。规格与质量复审最终均通过。
- 当前功能实现检查点更新为 `543f5eb47bd48e4ffa8d3ec79252dbfd8f4c3631`（不含本次方案状态提交）；Task 7 页面与 provider 聚焦测试 `34/34`、前端全套 `67/67`、定向 ESLint、demo/live/标准三种 Vite 构建和 `git diff --check` 通过。Task 10 前该页面仍未接入路由，因此三种构建只证明现有入口未回归，页面本身由 Babel JSX 解析、可执行 helper 测试和 ESLint 提供本地语法/行为证据；尚未执行 Task 11 浏览器验收，未合并或部署到 107，阶段 5 至 8 继续保持 `PENDING`。
- Task 8 已新增 URL 驱动的工作流检索列表和不可变证据详情，包含 query/status 筛选、显式 loading/empty/forbidden/error 状态、六项中文 provenance、完整非紧凑四步时间线及未来 live Operator 的取消/失败步骤重试控制。实施时发现原任务文件清单遗漏了“验收结论”所需的共享时间线改动，因此按最小范围纠偏：复用现有 `WorkflowTimeline` 并只为非紧凑模式增加 `accepted` 证据，不在详情页复制时间线。
- Task 8 规格复审发现并已修复按 provider mode 而非记录 `data_kind` 标记来源、身份字段使用内部键名以及 missing/error 仅靠字符串测试的问题；质量复审进一步修复 ready 坏对象向 provider 传递 `undefined` ID/step、未知 provenance 误标真实和重复命令窗口。详情现在要求路由与记录 ID 精确一致、`data_kind` 仅为 `demo/live`、失败步骤键仅为固定四步，按钮与可执行命令 helper 双层失败关闭并共享 pending 门禁。规格与质量复审最终均通过。
- 当前功能实现检查点更新为 `5e85981de92e900270065c7c3eb2355f9f1d30bf`（不含本次方案状态提交）；Task 8 页面与 provider 聚焦测试 `45/45`、前端全套 `78/78`、定向 ESLint、demo/live/标准三种 Vite 构建和 `git diff --check` 通过。Task 10 前两个新页面仍未接入路由，构建结果仍只证明现有入口未回归；尚未执行 Task 11 浏览器验收，未合并或部署到 107，也未实现真实工作流/Slurm 写接口，阶段 5 至 8 继续保持 `PENDING`。

### 2026-08-12

- Task 9 已新增 URL 驱动的结果列表和科学结果详情：列表只接受 `succeeded`、`failed`、`parse-error` 三类完成记录并排除运行中工作流；详情直接复用现有 `VaspTaskSummary`、`VaspStructureViewer`、`VaspCrystalDetails` 和 `VaspElectronicProperties`，通过 competition provider 加载 BAND/DOS 图和下载结构、数据及证据工件。成功科学区与失败证据区在 AST 分支中互斥，demo 结果和全部下载文件持续标记为“演示内容”及 `DEMO-` 文件名。
- Task 9 规格复审发现并已修复五类演示工件回归不足、空嵌套科学合同误判成功，以及工作流 ID 中 `band`/`dos` 子串干扰工件和绘图类型的问题。质量复审进一步修复无四步验收证据仍挂载成功科学区、合法 live 可空科学字段被误拒、畸形 provenance/时间线触发 React 渲染崩溃、结果行 `id` 覆盖权威 `workflow_id`，以及布尔值或非法数字冒充 Job ID/失败证据的问题；最终规格与质量复审均通过。绘图 `AbortSignal` 仍因现有 demo/live provider 接口只接受 `(id, kind)` 而留待真实接口阶段处理，本 Task 未越界修改 Task 1 provider。
- 当前功能实现检查点更新为 `38a653bb2575e45e38fb0804fdf282f5ed4e4953`（不含本次方案状态提交）；Task 9 相关聚焦测试 `65/65`、前端全套 `89/89`、定向 ESLint、3 个 JSX Babel 解析、demo/live/标准三种 Vite 构建和 `git diff --check` 均通过。Task 10 前结果页仍未接入路由，因此 107 两种构建仍只证明现有入口未回归；尚未执行 Task 11 三视口浏览器与 Canvas 像素验收，未合并或部署到 107，也未产生真实 Slurm/VASP 结果，阶段 5 至 8 继续保持 `PENDING`。
- Task 10 已完成周期表驱动的只读 VASP 数据库页和七条受保护竞赛路由接入：筛选、页码与选中记录由 URL 驱动，列表、详情及 provider 响应均严格校验；损坏响应、过期请求和页码归一化期间均失败关闭。数据库仅显示只读记录和结构检查器，竞赛导航保留紧凑“演示数据”标记，没有接入旧数据库写操作或完整旧 VASP router。规格复审与两轮质量复审均通过。
- 当前功能实现检查点更新为 `c9bcf5ed828866da7fca7978f1abc030e6e6e271`（不含本次方案状态提交）；Task 10 聚焦测试 `99/99`、前端全套 `103/103`、定向 ESLint、数据库页/`App107Cup`/`AppShell` 三项 Babel JSX 解析和 `git diff --check` 均通过。demo 与 live 107 构建各转换 `1857` 个模块，标准完整构建转换 `2201` 个模块；demo `dist/assets` 对 `AgentEntry`、`PersonalVaspDatabase`、`ServerMonitor*`、`AcademicReports` 和 `NotesJournal` 扫描为零命中。
- 上述结果仍仅是 Windows 本地实现和预检事实；Task 11 三视口浏览器及 3D Canvas 像素验收、Gitea PR 合并和 Task 12/13 的 107 独立 Slurm 预览尚未执行，也没有产生真实工作流、Slurm 控制或 VASP 计算证据。阶段 5 至 8 继续保持 `PENDING`。
- Task 11 已增加只面向外部目标的 Playwright 验收配置和单流程三视口套件，固定 `1440x900`、`1024x768`、`390x844`，覆盖五个入口、两个详情路由、刷新、禁用写控件、周期表筛选、BAND/DOS 切换、成功/失败互斥、3D Canvas 非空像素和页面级横向溢出；每个视口预定输出五张全页截图及一份像素/控制台/写请求计数 JSON 到外部证据目录。
- 本地仅完成验收代码预检：`@playwright/test 1.54.2` 与 `pngjs 7.0.0` 已锁定安装，Chromium 实际启动通过，缺少 `LMATELAB_PREVIEW_URL` 时配置按约定失败，提供占位环境后的 `--list` 精确列出三个视口项目；E2E 文件定向 ESLint、前端全套 `103/103`、demo 构建 `1857` 模块和 `git diff --check` 通过。尚未连接 107 预览、使用私有预览账号或生成正式截图/Canvas 像素结果，因此三视口验收清单继续保持未勾选。
- Task 12 已在本地实现隔离预览部署链路：固定合并提交的 Slurm 构建只生成 `previews/<commit>` 和独立 manifest，不创建或切换 `current`；预览服务把两套稳定 SQLite 通过 backup API 复制到 `preview-runtime/<commit>/<job>` 后仅迁移副本，并使用独立端口、可追溯运行元数据和 `preview/demo` 健康标识；running/stopped 验证器和 Slurm before/after 快照分别检查端口生命周期及稳定发布、数据库、服务元数据不变。稳定构建同时显式固定为 `live` 数据模式。
- 当前 Task 12 源码检查点为 `2b6e72ac15cc1cb83992f7c6a4b4c3aeae7de3c1`（不含本次方案状态提交）；预览/稳定部署合同、运行时和健康检查 `35/35` 通过，八个相关 Bash/Slurm 文件通过 `bash -n`，预览构建晋升令牌和预览服务稳定库 URL 两项零命中隔离扫描通过。实施计划中“验证器禁止出现 `uvicorn ` 字符串”与“验证器必须用 `pgrep` 检查登录节点 Uvicorn”存在冲突，最终合同按实际安全目标改为禁止可执行的安装、构建、迁移和服务命令，同时允许只读进程检查。
- 上述仍仅是 Windows 本地源码、合同和语法事实；没有向 107 提交构建、服务或快照 Job，没有创建远端 `previews/<commit>`、预览数据库、端口或运行证据，也没有修改稳定 `current`、数据库或服务。所有 107 Slurm、浏览器和前后快照清单继续保持未勾选，阶段 5 至 8 继续为 `PENDING`。
- Task 13 Step 1 已完成完整 Windows 本地预检：后端命令 `python -m unittest tests.test_107cup_authz tests.test_107cup_runtime tests.test_107cup_deploy_contract tests.test_107cup_preview_deploy_contract tests.test_health_readiness -v` 通过 `42/42`；前端 `npm test` 通过 `103/103`；`VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build` 成功转换 `1857` 个模块；定向 ESLint 与 `git diff --check` 均通过。
- 本地预检同时处理两项平台兼容问题：Windows 不提供可依赖的 POSIX 最终权限位，因此迁移测试仅在非 Windows 平台断言目录 `0700` 和备份 `0600`，Linux/107 的严格断言保持不变，跨平台仍检查 `os.open` 使用 `O_CREAT|O_EXCL` 和 `0600`；周期表组件仅为已批准的兼容 helper 重导出增加定向 ESLint 说明，没有扩大豁免范围。
- 当前五个竞赛入口、demo/live provider、三视口 Playwright 验收代码和隔离预览部署脚本均只完成本地实现与预检。尚未完成 Gitea PR 合并、107 Slurm 预览构建/服务、真实浏览器截图与 3D Canvas 像素验收，也没有生成真实工作流、Slurm 控制或 VASP 计算证据；阶段 5 至 8 继续为 `PENDING`。
