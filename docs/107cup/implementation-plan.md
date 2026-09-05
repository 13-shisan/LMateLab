# LMateLab 107 Cup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 107 平台独立交付一个围绕受控二维周期结构 `relax -> SCF -> BAND -> DOS` 闭环的 LMateLab 竞赛版本，并提供可追溯、可恢复、可只读演示的真实 Slurm/VASP 证据链。

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
内置 MoS2 基线或 Operator 上传一个受限的小型周期 POSCAR/CIF
  -> 输入生成与校验
  -> PAW-PBE POTCAR 由结构元素和 VASPKIT 103 生成
  -> 可追溯工作流草稿
  -> Slurm 受控执行
  -> relax
  -> SCF
  -> BAND（基于最终晶格由 VASPKIT 302 生成路径）
  -> DOS
  -> 解析、周期表驱动的 VASP 数据库、图表、导出和证据包
```

上传结构使用固定 `pbe_2d_v1` 基线，不扩展命令范围：单文件最大 `1 MiB`、最多 `200` 个原子、最多 `16` 种元素，只接受全周期文本 POSCAR/CIF，不接受压缩包、目录、任意模板或任意路径。该基线仅覆盖非磁性、无 SOC、无 DFT+U、无杂化泛函的 PAW-PBE 四步流程；“输入可执行”不等于对每种材料都具备充分的科学参数或收敛保证。

明确不进入第一版：

- Agent、聊天、RAG、Ollama 和 `vasp-wiki`。
- 机器学习、主动学习和跨服务器迁移。
- QE、EPW、Gaussian、DeepMD、LASP 和 CP2K 工作流。
- 将原 4090 LMateLab 生产数据库、上传文件、日志或密钥复制到 107。
- 任意计算模板、任意赝势目录、任意命令执行、任意 Slurm 脚本和任意路径浏览。
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

## 4. 2026-08-10 可验证基线快照（历史）

记录时间：`2026-08-10`。本节保留当日仓库、服务与网络入口的历史快照，不表示 `2026-08-14` 的当前运行状态；后续状态以第 5 节状态总表、第 10 节验收门禁和变更记录中的最新前后快照为准。

### 4.1 源码与仓库

- 初始来源提交：`4d51e5837e62bb8582646f371352eb958af2a9db`。
- 来源清单 SHA-256：`fe35216bb093894e8d7b2edbac67e4fc11939d67af776325e1045e4ccf4aa3f9`。
- Gitea：`ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git`。
- Gitea `main`：`f8aee97e4367fa45befab77c3a248d99dd3e36ae`，Windows 于 `2026-08-11` 重新 fetch 后确认。
- PR #11 已将 `codex/107cup-frontend-preview-design` 合并到 `main`，包含已批准设计和 14 项实施计划。
- 107 源码检出最后一次已记录同步仍为 PR #10 的合并提交 `11bac230cb9cd714596c4a460512699db76e0aca`；本次本地前端实现尚未合并或部署，下一次远端操作前必须重新现场核验 detached HEAD 和工作树状态。
- 截至该快照，生产为 Job `33852`、节点 `anode16` 和发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，该批次仓库收尾未重建或重启服务。

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

- 该快照的 Slurm 服务 Job：`33852`，账号 `competition`、分区 `P107-A100`、QOS `qos_p107-a100`，时限为 4 天，计划结束时间 `2026-08-12T11:46:52+08:00`。
- 节点：`anode16`。
- 服务端口：`18731`。
- `/api/health/live` 和 `/api/health/ready` 已实际返回成功。
- 两套 Alembic migration 已运行，两个 SQLite 数据库完整性检查均为 `ok`。
- 该快照的业务数据为空；唯一账号 `pb23030683` 已由 `root` 迁移为 `operator`，迁移前后密码哈希一致。
- 迁移备份：`backups/competition-roles/eln.db.before-competition-roles.20260805T170654166520Z.sqlite`，SHA-256 为 `8b2318b9d6c6fbc8c042a6a15a78c7f539db3635e2a1689a05cc3ed5dd0c57ce`；首次创建权限为 `0644`，发现后已将目录收紧为 `0700`、文件收紧为 `0600`。PR #4 的源码修正现已部署，后续新备份使用 `O_EXCL|0600` 创建且同名不覆盖。
- 新服务上线快照位于 `evidence/runtime/20260808T115141+0800-service-33852-post-deploy/`：`service-33852.out` 为 539 字节，SHA-256 为 `4a46550387c8430c1e4630be3744427e590c57588f58b017fd2cafb5a13e494c`；`service-33852.err` 为 455 字节，SHA-256 为 `b321cbd0ec52eb1431f0b63a842e5ca6b6a5bf70cc801281b13ba31e30c867b1`。快照目录权限为 `0700`，文件和哈希清单权限为 `0600`；活动日志继续增长。
- 被替换的 Job `32769` 于 `2026-08-08T11:49:47+08:00` 经归属核对后由 `scancel` 受控停止；Uvicorn 日志记录完整 shutdown，随后 `anode01:18731` 实测不可达。最终快照位于 `evidence/runtime/20260808T114947+0800-service-32769-controlled-cancel/`：stdout SHA-256 为 `e7cf0e647a9a97132c74aa8a8bff7fb2e1ddf51bc64ca4762de7d2337cbadbf3`，stderr 为 `2efe3681da0a134a0f5e6637ebe89a7bae78f8c823469fec437d6e8a2fac857a`，终止元数据为 `e8059a61b62d6b40284305653f9e339f08abb0b5833c207d165864c989a4cd88`；`sacct` 仍无记录，因此该证据不能写成正常零退出。
- 旧 Job `32676` 于 `2026-08-06T01:24:19+08:00` 因 Students 时限被 Slurm 取消，Uvicorn 正常关闭，随后 `anode16:18731` 实测不可达；因 `sacct` 空表，最终状态只能以保留的 `service-32676.err` 原始标记为证据。
- VASP 自定义数据库目录和上传目录均为 0 个文件。

### 4.4 网络入口

- 4090 用户态 Nginx：`/home/Pwjb/.config/lmatelab-107cup-proxy/conf/nginx.conf`。
- Nginx 监听：`0.0.0.0:18733`。
- 4090 到 107 的正式内部 SSH 转发：`127.0.0.1:18740 -> 11.11.10.17:18731 (anode17)`；临时转发 `18741` 已撤销。
- 4090 上的 107 SSH 复用主连接使用 `/home/Pwjb/.ssh/cm-107cup`，socket 权限为 `0600`，配置 96 小时 `ControlPersist` 和 30 秒保活；它减少重复二次验证，但不是永久自动恢复机制。
- 公网入口：`http://222.195.94.37:18733`。
- 已验证白名单 IP 返回 `200`，未授权 IP 返回 `403`。
- 运行中的 Nginx 已替换为只读公开入口：登录端点只允许 POST，其余页面和 API 只允许 GET；注册 POST、非登录 POST 和登录端点 PUT 实测均为 `403`。
- 当前 4090 内部入口、Windows Operator 入口 `http://127.0.0.1:21763` 与公网入口均返回 Stage 9 服务 Job `40917`、节点 `anode17`、提交 `551ba97fbfca3093c19ef4e98e636bcaa9b88fef` 和 manifest `163b52ad998f947f575589df07e1bafa36423e122e3eab00ba2008e0d031a58d`；三处 `live/ready` 均为 `200`。
- 该快照入口为 HTTP，尚未完成 TLS 和自动恢复。

## 5. 阶段状态总表

状态只允许使用 `DONE`、`PARTIAL`、`PENDING`、`BLOCKED`。

| 阶段 | 状态 | 当前结论 | 下一门禁 |
|---|---|---|---|
| 1. 竞赛仓库初始化 | PARTIAL | Windows 本地 `main`、Gitea `main` 与 107 只读 detached checkout 已同步到 PR #28 合并提交 `044ada5`，107 Deploy Key 只读和 `main` 保护均已完成 | 取得另外两名成员的个人 Git 身份和 PR 证据 |
| 2. 无 Docker 构建与发布 | DONE | Job 33839 完成构建和原子切换；Job 33979 证明失败不切换；Job 34005 证明旧发布无需重建即可隔离启动 | 保持证据和发布不可变；平台 `sacct` 空表作为已知限制保留 |
| 3. 最小 107 网页服务 | DONE | 当前稳定 Job `43737/anode16` 运行发布 `b58cfe40...`；4090 每分钟短守护、maintenance、单候选恢复和先验切换已通过真实停服/恢复验收 | 在通用工作流候选通过前保持 Job `43737` 不动；SSH 主连接真实失效时由 Operator 完成一次二次验证 |
| 4. 访问与角色控制 | PARTIAL | Viewer/Operator 认证已通过；阶段 5 业务路由角色边界已验收；阶段 6 Job `38628` 再证明非归属 Slurm 作业取消失败关闭 | 配置三名成员独立应用身份 |
| 5. 工作流模型与输入校验 | PARTIAL | 旧 `mos2_v1` 证据保持完成；`pbe_2d_v1` 通用周期结构、确定性元素顺序和安全 422 错误已随 `6012b2b` 构建并发布。Job `46103` 通过受影响测试 `116/116`，Job `46104/46105` 均通过正式后端白名单 `514` 项（另有 4 项跳过） | 由 Operator 在新网页完成一次 WS2 上传、草稿和提交前校验；不得用单元测试替代真实浏览器会话 |
| 6. Slurm 适配器 | DONE | PR #27 合并提交 `9346552` 已在 107 完成 Job `38620` 前快照、Job `38621` 构建、Job `38623` smoke 与 Job `38629` 后快照；`38625/38626/38627/38628` 分别覆盖成功、失败、自有取消和非归属拒绝，历史失败 Job `38598` 保留；独立证据 PR #28 已合并为 `044ada5` 并完成三端同步 | 保持证据不可变；阶段 7 仅在用户明确确认后开始 |
| 7. VASP 四步闭环 | PARTIAL | 旧 MoS2 成功/失败链证据保持完成且不可变；WS2 Job `46090` 已在 107 真实验证 VASPKIT 103 推荐 `W_sv/S`、源文件逐字节核对和基于实际晶格的 302 `GAMMA-M-K-GAMMA`。103/302 runner 已随 `6012b2b` 部署到 Job `46107`，但没有运行 WS2 VASP | Operator 上传 WS2 后再明确授权提交完整四步真实工作流；失败时保留现场且不影响当前网页服务 |
| 8. 结果解析与证据包 | DONE | PR `#42-#48` 已合并；Job `40308` 真实只读解析、Job `40831` 最终构建及 Job `40832` 稳定部署通过；用户确认结构、BAND、DOS、成功/失败详情、只读数据库和五种下载正常，旧服务与临时转发已清理 | 保持 `docs/107cup/stage8-results-evidence.md`、真实结果和下载哈希不可变；进入阶段 9 |
| 9. 恢复、安全和回归 | DONE | 功能 PR `#50` 和证据 PR `#51` 已合并；Job `40860` 构建、`40910/40913/40923` 快照、`40911` 隔离回滚、`40916` 真实结果只读复核、`40917` 稳定服务和 Viewer 浏览器验收全部通过 | 保持 `docs/107cup/stage9-recovery-security-evidence.md`、正式 SQLite、Stage 7/8 attempt 和证据包不可变；进入阶段 10 |
| 10. 比赛交付验收 | PARTIAL | PR #55/#56/#57/#60/#61/#63/#66/#68/#70 已合并；修改密码版由 Job `43709/anode01` 构建、`43710/anode16` 提供服务并经 `43711/anode16` 只读验收；公网入口和发布身份一致 | 当前发布仍需由用户现场完成一次真实改密与全新认证态 Viewer/Operator 复跑，三名成员还需使用各自 Gitea 身份完成独立复核 |

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
- Create: `deploy/107cup/service_recovery.py`
- Create: `deploy/107cup/recover-service.sh`
- Create: `deploy/107cup/relay/ensure_forward.py`
- Create: `deploy/107cup/relay/install-recovery.sh`
- Create: `deploy/107cup/relay/reauth-control-master.sh`
- Create: `docs/107cup/service-recovery-runbook.md`
- Test: `backend/tests/test_107cup_runtime.py`
- Test: `backend/tests/test_health_readiness.py`
- Test: `backend/tests/test_107cup_service_recovery.py`
- Test: `backend/tests/test_107cup_relay_recovery.py`

