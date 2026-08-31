# LMateLab 107 杯团队协作指南

更新时间：`2026-08-11`

本文是三名队员了解项目、选择工作、提交代码和核对证据的统一入口。它不替代总实施方案；阶段状态、验收事实和后续门禁仍以 [`implementation-plan.md`](./implementation-plan.md) 为唯一账本。

## 1. 先回答最常见的问题

### 1.1 直接访问 Gitea 能了解全部项目吗？

可以了解所有**已经提交并推送**的长期信息，包括：

- 源码、测试、部署脚本和文档；
- 每次提交的作者、时间、差异和提交说明；
- 分支、Pull Request、评审和合并历史；
- 已经写入文档的 Slurm Job ID、节点、日志路径、文件哈希和验收结论；
- 当前计划中已实现、未实现和禁止进入第一版的范围。

但 Gitea 不能自动代表以下实时状态：

- 当前 Slurm Job 是否仍在排队或运行；
- 当前计算节点和端口是否仍可访问；
- SSH 二次验证和复用连接是否仍有效；
- 107 上某个未提交的日志或失败 attempt 的最新内容；
- 4090 转发和 IP 白名单此刻是否健康。

因此规则是：**长期事实进 Git，实时事实先现场核验，再把证据摘要和路径提交回 Git。**

### 1.2 Gitea 地址

- Web 仓库：<https://wugroup.synology.me/107-team/LMateLab>
- 团队空间：<https://wugroup.synology.me/107-team>
- SSH 仓库：`ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git`

仓库是私有团队仓库。队员必须先登录自己的 Gitea 账号并加入 `107-team`，不能共用他人的 Gitea 账号、SSH 私钥或访问令牌。

## 2. 阅读顺序

第一次进入仓库时按以下顺序阅读：

1. [`README.md`](../../README.md)：确认这是独立的 107 杯项目。
2. 本文：理解边界、分工、Git 流程、107 操作和证据要求。
3. [`TEAMMATE_AI_START.md`](../../TEAMMATE_AI_START.md)：队友只需把这一个文件交给各自的 AI，由 AI 帮助连接 Gitea 并完成只读接手。
4. [`implementation-plan.md`](./implementation-plan.md)：查看唯一阶段状态和下一门禁。
5. [`source-provenance.md`](./source-provenance.md)：查看初始来源、清理范围和哈希。
6. [`2026-08-10-107cup-frontend-preview-design.md`](../superpowers/specs/2026-08-10-107cup-frontend-preview-design.md)：查看已批准的前端预览设计。
7. [`2026-08-10-107cup-frontend-preview.md`](../superpowers/plans/2026-08-10-107cup-frontend-preview.md)：查看当前 14 个实现任务和逐步验收命令。
8. [`.gitea/PULL_REQUEST_TEMPLATE.md`](../../.gitea/PULL_REQUEST_TEMPLATE.md)：提交 PR 前逐项填写。

如果文档之间出现冲突，优先级为：

```text
用户最新明确决定
  > implementation-plan.md 的阶段边界和状态
  > 已批准专项设计
  > 当前专项实施计划
  > 旧提交说明、聊天记录和临时命令
```

## 3. 项目目标和固定主线

第一版只围绕一个可验收的材料计算闭环：

```text
单层 MoS2 内置模板
或 Operator 上传受限的小型 POSCAR/CIF
  -> 结构解析与输入校验
  -> 工作流草稿
  -> Slurm 受控提交
  -> relax
  -> SCF
  -> BAND
  -> DOS
  -> 结构、能带、态密度、VASP 数据库和证据包
```

输入上传仍受固定边界限制：文本 POSCAR/CIF、单文件不超过 `1 MiB`、不超过 `200` 个原子；不接受压缩包、目录、任意脚本、任意模板或用户指定任意路径。

第一版明确不做：

- Agent、聊天、RAG、Ollama 和 `vasp-wiki`；
- 机器学习、主动学习和跨服务器迁移；
- QE、EPW、Gaussian、DeepMD、LASP、CP2K 等旁支工作流；
- 复制原 4090 LMateLab 的生产数据库、上传、日志或密钥；
- 任意命令、任意 Slurm 脚本、任意路径浏览；
- 与主线无关的实验记录、报告、文献和服务器监控扩展。

原项目已有 Agent 视为不可用，第一版不恢复。前端预览中的 demo 数据也不能被描述为真实 VASP 或真实 Slurm 结果。

