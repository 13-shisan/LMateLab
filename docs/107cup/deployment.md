# 107 杯部署与恢复说明

更新时间：`2026-09-05`

## 1. 部署边界

本项目不使用 Docker，也不在 107 登录节点执行依赖安装、前后端构建、测试、FastAPI 常驻服务或 VASP 计算。登录节点只做短时的只读 Git 核对、`sbatch` 提交和针对明确 Job ID 的调度查询。源码、Python/Node 环境、SQLite、工作流、VASP attempt、结果和证据都位于：

```text
/home/scc/pb23030683/lmatelab-107cup
```

4090 `222.195.94.37` 只提供用户态 SSH 转发、Nginx 受限入口和 IP 白名单，不保存竞赛业务数据库，不运行 FastAPI、Agent Worker 或 VASP。公网代理默认只允许 GET，仅精确放行登录、修改本人密码、固定竞赛工作流写操作和已列明的 Agent Operator 写接口。后端继续强制 Operator 角色和任务归属；Viewer 无法借助代理获得写权限，也没有整个 `/api/competition/agent/` 的通配写入口。Windows Operator SSH 隧道保留为受控备用入口。4090 入口失效只影响访问，不改变 107 内的数据和作业。

## 2. 固定目录

| 用途 | 路径 |
|---|---|
| 只读源码检出 | `/home/scc/pb23030683/projects/LMateLab-107Cup` |
| 固定发布 | `/home/scc/pb23030683/lmatelab-107cup/releases/<commit>` |
| 当前发布 | `/home/scc/pb23030683/lmatelab-107cup/current` |
| Python/Node 环境 | `/home/scc/pb23030683/lmatelab-107cup/envs` |
| 正式数据库 | `/home/scc/pb23030683/lmatelab-107cup/data/db` |
| 工作流和 attempt | `/home/scc/pb23030683/lmatelab-107cup/data/workflows` |
| Agent 上传和文献库 | `/home/scc/pb23030683/lmatelab-107cup/data/agent` |
| Qoder CN 私有配置 | `/home/scc/pb23030683/lmatelab-107cup/runtime/qoder/config` |
| Qoder workspace | `/home/scc/pb23030683/lmatelab-107cup/data/qoder-workspace` |
| Slurm 日志 | `/home/scc/pb23030683/lmatelab-107cup/logs` |
| 验收证据 | `/home/scc/pb23030683/lmatelab-107cup/evidence` |
| 私有配置 | `/home/scc/pb23030683/lmatelab-107cup/config` |

私有配置、密码、JWT、SSH 密钥、二次验证码、数据库和运行日志不得进入 Git。

## 3. 从合并后的 main 发布

Operator 先确认目标 PR 已合并，并在 107 登录节点执行短时核对。不要从功能分支构建，也不要在源码检出中直接改文件。

```bash
set -euo pipefail
project=/home/scc/pb23030683/projects/LMateLab-107Cup
cd "$project"
test -z "$(git status --porcelain)"
git fetch origin main
git checkout --detach origin/main
git rev-parse HEAD
bash deploy/107cup/submit-build.sh
```

`submit-build.sh` 只提交 `build.slurm`。依赖安装、后端回归、前端测试和 Vite 构建均在 `P107-RTX5090` 计算节点完成。`pypdf` 和大陆版 `qodercn-agent-sdk==1.0.14` 必须在这里按固定版本安装；网页和 Worker 运行时不得安装或更新包。构建作业还会创建权限为 `0700` 的 `runtime/qoder/config`，并由 `QODERCN_CONFIG_DIR` 固定引用。构建失败不得切换 `current`；构建成功后形成不可变 `releases/<commit>`，校验 `manifest.txt` 和 `manifest.sha256` 后原子切换。

查询明确的构建 Job：

```bash
root=/home/scc/pb23030683/lmatelab-107cup
job_id=$(<"$root/runtime/build-job-id")
squeue -j "$job_id"
sacct -j "$job_id" --format=JobID,State,ExitCode,Elapsed,NodeList
tail -n 80 "$root/logs/build-$job_id.out"
tail -n 80 "$root/logs/build-$job_id.err"
```