- [x] 单进程 Uvicorn 仅通过 Slurm 运行。
- [x] 前端静态文件由同一个 FastAPI 服务提供。
- [x] 使用独立空 SQLite 数据库和独立数据目录。
- [x] 记录 Job ID、节点、端口、提交和 manifest 哈希。
- [x] 登录节点不存在 Uvicorn、Vite、Celery 或 Redis 常驻进程。
- [ ] 在受控窗口让服务作业正常结束，验证 `anodeXX:18731` 和转发入口随之不可达。
- [x] 提交新服务作业并根据新节点安全更新 4090 内部转发。
- [x] 编写不依赖管理员权限的启动、检查、停止和恢复运行手册。
- [ ] 在 4090 安装每分钟短时 cron；唯一候选服务健康后才通过临时端口切换正式转发。
- [ ] 验证 SSH master 失效时失败关闭并明确要求人工二次验证，不保存验证码或私钥。

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
- Modify: `frontend/src/pages/competition/CompetitionNewCalculation.jsx`
- Modify: `frontend/src/features/competition/data/apiCompetitionDataProvider.js`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`
- Modify: `frontend/tests/competitionDataProvider.test.mjs`
- Create: `backend/tests/test_competition_workflow_service.py`
- Create: `backend/tests/test_competition_workflow_routes.py`

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

- [x] 先写失败测试覆盖缺文件、路径穿越、命令注入、错误元素顺序和参数越界。
- [x] 创建 Alembic migration，并在全新数据库和上一 schema 的数据库副本上各运行一次；两者均升级到 `107c0ffee001`，六张表齐全且 `PRAGMA integrity_check=ok`。
- [x] 保留内置 MoS2 基线 `mos2_v1`，上传周期结构使用固定 `pbe_2d_v1`；不接受用户上传模板。
- [x] Operator 可以上传一个最大 `1 MiB`、最多 `200` 原子的文本 POSCAR/CIF；Viewer 和 demo 模式在 provider 调用前拒绝写入。
- [x] 上传文件先使用结构解析器读取并记录 SHA-256，不依赖扩展名、MIME 字符串或用户提供的路径决定可信格式。
- [x] 合法输入先保存为可追溯草稿；只有 Operator 明确确认后才进入 `validated`，界面显示“已校验，等待 Slurm 适配器”。
- [x] 使用结构解析器核对 POSCAR 元素顺序，不使用字符串猜测。
- [x] INCAR 只允许阶段定义的键和值域。
- [x] KPOINTS 由固定模板或受控生成器产生。
- [x] 阶段 5 不调用 Slurm，不创建 Job ID、attempt 或执行目录，全部输入校验均在未来 `sbatch` 边界之前完成。
- [x] 校验失败写入事件表，但不得产生 Job ID 或 attempt 执行目录。
- [x] 功能 PR #16 已合并到受保护 `main`，合并提交为 `619b9116aee4f6cd4129debca87c1d4a35e12c5c`，包含阶段 5 状态提交 `aaee9a19b8d448d674c6b05abf86be430ab7168a`。
- [x] PR #17、#18 和 #21 已合并；固定提交 `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` 在 107 的隔离 preview 中完成正式数据库副本迁移、真实 Operator/Viewer API、SQLite 和三视口浏览器验收。
- [x] 最终验收服务 Job `37611` 只产生两条 `validated` 工作流，六类非法输入均在零 attempt、零 Job ID 条件下返回 `422`；服务停止后端口消失。
- [x] 前快照 Job `37593` 与后快照 Job `37614` 逐项比较确认稳定 `current`、Job `36597`、`anode01:18731` 和两套正式 SQLite 未改变。
- [x] `docs/107cup/stage5-workflow-evidence.md` 已通过独立证据 PR #22 合并，合并提交为 `3cf9b44f0b55a11e43f0a4960dc689cf0607ced2`；阶段 5 改为 `DONE`。

## 11. 阶段 6：Slurm 适配器

**Files:**

- Create: `backend/services/competition_slurm.py`
- Create: `backend/services/competition_reconcile.py`
- Create: `backend/tests/test_competition_slurm.py`
- Create: `backend/tests/fixtures/fake_slurm/`
- Create: `deploy/107cup/slurm/probe.slurm`
- Create: `deploy/107cup/slurm/stage6-smoke.py`
- Modify: `backend/routers/competition_workflows.py`

适配器只能使用参数数组调用固定二进制，不使用 `shell=True`。LMateLab 作业必须同时满足以下归属证据：

```text
JobName 前缀为 lmatelab-
WorkDir 位于 /home/scc/pb23030683/lmatelab-107cup/data/workflows
Slurm comment 含 workflow_id 和 attempt_id
数据库 ledger 中存在相同 Job ID
```

- [x] 从服务计算节点验证 `sbatch --test-only`、`squeue`、`sacct` 和 `scancel`；其中 `sacct` 因 `localhost:6819` 拒绝连接而确认不可用，适配器按 `unknown/stale` 失败关闭。
- [x] 假 Slurm 测试覆盖提交、排队、运行、完成、失败、取消和命令超时。
- [x] 状态映射保留原始 Slurm state、exit code、reason 和时间戳。
- [x] 日志读取限制在 attempt 目录并限制单次读取字节数。
- [x] `scancel` 前验证四项归属证据，任一不符即拒绝。
- [x] 服务重启后从数据库和 `squeue/scontrol/sacct` 对账；无权威终态时记录 `unknown/stale`，不把陈旧状态显示为运行中。
- [x] 真实提交短时普通作业：Job `38625` 成功、Job `38626` 故意失败、Job `38627` 受控取消，并由新 reconciler/数据库会话完成重启式对账。
- [x] smoke 自建非归属控制 Job `38628`；适配器以 `cancellation_ownership_mismatch` 拒绝取消，随后 harness 只按已知 Job ID 精确清理该控制作业。

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

- [x] 每一步创建独立 attempt 目录和独立 Slurm Job ID。
- [x] 前一步只有通过阶段验收函数后，下一步才允许提交。
- [x] relax 验收结构输出、电子收敛、离子收敛和正常结束标记。
- [x] SCF 验收 CHGCAR、WAVECAR、费米能级和正常结束标记。
- [x] BAND 只复用已验收 SCF 产物并记录输入文件哈希。
- [ ] `pbe_2d_v1` 的 POTCAR 按最终 POSCAR 元素顺序由 VASPKIT `103` 生成，并逐字节核对固定 PAW-PBE 源文件后记录哈希。
- [ ] `pbe_2d_v1` 的 BAND attempt 继承已验收 SCF 的最终 `POSCAR` 和 `CHGCAR`，由 VASPKIT `302` 生成 `KPATH.in`，受控发布为 `KPOINTS` 并记录生成器证据。
- [x] DOS 只复用已验收 SCF 产物并记录输入文件哈希。
- [x] 记录 VASP 版本、VASPKIT 版本、GPU/CPU、峰值内存、耗时和 Slurm ExitCode。
- [x] 执行一个完整成功工作流。
- [x] 执行一个人为失败工作流并验证后续步骤没有 Job ID。

真实 VASP 完成必须同时具备 Slurm `COMPLETED/0:0`、VASP 正常结束标记、阶段文件集合和哈希；缺一项都不能显示成功。

本地实现进展（`2026-08-19`，不勾选上述真实运行门禁）：固定 MoS2 输入、POTCAR 策略、不可变 attempt、科学验收、自动推进、重试/取消、受限日志、服务生命周期、Operator 写操作、前端轮询、计算节点 runner、预检和固定失败 profile 已实现。实现检查点为 `f2fe8acd4251b25a8d47f876be0213cca0062a2c`；Task 12 后端 `430` 项通过、`21` 项按本地平台条件跳过，前端 `125/125`、定向 ESLint、demo/live 两种 `107cup` Vite 构建均通过且每次转换 `1857` 个模块，WSL runner 行为测试 `10/10`、三个 Bash 语法检查、Python 编译和仓库安全检查通过。上述均为 Windows/WSL 本地证据；本次没有连接 107、没有提交 Slurm、没有运行 VASPKIT/VASP，也没有 107 Job ID、正常结束标记或科学结果。阶段 8 继续为 `PENDING`。

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
- Create: `docs/107cup/stage9-recovery-security-evidence.md`
- Modify: `deploy/107cup/verify-runtime.sh`

- [x] 服务重启时恢复未完成工作流并与 Slurm 对账。
- [x] Slurm 暂时不可用时保留最后可信状态并标记陈旧时间，不伪造失败或成功。
- [x] 数据库写入失败时不提交下一阶段。
- [x] 取消与完成竞态以最终调度状态、已提交取消意图和事件序列收敛。
- [x] 网关目标变化时公开入口失败关闭，不改为生产 4090 LMateLab。
- [x] 发布回滚不修改历史 attempt 和证据包。
- [x] 路径穿越、符号链接逃逸、参数注入、超大日志和非法文件名全部拒绝。
- [x] 验证平台不能查看或控制同一账号下的非 LMateLab 作业。
- [x] 重跑后端、前端、假 Slurm、107 真实 Slurm、真实 VASP 只读验收和浏览器六层测试。

## 15. 阶段 10：比赛交付验收

**Files:**

- Create: `docs/107cup/deployment.md`
- Create: `docs/107cup/data-and-provenance.md`
- Create: `docs/107cup/demo-script.md`
- Create: `docs/107cup/final-acceptance.md`
- Create: `docs/107cup/artifacts/manifest.sha256`

- [x] 从合并后的 `main` 固定提交重新构建发布。
- [x] 在全新浏览器会话分别复跑 Operator 和 Viewer 演示；Viewer 桌面/移动与 Operator 桌面均已完成。
- [x] 固定成功工作流和人为失败工作流已由 107 Stage 10 Job 只读复核，证据包哈希未变。
- [x] 导出桌面、移动页面截图和演示视频素材；Viewer/Operator 截图和连续视频均已完成。
- [x] 已通过 107 数据位置、计算节点服务和网络失败关闭证据验证业务不依赖原 4090 LMateLab；没有执行未授权的原生产项目停机。
- [x] 源码、环境、数据库、服务、VASP 任务和结果位于 107 的机器核对已由真实 Job `41482` 通过。
- [x] 107 router allowlist 与 Agent、机器学习、跨服务器迁移等旁支不进入竞赛运行面的机器核对和 Viewer 浏览器核对均已通过。
- [x] 已生成确定性的仓库交付 SHA-256 清单；三名成员复核尚未完成。

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
- [x] 将功能分支推送 Gitea 并通过 PR 合并；107 只拉取固定合并提交，不直接检出未合并功能分支。
- [x] 通过 107 Slurm 构建不晋升的 `previews/<commit>` 发布和独立 manifest。
- [x] 启动独立 Slurm 预览 Job，使用独立数据库、runtime 目录和未占用端口；不得切换 `current` 或修改稳定数据库。
- [x] 从 Windows 浏览器完成 `1440x900`、`1024x768` 和 `390x844` 验收，包括 3D Canvas 非空检查。
- [x] 记录预览 Job、节点、提交、端口、manifest、健康检查和结束后端口消失证据；详见 `docs/107cup/frontend-preview-evidence.md`。
- [x] 对比预览前后的稳定 `current`、正式数据库和稳定服务 Job，证明未受影响。
- [x] 用户确认前端预览后，再为阶段 5 工作流模型与输入校验创建下一份实施计划；专项计划为 `docs/superpowers/plans/2026-08-12-107cup-stage5-workflows.md`。

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
- PR #12 已合并为 `3fa7447372784a5b67c455690dc1b458197eb49e`，107 只读源码检出已刷新到该固定提交；稳定入口仍运行 Job `33852`、节点 `anode16`、端口 `18731` 和发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，尚未构建或启动新预览。
- 第一次部署前快照 Job `36592` 在 `P107-A100/anode17` 因平台 `sacct` 后端连接 `localhost:6819` 被拒绝，以 `FAILED/1:0` 结束。失败证据保留在 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/3fa7447372784a5b67c455690dc1b458197eb49e/before-36592`：目录/文件为 `0700/0600`，已记录稳定 `current`、两套数据库 SHA-256 和 `integrity_check=ok`、Job/节点/端口/提交、健康 JSON 与 `squeue`；因脚本在 manifest 生成前退出，该目录不能作为成功 before 快照。
- 本地热修复按 RED `8/10`、GREEN `10/10` 增加调度证据降级合同：快照和预览验证器必须保留 `scontrol` 权威状态；`sacct` stdout、stderr 和可用性需原样记录，但平台记账服务不可用不得掩盖其他成功门禁。热修复合并并在 107 重跑成功前，不提交预览构建或服务 Job，前后快照、浏览器验收和阶段 5 至 8 状态保持未完成。
- PR #13 已将上述 `sacct` 降级修复合并为 `25b0a8630e8ebf49abe7ec9fc85088f5045c9947`，107 只读检出同步到该提交。成功前快照 Job `36608` 在 `anode17` 以 `COMPLETED/0:0` 结束，两套稳定 SQLite 的 `integrity_check` 均为 `ok`，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/25b0a8630e8ebf49abe7ec9fc85088f5045c9947/before-36608`。
- 预览构建 Job `36611` 在 `anode02` 以 `COMPLETED/0:0` 结束：后端 `44/44`、前端 `103/103` 通过，Vite 转换 `1857` 个模块；生成不晋升的 `previews/25b0a8630e8ebf49abe7ec9fc85088f5045c9947`，manifest SHA-256 为 `011405ad3745e6bd31ca8f8f1ce23affeaa000f0b79f5eb1671a3fdc5fc7dd4c`。
- 独立预览服务 Job `36612` 在 `anode01:20612` 启动，健康元数据明确为 `release_kind=preview`、`data_mode=demo`，使用预览数据库副本且未切换稳定 `current`。真实三视口浏览器验收发现移动端表格把 `390px` 页面扩宽至 `736px`，同时发现上传控件验收顺序、工作流文案断言、软件 WebGL 参数和提交脚本 stdout 合同问题，因此该合并提交的浏览器验收判定为失败；Job `36612` 随后受控取消，Uvicorn 完整关闭并确认端口消失，失败现场和证据均保留。
- 本地分支 `codex/107cup-frontend-preview-qa-fix` 已针对上述问题完成热修复预检：后端 `44/44`、前端 `104/104`、定向 ESLint、demo 构建和 `git diff --check` 通过；连接 Job `36612` 的只读预览 API 后，Playwright 在 `1440x900`、`1024x768`、`390x844` 三个视口通过 `3/3`，控制台问题和业务写请求均为 `0`，三个视口的 3D Canvas 彩色像素分别为 `2248`、`2403`、`3125`。本地证据位于 `D:\Documents\matflow项目\LMateLab-107Cup-evidence\frontend-preview-local-qa-fix-3`；这只是本地热修复预检，不能替代合并后 107 构建和真实浏览器复验。
- 后快照 Job `36627` 在 `anode17` 以 `COMPLETED/0:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/25b0a8630e8ebf49abe7ec9fc85088f5045c9947/after-36627`。manifest 全量复核通过，且与 `before-36608` 逐项比较确认稳定 `current` 仍为发布 `1bba72d0ade2bb7024081d384584524a9c9d1c69`、稳定 Job `36597` 仍运行于 `anode01:18731`、两套数据库哈希和完整性、稳定服务提交及健康响应均未改变；平台 `sacct` 仍不可用但其 stderr 和降级状态已留证。
- 当前下一门禁是把热修复通过 PR 合并后，在 107 对新的固定 `main` 提交重新执行“前快照 -> Slurm 预览构建 -> 独立预览服务 -> 三视口 Playwright 与 Canvas 像素检查 -> 停服与端口消失 -> 后快照”。在该闭环通过前，三视口验收和预览运行证据清单保持未勾选，阶段 5 至 8 继续为 `PENDING`。

### 2026-08-12

- PR #14 已合并到受保护的 `main`，合并提交为 `7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8`。107 针对该固定提交完成前快照 Job `36637`、预览构建 Job `36638`、独立服务 Job `36641` 和后快照 Job `36653`；完整摘要见 `docs/107cup/frontend-preview-evidence.md`。
- Job `36638` 在 `anode02` 以 `COMPLETED/0:0` 结束，后端 `44/44`、前端 `104/104`、Vite `1857` 模块构建通过，生成不晋升的预览发布；manifest SHA-256 为 `837e85822cb74a24134423356b6d385505e0fb0fe51d1e80cd85adbb5edd789d`。
- Job `36641` 在 `anode01:20641` 以 `release_kind=preview`、`data_mode=demo` 启动。Windows Playwright 直接验收该 107 服务，三个固定视口通过 `3/3`，3D Canvas 彩色像素分别为 `2248`、`2403`、`3125`，控制台问题和业务写请求均为 `0`；验收后服务受控停止，Uvicorn 完整关闭且端口确认消失。
- 前后快照比较确认稳定 `current` 仍为 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，稳定 Job `36597` 仍运行于 `anode01:18731`，两套正式 SQLite 完整性为 `ok` 且哈希未变。平台 `sacct` 仍不可用，短作业 `scontrol` 记录已被集群清理，原始日志、前后快照和 SHA-256 证据均保留。
- 至此“前端完整形态预览”的三视口和隔离运行证据门禁已完成，但全部业务数据仍为演示数据。阶段 5 至 8 保持 `PENDING`；只有用户明确确认预览后，才为阶段 5 工作流模型与输入校验生成下一份实施计划。

- 用户已确认继续阶段 5。新增 `docs/superpowers/plans/2026-08-12-107cup-stage5-workflows.md`，把范围固定为六张工作流表、`mos2_v1` 模板、结构上传、草稿、确认和 `sbatch` 前校验；阶段 5 实现前仍为 `PENDING`，阶段 6 至 8 不变。

### 2026-08-13

- 阶段 5 的 Windows 本地实现检查点为 `9bfa6007c92868c3ee89e11be47e5ab0b52149af`（不含本次方案状态提交）：新增六张工作流表、唯一 Alembic head `107c0ffee001`、固定 `mos2_v1`、POSCAR/CIF 暂存与服务端摘要、私有输入物化、SHA-256 清单、草稿/确认事务、Operator/Viewer API 边界和 live 新建计算页面。确认成功只进入 `validated`，没有调用 Slurm/VASP，也没有创建 Job ID、attempt 或执行目录。
- Task 5 规格与质量复审均通过。前端对上传、保存和确认使用同步 lock 与 pending 双门禁；参数变化不会复用已消费 upload；写响应不确定时失败关闭，upload 来源要求重新上传，确认失败不再保留权威状态未知的旧草稿。
- 本地主流程门禁通过：阶段 5 与既有 107 后端专项 `114/114`、前端全套 `111/111`、定向 ESLint、`VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=live npm run build` 和 `git diff --check` 均为零失败。live 构建转换 `1857` 个模块；保留已有 Browserslist、3Dmol `eval` 和大 chunk 警告，不将其误报为本阶段失败。
- Alembic 显式验收同时覆盖 fresh SQLite 和停在 `2f694f47e108` 的上一 schema 副本：两条路径均升级到 `107c0ffee001`，六张工作流表无缺失且 `PRAGMA integrity_check=ok`；未迁移 source 保持原 revision。临时本地证据位于 `%TEMP%\lmatelab-stage5-migration-631a0b4072c245889f7cad59dfca907f`，不进入 Git 或运行环境。
- 功能分支已通过 PR #16 合并到受保护 `main`，合并提交为 `619b9116aee4f6cd4129debca87c1d4a35e12c5c`，并包含阶段 5 状态提交 `aaee9a19b8d448d674c6b05abf86be430ab7168a`。这只完成源码主线合并，107 尚未执行数据库副本迁移、真实 API/浏览器和前后快照验收，因此阶段 5 保持 `PARTIAL`，阶段 6 至 8 继续为 `PENDING`。
- 隔离分支 `codex/107cup-stage5-live-preview` 正在补齐 Task 7 专用链路：Slurm 构建固定 `live` 前端并生成不晋升发布；服务只迁移正式 SQLite 的私有副本，重定向全部写路径，使用 Job 专用随机 JWT 和私有 Operator/Viewer 凭据；登录节点辅助脚本仅执行 fetch、`sbatch`、调度状态和健康检查。该补丁当前尚未推送、合并或在 107 运行，不得记作远端验收证据。
- PR #17 已将上述隔离链路合并为 `644cb38282de24710e9eebda6754e07b8dac190b`。107 只读检出已固定到该提交；前快照 Job `37390` 在 `anode16` 以 `COMPLETED/0:0` 结束，两套正式 SQLite 的 `PRAGMA integrity_check` 均为 `ok`，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/644cb38282de24710e9eebda6754e07b8dac190b/before-37390`，manifest 全量校验通过。
- 首次 workflow preview 构建 Job `37391` 在 `anode01` 以 `FAILED/1:0` 结束。失败发生于后端测试收集：`requirements-107cup.txt` 未包含 Starlette `TestClient` 必需的 `httpx`，因而抛出 `ModuleNotFoundError`；尚未运行阶段 5 后端测试、前端测试或构建，也未创建正式 preview 发布、数据库副本、端口或服务。失败日志和 `.644cb38282de24710e9eebda6754e07b8dac190b.37391` 暂存目录保留，稳定 `current`、正式数据库和 Job `36597` 未被该构建修改。
- 当前修复门禁仅为在 107 专用依赖中固定兼容的 `httpx` 并增加依赖合同测试。该修复经独立 PR 合并前不得清理失败现场、重提构建或启动 workflow preview；合并后需对新的固定 `main` 重新执行前快照和完整 Task 7 闭环，阶段 5 继续保持 `PARTIAL`。
- PR #18 已合并为 `main` 提交 `a90745baef7c7e8bff27c9be85a6bc79e0e8885f`。前快照 Job `37394`、workflow preview 构建 Job `37395` 和隔离服务 Job `37397` 均运行于 107 Slurm 计算节点；构建通过后端 `124/124`、前端 `111/111` 和 live Vite 构建，API 验收确认 Operator/Viewer 角色、Viewer 写拒绝、四类恶意输入拒绝、两条 `validated` 工作流、六张表和 SQLite 完整性，且没有 attempt 或 Slurm Job ID。稳定 `current`、正式数据库和 Job `36597` 未被修改。
- 三视口浏览器验收没有通过：Desktop 在第一个真实工作流详情发现 `release_commit` 为空；随后直接读取两个 live API 对象，均确认 `data_kind=live`、`status=validated`、`template_version=mos2_v1`、四步为 `waiting` 且 Job ID 为空，但 `release_commit=null`。该结果违反工作流可追溯到固定发布提交的阶段 5 门禁，不能用构建或 API 其他成功项替代。Job `37397` 和本次失败截图/日志暂时保留用于诊断，不记为浏览器通过。
- 发布提交追溯修复在分支 `codex/107cup-stage5-release-provenance` 按 TDD 完成本地实现：RED 证明服务不接受提交参数、详情返回 `null` 且运行时无严格 SHA 读取；聚焦 GREEN `4/4` 证明合法 40 位小写 SHA 可持久化，非法值在文件生成前失败，详情 API 原样返回固定提交。完整本地门禁通过后端 `126/126`（另有 1 个 Windows 符号链接权限预期 skip）、前端 `111/111`、live Vite 构建 `1857` 个模块、定向 ESLint、19 个 Bash/Slurm 文件语法和 `git diff --check`；保留既有 Browserslist、3Dmol `eval` 和大 chunk 警告。上述仍仅为 Windows 本地事实；合并、107 新预览、API、三视口浏览器、停服和后快照全部重跑前，阶段 5 继续保持 `PARTIAL`，阶段 6 至 8 保持 `PENDING`。

### 2026-08-14