## 4. 系统边界

```text
个人 Windows 工作站
  -> 个人 Gitea 身份提交源码和文档
  -> 受保护 main 通过 PR 合并
  -> 107 使用只读 Deploy Key 拉取固定合并提交
  -> Slurm 计算节点构建、测试、运行 FastAPI 和 VASP
  -> 4090 仅做可替换的网络转发和 IP 白名单
  -> 浏览器查看 Operator 或 Viewer 页面
```

关键边界：

- 项目源码、环境、数据库、服务、VASP 作业和结果最终都在 107。
- 4090 `222.195.94.37` 只允许做网络入口，不保存竞赛业务数据，不执行 LMateLab/VASP 业务逻辑。
- 不使用 Docker，因为 107 账号没有管理员权限；构建和服务由 Slurm 作业提供。
- 107 登录节点 `tradmin-02` 不能运行依赖安装、构建、测试、FastAPI 常驻服务或长时间计算。
- 登录节点只允许短时 Git、`sbatch`、`squeue`、`sacct`、针对明确 Job ID 的只读 `scontrol show job`、`scancel` 前的归属核验和读取小型状态文件。

固定路径：

| 用途 | 路径 |
|---|---|
| 107 竞赛根目录 | `/home/scc/pb23030683/lmatelab-107cup` |
| 107 只读源码检出 | `/home/scc/pb23030683/projects/LMateLab-107Cup` |
| VASP | `/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell` |
| VASP 环境脚本 | `/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh` |
| VASP 提交脚本 | `/home/scc/pb23030683/scripts/vasp` |
| VASPKIT | `/home/scc/pb23030683/software/vaspkit.1.5.1` |

## 5. 当前状态

以下是 `2026-08-11` 的本地开发检查点，不代表已经合并或部署：

- `origin/main`：`f8aee97e4367fa45befab77c3a248d99dd3e36ae`，已包含前端预览设计和实施计划。
- 当前实现分支：`codex/107cup-frontend-preview`。
- 功能实现检查点（不含本文档提交）：`ab6064dcc869553b5e2d90f77826ccd87a6a42aa`。
- Task 0 已完成：从合并后的 `main` 创建隔离工作树并通过基线。
- Task 1 已完成并通过规格/质量复审：demo/live 数据提供器、MoS2 成功/运行/失败 fixture、只读 mutation 和 BAND/DOS 演示数据。
- Task 2 已完成并通过规格/质量复审：118 元素周期表和受控筛选组件；旧 VASP 页面保持兼容。
- Task 3 暂停在开始前：下一步是提取只读 `VaspRecordTable`。
- 当前前端测试为 `44/44` 通过，生产构建通过。
- 当前分支将在本文档提交后推送到 Gitea；尚未创建实现 PR、尚未合并、尚未在 107 创建 preview release。实际状态以 Gitea 分支和 PR 页面为准。
- 总阶段 5 至 8 仍为 `PENDING`；目前没有真实工作流模型、Slurm 控制、网页 VASP 四步执行或完整竞赛数据库。

不要把上述本地实现写成“107 已部署”或“真实 VASP 已完成”。最新状态必须同时查看当前分支、PR 和总实施方案变更记录。

## 6. 当前前端预览批次

当前批次共 14 个任务：

| Task | 内容 | 当前状态 |
|---|---|---|
| 0 | 合并设计、隔离工作树和基线 | 本地完成 |
| 1 | demo/live 数据提供器契约 | 本地完成，双重审查通过 |
| 2 | 118 元素周期表提取 | 本地完成，双重审查通过 |
| 3 | 只读 VASP 记录表提取 | 下一步 |
| 4 | 竞赛数据上下文和导航 | 未开始 |
| 5 | 共享状态组件和科学适配器 | 未开始 |
| 6 | 运行态 Dashboard 预览 | 未开始 |
| 7 | 新建计算预览工作区 | 未开始 |
| 8 | 工作流列表和证据详情 | 未开始 |
| 9 | 结果列表和科学结果详情 | 未开始 |
| 10 | 周期表 VASP 数据库和路由 | 未开始 |
| 11 | 三视口 Playwright 与 3D Canvas 像素检查 | 未开始 |
| 12 | 隔离的 107 Slurm preview 构建/服务 | 未开始 |
| 13 | 全量验证、PR、107 部署、浏览器验收、停止和证据 | 未开始 |