短作业可能很快从平台记账中消失；此时必须以原始 Slurm 日志、发布清单和运行时状态共同判断，不能把空 `sacct` 写成成功。

## 4. 启动和验证服务

服务通过 `service.slurm` 运行在 `P107-A100` 计算节点。同一 release 的服务丢失或异常时使用恢复入口；它会先核对已有 Job、状态文件和目标端口，并只在必要时提交一个候选：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/submit-service.sh
bash deploy/107cup/verify-runtime.sh
```

`submit-service.sh` 是同版本恢复入口，不是版本升级入口。新构建已经把 `current` 切到新 commit、但旧服务仍健康运行时，恢复器会以 `release_identity_mismatch` 失败关闭；此时不得循环重试或删除状态文件。版本升级应保留旧服务，排除旧节点并直接提交新 release 的候选：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
old_node=$(</home/scc/pb23030683/lmatelab-107cup/runtime/service-node)
candidate_job=$(sbatch --parsable --exclude="$old_node" deploy/107cup/service.slurm)
printf '%s\n' "$candidate_job"
```

等待候选自身的 live/ready、commit 和 manifest 全部一致，由 4090 临时探测端口确认后再切换正式 relay。只有新入口验证成功，才允许按 Job 归属清单核对并停止旧服务；候选失败时必须保留旧服务和旧 relay。

正式状态以 `runtime/service-state.json` 为原子来源，同时与 `service-job-id`、`service-node`、`service-port`、`service-commit` 和 `service-manifest-sha256` 逐项一致。健康检查必须同时满足 `/api/health/live` 身份一致和 `/api/health/ready` 返回 `ready`。

当前已验证稳定服务是 Job `50521`、`anode16:18731`、提交 `c4f82c3d27a21932e2063a32910f1cdb960837f4`，release manifest SHA-256 为 `c70faea0e439765e9082c47d7d7024f515c0ee37c602416e9ff05e73fd6eeb45`。正式构建 Job `50517/anode01` 的专属日志证明后端 `515` 项通过（另有 4 项环境跳过）、前端 `149/149` 和 Vite `1870` 个模块；该短作业已从队列和 `sacct` 消失，因此不写成有记账的 `COMPLETED/0:0`。107 内部、4090 与 Windows 公网 `live/ready` 均返回新身份；Stage 10 只读 Job `50526/anode16` 输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节。旧 Job `46107/anode19` 经完整归属核验后受控停止，日志包含完整 Uvicorn shutdown，旧端口不可达，未触及共享账号下其他作业。下一次服务发布仍必须重新走 Slurm 构建、候选服务、relay 切换和只读验收，不能沿用本组 Job 冒充新版本证据。

PR #79 已于 `2026-08-31` 把公网 Operator 精确写入门禁合并为 `cf813fe9564b2d29864acce089d21413547b3d94`。该次变更只更新 4090 Nginx，没有重建或重启 FastAPI release；变更完成时服务保持为 Job `46107/anode19`。活动配置 `/home/Pwjb/.config/lmatelab-107cup-proxy/conf/nginx.conf` 为 `0600`，SHA-256 为 `88b62e7331dda744a0d0ede7c94921eeb197a6b83af0667105ed1932816c6b6b`；旧配置备份为 `backups/nginx.conf.before-public-operator-write.20260831T035304Z`，SHA-256 为 `6c6dafe1d3091684e372a3431b562a5d05a829e499479e88ba97bd7f377211dc`。候选、替换前临时文件和活动配置均通过 Nginx `1.18.0` 的 `nginx -t`，reload 后 `live/ready` 身份不变。

## 5. Stage 10 只读验收