- PR #21 已合并为受保护 `main` 提交 `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7`，107 只读 detached checkout 已固定到同一提交且工作树干净。前快照 Job `37593` 在 `anode16` 以 `COMPLETED/0:0` 结束；workflow preview 构建 Job `37594` 在 `anode01` 以 `COMPLETED/0:0` 结束，通过后端 `126/126`、前端 `111/111` 和 live Vite `1857` 模块构建，生成 `482` 项 manifest，SHA-256 为 `ed0df15a583bc2fdf2b3174b14b7c8e1abaf93ffb4aa16f46aa79bde07728824`。
- 最终私有预览 Job `37611` 在 `anode01:21611` 启动，健康元数据为 `release_kind=preview`、`data_mode=live`。Operator 创建内置 MoS2 与上传 POSCAR 两条工作流，均进入 `validated`，详情均持久化完整发布提交；八个步骤全部为 `waiting`，数据库 attempt 计数为 `0`，没有 Slurm Job ID 或 attempt 目录。
- Viewer 可以读取两条工作流，但结构上传、草稿创建和确认三个写路由均为 `403`。路径文件名、额外字段、命令注入字符串、越界 `ENCUT`、超 `1 MiB` 文件和错误 `S Mo` 元素顺序六类输入均为 `422`，且拒绝响应不泄露服务器路径；Results 与 VASP Database 均为 `data_kind=live` 的真实空集合。
- Windows Playwright 1.54.2 通过临时双层 SSH 转发直接验收 Job `37611`；`1440x900`、`1024x768`、`390x844` 三个视口均通过，每个视口记录 `14` 个成功 API 响应和 `7` 张截图，控制台问题、页面错误、失败请求、意外写请求及页面横向溢出均为 `0`。最终外部证据目录含 `21` 张截图、`5` 份 JSON，`26` 项 SHA-256 清单自身哈希为 `8913d249ce53bfef8f946017ea349a1c2a2838c8d3cffbc840ac727148b0ed1b`。
- Job `37611` 验收后受控停止为 `CANCELLED/0:15`，Uvicorn 完整关闭，计算节点端口和 Windows/4090 临时 `18736` 转发均确认消失。后快照 Job `37614` 在 `anode16` 以 `COMPLETED/0:0` 结束，`comparison.txt` 为 `stable state matches before snapshot`；稳定发布仍为 `1bba72d0ade2bb7024081d384584524a9c9d1c69`，Job `36597` 仍位于 `anode01:18731`，两套正式 SQLite 哈希未变且完整性为 `ok`。
- 完整证据见 `docs/107cup/stage5-workflow-evidence.md`。独立证据 PR #22 已合并为 `3cf9b44f0b55a11e43f0a4960dc689cf0607ced2`；Windows 本地 `main`、Gitea `main` 与 107 只读 detached checkout 已同步到该提交且 107 工作树干净，因此阶段 5 改为 `DONE`。阶段 6 至 8 仍为 `PENDING`，没有提交普通 Slurm 测试作业或 VASP 作业。
- PR #23 已合并为受保护 `main` 提交 `a986bb65058a13dfbbee1456d9aefdcd7642bc64`。稳定前端部署前快照 Job `37678` 在 `anode19` 以 `COMPLETED/0:0` 保存旧 `current`、Job `36597`、正式数据库哈希和完整性；隔离构建 Job `37681` 在 `anode01` 以 `COMPLETED/0:0` 通过后端 `126/126`、前端 `111/111` 和 live Vite `1857` 模块构建，生成 `483` 项 manifest，SHA-256 为 `eeab8875f2963d64a60fe20747cb6170714e8c211cd8eebf196acac7ccb223bd`。
- 隔离候选服务 Job `37683` 曾运行于 `anode01:21683`，健康元数据固定为 `a986bb6`、`preview/live`。Windows Playwright 在 `1440x900`、`1024x768`、`390x844` 三个视口完成五个导航和七条受保护路由验收，共保留 `21` 张截图；live 工作流、结果和 VASP 数据库均为空且没有回退 demo，相关控制台问题、失败请求、意外业务写请求和横向溢出均为零。该候选使用正式数据库副本，没有修改正式数据、旧服务或公开入口。验收后 Job 于 `2026-08-14T16:39:56+08:00` 受控停止为 `CANCELLED/0:15`，Uvicorn 完整关闭，`anode01:21683` 和 Windows/4090 临时 `18736` 转发均确认消失。
- 第一次正式构建 Job `37689` 在 `anode01` 以 `FAILED/1:0` 结束，失败发生在后端 readiness 测试，尚未创建发布暂存目录或切换 `current`。根因是正式构建加载 `LMATELAB_EDITION=107cup` 后，标准数据库 readiness 单测没有隔离继承环境，因而误查 `workflow_runs`；隔离候选构建未加载正式运行环境，所以此前未暴露。失败日志保留在 `logs/build-37689.{out,err}`，稳定 `current` 仍为 `1bba72d0`，Job `36597` 与公开入口仍运行。当前只修复该测试的环境隔离；新 PR 合并并对新的固定 `main` 重跑候选和正式构建前，不得记录稳定部署完成。
- 环境隔离修复已按 RED/GREEN 在本地验证：显式继承 `LMATELAB_EDITION=107cup` 时，目标 readiness 测试修复前复现 `no such table: workflow_runs`，修复后通过；同一环境下后端 107 专项 `126/126`（另有一个 Windows 符号链接权限预期 skip）、前端 `111/111` 和 `git diff --check` 均通过。该结论仍只是本地事实，等待修复 PR 合并和新 `main` 的 107 Slurm 重跑。
- PR #24 已将环境隔离修复合并为受保护 `main` 提交 `bec82bc9fed3ad9355235b965f5bf8cdba152a60`；Windows `main` 与 107 只读 detached checkout 已固定到该提交且工作树干净。部署前快照 Job `37703` 在 `anode16` 以 `COMPLETED/0:0` 结束，证据 manifest SHA-256 为 `fc60d5051ebe8025ca3abfd4b5794d5b8690dc1fbd5d7d77ddbd0478bc26e94e`。
- workflow preview 构建 Job `37704` 在 `anode01` 以 `COMPLETED/0:0` 结束，通过后端 `126/126`、前端 `111/111` 和 live Vite `1857` 模块构建；生成 `483` 项 manifest，SHA-256 为 `89e43dec23c9d6cbb3382354ba07be6bdd67ee28cee434e7c9efe3dbb31728ea`。候选服务 Job `37707` 在 `anode01:21707` 以 `preview/live` 启动，六张工作流表、Alembic head `107c0ffee001`、ready 和 SQLite 完整性均通过。
- Windows Playwright 通过临时双层 SSH 转发验收 Job `37707`：`1440x900`、`1024x768`、`390x844` 三视口完成五个导航和七条受保护路由，共保存 `21` 张截图；live 工作流、结果与 VASP 数据库为真实空集合，相关控制台问题、页面错误、失败请求、意外写请求和横向溢出均为 `0`。补充 Canvas 门禁确认桌面与手机结构查看器分别有 `1676/339320` 和 `2708/122040` 个非空彩色像素。外部证据 manifest 覆盖 `29` 项受控载荷；目录共 `31` 个文件，另含 `evidence-manifest.txt` 和 `evidence-manifest.sha256`。清单 SHA-256 为 `0a2bd6c091c8f5a432333f53a70a6e067edc9483a0fbd83a6be4baa8e11245b6`。
- 正式构建 Job `37711` 在 `anode01` 以 `COMPLETED/0:0` 结束；正式构建自身通过后端部署专项 `54/54`、前端 `111/111` 和 live Vite `1857` 模块构建，原子切换到 `releases/bec82bc9fed3ad9355235b965f5bf8cdba152a60`。正式发布 manifest 含 `491` 项，SHA-256 为 `d953c0a6339e3ba68ab8f7709096770c6eb397cd441040719e62073ddf62495b`。候选的 `126/126` 是同一固定提交的扩大专项门禁，不能误写成正式构建脚本自身的测试数量。
- 首次新稳定服务 Job `37713` 因平台未识别 `SBATCH_EXCLUDE=anode01` 环境覆盖而仍分配到 `anode01`；它完成阶段 5 migration 后在绑定 `18731` 时因旧 Job 占用端口，以 `FAILED/1:0` 结束。旧 Job `36597` 在该失败期间持续健康，失败日志和调度记录保留。随后使用显式 `sbatch --exclude=anode01` 提交 Job `37715`，`scontrol` 确认 `ExcNodeList=anode01`，服务在 `anode02:18731` 以 `stable/live` 运行并返回提交 `bec82bc9` 与正式 manifest 哈希。
- 4090 临时 `18737 -> anode02:18731` 验证新服务后，稳定 `18734` 转发由 `anode01:18731` 切换到 `anode02:18731`；Nginx 和白名单配置未修改，配置 SHA-256 仍为 `0c011ea9442733daf5d3277d4632a662264083ff0432b9abdfaad5b5828c99c8`。公网 `http://222.195.94.37:18733` 的 login、Dashboard shell 与 ready 为 `200`，未认证业务 API 为 `401`，空登录 POST 为 `422`，注册和业务 POST 均为 `403`。
- 入口切换并验证新 Job 后，旧稳定 Job `36597` 经归属核对受控停止为 `CANCELLED/0:15`；Uvicorn 完整 shutdown，`anode01:18731` 确认不可达，公网入口仍返回 Job `37715`。候选 Job `37707` 随后受控停止，`anode01:21707`、Windows `18736` 和 4090 临时 `18736/18737` 均确认消失；稳定 `18734` 保留。
- 部署后状态快照 Job `37718` 在 `anode19` 以 `COMPLETED/0:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/bec82bc9fed3ad9355235b965f5bf8cdba152a60/before-37718`，manifest SHA-256 为 `2a9a3446a234fd97039586b5339f217cc41caf4163052ed4dd3520242156a9b7`。正式 `eln.db` SHA-256 从 `cd5d639bccfa35414769901f444bf64b867826ce20962d5098a0dac8e07f135a` 变为 `de6176f960e6b7cbe4e44254585b23a8032e7ca146236cab7ec2eea736c6ce86`，对应阶段 5 migration；`digests.db` 保持 `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969`，两库完整性均为 `ok`。完整摘要见 `docs/107cup/stable-frontend-deployment-evidence.md`。
- 本次只完成既有完整竞赛前端的稳定部署，没有开始阶段 6，没有提交普通 Slurm 控制作业或 VASP 作业，也没有创建 Agent、机器学习或其他旁支功能。阶段 5 继续为 `DONE`，阶段 6 至 8 继续为 `PENDING`。

### 2026-08-15

- 阶段 5 已完成并维持 `DONE`。PR #25 已把稳定前端部署证据合并到受保护 `main`，合并提交为 `2c7366d4dc7c53ff63841607f1c0b896949d24e4`；稳定网页仍正确运行源码提交 `bec82bc9fed3ad9355235b965f5bf8cdba152a60`，因为 PR #25 只修改文档。
- 阶段 6 已在隔离分支 `codex/107cup-stage6-slurm-adapter` 开始，基线为 `2c7366d`。详细设计与实施计划分别为 `docs/superpowers/specs/2026-08-15-107cup-stage6-slurm-adapter-design.md` 和 `docs/superpowers/plans/2026-08-15-107cup-stage6-slurm-adapter.md`；本条记录只表示开始，不是实现、合并或远端验收完成。
- Windows 新 worktree 使用项目锁定依赖完成阶段 5 模型、输入、服务和路由基线 `67/67`。首次复用旧虚拟环境因缺少 `httpx` 在测试收集前失败，随后建立 worktree 专用 `.venv` 后原命令通过；该环境问题不记作代码回归。
- 从稳定服务 Job `37715` 的 `anode02` 计算分配内实测：`sbatch --test-only`、`squeue`、`scontrol --json`、`squeue --json` 和 `scancel` 客户端可用；test-only 报告的测试 ID `38285` 不存在于 `squeue`，没有创建作业。`sacct` 仍因 `localhost:6819` 连接被拒绝而不可用。
- 阶段 6 对账因此固定为：在线状态以结构化 `squeue/scontrol` 为权威，`sacct` 可用时补最终记账；若两类来源都不能证明最终状态，则记录 `unknown/stale`，不得继续显示为运行中，也不得猜测成功。当前没有提交普通测试作业、没有调用 `scancel`、没有运行 VASP，阶段 6 仍为 `PENDING`。
- 阶段 6 本地实现检查点为 `a6a59d4`（不含本次状态记录提交）：固定绝对 Slurm 二进制与 argv、`sbatch --test-only`/提交、attempt 私有目录和 receipt、SQLite 提交 ledger、重启对账、四项归属取消、Operator API、ledger-only Dashboard、固定 `success|fail|cancel` 探针以及独立 smoke 证据包均已实现。107/阶段 5/阶段 6 后端范围回归 `169/169` 通过，另有 2 项仅因 Windows 文件符号链接权限跳过；前端在按锁文件执行 `npm ci` 后 `111/111` 通过，live 构建转换 `1857` 个模块；四个变更 Slurm/Bash 文件通过 WSL `bash -n`，Python smoke 通过 `py_compile`。保留既有 Browserslist、3Dmol `eval` 和大 chunk 警告；`npm ci` 同时报告既有依赖树 8 个 high 漏洞，本分支未运行会改写锁文件的自动修复。
- 上述仍只是 Windows 本地源码和测试证据，分支尚未合并，107 未构建该提交，也没有提交真实 `success`、`fail`、`cancel` 或非归属控制作业。阶段 6 因此只改为 `PARTIAL`；合并后必须在 107 Slurm 计算节点运行 smoke、保留 Job ID/原始调度输出/SQLite 完整性/SHA-256 清单并通过独立证据 PR 后，才能改为 `DONE`。阶段 7 保持 `PENDING`，没有运行 VASP。

### 2026-08-16

- PR #26 已把阶段 6 功能分支合并到受保护 `main`，合并提交为 `74fb0b45d69dbc56ba6bb8f4ef27f27106d51ff2`；107 detached checkout 已固定到该提交且工作树干净。稳定服务继续为 Job `37715`、`anode02:18731` 和发布 `bec82bc9fed3ad9355235b965f5bf8cdba152a60`，公网 live、ready 与 Dashboard 均为 `200`。
- 前快照 Job `38592` 在 `anode16` 以 `COMPLETED/0:0` 结束，证据位于 `evidence/previews/74fb0b45d69dbc56ba6bb8f4ef27f27106d51ff2/before-38592`，manifest SHA-256 为 `1645c0fa20f9efd528f521af7d00427a00152e513add0c129170ff571ae2b49a`。快照记录 `eln.db` 与 `digests.db` SHA-256 分别为 `de6176f960e6b7cbe4e44254585b23a8032e7ca146236cab7ec2eea736c6ce86`、`2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969`，两库完整性均为 `ok`。
- 正式构建 Job `38593` 在 `anode01` 以 `COMPLETED/0:0` 结束，通过后端 `164/164`、前端 `111/111` 和 live Vite 构建；`current` 原子切换到 `releases/74fb0b45d69dbc56ba6bb8f4ef27f27106d51ff2`。发布 manifest 含 `516` 项，SHA-256 为 `e1fc197fb4fb1de0383d724c7ba962cdaa770033c08038b8b786d8c22cc05329`，并包含固定 `probe.slurm` 与 `stage6-smoke.py`。
- 首次真实 smoke Job `38598` 在 `anode01` 以 `FAILED/1:0` 结束，stderr 为 `competition backend source is unavailable`，SHA-256 为 `36d0f6242943582f438e2bc061f49b0bb9abeb448eac151ae7f7a6c6766a64c3`。失败发生在任何 `sbatch --test-only`、普通探针、`scancel` 或非归属控制作业之前，因此没有子 Job ID、没有修改数据库，也没有可误记为 Slurm 适配器验收的成功证据；失败日志保留，队列仍只有稳定 Job `37715`。
- 根因是 Slurm 把 Python 批脚本复制到 spool 路径后，`__file__` 不再位于发布目录，而 smoke 用其父目录定位 backend。修复通过完整小写 commit 固定 `releases/<commit>/source/backend` 和同一 release 内的探针，并在业务依赖导入前建立私有证据目录、记录早期 `failure.json` 与 SHA-256 manifest。新增合同测试先 RED 后 GREEN；Windows 阶段 5/6 与 107 专项回归 `165/165` 通过，另有 1 项 Windows 符号链接权限预期跳过，`py_compile` 与 `git diff --check` 通过。
- 上述修复尚未合并、没有部署到 107；在修复 PR 合并并针对新的固定 `main` 重做构建和完整 smoke 前，阶段 6 继续为 `PARTIAL`。阶段 7 与阶段 8 保持 `PENDING`，没有运行 VASP。
- PR #27 已把 Slurm spool 启动修复合并为受保护 `main` 提交 `93465522424ce0db24dabdfca04efe22fc523fa7`；107 只读 detached checkout 已固定到该提交且工作树干净。前快照 Job `38620` 在 `anode16` 以 `COMPLETED/0:0` 结束，manifest SHA-256 为 `476ebc4a1175419dfb1b115451f5ad0743c5abc04dd2d039dc1067851d895171`。
- 正式构建 Job `38621` 在 `anode01` 以 `COMPLETED/0:0` 结束，耗时 `42` 秒；后端 `165/165`、前端 `111/111` 和 Vite `1857` 模块构建通过，生成 `516` 项发布 manifest，SHA-256 为 `ae7e8772b2d24c394a5862762693ffb196c1b2967c06c4ee04fb93e95a096623`。
- Stage 6 smoke Job `38623` 在 `anode01` 以 `COMPLETED/0:0` 结束，耗时 `8` 秒。Job `38625` 为 `COMPLETED/0:0`，Job `38626` 为 `FAILED/42:0` 且 `Reason=NonZeroExitCode`，Job `38627` 经归属检查后为 `CANCELLED`；适配器以 `cancellation_ownership_mismatch` 拒绝取消 smoke 自建控制 Job `38628`，harness 随后只清理该已知作业。
- `sbatch --test-only` 返回 `0` 且没有残留作业；受控调度拒绝没有产生 Job ID；新 reconciler 对象和数据库会话完成成功、失败与取消对账。独立 SQLite 完整性为 `ok`，`54` 项证据清单全部复核通过，清单文件 SHA-256 为 `dec0f89f1ad317d996286b72563973dad5f38ce2fcfabd5f52f641b6d60437f4`。`sacct` 仍因 `localhost:6819` 拒绝连接而不可用，保留的结构化 `scontrol` 记录为权威终态。
- 后快照 Job `38629` 在 `anode16` 以 `COMPLETED/0:0` 结束，standalone 模式证据目录为 `before-38629`，manifest SHA-256 为 `4bb663dca35f6d92f02f54177b279fc8e4f467c2e008f5436f765e000ea876a4`。两套正式 SQLite 哈希和完整性、稳定 Job `37715`、`anode02:18731`、运行提交 `bec82bc9...` 及公开 live/ready/Dashboard 均未改变；`current` 按构建合同切换到新发布，不表示运行中的稳定服务已重启。
- 完整运行证据见 `docs/107cup/stage6-slurm-evidence.md`。该证据尚在独立待合并分支，因此阶段 6 继续为 `PARTIAL`；证据 PR 合并并完成 Windows、Gitea `main` 与 107 同步后，才可在后续状态提交中改为 `DONE`。阶段 7 和阶段 8 保持 `PENDING`，没有运行 VASP。
- 独立证据 PR #28 已合并为 `044ada5a5287f402f57507f25245764a807bc8d4`。Windows 本地 `main`、Gitea `main` 与 107 只读 detached checkout 已同步到该提交，107 工作树干净；稳定 Job `37715` 仍在 `anode02` 运行，公开 live、ready 和 Dashboard 均为 `200`。因此阶段 6 改为 `DONE`；阶段 7 和阶段 8 继续为 `PENDING`，本次未运行 VASP。

### 2026-08-19