预览固定提供五个认证入口：

```text
/dashboard
/dashboard/calculations/new
/dashboard/workflows
/dashboard/results
/dashboard/database/vasp
```

预览约束：

- demo/live 模式在构建时固定，不能在浏览器中切换。
- demo 必须持续显示演示标识；上传、保存、提交、取消、重试和数据库写入在网络请求前失败。
- live 只定义未来 `/api/competition/` 契约，不得在 404、403 或解析失败后回退 demo。
- 复用旧项目的 3D 结构、晶体详情、BAND/DOS、颜色、格式化、周期表和只读表格能力。
- 不挂载完整旧 VASP router，不恢复 Agent、QE/EPW、监控、报告或 4090 生产数据。

## 7. 预览之后的主路线

预览验收后才按顺序进入：

1. **阶段 5，工作流模型和输入校验**：工作流、步骤、attempt、事件、文件哈希、MoS2 模板和所有 `sbatch` 前校验。
2. **阶段 6，Slurm 适配器**：固定参数数组调用、状态映射、日志限制、归属核验、取消和重启对账。
3. **阶段 7，真实 VASP 四步闭环**：每步独立 Job/attempt，成功链和人为失败阻断链。
4. **阶段 8，结果和证据包**：解析、图表、原始数据下载、不可变证据包和周期表数据库。
5. **阶段 9，恢复、安全和回归**：故障、竞态、路径逃逸、非 LMateLab 作业隔离和发布回滚。
6. **阶段 10，比赛交付**：从固定 main 重建，Operator/Viewer 演示，真实成功/失败复跑，截图、视频和最终哈希清单。

## 8. 三人分工建议

分工以 PR 为边界，不按共享 Unix 用户区分。每项工作只设一名直接负责人，至少一名队友审查。

| 责任方向 | 主要内容 | 交付物 |
|---|---|---|
| 前端与浏览器验收 | Task 3-11、响应式、3D Canvas、无写请求检查 | React 代码、Node/Playwright 测试、截图哈希 |
| 工作流与科学计算 | 阶段 5-8、输入生成、Slurm/VASP、解析和证据包 | 后端代码、假 Slurm 测试、真实 Job/输出证据 |
| 发布、安全与证据 | Task 12-13、构建/服务、前后快照、恢复与文档 | Slurm 脚本、manifest、运行证据、交付文档 |

这只是责任方向，不表示可以并行修改同一文件。开始前在 Gitea issue/PR 描述中声明文件范围；共享文件由当前主线负责人协调，避免两个分支同时大改。

推荐评审关系轮换：实现者不能用自己的自审替代队友评审；涉及 VASP 科学验收时，由未编写该阶段输入生成器的队员复核原始输入输出和完成标记。

## 9. 个人 Gitea 身份

虽然三人登录 107 时共用 Unix 账号 `pb23030683`，Git 身份必须不同：

```powershell
git config user.name "你的真实姓名或约定英文名"
git config user.email "你在 Gitea 中验证的个人邮箱"
git config --get user.name
git config --get user.email
```

每人必须具备：

- 自己的 Gitea 账号；
- 自己的 SSH key；
- 自己的提交姓名和邮箱；
- 自己创建的功能分支和 PR；
- 至少一个可追溯到个人 Gitea 身份的合并提交证据。

不要在 107 共享账号中写全局 `git config --global user.*` 来冒充个人身份。107 Deploy Key 只用于只读拉取合并提交，不用于成员推送。

## 10. 本地开发流程

首次克隆：

```powershell
git clone "ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git"
Set-Location LMateLab
git fetch origin main
git switch -c "member/<姓名缩写>-<短任务名>" origin/main
```

开始前：

```powershell
git status --short --branch
git log -1 --oneline
git diff --check
```

要求：

- 不直接在 `main` 开发或推送；
- 使用独立工作树或独立克隆，避免覆盖他人未提交改动；
- 一个分支只解决一个计划任务或一组紧密耦合的小任务；
- 修改前先读对应计划的完整 Task；
- 功能或修复先写失败测试，再实现，再跑完整相关回归；
- 不清理、回退或覆盖不是自己产生的修改。

## 11. 测试和证据门禁

本地前端：