新发布健康后，在登录节点运行：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/submit-stage10-acceptance.sh
```

助手要求源码检出干净、`HEAD == origin/main`、`current` 与同一提交一致，然后提交 `stage10-acceptance.slurm`。该作业只读复核固定成功/失败工作流、发布全量清单、SQLite 完整性、服务身份和 107 专用路由；它不会运行 VASP、`sbatch` 新工作流或 `scancel`。

成功标记为 `STAGE10_ACCEPTANCE_OK`，证据目录为 `evidence/stage10/acceptance-<job-id>`。机器门禁通过后仍需完成全新 Operator/Viewer 浏览器会话和三名成员复核，Stage 10 才能从 `PARTIAL` 变为 `DONE`。

## 6. 访问入口

- Operator：白名单网络可直接访问 `http://222.195.94.37:18733`，登录后可通过精确放行的工作流接口上传结构、保存草稿、提交、启动、取消或重试本人任务。Windows 本机 `http://127.0.0.1:21763` SSH 隧道保留为备用。
- Viewer：使用同一公网地址查看；后端角色门禁使其无法调用任何工作流写操作。
- 107 内部：服务状态记录的 `anodeXX:18731`，仅用于运行时核验，不作为公开地址。

Viewer 必须无法提交、取消、重试、创建 Agent 运行或访问敏感文件；Operator 也只能操作本人工作流和 Agent 数据。已登录的 Operator 和 Viewer 都可以从右上角用户菜单修改自己的密码；必须输入当前密码，新密码必须通过服务器密码策略且两次一致。修改成功后全部旧 JWT 立即失效，当前浏览器清除登录态并返回登录页；不要在聊天、终端命令、截图、录屏或 Git 中记录密码、LLM API Key 或 Qoder 凭据。公网入口当前为 HTTP，没有 TLS 传输加密，只应在可信的白名单网络使用强密码访问；它不应被描述为互联网级安全入口。返回 `403` 时先检查来源 IP、账号角色和请求是否在精确写接口中；返回 `502` 时检查 4090 到 107 的 ControlMaster 和转发状态；不要把任一网络入口故障误判成数据丢失。

## 7. Agent/Qoder Worker

Agent 页面和 API 由正式 Web 作业提供，排队中的 Agent 请求由独立 `P107-A100` Slurm Worker 处理。构建和候选 Web 服务通过后，在登录节点只运行短时提交/核对入口：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/submit-agent-worker.sh
cat /home/scc/pb23030683/lmatelab-107cup/runtime/agent-worker-recovery-state.json
cat /home/scc/pb23030683/lmatelab-107cup/runtime/agent-worker-state.json
```

控制器只在没有活动归属 Worker 时执行一次 `sbatch --parsable`。如果发现多个 Worker、同名但归属字段不匹配、调度查询失败或状态文件身份不一致，必须停止并保留证据，不能循环提交或自动取消。Worker 最长运行 4 天，读取 `config/runtime.env`，解析固定 `current` release 后进入无限空闲等待；它不是登录节点常驻进程。

`LMATELAB_COMPETITION_AGENT_PROVIDER=llm` 是当前默认生产路径，API Key 只写入 `config/secrets/llm-api-key` 且权限必须为 `0600`。公网 `http://222.195.94.37:18733` 没有 TLS，不允许提交 API Key；页面会禁用密钥输入并说明原因，但 API URL 和模型仍可单独保存。Operator 必须通过 HTTPS，或直达当前 107 计算节点 Web 服务的 Windows `127.0.0.1` SSH 隧道保存密钥。4090 Nginx 在设置路由覆盖写入实际入口 scheme，后端优先据此判定，不能用伪造 `Host: 127.0.0.1` 绕过。

Qoder 使用大陆版 `qodercn-agent-sdk==1.0.14` 和内置 `qoderclicn`；认证状态只保存在 `QODERCN_CONFIG_DIR` 指向的私有目录，PAT 环境变量名为 `QODERCN_PERSONAL_ACCESS_TOKEN`。网页“安装”动作只验证固定版本和 CLI；授权 URL 必须是 `qoder.cn` 或 `qoder.com.cn` 的带 challenge 设备授权页，全球版 `qoder.com` 链接会被拒绝。启用真实 Qoder 前，必须先在 107 计算节点验证外网、完成受控登录并把 `LMATELAB_QODER_REAL_NETWORK_AUTHORIZED` 显式改为 `1`。调度完成只能证明 Worker 运行，不能替代真实 Agent 响应、引用约束和 Viewer 只读验收。