- 阶段 7 固定 MoS2 `relax -> SCF -> BAND/DOS` 本地实现检查点为 `f2fe8acd4251b25a8d47f876be0213cca0062a2c`（不含本次状态记录提交）。实现范围严格限于固定材料、固定模板和固定 runner，不加入 Agent、机器学习、任意材料/命令或阶段 8 结果包。
- Task 12 本地门禁通过：后端完整 14 模块回归 `430` 项通过、`21` 项按 Windows/POSIX 条件跳过；前端 `125/125`、竞赛范围 ESLint、demo/live 两种 `107cup` Vite 构建均通过且每次转换 `1857` 个模块；WSL runner 行为测试 `10/10`，三个 Stage 7 Bash 文件通过 `bash -n`，内部验收脚本通过 `py_compile`。
- 仓库检查未发现本分支新增的 `shell=True`、`eval`、`bash -c`、`sh -c`、Docker/Singularity 或 POTCAR 内容路径，凭据模式扫描无命中，`git diff --check` 通过。构建保留既有 Browserslist、3Dmol 依赖 `eval` 和大 chunk 警告，不把第三方依赖警告误报为本阶段失败。
- 上述只证明本地源码和合同门禁。分支尚未合并，107 未构建或部署该实现，本次没有连接 107、提交 Slurm 或执行 VASPKIT/VASP，因而没有真实 VASP Job ID、正常结束标记、四步文件集合或人为失败链证据。阶段 7 仅改为 `PARTIAL`，阶段 8 继续为 `PENDING`；必须在实现 PR 合并并同步固定提交后，再按 Task 13 和 Task 14 完成真实 107 验收。
- 阶段 7 实现 PR #30 已合并；107 预检 Job `39373` 在 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage7/preflight-39373` 以 `FAILED/1:0` 结束。真实 VASPKIT 输出为 `|         VASPKIT Standard Edition 1.5.1 (27 Jan. 2024)         |`，旧脚本由 `grep` 保留整行后与 `VASPKIT Standard Edition 1.5.1` 严格比较，因边框和日期必然不匹配。
- Job `39373` 在该版本门禁处停止，没有执行 `vasp_std`，也没有进入正式构建；不得将该保留失败现场记为 VASP 成功或四步链证据。
- 预检修复在 `codex/107cup-stage7-preflight-fix` 严格按 TDD 仅在本地完成：受限提取唯一 VASPKIT 规范版本令牌并仍严格等于 `1.5.1`，在所有证据生成后写入不自包含的 `manifest.txt` 和仅哈希该文件的 `manifest.sha256`，两层均在作业内自校验；正式 `vasp-stage.slurm` runner 的同根因整行比较也已同步为完全相同的受限提取。阶段 7 保持 `PARTIAL`；该修复必须经 PR 合并并在 107 重新提交预检通过后，才能继续。
- PR #31 已合并为 `eae6ac17575143d81e737ae7395def69960d1c95`，107 只读 checkout 已同步到该提交。预检前快照 Job `39382` 以 `COMPLETED/0:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/eae6ac17575143d81e737ae7395def69960d1c95/before-39382`，manifest SHA-256 为 `030a0a56958e7694493dbaf3efe8d860aed3a3e5b46fc51de783af934cd10b39`。
- 第二次预检 Job `39383` 在 `anode02` 以 `FAILED/127:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage7/preflight-39383`。VASPKIT 成功生成并校验固定 POTCAR；现场仅有 `POSCAR`、`POTCAR.spec`、`POTCAR`、`potcar-source-sha256.txt` 和 `vaspkit-version.txt`，没有 `vasp-std-path.txt`、`vasp-std-ldd.txt` 或 manifest。
- Job `39383` 停在 `source env-nvhpc.sh` 之前后边界；该环境脚本执行 `module load mkl/2026.0`，而 Stage 7 批处理脚本未像已验证的构建脚本那样先加载 `/etc/profile.d/modules.sh`。修复范围仅为在预检和正式 runner 中按相同顺序初始化 modules；合并并在 107 重跑预检成功前，阶段 7 继续保持 `PARTIAL`。
- module 初始化修复在 `codex/107cup-stage7-module-init` 按 TDD 完成本地门禁：新合同首先对两个 Stage 7 脚本各失败一次，增加固定 `source /etc/profile.d/modules.sh` 并保证其早于 `env-nvhpc.sh` 后转为通过；Linux 夹具中的伪环境脚本也会真实调用 `module load mkl/2026.0`。Windows 后端完整回归 `435` 项通过、`23` 项按平台条件跳过，WSL 两组 Bash 行为测试 `12/12`通过，前端 `125/125`、定向 ESLint、demo/live 两种构建（各 `1857` 个模块）、三个 Stage 7 Bash 语法和 Python 编译检查全部通过。该分支尚未合并，本轮未在 107 提交新作业；本地通过不替代合并后的真实预检。
- module 初始化 PR #32 已合并为 `b25eb7ae55c4aaea32e0e93779a830df643aa40a`，Windows 本地 `origin/main` 与 107 只读 checkout 均已固定到该提交，107 工作树干净。
- 部署前快照 Job `40038` 在 `anode16` 运行 2 秒后以 `COMPLETED/0:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/b25eb7ae55c4aaea32e0e93779a830df643aa40a/before-40038`，manifest SHA-256 为 `59171ae15c3c3d0f56fb543c1bd43f861a97ddb81ba818524ea36270422995a8`。稳定服务仍为 Job `39370`、`anode02:18731`、发布 `93465522424ce0db24dabdfca04efe22fc523fa7`；两套 SQLite 完整性均为 `ok`，4090 入口 `/`、`/dashboard`、live 和 ready 均返回 `200`。
- Stage 7 预检 Job `40039` 在 `anode01` 运行 3 秒后以 `COMPLETED/0:0` 结束，证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage7/preflight-40039`。证据目录为 `0700`、全部文件为 `0600`，manifest SHA-256 为 `06fe38bf27b163684f628db1c3ee4e89134b199ae08240ed2ad327d5b6fc1879`，两层自校验均通过。
- Job `40039` 验证 VASPKIT `1.5.1`、Mo_sv/S 两个固定源哈希、合并 POTCAR 哈希 `509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045`、`Mo_sv -> S` TITEL 顺序和 `/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/bin/vasp_std`；`ldd` 无 `not found`，stderr 为空。现场不存在 `runtime-time.txt`、`vasp-exit-code.txt`、`OUTCAR` 或 `vasprun.xml`，因此该作业只是环境预检，不是 VASP 计算成功证据。Stage 7 保持 `PARTIAL`，下一门禁是 Task 13 正式构建与隔离候选服务。
- PR #33 合并预检证据后，107 只读 checkout 同步到 `132a7bbd1728efd9c6bb31f66888ca6b091368a9`，工作树干净。正式构建前快照 Job `40052` 以 `COMPLETED/0:0` 结束，manifest SHA-256 为 `24d0737c1e3c620ccab70395390f241e02d4e4a8fc03880aee57fe8f8eeec164`。
- Task 13 首次正式构建 Job `40053` 在 `anode01` 运行 65 秒后以 `FAILED/1:0` 结束。后端共执行 `436` 项，结果为 `25 errors + 1 failure + 4 skipped`；前端和发布阶段未进入，没有生成新 release，也没有切换稳定服务。稳定 Job 仍为 `39370`、`anode02:18731`，运行发布仍为 `93465522424ce0db24dabdfca04efe22fc523fa7`，公开入口、Dashboard、live 和 ready 均为 `200`。
- Job `40053` 的 `25` 个 error 同源于 107 Python 不提供 `os.memfd_create`、`os.MFD_*` 及 `fcntl.F_*SEAL*`；唯一 failure 是真实 Linux 符号链接在 `_safe_row_path()` 已被正确拒绝为 `input_path_invalid`，而旧测试错误期待了更后级的 `input_source_invalid`。诊断 Job `40054` 确认所有 memfd/seal Python 符号均缺失。
- 受控探测 Job `40055` 证明 107 的 `/tmp` 支持 Linux `O_TMPFILE`：匿名 inode 能经 `/proc/self/fd/<fd>` 重开为只读描述符，inode 一致，关闭唯一可写描述符后写入失败为 `EBADF`、截断失败为 `EINVAL`，子进程能完整读取匿名快照。
- 构建兼容修复在 `codex/107cup-stage7-build-portability` 完成：优先使用已封印 memfd；Python 不提供该能力时，改用无路径 `O_TMPFILE`、哈希复核、同 inode 只读重开，关闭唯一可写 fd 后再复核身份和哈希并交给 `sbatch`；两种 Linux 匿名机制都不可用时继续失败关闭。本地 Windows 完整后端 15 模块回归为 `438/438`，`25` 项按平台条件跳过；WSL 真实匿名快照行为测试 `2/2` 通过。上述仍是本地修复证据；必须经 PR 合并、107 固定合并提交重建通过后，才能继续候选服务和 Task 14 真实 VASP 四步闭环。
- 构建兼容修复 PR #34 已合并为 `c677e7b8f163610a21fbb5729a9538d979ac107b`。正式构建 Job `40059` 以 `COMPLETED/0:0` 结束，通过后端 `438/438`（另有 4 项按平台条件跳过）、前端 `125/125` 和 Vite 构建；发布 manifest 含 `545` 项，SHA-256 为 `66c69ad238619255c61280f93fa64f3c393d7bbd1e60f14574f7acbefad6d721`。候选构建 Job `40060` 亦为 `COMPLETED/0:0`；候选服务 Job `40062` 完成 API、认证和 15 页面三视口浏览器验收后受控停止为 `CANCELLED/0:15`，外部证据位于 `LMateLab-107Cup-evidence/stage7-candidate-c677e7b-job40062`。
- 中间稳定服务 Job `40081` 曾运行于 `P107-RTX5090/anode01:18731`，独立部署后快照 Job `40088` 以 `COMPLETED/0:0` 结束，manifest SHA-256 为 `fde397e9211057b580668442cbc93360089fd36830ae9c2d28048816d8a8f24d`。由于同一 `qos_p107-rtx5090` 的用户 CPU 上限为 16，2 CPU 网页服务阻塞了请求 16 CPU 的 VASP Job，故网页服务迁移到独立 A100 QOS；这只是服务资源隔离，不改变 VASP runner 的 RTX5090 分区。
- 新稳定服务 Job `40091` 已在 `P107-A100/anode16:18731` 运行同一发布 `c677e7b`。验收确认 live/ready、545 项发布 manifest、两套 SQLite `PRAGMA integrity_check=ok`、Viewer 登录与 `/api/auth/me` 为 `200`、Viewer 业务写为 `403`，且 Uvicorn 实际工作目录和环境均固定到不可变 release，`LMATELAB_COORDINATOR_ENABLED=1`。
- 4090 新增 `127.0.0.1:18736 -> anode16:18731` 后，用户态 Nginx 三个 upstream 从 `18735` 原子切换到 `18736`；候选和活动配置均通过 `nginx -t`，公网 live/ready/Dashboard 为 `200`，登录 POST 到达应用层为 `422`，注册与业务 POST 仍为 `403`。活动配置权限为 `0600`，SHA-256 为 `06560c602f23c1bd4c69e517f3b13b1f39bdad006a8aea9c2d13fce9bba4e173`。核对归属后旧 Job `40081` 受控停止，`anode01:18731` 不可达，旧 `18735` 转发撤销，公网入口继续返回 Job `40091`。
- Operator 从稳定网页创建真实成功链工作流 `4b566547-961b-4e10-a8d0-99431f2e2229`；Relax attempt 为 `101154ee-4dd7-4c41-94cf-d9a922741f59`、Job 为 `40090`。释放 RTX5090 QOS 资源后该 Job 在 `anode02` 启动，但以 `FAILED/1:0` 立即结束；唯一 stderr 为稳定服务未导出 `LMATELAB_WORKFLOW_ROOT`。现场仅有固定输入和 Job receipt，没有 POTCAR、`runtime-time.txt` 或 VASP 输出，因此这是执行前基础设施失败，不是 VASP 失败或科学不收敛。
- 修复分支 `codex/107cup-stage7-workflow-env` 的提交 `4778ee4` 显式从稳定服务导出 `LMATELAB_WORKFLOW_ROOT="$root/data/workflows"` 并增加部署契约。首次构建 Job `40096` 中该新契约通过，但完整后端套件暴露 POTCAR 描述符竞态测试依赖目录 `mtime` 精度：文件路径替换会改变目录元数据，却不改变安全 `dir_fd` 已打开的文件身份。提交 `ac363d2` 将目录身份签名收窄为 device/inode/mode，仍拒绝目录换位和类型变化，同时不再误判目录内容变更。
- 修复构建 Job `40097` 在 `anode01` 以 `COMPLETED/0:0` 结束，耗时 `106` 秒；后端 `438/438`（另有 4 项跳过）、前端 `125/125`、Vite `1857` 模块构建和 545 项 manifest 自检均通过。新 release 为 `ac363d2d1f14c9d70253dc88185c215dc91d32fc`，`manifest.txt` SHA-256 为 `c944b34662feb837e0e1cf38113fc966986b7f1ffc5645789f827608c3ea689c`。该分支尚未合并，运行中的 Job `40091` 仍固定在 `c677e7b`；因此不得重试工作流或把阶段 7 标为完成。下一门禁是合并修复 PR、按合并提交重建与安全替换服务，再对原工作流执行受控 Relax retry。
- PR #35 已合并工作流根目录修复；后续 PR #36 将 VASPKIT 发布证据收窄为规范版本，PR #37 允许真实 POTCAR `TITEL` 记录的行首空白。三个修复均已进入受保护 `main`，当前合并提交为 `09ed330536ae3bad44f2a662f6d3611779213027`。
- 按 `09ed330` 构建的 Job `40210` 以 `COMPLETED/0:0` 结束：后端 `439/439`（另有 4 项跳过）、前端 `125/125`通过，发布 manifest 含 `545` 项，SHA-256 为 `ca356234b1288db149139bc5f2ce877b9a17338721bf250d741e20a315a190fb`。稳定服务 Job `40211` 位于 `P107-A100/anode17:18731`，本次复核仍为 `RUNNING`；4090 入口继续只作为转发。
- 原成功链工作流 `4b566547-961b-4e10-a8d0-99431f2e2229` 的 Relax retry attempt `3f1a34a4-6efb-4de2-a299-cbec2c1a96cb`、Job `40212` 已通过科学验收，耗时 `24.92 s`、峰值 RSS `2305260 KiB`。随后 SCF attempt `de4c6c9b-f61d-4a50-9d9a-28a1f4b2f6a6`、Job `40213` 在 Slurm 层为 `COMPLETED/0:0`，耗时 `34.47 s`、峰值 RSS `2362168 KiB`，但科学验收以 `scf_efermi_invalid` 失败；BAND 和 DOS 均未产生 attempt，正确保持阻断。
- SCF 现场 `vasprun.xml` 为 `70852` 字节，且只有一个规范 `<calculation><dos><i name="efermi">-1.73484146</i>` 记录。根因是默认 Pymatgen loader 为限制开销使用 `parse_dos=False` 和 `parse_eigen=False`，验收却仍读取 `Vasprun.efermi`，导致真实有效值被误判为空。
- 修复分支 `codex/107cup-stage7-scf-efermi` 已按 RED/GREEN 完成本地实现：从已固定、已哈希复核的 XML 快照流式提取唯一有限十进制 `efermi`，且缺失、重复、`nan/inf`、非数值或错误 XML 路径仍失败关闭。`competition_vasp` 单模块 `100/100` 通过；Stage 7 相关 15 模块 `440/440` 通过，25 项仅因 Windows/POSIX 条件跳过。该结论仍是本地事实；修复 PR 合并、107 Slurm 构建、服务替换和原 SCF 证据重验收完成前，Stage 7 继续为 `PARTIAL`。
- SCF Fermi 修复 PR #38 已合并为 `6ac224fbca09d35854c9cd054e00cadfe017b020`。构建 Job `40248` 通过后端 `440/440`（另 4 项平台跳过）和前端 `125/125`，生成 545 项 manifest，SHA-256 为 `e998cb0363533e4913a12d75d318de9fb8b688a2a1ce44b0161224530471d3d4`。稳定服务 Job `40249` 运行于 `P107-A100/anode16:18731`，4090 内部转发已切换到 `127.0.0.1:18738`，公网与 Operator 入口均返回新 Job 和提交。
- 成功链工作流 `4b566547-961b-4e10-a8d0-99431f2e2229` 已全部验收：Relax Job `40212`、SCF Job `40250`、BAND Job `40251`、DOS Job `40252` 均为 `COMPLETED/0:0` 且科学验收通过；页面同时显示四个独立 attempt 目录、资源耗时和固定输出哈希。
- 首次固定失败链创建作业 `40253` 为 `FAILED/1:0`，唯一原因是 `stage7-acceptance.py` 以发布内绝对路径执行时没有将 `source/backend` 加入模块搜索路径，在导入 `competition_runtime` 时立即终止。该作业没有创建工作流或提交 VASP 作业，不得作为受控不收敛证据。
- `codex/107cup-stage7-acceptance-import-fix` 已用部署契约先 RED 后 GREEN 固定 `PYTHONPATH="$release/source/backend"` 且确保在 Python 启动前生效；完整 Stage 7 后端回归 `438/438` 通过，23 项仅因 Windows/POSIX 条件跳过，Bash 语法与 `git diff --check` 通过。修复合并、在 107 重建并完成 `scf_nonconvergence_v1` 真实失败链前，阶段 7 仍为 `PARTIAL`。
- acceptance import 修复 PR #39 已合并为 `e3ea99c7c8eff76c37c7fc2bda4b205d5e9a4501`。构建 Job `40259` 以 `COMPLETED/0:0` 结束，通过后端 `440/440`（另 4 项平台跳过）和前端 `125/125`，发布 manifest 含 `545` 项，SHA-256 为 `461b87da725b038c1a8567052b7baf55bcf7eb60ab601cbc381dbbda9acdf490`。稳定服务 Job `40262` 运行于 `P107-A100/anode17:18731`，4090 内部转发为 `127.0.0.1:18739`，公网、Dashboard、live 和 ready 均返回该新服务；旧 Job `40249` 和旧转发 `18738` 已核对后停止。
- 固定失败链创建器 Job `40263` 以 `COMPLETED/0:0` 结束，创建工作流 `db9c793d-cf8f-4207-823b-5943d825f21d`。Relax attempt `2f5a7850-e3c3-4ffe-b2ab-fdaacf0562b8`、Job `40264` 通过科学验收；SCF attempt `2f3080ae-b445-4575-975a-e85cccbeafc9`、Job `40265` 在 Slurm 层为 `COMPLETED/0:0`，科学状态精确为 `scientific_failed/electronic_not_converged`。BAND/DOS 没有 attempt、目录或 Job ID，但事务回滚使其暂时仍显示 `waiting`，工作流顶层仍显示 `running`。
- 诊断 Job `40269` 因诊断包装未设置前端路径，在业务诊断前失败且未修改工作流；诊断 Job `40270` 保留了真实 traceback：终态聚合同时创建 BAND 和 DOS 的 `workflow_step_blocked` 事件时触发 `UNIQUE constraint failed: workflow_events.workflow_id, workflow_events.sequence`。生产 `SessionLocal` 使用 `autoflush=False`，旧 `_next_event_sequence()` 只查询数据库，两个尚未 flush 的事件因而都取得 sequence `16`，事务整体回滚。
- 事件序列修复在 `codex/107cup-stage7-event-sequence` 将协调器测试会话改为与生产一致的 `autoflush=False`，并令 `_next_event_sequence()` 同时考虑 `session.new` 中同一工作流的待写事件。目标测试先 RED 后 GREEN，协调器套件 `40/40`、Stage 7 本地完整后端回归 `440/440` 通过，25 项仅因 Windows/POSIX 条件跳过；前端 `125/125` 和 Bash 语法检查亦通过。稳定 `service.slurm` 同时固定到 `P107-A100/qos_p107-a100`，避免长期网页服务再次占用 VASP runner 的 RTX5090 QOS；VASP runner 保持 RTX5090 不变。该修复合并、重建和现有失败链真实收敛前，阶段 7 继续为 `PARTIAL`。
- 事件序列修复 PR #40 已合并为 `e58b769c435da7eaf9c6a9e672a3f4f99ab6401f`。构建 Job `40272` 在 `P107-RTX5090/anode02` 以 `COMPLETED/0:0` 结束，通过后端 `440/440`（另 4 项平台跳过）、前端 `125/125` 和 1857 模块构建；新 release manifest 含 545 项，SHA-256 为 `0b006c6e0b7dbb1dbcfefcb2da048be704ff532cbddd8332ee7c42a02fe90373`。
- 新稳定服务 Job `40273` 运行于 `P107-A100/anode16:18731`；4090 内部转发、Nginx 和 Windows Operator 隧道分别切换到 `18740`、公网 `18733` 和本地 `21763`，三处 live/ready 均返回 Job `40273` 与提交 `e58b769...`。新入口验证后，旧服务 Job `40262` 与旧转发 `18739` 已核对归属并停止。
- 短时只读核验 Job `40274` 在 `anode16` 以 `COMPLETED/0:0` 结束：SQLite 完整性为 `ok`，失败 workflow 顶层为 `failed`，四步为 `succeeded/scientific_failed/blocked/blocked`，事件序号连续唯一 `1-18`，阻断事件为 `16/17`；attempt 表和目录恰有 Relax/SCF 两项，Job ID 恰为 `40264/40265`，BAND/DOS 零 attempt、零目录和零 Job ID。
- Demo Viewer 浏览器验收与数据库、目录和调度证据一致：Dashboard 为 2 个工作流、0 个运行中、1 个成功和 1 个需关注；失败详情明确显示 SCF `electronic_not_converged`、BAND/DOS 已阻断且 Attempt 为 0，Viewer 命令禁用。完整证据见 `docs/107cup/stage7-vasp-evidence.md`。阶段 7 至此改为 `DONE`，阶段 8 继续为 `PENDING`。
- Stage 8 结果服务 PR #42 已合并，独立验收注册修复 PR #43 和 ASE CIF 二进制缓冲区修复 PR #44 也已合并；功能验收和运行 release 固定为 `db05369fe3d0b86844d1242d5ec7a37195cf37e4`。失败 Job `40304` 在解析前因模型未注册终止；失败 Job `40306` 在真实结果和图已解析后因 CIF 文本缓冲区终止。两者均未重跑 VASP、未修改 Stage 7 工作流。
- 最终构建 Job `40307` 在 `P107-RTX5090/anode02` 以 `COMPLETED/0:0` 结束：后端 `457/457`（另有 4 项平台跳过）、前端 `125/125`、Vite `1857` 模块和 `560` 项 release manifest 通过；manifest SHA-256 为 `e12ad90ba9bb8e4af00c90926bf9ba834267828db9fafde84e1fb7b0139a4007`。
- 最终只读验收 Job `40308` 在 `P107-A100/anode16` 以 `COMPLETED/0:0` 结束并输出 `STAGE8_ACCEPTANCE_OK`。成功工作流带隙为 `1.6919 eV`、SCF 总能为 `-21.85260744 eV`；CIF、POSCAR、BAND 数据、DOS ZIP、成功证据包和失败证据包均生成固定 SHA-256，原始证据位于 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage8/acceptance-40308`，清单文件自身 SHA-256 为 `5b2d2caa25162d512baeb3e0e9b6de5b32502ad98fe1642e93f4495ac77448a4`。
- 新稳定服务 Job `40309` 正在 `P107-A100/anode19:18731` 运行 `db05369...`；4090 `18740`、公网 `222.195.94.37:18733` 和 Windows `127.0.0.1:21763` 的 `live/ready` 均返回同一 Job、commit 和 manifest。Chrome 登录态控制当前未能建立，因此真实结果列表、成功/失败详情、VASP 数据库和浏览器下载尚未完成人工验收；旧 Job `40273` 与临时 `18741` 转发继续作为回滚路径保留。完整证据见 `docs/107cup/stage8-results-evidence.md`，Stage 8 暂为 `PARTIAL`。
- 证据 PR #45 已合并为 `d32aafd57a8a5032d52c1edab81e0802e332a967`；Windows 本地 `main`、Gitea `main` 和 107 只读 checkout 已同步到该提交且工作树干净。文档合并不改变运行中的 `db05369...` 不可变 release。
- PR #46 将源码提交和运行 release 的来源分开记录；PR #47 补齐四步资源、输出 SHA-256 并把 MoS2 正确显示为二维结构；PR #48 在成功和失败结果页增加受工件白名单控制的证据包下载。PR #48 合并提交为 `6242132c30e8772288e31d9fb5eec930d2f44962`。
- 最终构建 Job `40831` 在 `P107-RTX5090/anode01` 以 `COMPLETED/0:0` 结束：后端 `458/458`（另有 4 项平台跳过）、前端 `126/126`、Vite `1857` 模块和 `561` 项 release manifest 通过；manifest SHA-256 为 `627b8c0409758e7226b58d5ba198fbc6f69f3140ab799ea3273b0110ca072e8c`。
- 最终服务 Job `40832` 运行于 `P107-A100/anode18:18731`，4090 正式转发使用节点地址 `11.11.10.18`。4090 内部、Windows `127.0.0.1:21763` 和公网 `222.195.94.37:18733` 的 live/ready 与结果页均返回该 Job 或 HTTP `200`。
- 用户在登录浏览器中确认结果列表、成功结果结构/BAND/DOS、失败结果、VASP 只读数据库和 CIF、POSCAR、BAND、DOS、证据包五种下载均正常。该人工确认与 Job `40308` 的 Viewer/Operator 字节级下载验收共同关闭浏览器门禁。
- 旧 Job `40273/40309/40786` 经用户、作业名、命令和日志路径归属核对后受控停止，三者均显示 `CANCELLED`；临时 `18741 -> anode19:18731` 已撤销。清理后仅保留正式 `18740`，三处正式入口仍返回 Job `40832`。
- Stage 8 至此为 `DONE`。没有重跑 VASP，也没有加入 Agent、机器学习、任意材料或任意命令功能；下一阶段按阶段 9 的恢复、安全和回归范围另行执行。