```powershell
Set-Location frontend
npm ci
npm test
$env:VITE_LMATELAB_EDITION='107cup'
$env:VITE_COMPETITION_DATA_MODE='demo'
npm run build
```

本地后端专项测试使用项目虚拟环境；Windows 无法表达 POSIX `0600/0700` 权限位时，应在 Linux/WSL 或 107 Slurm 作业中验证权限测试，不能删除断言让 Windows 变绿。

107 上所有耗时测试、构建和服务必须通过 Slurm。登录节点只提交和查询：

```bash
set -euo pipefail

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
cd "$project"

# 先失败关闭：路径必须准确、工作树必须干净、稳定 current 和活动作业不能引用该检出。
test "$(git rev-parse --show-toplevel)" = "$project"
test -z "$(git status --porcelain)"
current_target=$(readlink -f "$root/current" 2>/dev/null || true)
case "$current_target" in
  "$project"|"$project"/*) printf 'stable current references project checkout: %s\n' "$current_target" >&2; exit 1 ;;
esac
squeue_output=$(squeue -h -u "$USER" -o '%i|%j|%Z|%o')
active_refs=$(printf '%s\n' "$squeue_output" | grep -F "$project" || true)
test -z "$active_refs" || { printf 'active jobs reference project checkout:\n%s\n' "$active_refs" >&2; exit 1; }

git fetch origin main
commit="${LMATELAB_MERGED_COMMIT:?export LMATELAB_MERGED_COMMIT as the 40-character merged main commit}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
git cat-file -e "$commit^{commit}"
git merge-base --is-ancestor "$commit" origin/main
git checkout --detach "$commit"
test "$(git rev-parse HEAD)" = "$commit"

# 此后只运行对应专项计划指定的 submit helper 或受控 sbatch 脚本。
squeue -u "$USER"
job_id="${JOB_ID:?export the exact LMateLab JOB_ID being verified}"
[[ "$job_id" =~ ^[0-9]+$ ]]
sacct -j "$job_id" --format=JobID,State,ExitCode,Elapsed,NodeList
scontrol show job "$job_id"
```

如果平台 `sacct` 没有记录，必须保留 `scontrol`、原始 Slurm 输出、应用日志、端口检查和文件哈希；不能凭目录存在写成 `COMPLETED/0:0`。

每个完成结论至少回答：

- 运行的是哪个合并提交？
- 哪个 Slurm Job ID、分区、节点和退出状态？
- 哪些原始输入输出和正常结束标记通过？
- 哪些 manifest/SHA-256 可以复核？
- 失败产物保存在哪里？
- 是否影响稳定 `current`、数据库、服务 Job 或非 LMateLab 作业？

## 12. 提交和 PR 流程

提交前：

```powershell
git status --short
git diff --check
git diff --stat
```

提交只包含计划内文件，使用清楚的 Conventional Commit 风格，例如：

```text
feat(107cup): add preview data providers
refactor(vasp): extract periodic table filter
test(107cup): cover preview access controls
docs(107cup): record preview evidence
```

推送：

```powershell
git push -u origin HEAD
```

然后在 Gitea 创建目标为 `main` 的 Pull Request，填写模板中的：

- 目标和范围；
- 明确未实现的部分；
- 运行过的测试及精确结果；
- 是否接触 107、稳定服务、数据库或 4090；
- 运行证据和失败证据位置；
- 回滚方式；
- 是否含敏感信息。

当前 `main` 禁止直接和强制推送，必须通过 PR；但 Gitea 当前最低批准数仍为 `0`，没有 CI 状态检查门禁，签名提交也不是强制。团队不能把“平台允许合并”误当成“已经有人审查”。建议每个功能 PR 至少由另一名队员明确审查后再合并。

PR 合并后：

1. 记录新的 40 字符 `origin/main` 合并提交；
2. 107 只读检出该固定提交；
3. 通过 Slurm 构建或运行；
4. 把真实证据写回文档分支，再走一次 PR；
5. 不从 107 推送源码或直接修改 `main`。

## 13. 共享 107 账号的安全规则

三人共用 `pb23030683` 会带来两个问题：无法从 Unix 用户名区分操作者，也能看到同账号下其他作业的基本调度信息。因此：