Web 服务启动会在 Alembic 迁移前把两套现有 SQLite 用 Online Backup API 复制到 `backups/pre-migration`，文件名包含 Job ID 和 restart count，且禁止覆盖；迁移后要求两个 Alembic 配置都位于 head，并再次执行 `integrity_check`。候选服务或 Worker 失败时保留旧 `18733` relay 和 `18755`，不得静默重试。只有新 `18733` 通过 Operator/Viewer 和 Agent/Qoder 全流程后，才由进程所有者 `Pzxp` 停止 `18755`。

## 8. 回滚和恢复

发布失败时保持上一版本 `current` 和服务不变。若新服务健康检查失败，恢复器保留旧转发；只有候选完全就绪后才切换正式目标。需要暂停自动恢复时使用运行手册规定的权限 `0600` maintenance 标记，处理完再移除。

回滚只允许选择已存在且清单自检通过的 `releases/<commit>`，先运行隔离 `rollback-smoke.slurm`，不得直接用旧源码覆盖当前目录。服务停止或 `scancel` 前必须核对用户、JobName、Command、WorkDir、Account、Partition/QOS 和 LMateLab ledger，不能操作同一共享账号下的其他作业。完整恢复步骤见 [`service-recovery-runbook.md`](./service-recovery-runbook.md)。

## 9. 通用二维 PBE 输入策略

内置示例继续使用 `mos2_v1` 和既有 `Mo_sv/S` 固定哈希合同。Operator 上传的周期 POSCAR/CIF 使用 `pbe_2d_v1`：POSCAR 保留其元素头顺序，CIF 按 IUPAC 元素顺序确定性分组，服务把该规范顺序写入 `POTCAR.spec`；VASPKIT 103 在计算节点把实际推荐名写入 `POTCAR.resolved`。因此同一 CIF 的原子行顺序变化不会把 `MoS2` 显示为 `S2Mo`，也不会导致 POTCAR 顺序漂移。Git、数据库和 API 都不保存 POTCAR 内容或赝势源路径。

VASP stage 作业在计算节点内执行以下固定步骤：

```text
最终 POSCAR 元素顺序
  -> POTCAR.spec（请求元素，例如 W / S）
  -> VASPKIT 103
  -> POTCAR.resolved（实际推荐赝势，例如 W_sv / S）
  -> /home/scc/pb23030683/POTCAR/PBE/<resolved>/POTCAR
  -> 与解析后源文件顺序拼接结果逐字节核对
  -> POTCAR + 请求/解析映射 + 源哈希 + VASPKIT 版本证据

已验收 SCF POSCAR + CHGCAR
  -> VASPKIT 302
  -> KPATH.in 格式与大小门禁
  -> 校验真实四列高对称点标签，例如 kx ky kz GAMMA
  -> KPOINTS + band-path-generator.txt
  -> BAND VASP
```

允许范围为全周期 POSCAR/CIF、最大 `1 MiB`、最多 `200` 原子和 `16` 种元素，以及非磁性、无 SOC、无 DFT+U、无杂化泛函的 PAW-PBE 基线。应用层不维护元素白名单；只要结构元素合法且 107 的 VASPKIT/PBE 库能够解析对应赝势，103 就会生成并复核 POTCAR。页面能够接受结构不代表默认参数对所有金属、磁性材料、强关联材料、分子或三维体相都科学充分；超出范围时应新增经过评审的版本化模板，不能绕过当前策略修改命令或赝势路径。

任何通用化发布前，先通过 Slurm 短作业验证真实 VASPKIT `103` 和 `302`，但不运行 VASP；随后才允许完整 Slurm 构建、候选服务和 Operator 工作流验证。预检、构建或候选任一失败都必须保留旧稳定服务和原始证据。