### 17.9 Stage 9 实施启动

- 从 `origin/main` 提交 `027c10f39f93e174c0ff2871d911f18b70116f0d` 创建 `codex/107cup-stage9-recovery-security`，正式 Job `40832`、正式 SQLite、正式 `current` 和 Stage 7/8 证据均未用于故障注入。
- 修正 Slurm 暂时不可用时覆盖可信状态的问题：普通失联保留最后 `queued/running`，记录固定首次 `stale_since` 并停止推进；作业身份不匹配仍降为 `unknown`。
- 新增 `test_competition_recovery.py`、`test_competition_security.py` 和 `competitionWorkflowE2E.test.mjs`，覆盖重启对账、数据库失败、取消竞态、网关错误目标、回滚不可变、路径/符号链接/注入、超大日志、非法文件名和非归属作业拒绝。
- 强化 `verify-runtime.sh`：所有调度和 HTTP 查询均有超时，精确核对 Job、节点、commit、manifest、release/data mode、SQLite 完整性和登录节点进程；配置公开入口时若目标不一致则失败关闭且不自动切换。
- 隔离操作、六层测试和证据要求见 `docs/107cup/recovery-runbook.md`。当前仅完成第一批本地聚焦测试，Stage 9 保持 `PARTIAL`，不得提前记录为完成。
- 功能 PR #50 已合并，功能提交为 `7a2c2d62f7368436a9c1f03d9df9ea044d41d011`，合并提交为 `551ba97fbfca3093c19ef4e98e636bcaa9b88fef`。107 构建 Job `40860` 在 `P107-RTX5090/anode01` 通过后端 `470/470`（另有 4 项环境跳过）、前端 `129/129` 和 Vite 生产构建；release manifest SHA-256 为 `163b52ad998f947f575589df07e1bafa36423e122e3eab00ba2008e0d031a58d`。
- Job `40910` 生成正式状态前快照；隔离回滚 Job `40911` 在 `anode17:18732` 启动旧 release `6242132...` 并完成独立 SQLite 迁移、live/ready 和受控关闭；Job `40913` 的后快照输出 `stable state matches before snapshot`。正式 `current` 和两库哈希均未改变。
- Job `40916` 对 Stage 7/8 固定成功/失败工作流进行只读复核并输出 `STAGE8_ACCEPTANCE_OK`，没有创建 VASP 作业或修改历史 attempt。最终快照 Job `40923` 的运行时终态为 `COMPLETED/0:0`；平台随后已清除短作业的 `scontrol/sacct` 记录，该限制与原始日志一并保留。
- 新服务 Job `40917` 运行于 `P107-A100/anode17:18731`。4090 `18740`、Windows `127.0.0.1:21763` 和公网 `222.195.94.37:18733` 的 live/ready 均返回 Job `40917`、提交 `551ba97...` 和同一 manifest；旧 Job `40832` 经归属核对后停止为 `CANCELLED/0:15`。
- 隔离 Playwright Viewer 会话以零控制台错误通过只读验收：新建、取消、重试均禁用；成功工作流显示四个 Job、日志、结构、BAND/DOS；失败工作流保持 SCF `electronic_not_converged` 与 BAND/DOS 零 attempt；VASP 数据库显示两条真实记录。
- 验收证据 PR #51 记录完整证据于 `docs/107cup/stage9-recovery-security-evidence.md`。Stage 9 至此为 `DONE`，Stage 3 仍因服务和转发自动恢复未实现而保持 `PARTIAL`；下一阶段进入比赛交付验收。

### 17.10 Stage 3 自动恢复补全启动

- 从 PR #51 合并提交 `6f980311dbb32bfe208e414847ae8a87d196f03f` 创建 `codex/107cup-stage3-auto-recovery`，只补网页服务和 4090 正式转发恢复，不改变工作流、VASP、结果解析或数据库模型。
- 107 端恢复状态机使用共享文件锁和原子 JSON：固定归属服务消失时只保留一个候选 Job，失败后 300 秒冷却，最多三次；调度不可用、归属不匹配、状态损坏和重试耗尽全部阻断，不调用 `scancel`。
- `service.slurm` 改为 Uvicorn 通过本机 live/ready 后才发布 `service-state.json`，旧六项 runtime 文件继续同步；收到 TERM/INT 时由批作业包装器等待 Uvicorn 完整退出。
- 4090 用户 cron 每分钟执行一次短命令，先用 `18742` 验证候选身份，再切换 `18740`；失败时保留或恢复旧 forward。`maintenance` 普通文件允许 Operator 暂停自动恢复，便于受控停服验收。
- SSH ControlMaster 失效时状态固定为 `ssh_authentication_required`，必须人工二次验证；cron 不保存验证码、密码或私钥内容。安装、检查、停止和恢复步骤见 `docs/107cup/service-recovery-runbook.md`。
- 当前仅完成本地 TDD 第一轮；正式 Job `40917`、4090 cron、现有 forward、正式 SQLite 和 `current` 尚未修改，Stage 3 保持 `PARTIAL`。

### 17.11 Stage 3 首次正式构建失败

- PR #52 已将自动恢复实现合并到 `main`，合并提交为 `3310972b93e58a3627605c6bcc2ce225db412fa2`；107 checkout 已同步到该固定提交。
- 发布前快照 Job `41038` 为 `COMPLETED/0:0`，证据保存在 `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/3310972b93e58a3627605c6bcc2ce225db412fa2/before-41038`。
- 正式构建 Job `41039` 在 `anode01` 运行 485 项后端测试时以 `FAILED/1:0` 结束；唯一失败为 `RuntimeVerifierExecutionTests.test_gateway_identity_match_passes_and_old_job_target_fails_closed`。根因是既有 runtime verifier 执行夹具只生成旧 `service-*` 文件，没有生成 PR #52 新增且校验器强制要求的 `service-state.json`。
- 失败构建没有切换 `current`；稳定发布仍为 `551ba97...`，服务 Job `40917` 仍在 `anode17` 健康运行。4090 cron 和正式转发均未修改。
- 修复范围仅限为该执行夹具生成与旧字段、live 身份及 release manifest 一致的 `service-state.json`。热修复通过独立 PR 合并并在 107 重新完成正式构建前，Stage 3 继续保持 `PARTIAL`。
- Windows 热修复定向门禁通过 `49` 项，另有 `14` 项按 POSIX 条件跳过；其中本次修复的 runtime verifier 执行用例必须由 107 Linux 正式构建给出 GREEN 证据，不能用 Windows skip 替代。

### 17.12 Stage 3 自动恢复补全完成

- 热修复经 PR #53 合并为 `e565851ff3ac67d8c143331b4dee175d82b6d04c`。前快照 Job `41041`、正式构建 Job `41042` 和恢复后快照 Job `41045` 全部生成自校验清单；构建通过后端 `485` 项（4 项平台 skip）、前端 `129/129` 和 Vite `1857` 模块构建。
- 4090 安装器收养旧 Job `40917` 后只增加一个项目 cron 标记块，保留全部既有 cron。Job `41043` 在 `anode16` 原子发布健康状态并通过 `18742` 先验探测切换正式 `18740`；旧 Job `40917` 经归属核对后停止。
- maintenance 验收中停止 Job `41043` 后，计算节点端口连接失败且 4090/公网返回 `502`，没有回退到原 4090 LMateLab。移除 maintenance 后只提交 Job `41044`，三层入口最终返回同一 Job、node、commit 和 manifest。
- 停服前后两库 SHA-256 完全一致、完整性均为 `ok`；Stage 7/8 既有证据 manifest 原地复核通过，没有运行 VASP。登录节点无 LMateLab 常驻进程；ControlMaster 真实失效仍必须人工二次验证。
- 完整证据见 `docs/107cup/stage3-service-recovery-evidence.md`。Stage 3 更新为 `DONE`。

### 17.13 Stage 10 交付验收启动

- PR #55 已将 Stage 10 交付合同、计算节点只读验收入口、部署/溯源/演示/最终验收文档和确定性 SHA-256 清单合并为 `db03e360b450b41f483fa98e62157ec6c993f6ba`。
- 发布前快照 Job `41063` 完成两套正式 SQLite 完整性、服务 Job `41044` 健康状态和证据清单核对；证据位于 `evidence/previews/db03e360b450b41f483fa98e62157ec6c993f6ba/before-41063`。
- 首次正式构建 Job `41064` 在 `P107-RTX5090/anode01` 运行后端 `489` 项，结果为 `1 failure + 4 skipped`。唯一失败是 Windows 工作树中的既有 `implementation-plan.md` 使用 CRLF，而 Git/107 检出使用 LF，导致仓库交付清单哈希跨平台不一致。构建在前端和 release 生成前失败，稳定 `current` 仍为 `e565851...`，服务仍为 Job `41044/anode16`，数据库和固定 VASP 工作流未修改。
- 热修复范围仅为固定 UTF-8 文本在计算交付清单前规范化为 LF，并由同一合同测试复核；重新合并、在 107 Slurm 构建通过、部署新服务、执行 Stage 10 只读 Job 和浏览器验收前，Stage 10 保持 `PARTIAL`。
- PR #56 已将清单换行规范化修复合并为 `4e79c07b198b34e54be332638868e82249357d1f`。发布前快照 Job `41138` 通过；正式构建 Job `41139` 通过后端 `489/489`（另有 4 项环境跳过）、前端 `129/129`、Vite `1857` 个模块和 `595` 项 release manifest，release manifest SHA-256 为 `33891563e9e69232b60661176cf132c9e9f4524a88515a61693f59e1d841cac3`。
- 新候选服务 Job `41142` 正在 `P107-A100/anode18:18731` 运行，使用固定内部地址 `11.11.10.18` 探测时 live/ready 均返回该 Job、固定提交和 manifest；`service-state.json` 已原子发布相同身份。107 登录节点不能解析 `anode18`，旧恢复器因此报告 `service_not_ready`，4090 relay 正确拒绝切换，Windows 与公网入口继续返回旧 Job `41044/anode16`。两项服务都未停止。
- 节点地址修复在 `codex/107cup-stage10-node-address` 按 RED/GREEN 开发：只接受 `anode01..anode26` 并映射为 `11.11.10.1..26`，连接探测使用内部 IP，健康身份仍核对原节点名；同一规则进入服务恢复器、`verify-runtime.sh` 和 Stage 10 Slurm harness，并纳入确定性交付清单。本地恢复/relay/运行时/Stage 10 聚焦测试 `40/40`、Python 编译、Bash/Slurm 语法和 `git diff --check` 通过。修复尚未合并或在 107 重建，Stage 10 继续为 `PARTIAL`。

### 17.14 Stage 10 正式发布、机器门禁与 Viewer 复跑

- PR #57 已将节点内部地址修复合并为 `4f81d727a9dc86f7a5fc1591e2831abb80b89d03`。发布前快照 Job `41477`、正式构建 Job `41478/anode01`、服务 Job `41479/anode19`、发布后快照 Job `41481` 和只读验收 Job `41482/anode16` 均完成。构建通过后端 `492/492`（另有 4 项环境跳过）、前端 `129/129` 和 595 项 release manifest，自检后的 manifest SHA-256 为 `46097b601f16d0c08b9c2afaf6c18eb465259d67b00809df6f129f5ff7c41489`。
- 4090 relay 已切换为 `11.11.10.19:18731`；107、4090 内部入口、Windows `127.0.0.1:21763` 和公网 `222.195.94.37:18733` 返回同一 Job、node、commit 和 manifest。旧 Job `41044/41142` 在严格核对归属后受控停止，旧端口不可达，新服务保持健康。
- Job `41482` 日志结尾为 `STAGE10_ACCEPTANCE_OK`。证据 manifest SHA-256 为 `0292213052f55fd72cf27c72c224ff914646dd3491435050de99c6b5ccccb48e`，摘要 SHA-256 为 `d1956ad5fc68cd830fe87f7c71b0fa1ba8c924dede1e2447bbc2789ae3fca52f`。两套 SQLite 前后哈希和完整性均未改变，固定成功/失败证据包哈希未变，没有提交新 VASP。
- 全新 Viewer 会话完成 `1440x900` 和 `390x844` 的 Dashboard、工作流、成功/失败结果、新建计算只读门禁、VASP 数据库、Mo+S 周期表筛选、结构/BAND/DOS 像素和页面溢出检查。桌面与移动控制台错误均为 0；相关 GET API 均为 `200`，没有观察到意外写请求。19 张 PNG 位于私有目录 `evidence/stage10/browser-4f81d727-20260822`，截图清单 SHA-256 为 `fdd5b0c047be047e325675661001b3714bdbee976cfff7f14c86bdd899fb59c5`。
- 全新 Operator headed 会话已经通过 Windows 隧道打开登录页，但密码必须由用户现场输入，不能读取、猜测或重置。连续视频素材和三名成员独立复核也未完成，因此 Stage 10 保持 `PARTIAL`。

