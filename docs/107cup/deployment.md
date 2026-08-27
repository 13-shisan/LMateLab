# 107 杯部署与恢复说明

更新时间：`2026-08-27`

## 1. 部署边界

本项目不使用 Docker，也不在 107 登录节点执行依赖安装、前后端构建、测试、FastAPI 常驻服务或 VASP 计算。登录节点只做短时的只读 Git 核对、`sbatch` 提交和针对明确 Job ID 的调度查询。源码、Python/Node 环境、SQLite、工作流、VASP attempt、结果和证据都位于：

```text
/home/scc/pb23030683/lmatelab-107cup
```

4090 `222.195.94.37` 只提供用户态 SSH 转发、Nginx Viewer 入口和 IP 白名单，不保存竞赛业务数据库，不运行 FastAPI 或 VASP。公网代理默认只允许 GET，认证例外精确限制为登录和当前用户修改自己密码的 POST；它不能放行业务写接口。Windows Operator 使用独立 SSH 隧道。4090 入口失效只影响访问，不改变 107 内的数据和作业。

## 2. 固定目录

| 用途 | 路径 |
|---|---|
| 只读源码检出 | `/home/scc/pb23030683/projects/LMateLab-107Cup` |
| 固定发布 | `/home/scc/pb23030683/lmatelab-107cup/releases/<commit>` |
| 当前发布 | `/home/scc/pb23030683/lmatelab-107cup/current` |
| Python/Node 环境 | `/home/scc/pb23030683/lmatelab-107cup/envs` |
| 正式数据库 | `/home/scc/pb23030683/lmatelab-107cup/data/db` |
| 工作流和 attempt | `/home/scc/pb23030683/lmatelab-107cup/data/workflows` |
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

`submit-build.sh` 只提交 `build.slurm`。依赖安装、后端回归、前端测试和 Vite 构建均在 `P107-RTX5090` 计算节点完成。构建失败不得切换 `current`；构建成功后形成不可变 `releases/<commit>`，校验 `manifest.txt` 和 `manifest.sha256` 后原子切换。

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

当前已验证稳定服务是 Job `43737`、`anode16:18731`、提交 `b58cfe40be19fbd7543ca970a728aba89e69386b`，release manifest SHA-256 为 `cd99bd2090d57974526061b34ecd06534ef1266e1ae617aab0f2c3249441bc7f`。正式构建 Job `43736/anode01` 为 `COMPLETED/0:0`；4090、Windows Operator 和公网 `live/ready` 均返回新身份；Stage 10 只读 Job `43738/anode16` 为 `COMPLETED/0:0`，输出 `STAGE10_ACCEPTANCE_OK` 且 stderr 为 0 字节。旧 Job `43726/anode18` 经完整归属核验后已受控停止，旧端口不可达，未触及共享账号下其他作业。4090 活动 Nginx 配置的 IP 白名单、`0600` 权限和精确 `POST /api/auth/change-password` 例外均未修改。下一次发布仍必须重新走 Slurm 构建、候选服务、relay 切换和只读验收，不能沿用本组 Job 冒充新版本证据。

## 5. Stage 10 只读验收

新发布健康后，在登录节点运行：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/submit-stage10-acceptance.sh
```

助手要求源码检出干净、`HEAD == origin/main`、`current` 与同一提交一致，然后提交 `stage10-acceptance.slurm`。该作业只读复核固定成功/失败工作流、发布全量清单、SQLite 完整性、服务身份和 107 专用路由；它不会运行 VASP、`sbatch` 新工作流或 `scancel`。

成功标记为 `STAGE10_ACCEPTANCE_OK`，证据目录为 `evidence/stage10/acceptance-<job-id>`。机器门禁通过后仍需完成全新 Operator/Viewer 浏览器会话和三名成员复核，Stage 10 才能从 `PARTIAL` 变为 `DONE`。

## 6. 访问入口

- Operator：Windows 本机 `http://127.0.0.1:21763`，通过 Windows 到 107 的 SSH 隧道访问，只在需要受控写操作时使用。
- Viewer：`http://222.195.94.37:18733`，经过 4090 白名单和受限代理，供队友或评委查看；除登录和修改本人密码外，业务接口仍为只读。
- 107 内部：服务状态记录的 `anodeXX:18731`，仅用于运行时核验，不作为公开地址。

Viewer 必须无法提交、取消、重试或访问敏感文件。已登录的 Operator 和 Viewer 都可以从右上角用户菜单修改自己的密码；必须输入当前密码，新密码必须通过服务器密码策略且两次一致。修改成功后全部旧 JWT 立即失效，当前浏览器清除登录态并返回登录页；不要在聊天、终端命令、截图、录屏或 Git 中记录密码。公网入口返回 `403` 时先检查来源 IP 是否在白名单或请求是否超出精确认证例外；返回 `502` 时检查 4090 到 107 的 ControlMaster 和转发状态；不要把任一网络入口故障误判成数据丢失。

## 7. 回滚和恢复

发布失败时保持上一版本 `current` 和服务不变。若新服务健康检查失败，恢复器保留旧转发；只有候选完全就绪后才切换正式目标。需要暂停自动恢复时使用运行手册规定的权限 `0600` maintenance 标记，处理完再移除。

回滚只允许选择已存在且清单自检通过的 `releases/<commit>`，先运行隔离 `rollback-smoke.slurm`，不得直接用旧源码覆盖当前目录。服务停止或 `scancel` 前必须核对用户、JobName、Command、WorkDir、Account、Partition/QOS 和 LMateLab ledger，不能操作同一共享账号下的其他作业。完整恢复步骤见 [`service-recovery-runbook.md`](./service-recovery-runbook.md)。

## 8. 通用二维 PBE 输入策略

内置示例继续使用 `mos2_v1` 和既有 `Mo_sv/S` 固定哈希合同。Operator 上传的周期 POSCAR/CIF 使用 `pbe_2d_v1`，服务只把规范元素顺序写入 `POTCAR.spec`；VASPKIT 103 在计算节点把实际推荐名写入 `POTCAR.resolved`。Git、数据库和 API 都不保存 POTCAR 内容或赝势源路径。

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

允许范围为全周期 POSCAR/CIF、最大 `1 MiB`、最多 `200` 原子和 `16` 种元素，以及非磁性、无 SOC、无 DFT+U、无杂化泛函的 PAW-PBE 基线。页面能够接受结构不代表默认参数对所有金属、磁性材料、强关联材料、分子或三维体相都科学充分；超出范围时应新增经过评审的版本化模板，不能绕过当前策略修改命令或赝势路径。

任何通用化发布前，先通过 Slurm 短作业验证真实 VASPKIT `103` 和 `302`，但不运行 VASP；随后才允许完整 Slurm 构建、候选服务和 Operator 工作流验证。预检、构建或候选任一失败都必须保留旧稳定服务和原始证据。
