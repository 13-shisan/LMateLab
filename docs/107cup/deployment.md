# 107 杯部署与恢复说明

更新时间：`2026-08-21`

## 1. 部署边界

本项目不使用 Docker，也不在 107 登录节点执行依赖安装、前后端构建、测试、FastAPI 常驻服务或 VASP 计算。登录节点只做短时的只读 Git 核对、`sbatch` 提交和针对明确 Job ID 的调度查询。源码、Python/Node 环境、SQLite、工作流、VASP attempt、结果和证据都位于：

```text
/home/scc/pb23030683/lmatelab-107cup
```

4090 `222.195.94.37` 只提供用户态 SSH 转发、Nginx Viewer 入口和 IP 白名单，不保存竞赛业务数据库，不运行 FastAPI 或 VASP。Windows Operator 使用独立 SSH 隧道。4090 入口失效只影响访问，不改变 107 内的数据和作业。

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

服务通过 `service.slurm` 运行在 `P107-A100` 计算节点。发布后使用恢复入口，它会先核对已有 Job、状态文件和目标端口，并只在必要时提交一个候选：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/submit-service.sh
bash deploy/107cup/verify-runtime.sh
```

正式状态以 `runtime/service-state.json` 为原子来源，同时与 `service-job-id`、`service-node`、`service-port`、`service-commit` 和 `service-manifest-sha256` 逐项一致。健康检查必须同时满足 `/api/health/live` 身份一致和 `/api/health/ready` 返回 `ready`。

当前 Stage 10 开始前的已验证基线是 Job `41044`、`anode16:18731`、提交 `e565851ff3ac67d8c143331b4dee175d82b6d04c`。Stage 10 最终证据必须用新合并的固定 `main` 发布替换这组基线，不能直接沿用旧 Job 作为最终发布证据。

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
- Viewer：`http://222.195.94.37:18733`，经过 4090 白名单和只读代理，供队友或评委查看。
- 107 内部：服务状态记录的 `anodeXX:18731`，仅用于运行时核验，不作为公开地址。

Viewer 必须无法提交、取消、重试或访问敏感文件。公网入口返回 `403` 时先检查来源 IP 是否在白名单；返回 `502` 时检查 4090 到 107 的 ControlMaster 和转发状态；不要把任一网络入口故障误判成数据丢失。

## 7. 回滚和恢复

发布失败时保持上一版本 `current` 和服务不变。若新服务健康检查失败，恢复器保留旧转发；只有候选完全就绪后才切换正式目标。需要暂停自动恢复时使用运行手册规定的权限 `0600` maintenance 标记，处理完再移除。

回滚只允许选择已存在且清单自检通过的 `releases/<commit>`，先运行隔离 `rollback-smoke.slurm`，不得直接用旧源码覆盖当前目录。服务停止或 `scancel` 前必须核对用户、JobName、Command、WorkDir、Account、Partition/QOS 和 LMateLab ledger，不能操作同一共享账号下的其他作业。完整恢复步骤见 [`service-recovery-runbook.md`](./service-recovery-runbook.md)。