### 17.15 Stage 10 Operator 复跑与视频素材

- 用户在 Windows 隧道入口现场登录后，页面确认身份为“107杯管理员 / 操作员”。全新 Operator 桌面会话以固定发布 `4f81d727...` 复跑 Dashboard、工作流成功/失败证据、结果、结构、BAND、DOS、新建计算和 VASP 数据库 Mo+S 精确筛选；控制台错误与警告均为 0，7 个业务请求全部为成功 GET，没有任何意外写请求。
- 连续录屏时长 `422.04` 秒，13 张 PNG、1 个 WebM、`operator-manifest.sha256` 和 `operator-summary.json` 已上传到私有目录 `evidence/stage10/browser-4f81d727-20260822`，权限均为 `0600`。Operator 清单 SHA-256 为 `6edcebe75ebb995e5534234809acd8c402e47a4b7ce47d8f1f4e0a14205d1596`，摘要 SHA-256 为 `40bf967125c6acd89f6cdd7267a4d0b1f63e38fe020352817b7c7dda5500249e`，视频 SHA-256 为 `e752d36a311a1a31e56ce42da588db2e64e9a634ac51f1cb1c13fd8c39cec2ab`。
- 结构/BAND/DOS 非白像素比例为 `0.006547/0.027192/0.083188`。录屏从已登录工作台开始，经抽帧检查没有密码、token、JWT、Cookie 或 SSH 信息；临时认证会话和抽帧接触表已删除。没有提交、取消、重试、Slurm 或 VASP 操作。
- 发现终态工作流仍显示可用的“取消工作流”按钮。源码和后端测试确认没有活动 attempt 时协调器固定返回 `workflow_not_cancellable` 且不调用 `scancel`；本次没有点击或发送取消 POST。该项记录为不突破安全边界的前端 UX 后续项，不改写固定发布证据。
- 对固定发布 `4f81d727...`，Viewer 与 Operator 浏览器门禁和连续视频至此完成，当时唯一剩余 DONE 门禁是三名成员独立复核。后续公开首页发布改变了固定 commit，因此当前发布仍需重新完成认证态 Viewer/Operator 复跑，三名成员门禁也继续保留。

### 17.16 107 杯公开首页增量

- PR #60 把公开根路径 `/` 从登录重定向改为 107 杯项目首页，`/login` 保持为认证入口；登录页导航同步指向首页的平台、工作流和证据区段。首页只介绍固定 MoS2、`relax -> SCF -> BAND -> DOS`、Slurm 归属与结构/BAND/DOS 证据，不引入 Agent、机器学习、QE/EPW、任意材料或任意命令。
- PR #60 合并提交 `4422dbcf87d813360102a8ee49b986b3a2754078` 由 Slurm Job `41560/anode01` 构建。平台记账已过期，但构建日志明确通过后端 `492/492`（另有 4 项环境跳过）、前端 `132/132`、Vite `1861` 个模块和 `606` 项 release manifest；`current` 原子指向该 release，manifest SHA-256 为 `3877590fbd6f3b58eb3c8c61824d82522119175d5cc3884123ee1b76b6ed8ae5`。
- 服务 Job `41561/anode18` 通过本机 live/ready 后发布状态，4090 relay 与公网入口切换到新身份；旧 Job `41479` 经完整归属核对后受控停止，旧节点端口不可达。只读 Job `41563/anode16` 输出 `STAGE10_ACCEPTANCE_OK`，数据库完整性、固定成功/失败工作流及证据包哈希未变，没有提交 VASP。
- 公网首页在 `1440x900` 与 `390x844` 验证两张背景均返回 `200`、页面零横向溢出、控制台错误为 0，首页与登录页双向跳转通过。既有 Viewer/Operator 全流程截图和 `422.04` 秒视频继续严格绑定 `4f81d727...`，因此当前发布的全新认证态复跑仍待完成，Stage 10 保持 `PARTIAL`。

### 17.17 107 杯四季首页增量

- 分支 `codex/107cup-four-seasons-home` 按用户提供顺序把四张校园图映射为春、夏、秋、冬：春季樱花用于首屏，夏季主楼用于平台主线，秋季湖景用于四步工作流，冬季雪景用于验收证据。四段均为全宽背景和受控深色遮罩，底部登录入口保持独立简洁区段。
- 改动不增加业务能力或路由，不修改 MoS2、VASP、Slurm 和证据链文案。新增夏、冬 WebP 分别为 `191618` 与 `213358` 字节，避免直接发布原始 PNG。
- 本地 TDD 先由缺失资产和样式得到 `2` 项预期失败，随后聚焦合同 `8/8`、前端全量 `132/132`、定向 ESLint 和 107 Cup live Vite 构建（`1863` 个模块）通过。Playwright 在 `1440x900` 与 `390x844` 确认四张背景全部加载、页面零横向溢出、控制台错误为 0；截图位于未跟踪目录 `output/playwright/four-seasons-home/`。
- PR #61 已合并为 `2bf0a0bb98246d1f627e3f131102f033cf3c54df`。Slurm Job `41569/anode01` 通过后端 `492/492`（另有 4 项环境跳过）、前端 `132/132`、Vite `1863` 个模块和 `610` 项 release manifest，`current` 原子指向新 release，manifest SHA-256 为 `619ba7f25c07faa0a7add43c6d5a87706468eab9ea1554e18f60c15c39dd98c5`。
- 服务 Job `41570/anode16` 在排除旧节点 `anode18` 后提交，通过本机 live/ready 才发布状态；4090 通过临时端口核对身份后切换 relay，旧 Job `41561` 在完整归属核对后停止，旧端口不可达。
- Stage 10 只读 Job `41571/anode16` 为 `COMPLETED/0:0` 且输出 `STAGE10_ACCEPTANCE_OK`；证据 manifest 和摘要 SHA-256 分别为 `46a9c139a63918edfd5b73539a7447eed1e6642e3cbccdb3d017189d2a4cd29f` 与 `acb9c834f45e6886ee289e87b533c43a1dca560027289463f59021f46c2fd2dd`。数据库完整性、固定成功/失败工作流和证据包哈希未变，没有提交 VASP。
- 公网入口在 `1440x900` 与 `390x844` 确认四张独立 WebP 全部返回 `200`、页面零横向溢出、控制台零错误/警告，首页与登录页双向跳转通过。当前认证态 Viewer/Operator 全流程与视频仍待重做，三名成员门禁也仍保留，Stage 10 继续为 `PARTIAL`。

### 17.18 四季首页画幅与排版整改发布

- 分支 `codex/107cup-home-layout-polish` 针对四季首页的图片裁切、区段高度不一致、内容轴线错位和底部重复登录 CTA 做单一范围整改，不增加路由、业务能力或计算功能。
- 四个桌面区段统一为 `3:2` 画幅，以真实 `<img>` 和 `object-fit: contain` 完整显示原图；五个主要内容块统一使用 `1180px` 居中内容轴。秋季工作流固定为标题在上、四步列表在下，避免共享 flex 布局把两者横向拆开。
- `820px` 以下将每张图放入统一 `3:2` 图片带，文案排列在图片下方；删除底部“进入计算工作台 / 登录平台”区段，以紧凑深色页脚直接收尾。
- TDD 已先复现缺少完整图片层、画幅不统一、重复 CTA 和秋季横向错排，修复后首页合同 `3/3`、前端全量 `132/132`、Stage 10 交付合同 `5/5`、定向 ESLint 和本地 107 Cup Vite 构建（`1863` 个模块）通过。
- PR #63 已把功能提交 `44ea4ff55b1c772e56d37ede5c5b936b46800c96` 合并为 `565edfda8d36018e4516e2d22e27be351d9f0a41`。发布前快照 Job `41645` 的 manifest SHA-256 为 `55aeec7bf48b963a0c491c91f16b21467317aa09b373fcc9fbd9f2d3cf48b47e`；正式构建 Job `41646/anode01` 通过后端 `492/492`（另有 4 项环境跳过）、前端 `132/132`、Vite `1863` 个模块和 `609` 项 release manifest，自检后的 release manifest SHA-256 为 `57e777bf8f3ac94ae6c6b0816b00afe5175016f4f5b66f6905d57948c22ea78b`。
- 新服务 Job `41648/anode18:18731` 健康后发布运行身份，4090 relay 切换到 `11.11.10.18:18731`。旧 Job `41570` 经归属核对后受控停止，旧端口实测不可达；公网 `live/ready` 返回新 commit、Job、node 和 manifest。
- Stage 10 只读 Job `41649/anode16` 输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节；证据 manifest 和摘要 SHA-256 分别为 `5109b681cef330c2e0fc26ccb6db2e50495739c9c346815ff14257117b734b52` 与 `d6dd822b37420695ae108c5a35689b54bc21206e5ea1de9f71d96f0417e8b768`。固定成功/失败工作流与证据包哈希未变，没有提交 VASP。
- 发布后快照 Job `41650` 的 manifest SHA-256 为 `39da9dc85b04811af05c792f4e92329cd0e4be35d9159efdfd028fdcc91c0da1`；两套正式 SQLite 完整性均为 `ok`，前后 SHA-256 保持 `29cf102884c1b36f6cef8c251bb569aa6cebd837b4d3957989a6efaa8a96ddbc` 与 `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969`。
- 公网 Playwright 在 `2560x1440` 和 `1440x900` 验证四段高度分别统一为 `1706.65625px` 和 `960px`，五个内容块左边缘分别统一为 `690px` 和 `130px`；`390x844` 的四个图片带均为 `260px`。四张图片固有尺寸非零且 `object-fit: contain` 生效，三种视口横向溢出、控制台错误/警告和重复 CTA 数量均为 `0`。
- 当前发布已完成公开首页、Slurm 构建、服务切换和只读机器门禁，但尚未针对 `565edfda...` 重做全新认证态 Viewer/Operator 全流程与视频；三名成员独立复核也未完成，因此 Stage 10 保持 `PARTIAL`。

### 17.19 四季首页可读性与平台定位整改候选

- 分支 `codex/107cup-home-readability` 只调整公开首页文案、文字层级和摄影背景上的可读性，不修改认证页、工作台、数据库、Slurm/VASP 适配器、固定成功/失败工作流或既有证据。
- 公开定位由“固定 MoS2 / 二维材料计算”收敛为“面向材料计算的可追溯 VASP 工作流平台”，并把平台主线表述为从结构优化到电子结构分析。首页不再出现 `MoS2`，避免把一个已验收算例误解为平台的唯一适用对象；同时不宣称任意材料、任意命令、QE/EPW、高通量、Agent 或机器学习能力。
- 四个季节区段统一增强信息层级：桌面首屏主标题为 `80px`、平台标题为 `48px`、正文为 `16-20px`，导航为 `16px`；摄影背景使用更强的实色深色遮罩、白色高对比文字和受控阴影。`820px` 以下继续使用完整 `3:2` 图片带与独立深色正文区，避免文字压住校园照片。
- 本地首页合同 `4/4`、前端全量 `143/143`、定向 ESLint 和 107 Cup Vite 构建（`1867` 个模块）已通过。Playwright 在 `2560x1440`、`1440x900` 和 `390x844` 完成视觉复核：四张图片均加载、公开正文不含 `MoS2`、页面横向溢出和控制台错误/警告均为 `0`；手机端四个区段 `scrollHeight` 与 `clientHeight` 一致，没有内容裁切。
- 本节当前仅记录本地候选。PR 合并、107 Slurm 构建、服务切换和 Stage 10 只读验收完成前，线上发布仍为 `565edfda...`；本次改动不把 Stage 7 的固定 MoS2 真实验收外推为其他材料已经完成真实 VASP 验收，Stage 10 继续为 `PARTIAL`。

### 17.20 四季首页可读性整改发布与验收

- PR #66 已将功能提交 `7c282730e148d4b205deab6c65a8444491dd5680` 合并为 `4f652db91bdfb1dc28fea0daed4d12b0d9d57215`。发布前快照 Job `41670` 完成自校验，manifest SHA-256 为 `b484d9d7d99ab8f96db6fabb1b77ae1d84c65526572b4134f8c848279c5a95c0`。
- 正式构建 Job `41672/anode01` 后端共运行 `494` 项并为 `OK`（其中 4 项环境跳过），前端 `143/143`，Vite 转换 `1867` 个模块；`current` 原子指向新 release，`640` 项 release manifest 自校验通过，SHA-256 为 `616b86b1460debd7570d6ba59ccfd19b68d103019fa99c5049ef7e021d55d9ca`。
- 候选服务 Job `41673/anode16:18731` 在排除旧节点 `anode18` 后提交，本机 live/ready 和身份一致后由 4090 临时探测并切换正式 relay。Windows Operator、公网和 4090 内部入口均返回新 Job、node、commit 与 manifest；旧 Job `41648/anode18` 经用户、名称、账号、分区、命令和专属日志路径核对后停止，Uvicorn 完成正常 shutdown，旧节点端口不可达。
- Stage 10 只读 Job `41676/anode16` 输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节；证据 manifest 和摘要 SHA-256 分别为 `488e809e2b43dee581c34c73182b1cbf2a4954e235a4dfbdd376936db34a96c7` 与 `ff92d05d388db5f9a992e0805ba45413a354ce5484daf14567bd8ec4477712b7`。数据库完整性为 `ok`，固定成功/失败工作流和证据包哈希未变，没有提交 VASP。
- 公网 Playwright 在 `1440x900` 和 `390x844` 确认四图全部加载、公开正文不含 `MoS2`、页面无横向溢出或内容裁切、控制台错误/警告为 0；首页进入登录页和返回首页均实际点击通过。桌面首屏摘要和区段标题计算字号分别为 `20px` 与 `48px`。
- 发布后 Job `41680` 误用了要求 `current` 和服务身份前后不变的预览快照合同，因此在比较旧、新 release 的 `current-target.txt` 时失败，且未生成后快照 manifest；本项保留为失败证据，不能写成成功。两套 SQLite 前后完整性均为 `ok`，`digests.db` 哈希不变；`eln.db` 因此前已合并 PR #65 的 Agent 表迁移从 `29cf1028...` 变为 `018bd0e1...`，不是首页写入。
- 当前公开首页、Slurm 构建、服务切换和只读机器门禁均已完成。全新认证态 Viewer/Operator 全流程与连续视频仍需针对 `4f652db9...` 重做，三名成员独立复核也未完成，因此 Stage 10 继续为 `PARTIAL`。

### 17.21 认证态科研工作台视觉统一发布

- 分支 `codex/107cup-workbench-visual-polish` 只统一登录后的工作台视觉，不修改公开四季首页、计算流程、API、数据库、角色权限、Slurm/VASP 适配器或固定成功/失败证据。公开首页继续使用校园摄影；工作台明确不使用图片背景，避免结构、表格、日志和 BAND/DOS 图受到干扰。
- 共享应用外壳新增中性灰绿画布、低对比度技术网格、增强的顶栏边界和带左侧色标的侧栏选中态。页面标题、筛选区、配置区、证据区和数据库检查器使用同一边界与文字层级；状态概览分别使用蓝、青绿、绿色和琥珀色，避免界面只有一种蓝色。
- 同一视觉合同覆盖工作台、新建计算、工作流列表与详情、结果列表与详情、VASP 数据库，以及功能开关启用时的 Qoder Agent。宽表继续只在自身边界内滚动，结构查看器、周期表、BAND/DOS 组件和 Viewer/Operator 门禁不变。
- 本地前端全量测试 `144/144`、107 Cup Vite 构建（`1867` 个模块）和 `git diff --check` 通过。新增只读 Playwright 验收在 `1440x900`、`1024x768`、`390x844` 三个视口逐页检查 6 个入口，共生成 `18` 张未跟踪截图；页面横向溢出、图片背景、控制台错误和警告均为 `0`。
- PR #68 已合并为 `217cf255e0c1ad0090e2215b9c0a5928a0da19ca`。正式构建 Job `41712/anode01` 通过后端 `494` 项（另有 4 项环境跳过）、前端 `144/144` 和 Vite 构建，release manifest 含 `641` 项，SHA-256 为 `d2eccbbb19f9be4cc556da4816d1c24adfd4271160b9373959cb49398faf2509`。
- 候选服务 Job `41721/anode18:18731` 的 live/ready 与提交、manifest 一致后，4090 relay 完成受控切换；Windows `127.0.0.1:21763` 和公网 `222.195.94.37:18733` 均返回该身份。旧服务 Job `41673/anode16` 经用户、JobName、Command、WorkDir 和日志路径核对后受控停止为 `CANCELLED`，未触及共享账号下其他作业。
- Stage 10 只读 Job `41724/anode16` 为 `COMPLETED/0:0`，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节；证据 manifest 和摘要 SHA-256 分别为 `628e1fba86b1def08a5c50378b95a1fd8b2085e07c2410e15691b338bfa5aba0` 与 `722ab701c0720fdc684730a5d94fbbcaa0464c86e3bb4536a77e29a405897dbd`。数据库完整性为 `ok`，固定成功/失败工作流和证据包哈希未变，没有提交 VASP。
- 公网公开首页在 `1440x900` 通过生产 Playwright 复核，控制台错误和警告均为 `0`。Chrome 登录态控制未能建立，因此当前发布的全新认证态 Viewer/Operator 全流程和连续视频仍待人工复跑；三名成员独立复核也未完成，Stage 10 保持 `PARTIAL`。

### 17.22 登录后修改本人密码发布与验收