- 不共享个人 Gitea key、Windows SSH key 或浏览器凭据；
- 每个 LMateLab 作业使用固定 `lmatelab-` JobName、受控 WorkDir、Slurm comment 和数据库 ledger 四项归属；
- `scancel` 前必须同时核对四项归属，任一不符就拒绝；
- 不读取、取消或修改同账号下不属于 LMateLab 的作业；
- 重大远端操作前在团队中声明负责人、目标 Job ID、路径和预期影响；
- 登录节点禁止常驻 Vite、Uvicorn、Celery、Redis 或计算进程。

## 14. 网络访问

当前允许两种访问方式：

- 白名单公网入口 `http://222.195.94.37:18733`：Viewer 保持只读；Operator 可以上传结构、保存草稿、提交、启动、取消和重试本人的固定工作流。Nginx 只放行这些精确 POST，其他业务写入继续拒绝；
- Windows 到 4090 内部 relay 的独立 SSH 隧道：保留为 Operator 备用和受控验收入口。

4090 入口不是永久依赖。转发失效时，项目数据、源码、服务和 VASP 作业仍应全部留在 107；只需重新建立隧道或替换入口。当前公网入口为 HTTP 且白名单包含校园网段，所以 IP 白名单不能代替强密码、Operator 角色和任务归属检查。

不要把密码、JWT、SSH 私钥、二次验证码、完整运行环境文件或私有数据库内容提交到 Gitea。IP 白名单如需记录，只保留必要的配置模板和非敏感说明，运行配置保持私有权限。

## 15. 状态用词

总实施方案只使用：

- `DONE`：对应门禁有完整证据；
- `PARTIAL`：部分完成，剩余门禁明确；
- `PENDING`：未开始或没有可验收实现；
- `BLOCKED`：明确外部条件阻止继续。

同时区分：

- **本地已实现**：源码和本地测试存在；
- **已合并**：Gitea `main` 包含提交；
- **107 已构建**：固定合并提交在 Slurm 构建作业中通过；
- **107 已运行**：真实服务/作业、节点、端口和健康检查存在；
- **科学验收通过**：调度状态、程序正常结束、必要文件和哈希同时通过。

页面能打开、静态测试通过、Job 进入 `COMPLETED`、目录名叫 `success`，都不能单独替代科学验收。

## 16. 队员接手检查单

开始任务前：

- [ ] 已用个人 Gitea 账号打开仓库。
- [ ] 已读本文、总实施方案和对应专项 Task。
- [ ] 已确认当前 `origin/main`、目标分支和工作树干净。
- [ ] 已配置个人 Git 姓名和邮箱。
- [ ] 已声明负责的任务、文件范围和验收命令。
- [ ] 已确认没有人在同一共享文件上并行修改。

提交 PR 前：

- [ ] 先看到预期失败测试，再看到实现后通过。
- [ ] 相关专项测试、完整回归、构建和 `git diff --check` 已通过。
- [ ] 没有密钥、验证码、JWT、数据库、日志或上传文件。
- [ ] 没有扩大到 Agent、ML、QE/EPW 或其他旁支。
- [ ] 总实施方案记录了变更和验证边界。
- [ ] PR 明确哪些只是 demo、本地或尚未在 107 验证。

远端验收前：

- [ ] 使用合并后的固定 `main` 提交，而不是未合并分支。
- [ ] 耗时工作通过 Slurm 计算节点运行。
- [ ] 稳定 `current`、数据库、服务 Job 已做操作前快照。
- [ ] 只操作归属明确的 LMateLab Job 和目录。
- [ ] 失败证据有保存路径，不会被下一次尝试覆盖。
- [ ] 操作后记录 Job、节点、状态、日志、哈希和稳定状态对比。

## 17. 需要三人最终共同完成的门禁

- 三名成员各自的 Gitea 账号、SSH key、提交邮箱、提交和 PR 证据；
- 三名成员独立 LMateLab 应用身份及角色边界；
- Operator 真实完成 `relax -> SCF -> BAND -> DOS`；
- Viewer 只读查看真实成功/失败状态、日志、BAND/DOS 和证据包；
- 平台不能控制同账号下的非 LMateLab 作业；
- 单元、假 Slurm、真实 Slurm、真实 VASP、浏览器 E2E、最终演示六层测试全部通过；
- 最终发布和证据 SHA-256 清单由三人复核。

任何人发现计划、实现和真实运行不一致时，应先保留证据、停止扩大影响，再通过 PR 修正文档和代码；不能只在聊天中口头修正而不回写仓库。