- 分支 `codex/107cup-change-password` 只增加已登录用户修改本人密码，不恢复注册、邮箱验证码或忘记密码，不增加管理员查看密码、替他人重置密码或业务写权限。Operator 与 Viewer 使用相同入口，均必须提供当前密码、新密码和确认密码，并复用 `deploy/107cup/security_policy.json` 的服务器策略。
- 登录 JWT 新增与当前 `password_hash` 绑定的 HMAC-SHA256 版本指纹；认证时用常量时间比较。密码提交成功后数据库哈希变化，所有旧 JWT（包括本次发布前不含版本指纹的 JWT）立即返回 `401`，用户必须以新密码重新登录。实现不修改数据库结构，也不在响应、日志或浏览器存储中保留密码。
- 107 杯专用后端新增精确 `POST /api/auth/change-password`，当前密码错误不写库，提交异常必须回滚且不向客户端泄露数据库细节；旧版认证 router 不挂载该路由。4090 Nginx 模板只为该路径增加精确 POST 例外，通用 `/api/` 继续仅允许 GET，Viewer 的提交、取消、重试等业务写请求仍被拒绝。
- 登录后的右上角用户菜单新增“修改密码”对话框，桌面与移动端均显示密码规则和三项密码输入。成功后清除本地全部认证状态并跳转 `/login?passwordChanged=1`，登录页显示“密码已修改，请使用新密码登录”。对话框关闭即卸载，不使用 `localStorage`、`sessionStorage` 或控制台保存表单值。
- 本地 TDD 已先得到缺少后端指纹/路由/代理和前端组件的预期失败；实现后后端认证与部署定向测试 `58` 项通过（其中 `12` 项按 Windows 非 POSIX 条件跳过），前端全量 `146/146`、新增行为测试、定向 ESLint、107 Cup live Vite 构建（`1870` 个模块）和 `git diff --check` 通过。
- PR #70 已合并为 `79e7f77312e3ceb20bce901d0be3d85d212afa2c`。正式构建 Job `43709/anode01` 为 `COMPLETED/0:0`，通过后端 `501` 项（另有 4 项环境跳过）、前端 `146/146` 和 Vite 构建；release manifest 含 `645` 项，SHA-256 为 `a83ffc9d362d2f217d66312c56cf5d7053ed670ff98e3dfa723875aa13105069`。
- 候选服务 Job `43710/anode16:18731` 通过内部 live/ready、提交/manifest 一致性和数据库完整性检查后，4090 恢复器完成临时探测与正式 relay 切换。活动 Nginx 配置保留原 IP 白名单和 `0600` 权限，新增唯一精确 `POST /api/auth/change-password` 例外并通过 `nginx -t`；未认证改密 POST 到达后端返回 `401`，同路径 GET 和其他业务 POST 均返回 `403`。Windows `127.0.0.1:21763`、4090 内部入口和公网 `222.195.94.37:18733` 返回同一新身份。
- 旧服务 Job `41721/anode18` 在用户、JobName、节点、Command 和实际 WorkDir 全部匹配后受控停止为 `CANCELLED`，旧节点端口不可达，新服务保持运行；未触及共享账号下其他作业。
- Stage 10 只读 Job `43711/anode16` 为 `COMPLETED/0:0`，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为空。数据库完整性为 `ok`，三条既有工作流与固定成功/失败证据包未变，没有提交 VASP；证据 manifest 和摘要 SHA-256 分别为 `66b04773ca4ce5fcaa8f3ae78b1482eb4b51a1eb0f5b5bd8eaacf0aa87784ca4` 与 `1f9f699c8095c67d2ed0bda868df208a8d1508e4d0124631a2ee2d3d169dcb5d`。
- 生产 Playwright 通过 Windows Operator 隧道复核公开首页和 `/login?passwordChanged=1`：`390x844` 页面无横向溢出，控制台错误/警告为 0，登录页正确显示“密码已修改，请使用新密码登录”。未使用、读取或记录真实密码；用户仍需现场完成一次真实改密、旧 JWT 拒绝和新密码重新登录验收，当前发布的全新认证态 Viewer/Operator 全流程与三名成员独立复核也仍待完成，因此 Stage 10 保持 `PARTIAL`。

### 17.23 VASP 数据库周期表居中发布与机器验收

- 分支 `codex/107cup-periodic-table-center` 只修复共享元素周期表在竞赛 VASP 数据库宽屏页面左贴边的问题，不修改元素数据、筛选语义、查询、数据库 API、角色权限或 Slurm/VASP 工作流。查询框继续按表单惯例左对齐，避免与周期表的几何中心耦合。
- 根因是共享 `.vasp-periodic-scroll` 声明了 `justify-content: safe center`，却没有建立 flex 格式化上下文；个人数据库因额外样式偶然生效，竞赛数据库没有导入该样式，因此同一组件表现不一致。共享组件现在显式使用 `display: flex`，并在 `700px` 以下恢复 `justify-content: flex-start`，保证窄屏横向滚动从 H 开始。
- TDD 先确认现有 7 项周期表测试中只有新增布局合同失败，修复后 `7/7` 通过。演示数据浏览器在 `2100px` 宽度测得周期表左右留白均为 `368.5px`，页面无横向溢出；`390x844` 下内部 `scrollWidth/clientWidth=845/330`、初始 `scrollLeft=0`、页面无横向溢出，控制台错误和警告均为 0。
- 功能提交 `26905b397b99623881c51909853b4636f5b69837` 已通过 PR #72 合并为 `8ccbc0fa9a073f29965e4ab339923658638d1750`。正式构建 Job `43725/anode01` 为 `COMPLETED/0:0`，通过后端 `501` 项（另有 4 项平台跳过）、前端 `146/146` 和 Vite `1870` 个模块构建；`current` 原子指向该 release，`645` 项 manifest 自检通过，SHA-256 为 `3ab2c2f00997bf8016883c6dad06fb86d8235a6a078291eef7ac49a8842747dd`。
- 候选服务 Job `43726/anode18:18731` 在排除旧节点 `anode16` 后提交，内部 live/ready、commit/manifest、两套 SQLite `integrity_check=ok` 和登录节点无 LMateLab 常驻进程均通过。4090 受控 relay 切换后，Windows `127.0.0.1:21763`、4090 内部入口和公网 `222.195.94.37:18733` 均返回新 Job、node、commit 和 manifest。旧 Job `43710/anode16` 经完整归属核验后受控停止，旧端口已不可达，未触及共享账号下其他作业。
- Stage 10 只读 Job `43728/anode16` 为 `COMPLETED/0:0`，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节。数据库完整性为 `ok`，三条既有工作流与固定成功/失败证据包哈希未变，没有提交 VASP；证据 manifest 和摘要 SHA-256 分别为 `08b5f0d037768fb59b489b2fdc1777ecf2f94b1cb228d1824d3b91760e1f7144` 与 `42c013108cc7a9049cb271a36874b804d544696b8b7241d987ac0369ae2497db`。
- 生产已运行与本地布局验收相同的固定前端 release。本次未读取或记录真实密码，因此不把本地演示数据截图写成全新生产认证会话；用户刷新后的生产 VASP 数据库页面、全新 Viewer/Operator 全流程和三名成员独立复核仍属人工门禁，Stage 10 保持 `PARTIAL`。

### 17.24 VASP 数据库筛选工具栏发布与机器验收

- 分支 `codex/107cup-periodic-filter-toolbar` 只调整 VASP 数据库的查询与元素筛选布局，不修改元素周期表数据、筛选语义、数据库 API、角色权限、Slurm/VASP 工作流或既有证据。共享个人数据库仍保留原“清空选择”行为。
- 竞赛 VASP 数据库在桌面端把“至少含有所选元素 / 只含所选元素”、搜索框和“重置筛选”放在周期表上方同一行；`700px` 以下改为模式与重置同处第一行、搜索框独占第二行。周期表继续在宽屏独立居中，在窄屏只于自身边界内横向滚动。
- “重置筛选”一次清空查询与所选元素，把模式恢复为 `at_least`、页码恢复为 `1`，并清除已选记录。真实浏览器交互已依次验证 `q=MoS2`、`elements=S`、`element_mode=only` 写入 URL；重置后 URL 为 `?element_mode=at_least&page=1`，搜索为空、没有已选元素、默认模式按下且重置按钮禁用。
- 本地聚焦测试 `73/73`、前端全量 `148/148`、定向 ESLint、`git diff --check` 和 107 Cup Vite 构建（`1870` 个模块）通过。Playwright 在 `2100x1200`、`1024x768` 和 `390x844` 完成布局复核，三种视口均无页面横向溢出；移动端周期表内部 `scrollWidth/clientWidth=845/331`，控制台错误和警告均为 `0`。
- PR #74 已把功能提交 `116f0222e3e8066b957b48bfdbb3af4b933ccc1b` 合并为 `b58cfe40be19fbd7543ca970a728aba89e69386b`。正式构建 Job `43736/anode01` 为 `COMPLETED/0:0`，通过后端 `501` 项（另有 4 项平台跳过）、前端 `148/148` 和 Vite `1870` 个模块构建；`current` 原子指向该 release，`645` 项 manifest 自检通过，SHA-256 为 `cd99bd2090d57974526061b34ecd06534ef1266e1ae617aab0f2c3249441bc7f`。
- 候选服务 Job `43737/anode16:18731` 在排除旧节点 `anode18` 后提交，内部 live/ready、commit/manifest 和服务状态一致后，4090 恢复器完成临时探测与正式 relay 切换。Windows `127.0.0.1:21763`、4090 内部入口和公网 `222.195.94.37:18733` 均返回新身份；旧 Job `43726/anode18` 经完整归属核验后受控停止为 `CANCELLED`，旧端口不可达，未触及共享账号下其他作业。
- Stage 10 只读 Job `43738/anode16` 为 `COMPLETED/0:0`，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节。数据库 `integrity_check=ok`，三条既有工作流与固定成功/失败证据包哈希未变，没有提交 VASP；证据 manifest 和摘要 SHA-256 分别为 `b316bdc39ee29dc62c754d5cd06836e2e7a8b34fb2f99dd700c3ddf059cb81d6` 与 `6633e7aa0b282487c4c7e6dc62112255b704fc274374ddf9566317f79b3199ae`。
- 生产运行的是已通过本地三视口布局与交互验收的同一固定前端 release。本次 Chrome 登录态控制未能建立，且未读取浏览器存储或真实密码，因此不把本地截图冒充全新生产认证会话；用户刷新后的生产 VASP 数据库页面、全新 Viewer/Operator 全流程和三名成员独立复核仍属人工门禁，Stage 10 保持 `PARTIAL`。

### 17.25 通用周期结构 POTCAR 与 BAND 路径修复

- 分支 `codex/107cup-general-material-workflow` 保留 `mos2_v1` 历史合同，为上传结构新增固定 `pbe_2d_v1`。当前范围严格限制为全周期 POSCAR/CIF、最多 `1 MiB`、`200` 原子和 `16` 种元素，以及非磁性、无 SOC、无 DFT+U、无杂化泛函的 PAW-PBE 四步基线；不开放任意模板、赝势路径、命令或 Slurm 参数。
- Stage 5 从结构解析器取得规范元素顺序，为每一步写入对应 `POTCAR.spec`。BAND 不预写固定 `KPOINTS`，只发布不可变 `BAND_PATH.policy`；attempt 从已验收 SCF 继承最终 `POSCAR` 和 `CHGCAR`。
- 计算节点 runner 先执行 VASPKIT `103`，把结构请求元素保留在 `POTCAR.spec`，把实际推荐赝势写入 `POTCAR.resolved`。随后对解析后的源执行普通文件、非符号链接、基础元素/顺序和 SHA-256 检查，并把生成 POTCAR 与按解析顺序直接拼接的 PAW-PBE 源文件逐字节比较。旧 `Mo_sv/S` 继续额外执行既有两个源哈希和合并哈希门禁。
- 通用 BAND runner 在已验收 SCF 的最终结构目录执行 VASPKIT `302`，只接受非符号链接、非空、最大 `8192` 字节且具有 `Line-mode/Reciprocal` 头的 `KPATH.in`，再发布为 `KPOINTS`，同时记录 `band-path-generator.txt`。后端验收接受 VASPKIT 1.5.1 的真实 `kx ky kz LABEL` 与兼容的 `kx ky kz ! LABEL`，并检查标签、数值有限性、分段点数和值域。
- 初次真实预检 Job `46081` 保留在 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage7/generic-vaspkit-preflight-46081`。它证明 VASPKIT 103 对结构元素 `W/S` 实际推荐 `W_sv/S`，也暴露了旧实现错误要求推荐名必须仍为 `W/S`；该失败现场不得删除。
- 修复后 Job `46090/anode01` 输出 `GENERIC_VASPKIT_PREFLIGHT_OK`，stderr 为 `0` 字节。`POTCAR.spec` 为 `W/S`，`POTCAR.resolved` 为 `W_sv/S`，真实源 SHA-256 分别为 `931c2d770f65867ef30f3db3421922900fc0890ebac5c3e12f63b6a2064023d7` 和 `0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132`；VASPKIT 302 从 WS2 六方晶格生成 `GAMMA-M-K-GAMMA`，manifest SHA-256 为 `003c2c1b55e60db99d37621ac3929bc4f9a34d611949efc30cf3bf06d27b07af9`。该作业没有 VASP 输出。
- Job `46092` 因 `sbatch --wrap` 默认 `/bin/sh` 不支持 `pipefail` 而在测试前退出；Job `46093` 随后真实暴露两项 302 元数据未使用 8 KiB 上限。两份失败日志保留。修复后的 Job `46096` 在提交 `6898739efe9aa451ffce3320962fb97c81321790` 上通过 `test_competition_vasp` 与 `test_107cup_deploy_contract` 共 `152/152`。
- 本地同时通过 Python 编译、`git diff --check` 和 WSL runner/部署合同 `46/46`。这些结果证明 103/302 与后端合同，不表示 WS2 已运行真实 VASP，也不表示该分支已经部署。
- PR #76 已把通用工作流合并为 `a498f69fa7628982bd294fd9627359ec717f8f48`。正式构建 Job `46098/anode01` 在后端白名单阶段以 `FAILED/1:0` 结束：共运行 `513` 项，结果为 `4 failures、40 errors、4 skipped`。根因是协调器旧测试夹具没有随执行范围合同补写 `structure_summary.formula`，以及 CIF 化学式沿用原子行顺序而把同一 MoS2 写成 `S2Mo`；失败构建没有生成 release、没有切换 `current`，旧 Job `43737` 保持在线。
- 修复分支 `codex/107cup-general-material-fix` 的提交 `4257c0243c097142b25b9b39848b719a4aa63f9c` 为协调器夹具补齐真实结构摘要，并保留缺失摘要时在产生 attempt/Slurm 作业前失败关闭的测试。CIF 现在按 IUPAC 元素顺序确定性分组和显示，POSCAR 上传仍保持其元素头顺序；两种格式写出的 `POTCAR.spec` 都只包含结构请求元素，不建立材料或元素白名单，实际后缀仍由计算节点 VASPKIT 103 解析。
- Slurm Job `46103/anode01` 为 `COMPLETED/0:0`，在 17 秒内通过受影响的结构、协调器、部署 runner 和清单合同 `116/116`；其中 `generic_ws2_band_generates_potcar_and_302_path_from_final_poscar` 明确验证 BAND attempt 对最终 POSCAR 执行 302。Job `46104/anode01` 为 `COMPLETED/0:0`，在 37 秒内通过正式构建使用的完整后端白名单 `514` 项，另有 4 项平台条件跳过。
- Stage 10 交付清单生成器已扩展覆盖本次通用工作流的模板、路由、服务、测试、103/302 Slurm runner 和前端入口；`artifacts/manifest.sha256` 继续按规范 LF 文本 SHA-256 确定性生成且不包含自身。
- PR #77 已把修复合并为 `6012b2bbb976a534e4ca18e93bfe1eb0a4dc6aec`。正式构建 Job `46105/anode01` 为 `COMPLETED/0:0`，耗时 97 秒；后端 `514` 项通过（另有 4 项跳过）、前端 `149/149`、Vite `1870` 个模块构建完成。release 清单覆盖 `653` 项，`manifest.txt` SHA-256 为 `fded9e2b4cd14d049c244e9185597432afc3d561025373dca970929f47a6e4b9`。
- 候选服务 Job `46107` 在排除旧节点 `anode16` 后运行于 `P107-A100/anode19:18731`。内部 `verify-runtime.sh`、4090 恢复状态、Windows Operator 隧道和公网 `222.195.94.37:18733` 的 live/ready 均返回 Job `46107`、commit `6012b2b` 和同一 manifest。旧 Job `43737/anode16` 经用户、JobName、Account、Partition/QOS、Command、WorkDir 和节点完整匹配后受控停止为 `CANCELLED`；旧端口已关闭，未触及共享账号下其他作业。
- Stage 10 只读 Job `46109/anode19` 为 `COMPLETED/0:0`，耗时 41 秒，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为空。两套数据库完整性为 `ok`，release `653` 项清单、4 条现有工作流和既有成功/失败证据只读复核通过；证据 manifest 与 summary 的 SHA-256 分别为 `28709bb9a51a8dde374b3d99f223a257b5781a694d01c65edd191b7b9d1f909d` 和 `5bd4eb5f54afc66c2a4b96ea6ccbd8c18c5fc4f845a6d4dae58a78dc8448ce94`。该作业没有提交 VASP。
- [ ] 当前机器门禁已完成；阶段 5/7 仍保持 `PARTIAL`，直到 Operator 在全新登录会话完成通用结构上传、草稿和提交前校验，并在明确授权后取得 WS2 四步真实 VASP 证据。不得把 Job `46090` 的无 VASP 预检或 Job `46109` 的只读验收写成 WS2 计算完成。

### 17.26 公网 Operator 精确写入门禁候选

- 用户明确要求队友无需各自建立 SSH 隧道，在白名单网络中直接通过 `http://222.195.94.37:18733` 使用各自 Operator 账号提交和取消计算。
- 候选只为 `/api/competition/structures`、`/api/competition/drafts` 以及带严格 UUID 的 `submit|start|cancel|retry` 路径增加 POST 例外。通用 `/api/` 仍只允许 GET，不放行注册、Agent、VASP/QE 数据库写入、管理接口或任意工作流路径。
- 白名单只是第一层；FastAPI 的 `require_operator` 和 owner 范围检查继续是必须门禁。Nginx 请求体上限为 `2 MiB` 仅用于容纳 multipart 开销，后端结构文件上限仍为 `1 MiB`。
- 当前入口是 HTTP，没有 TLS，且 `211.86.0.0/16` 白名单覆盖较广。该方案是比赛期间受限入口，不得仅依赖 IP 认证，也不得描述为已完成互联网级 TLS 安全。
- PR #79 已将功能提交 `956804701414ba89243dd169e83b58c94ddcb3ff` 合并为 `cf813fe9564b2d29864acce089d21413547b3d94`。本地部署合同 `33/33` 通过；4090 上与合并后 `main` blob 一致的候选配置通过 Nginx `1.18.0` 语法检查。
- 107 Slurm Job `50263` 固定运行功能提交的部署合同和工作流路由权限测试，输出 `PUBLIC_OPERATOR_WRITE_TEST_OK` 并通过 `78/78`。短作业结束后 `squeue/sacct` 无保留行，因此不写成 `COMPLETED/0:0`；stdout/stderr 为 `30/23287` 字节，SHA-256 分别为 `47ef178c7361ea0adf6e0f921b0092338423d46d6456215cde5a48dcb0d18a92` 与 `42146f5a8c0d9b72b6df752c95e8ecc97d3149f30162dbf10ca357ee809cf59d`，权限已收紧为 `0600`。
- 4090 活动配置以旧 SHA-256 锁定后备份、原子替换并 reload；新配置为 `0600`，SHA-256 为 `88b62e7331dda744a0d0ede7c94921eeb197a6b83af0667105ed1932816c6b6b`。备份 `nginx.conf.before-public-operator-write.20260831T035304Z` 为 `0600`，SHA-256 为 `6c6dafe1d3091684e372a3431b562a5d05a829e499479e88ba97bd7f377211dc`。
- 公网无认证真实 multipart 结构上传与 `drafts/submit/start/cancel/retry` 均到达 FastAPI 并返回 `401`；注册、Agent、VASP 数据库 POST 和对写入路径的 GET 仍由 Nginx 返回 `403`。`live/ready` 仍返回 Job `46107`、`anode19`、运行提交 `6012b2b...` 和原 manifest。
- [x] 机器门禁完成；本次没有读取真实密码/JWT，没有创建草稿、工作流或 VASP Job。队友仍需使用各自 Operator 账号完成一次真实公网上传/草稿验收；在用户明确授权前不点击正式提交。

### 17.27 未开始工作流取消修复

- 截图中的目标工作流已经通过校验，但尚未点击开始计算：工作流状态为 `validated`，四个步骤均为 `waiting`，attempt 数为 `0`，Job ID 为空。旧协调器只允许存在活动 attempt 的工作流取消，因此返回 `workflow_not_cancellable`；这不是权限错误，也没有调用 `scancel`。
- 候选允许 Operator 取消本人名下仍为 `validated` 且数据库中不存在任何 attempt 的工作流。状态更新在同一事务中把工作流和固定四步全部置为 `cancelled`，写入 `workflow_cancelled_before_start` 与 `workflow_status_changed` 事件，并返回 `result=cancelled_before_start`、`attempt_id=null`、`job_id=null`；不创建虚假 attempt，不调用 Slurm。
- 已有 `queued/running` 工作流继续走原有活动 attempt、作业归属和 `scancel` 门禁。终态、存在历史 attempt 的 `validated` 异常账本以及并发状态变化全部失败关闭，不得借本修复操作同一 107 账号下的其他作业。
- 前端只在 `validated/queued/running/unknown` 状态允许点击取消；`cancelled/succeeded/failed/cancelling` 等状态禁用按钮。取消或重试成功后立即刷新工作流，不要求用户手动刷新；四步取消状态显示为“已取消”。
- 本地聚焦后端取消与 API 测试 `74/74`、Slurm 与安全回归 `77/77`（另有 4 项平台条件跳过）、正式构建同款后端白名单 `515/515`（另有 28 项 Windows/POSIX 条件跳过）以及前端全量 `149/149` 已通过。
- PR #81 已把功能提交 `5ee0101ae3dd7140a59023c5562970dd92066f90` 合并为 `c4f82c3d27a21932e2063a32910f1cdb960837f4`。正式构建 Job `50517/anode01` 完成后已从队列和 `sacct` 短时记账中消失，不能写成有 Slurm 记账的 `COMPLETED/0:0`；专属日志证明后端 `515` 项通过（另有 4 项环境跳过）、前端 `149/149`、Vite `1870` 个模块。新 release 清单覆盖 `653` 项，`manifest.txt` SHA-256 为 `c70faea0e439765e9082c47d7d7024f515c0ee37c602416e9ff05e73fd6eeb45`。
- 候选服务 Job `50521` 在排除旧节点 `anode19` 后运行于 `P107-A100/anode16:18731`。107 内部、4090 relay 与 Windows 公网 `222.195.94.37:18733` 的 live/ready 均返回该 Job、新 commit 和同一 manifest。旧 Job `46107/anode19` 在用户、JobName、账号、分区/QOS、Command、WorkDir 和专属日志全部匹配后受控停止；日志记录完整 Uvicorn shutdown，旧端口已关闭，未触及共享账号下其他作业。
- Stage 10 只读 Job `50526/anode16` 输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节；数据库 `integrity_check=ok`、workflow 数为 `6`，release `653` 项清单和既有成功/失败证据复核通过，没有运行 VASP。证据 manifest 与 summary 的 SHA-256 分别为 `1400e577a7e142429f9440171575d635e6cedb03d150491e94b5a636a4232bf9` 和 `53bbdc6d96801d5b20fce58b6fb58e9f8d59065763f3176a5fcd4690dab8b456`。
- 首次真实取消验收 Job `50529` 因验收包装遗漏 `LMATELAB_FRONTEND_DIST` 而在导入应用时失败，随后只读复核确认目标仍为 `validated` 且 attempt 为 `0`；该失败发生在协调器和数据库修改前，原始 stderr 保留。补齐正式服务环境后的 Job `50530` 返回 `status=cancelled`、`result=cancelled_before_start`、`attempt_id=null` 和 `job_id=null`，stderr 为 0 字节。
- 正式数据库随后只读确认工作流 `6f02776d-d59c-4755-94b5-1e391ba9dcf2` 及 `relax/scf/band/dos` 四步均为 `cancelled`，attempt 数仍为 `0`，事件序列新增 `workflow_cancelled_before_start` 与 `workflow_status_changed`。取消前后队列都没有 VASP 作业，最终只保留服务 Job `50521`，因此本次没有调用 `scancel` 或创建 VASP Job。全新认证态浏览器刷新和三名成员复核仍为 Stage 10 外部门禁，Stage 10 保持 `PARTIAL`。

### 17.28 算力集群运行数据交付

- 按“取得真实 Slurm Job ID 即计入”的统一口径，从项目根日志、Stage 6 子作业证据、正式工作流数据库和 Stage 7 专属证据目录完成去重；快照共 `218` 个作业，分为 `138 completed / 32 failed / 47 cancelled / 1 running`。
- `sbatch --test-only` 的 `38285`、Fake Slurm 的 `73001`、无关 `sacct` 作业 `30121/30147`、调度前 422/403 和没有 Job ID 的 `cancelled_before_start` 均明确排除。
- 26 个 VASP Job 单独保留 Slurm 终态和科学终态：`25` 个 Slurm completed、`1` 个 Slurm failed；其中 `21` 个科学通过、`4` 个科学拒绝、`1` 个未进入科学验收。排队、运行、VASP wall time 和峰值 RSS 均来自数据库事件、保存的 `scontrol` 与 `runtime-time.txt`，不从文件时间或 Job ID 推算。
- 新增 `compute-cluster-run-data.md`、218 行 `slurm-job-ledger.csv` 和确定性生成器；Stage 10 交付清单覆盖这三项。完整日志使用 Windows 独立附件包交付，不提交 Git，且排除正式数据库、凭据、VASP 大文件和 POTCAR。
- 本次只执行短时只读查询和日志打包，没有提交新的 Slurm 作业。快照时服务恢复 Job `54176/P107-A100/anode18` 健康运行，未被取消或修改。

### 17.29 107 服务器界面合并

- 分支 `codex/107cup-server-ui` 从最新 `origin/main` 建立，只把旧 MatFlow “服务器”能力的界面结构收敛迁移到 107 杯左侧导航；新增固定入口 `/dashboard/server`，不恢复 Dell、4090、Dawn、多服务器入口或用户跨服务器分布，也不采用正在另行更新的服务器界面。
- 页面固定展示 `P107-RTX5090` 与 `P107-A100` 两个竞赛分区的已知配置，分别对应 `anode01-anode15 / 120 GPU` 与 `anode16-anode26 / 88 GPU`。配置资源与动态利用率严格分开：节点数和 GPU 数标注为配置值，实时空闲、忙碌、CPU 和内存仍显示“待接入”，不得从个人工作流数量推断全体集群负载。
- 页面只复用现有只读接口：`/api/health/live` 提供网页服务 Job、计算节点、发布类型、数据模式和提交身份，`/api/competition/dashboard` 提供当前账号可见的 attempt 排队、运行、累计数量和更新时间。没有增加写路由、Slurm 命令或后端服务器监控 router，也没有修改 107 数据库、作业或当前生产服务。
- 桌面 `1440x900` 与移动 `390x844` 已用本地演示发布完成真实浏览器检查；两种视口均无整页横向溢出，控制台错误和警告为 `0`。首次移动截图发现宽表格空态落在横向滚动区右侧，修复后空态固定在首个可见区域；浏览器截图保留在本地 `frontend/output/playwright/`，不作为生产证据提交 Git。
- 本地前端测试 `157/157`、定向 ESLint 和 107 杯 Vite 构建（`1871` 个模块）已通过。本次页面及其导航、Provider、响应式样式、E2E 路由和测试均加入 Stage 10 确定性交付清单。
- PR #87 已把功能提交 `6ee01f2110ef197fec484c66d710eeb32cea567f` 合并为 `4eca4f39cae9dc67a553489d573a8811cb5947cb`。当前完成的是源码、测试和本地真实浏览器验收；107 Slurm 构建、候选服务、`18733` 切换和真实账号浏览器复核尚未执行，因此不能把该页面写成已经上线。
- `18733` 与 `18755` 均未因本节工作停止或修改。下一步进入 Agent/Qoder 的 `18755 -> 18733` 生产化迁移；集群级实时资源采集是独立后续项，不阻塞 Agent 迁移，也不能用工作流数量代替。

### 17.30 Agent/Qoder 107 生产合同合并

- 分支 `codex/107cup-agent-production` 基于服务器页面合并提交建立。`18755` 的 Agent、Qoder、文献/PDF、结构构建、计算规划和个人结果源码已经由 PR #83 进入 `main`；本节不再次复制页面或业务代码，只补齐其在 107 上运行并由 `18733` 访问所需的生产合同。
- 107 专用依赖固定加入 `pypdf==5.9.0` 与 `qoder-agent-sdk==1.0.14`。Qoder 的“安装”接口改为只校验构建时安装的固定版本和 CLI，不得在网页或 Worker 运行时执行 `pip install`，从而保持 `releases/<commit>` 不可变。
- Agent 上传、文献 SQLite、示例、设置、LLM 密钥、Qoder runtime 和 workspace 全部固定在 `/home/scc/pb23030683/lmatelab-107cup` 的私有目录。构建作业创建 `0700` 目录并补齐只读示例；密钥文件不创建占位内容、不进入 Git，必须由 Operator 在受控入口配置。
- Agent Worker 改为 `P107-A100` 上最长 4 天的 Slurm 服务作业，读取与 Web 服务相同的 `runtime.env` 和不可变 release。`agent_worker_control.py` 在登录节点只执行短时 `squeue/scontrol/sbatch`，逐项核对用户、JobName、Command、WorkDir、Account、Partition 和 QOS；已有唯一归属 Worker 时复用，存在重复或归属不符时失败关闭，绝不自动 `scancel`。
- Web 服务每次迁移前使用 SQLite Online Backup API 生成不可覆盖的 `0600` 一致性备份，迁移后同时执行 Alembic head 与两套数据库 `integrity_check`。该机制不等于数据库回滚；候选失败时保留备份、旧服务和旧 relay，由人工确认迁移兼容性后处理。
- 4090 Nginx 仍以 IP 白名单和应用角色双重限制访问。Agent 的 Qoder 管理、设置、文件上传、文献索引、结构包、运行创建、会话删除和批准接口按实际 HTTP 方法逐条精确放行；不存在整个 `/api/competition/agent/` 的通配写权限。PDF 上限为应用限制 `20 MiB`，代理请求体上限相应设为 `21 MiB`。
- 本地正式门禁已通过：后端 `594` 项全部通过（`28` 项只因 Windows 不具备 POSIX 能力而按设计跳过），前端 `157/157` 通过，107 生产构建转换 `1871` 个模块；Shell 语法、Python 编译、清单和 diff 检查均通过。功能提交 `48b9e825fc3f846ff57555b0ce0a26ccde1f70df` 已通过 PR #88 合并为 `1311e2997b17317132a59207d4953755bc279b08`。
- 107 计算节点预检、正式 Slurm 构建、候选 Web/Worker 和 `18733` 切换已于 17.31 完成；真实 Operator/Viewer Agent 复核、LLM 密钥、Qoder 登录与 `18755` 停止仍是外部门禁。

### 17.31 Agent 107 计算节点预检与构建失败边界

- 网络探测 Job `54298` 因 `sbatch --wrap` 的 `/bin/sh` 不支持 `pipefail` 而在请求前失败；日志保留且没有被覆盖。修正后的新 Job `54299` 在 `P107-A100` 计算节点取得 DeepSeek HTTP `401` 和 Qoder HTTP `200`，证明两个站点的 DNS、TLS 和 HTTP 通路可用；未携带 API Key，也未产生模型调用。
- 首次正式构建 Job `54300` 在安装固定 Qoder/PDF 依赖、通过后端 `594` 项与前端 `157` 项测试并完成 Vite 构建后，被最终 Agent 路由门禁拒绝；原因是生产 `runtime.env` 尚未显式启用 Agent。旧配置已以 `0600` 备份，新增键按合并模板原子写入，不包含 API Key。
- 第二次正式构建 Job `54301` 显示 4 个路由测试泄漏了生产 `LMATELAB_COMPETITION_AGENT_PROVIDER=llm`：测试只启用功能开关，却未显式固定自己的 `mock` provider。这不能通过把生产 provider 降级为 mock 规避；当前修复将所有相关测试的 provider 显式固定为 `mock`，再在同样的真实生产环境下复跑。
- `54300` 和 `54301` 都在发布目录生成和 `current` 切换前终止，正式 Web Job `54176`、`18733` 和 `18755` 均未改变。
- 环境隔离修复提交 `df0515600bcd29c54f39f4595463e2b631feb6e0` 已通过 PR #90 合并为 `64e9d20a494d13a280cbaac1fc32e7e8b5556768`。第三次正式构建 Job `54302/P107-RTX5090/anode03` 在生产 `provider=llm` 环境下通过后端 `594` 项（Linux 条件跳过 `4`）、前端 `157/157`、Vite 构建、Agent 路由和双重清单门禁，原子生成新 release；manifest SHA-256 为 `39c529774070b8b052bcba4535e7ef481ea69408bd275b0da11ff3d4923c45f0`。
- Qoder 计算节点探测 Job `54303/P107-A100` 确认 SDK 版本 `1.0.14`、CLI 可执行且 stderr 为空；`authenticated=false` 是当前真实状态，不得写成 Qoder 已可用。
- 候选 Web Job `54304/P107-A100/anode16` 在迁移前为两套 SQLite 生成不可覆盖备份，迁移后同时通过两套 Alembic head、`integrity_check`、live 和 ready；Agent Worker Job `54305/P107-A100/anode16` 作为唯一归属 Worker 发布了与 Web 相同的 commit 和 manifest。
- 4090 Nginx 活动配置在保留全部 IP 白名单的前提下，已更新为 `21m` 请求体上限和逐条 Agent 写路由，源模板 SHA-256 为 `298b1cb799fba9c44a6638b3711733b67c0fdc57e329a67ebe1a135a61d5ce34`，旧配置备份为 `nginx.conf.before-agent.54304`。切换前公网仍返回旧 Job `54176`；取消临时 `18742` 后，恢复器原子把 `18740/18733` 切换为 Job `54304`，4090 内部、Windows 公网的 live/ready、首页、服务器页和 Agent 页均通过，未登录 Agent 读写返回 `401`。
- 旧 107 Web Job `54176` 与 `Pzxp` 所有的 4090 `18755` 仍保留作为回退边界。下一门禁是使用真实 Operator 与 Viewer 复核 Agent 权限，由 Operator 在网页写入 LLM API Key 并完成 Qoder 登录；这些通过前不停止两个旧服务，`18755` 最终只能由其进程所有者 `Pzxp` 停止。

### 17.32 Qoder CN 与 API Key 安全入口纠正

- 17.30 和 17.31 记录的是当时真实执行过的全球版 `qoder-agent-sdk/qodercli` 构建与探测，历史证据不改写。后续核对确认比赛使用的是大陆版 Qoder，因此新候选改为固定 `qodercn-agent-sdk==1.0.14`、内置 `qoderclicn 1.1.38`、`QODERCN_CONFIG_DIR` 和 `QODERCN_PERSONAL_ACCESS_TOKEN`；只接受 `qoder.cn` 或 `qoder.com.cn` 的带 challenge 设备授权链接。
- 截图中的“请求参数无效”实际来自后端已有的密钥传输门禁 `API key requires HTTPS or loopback access`，不是 API Key 格式校验失败。公网 `http://222.195.94.37:18733` 没有 TLS，因此新页面禁用密钥输入并给出明确提示；API URL 和模型仍可单独保存。
- 允许的密钥入口限定为 HTTPS 或直达 107 Web 服务的 `127.0.0.1` SSH 隧道。4090 Nginx 在 Agent 设置路由覆盖写入实际入口 scheme，后端优先采用该可信标记，防止公网请求通过伪造 `Host: 127.0.0.1` 绕过。
- 构建作业显式创建权限为 `0700` 的 `runtime/qoder/config`。API Key 仍只进入权限为 `0600` 的 `config/secrets/llm-api-key`；Git、日志和聊天中均不得出现真实密钥或 Qoder PAT。
- 本节完成条件是：本地门禁通过；107 Slurm 计算节点完成全量后端测试、大陆版 CLI 版本与登录命令探测；新 Web/Worker 候选通过身份、manifest 和数据库完整性核对；公网入口明确拒绝密钥并仍可保存 URL/模型；Windows 回环隧道可以保存密钥；真实 Qoder CN 登录完成前不得显示或宣称“已连接”。
- `18733` 的 Agent 页面、文献/PDF、结构构建、计算规划和个人结果功能以已合并的 `18755` 源码为基线，但运行位置、认证边界和数据路径按 107 生产合同收敛，因此不是逐字节复制。`18755` 的既有历史只有在取得完整、已认证且归属明确的导出文件后，才能通过一次性 Slurm 迁移作业导入；不得从页面截图、部分分页或其他用户数据推断补写。
- 首次计算节点预检 Job `54388/P107-RTX5090/anode01` 在测试开始前以 `FAILED/1:0` 结束，直接原因是该节点没有定义 `SLURM_TMPDIR`。失败日志保留为 `/home/scc/pb23030683/lmatelab-107cup/logs/qodercn-test-54388.{out,err}`，权限均为 `0600`；stdout 为空，stderr SHA-256 为 `636c8a987916840c6d5985aaf3d5a6c39da35c107fed5009378af3f0b551c58f`。修复只把临时目录改为带 Job ID 的 `/tmp` 兜底，没有覆盖或重用该记录。
- 新 Job `54389/P107-RTX5090/anode01` 为 `COMPLETED/0:0`，耗时 `00:01:27`。正式后端清单 `602` 项全部通过，另有 `4` 项按 Linux 能力条件跳过；临时隔离安装确认 `qodercn-agent-sdk 1.0.14`、`qoderclicn 1.1.38`，且 `login --help` 与 `remote-control --help` 均零退出，最终标记为 `QODERCN_PREFLIGHT_OK`。stdout/stderr 权限均为 `0600`，SHA-256 分别为 `b08cf89fd51042e6d3e081f84fab107345a154f13e6933e26415e4baf00f22d6` 和 `1a379645e489b572e8cc21c4a94fa0b4262a6217995fc28d9e584f5524ef7b8a`。该作业使用临时 site/config，没有修改正式 Python 环境、数据库、Web、Worker 或 VASP 作业。
