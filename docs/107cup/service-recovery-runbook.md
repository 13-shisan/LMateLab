# 107 杯网页服务与转发恢复运行手册

更新时间：`2026-08-21`

## 1. 目标和边界

本手册只管理 107 杯网页服务及其 4090 网络入口：

```text
4090 用户 cron（每分钟一次短命令）
  -> 已认证 SSH ControlMaster
  -> 107 登录节点短时 recover-service.sh
  -> Slurm 服务 Job（计算节点）
  -> 4090 127.0.0.1:18740
  -> 用户态 Nginx 0.0.0.0:18733
```

固定边界：

- 107 登录节点没有 Uvicorn、Vite、Celery、Redis 或恢复守护进程。
- 107 恢复命令只执行文件校验、`scontrol`、最多一次 `sbatch` 和有超时的健康检查。
- 4090 cron 每次运行有文件锁，不并发，不保存竞赛数据库、输入、输出或证据。
- 新服务必须先在临时转发端口 `18742` 通过 live/ready 身份检查，才允许切换正式 `18740`。
- `18740` 切换失败时恢复原节点；未知旧转发、外来 Slurm Job、异常状态文件和耗尽的三次重试预算全部失败关闭。
- SSH 主连接失效时不绕过二次验证，状态记录为 `ssh_authentication_required`，由 Operator 手工重新认证。
- 不使用 Docker，不需要 root，不修改系统 Nginx、Slurm 配置或其他用户作业。

## 2. 文件和状态

107：

```text
/home/scc/pb23030683/projects/LMateLab-107Cup/deploy/107cup/recover-service.sh
/home/scc/pb23030683/lmatelab-107cup/runtime/service-state.json
/home/scc/pb23030683/lmatelab-107cup/runtime/service-recovery-state.json
/home/scc/pb23030683/lmatelab-107cup/runtime/service-recovery.lock
```

4090：

```text
/home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh
/home/Pwjb/.config/lmatelab-107cup-proxy/bin/reauth-control-master.sh
/home/Pwjb/.config/lmatelab-107cup-proxy/state/forward-state.json
/home/Pwjb/.config/lmatelab-107cup-proxy/state/recovery-status.json
/home/Pwjb/.config/lmatelab-107cup-proxy/state/maintenance
/home/Pwjb/.config/lmatelab-107cup-proxy/log/recovery.log
```

`service-state.json` 只有在新 Uvicorn 进程通过本机 live/ready 后才原子发布。它是自动恢复的正式服务身份；旧的六个 `service-*` 文件继续同步写入，供既有快照和验收脚本使用。

## 3. 自动恢复状态

107 恢复结果只有四种：

| 状态 | 含义 | 行为 |
|---|---|---|
| `ready` | 固定归属 Job 正在运行且身份、release、manifest、live/ready 一致 | 不提交新 Job |
| `waiting` | 候选 Job 正在排队/启动、健康尚未就绪或处于重试冷却 | 不重复提交 |
| `submitted` | 原服务已不存在，锁内提交了唯一候选 Job | 保存候选 Job ID、次数和时间 |
| `blocked` | 调度器不可用、归属不匹配、状态损坏或三次重试耗尽 | 不提交、不取消，等待人工检查 |

服务 Job 发布成功时清空候选并重置重试预算。候选终止后至少等待 300 秒才允许重试，连续最多三次；不存在无限 `sbatch` 循环。

4090 转发恢复状态额外包括：

- `adopted`：首次安装时采纳已经健康的正式 `18740`，不重绑端口；
- `switched`：新目标已通过 `18742` 验证，并完成 `18740` 切换；
- `maintenance`：Operator 明确暂停自动恢复；
- `ssh_authentication_required`：ControlMaster 已失效，需要二次验证。

## 4. 安装

源码 PR 合并且 107 checkout 同步后，从 107 checkout 读取三个 relay 文件并安装到 4090 用户目录。安装器会先通过现有 `18740` 健康身份创建初始 `forward-state.json`，然后只替换自己的 cron 标记块，保留其他 cron 项：

```bash
bash deploy/107cup/relay/install-recovery.sh
```

实际安装目标是 4090，因此部署时应先把 `deploy/107cup/relay/` 的四个文件传到 4090 的私有临时目录，再在 4090 执行安装器。安装完成后 `crontab -l` 必须包含且只包含一个：

```text
# BEGIN LMATELAB 107CUP RELAY RECOVERY
...
# END LMATELAB 107CUP RELAY RECOVERY
```

cron 的 `@reboot` 不能替代二次验证；它只会记录需要重新认证。

## 5. 日常检查

107 短时检查：

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
bash deploy/107cup/recover-service.sh
cat /home/scc/pb23030683/lmatelab-107cup/runtime/service-state.json
squeue -j "$(cat /home/scc/pb23030683/lmatelab-107cup/runtime/service-job-id)"
```

4090 短时检查：

```bash
cat /home/Pwjb/.config/lmatelab-107cup-proxy/state/recovery-status.json
tail -n 50 /home/Pwjb/.config/lmatelab-107cup-proxy/log/recovery.log
curl --fail --max-time 10 http://127.0.0.1:18733/api/health/live
curl --fail --max-time 10 http://127.0.0.1:18733/api/health/ready
```

`recovery-status.json` 中的 Job、node、commit 和 manifest 必须与 107 `service-state.json` 一致。

## 6. 手工启动或恢复

SSH ControlMaster 有效时，在 4090 执行一次守护即可完成“检查、必要时提交、候选健康后切换”：

```bash
/bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh
```

若状态为 `ssh_authentication_required`，在可输入二次验证码的 4090 交互终端执行：

```bash
/bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/reauth-control-master.sh
```

该脚本只在旧 master 确认失效后移除陈旧 socket，随后使用固定专用密钥重新建立 96 小时 ControlPersist。每分钟 cron 会持续使用该连接，因此正常运行时不会频繁要求二次验证；4090 重启、网络长时间中断或认证失效后仍必须人工输入一次验证码。

## 7. 受控停止

### 7.1 暂停自动恢复

在 4090 创建私有 maintenance 标记：

```bash
install -m 600 /dev/null \
  /home/Pwjb/.config/lmatelab-107cup-proxy/state/maintenance
/bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh
```

确认状态为 `maintenance` 后，才允许停止网页服务。

### 7.2 核对归属并停止

在 107 读取正式 Job ID，并同时核对用户、作业名、命令、工作目录、账号、分区和 QOS：

```bash
job_id=$(cat /home/scc/pb23030683/lmatelab-107cup/runtime/service-job-id)
scontrol show job -o "$job_id"
scancel "$job_id"
```

不得从浏览器或用户输入接收 Job ID。若任一归属字段不匹配，禁止 `scancel`。

停止后应验证：

```bash
curl --fail --connect-timeout 2 --max-time 5 \
  http://anodeXX:18731/api/health/live
```

该命令必须失败；4090 `18733` 也应失败关闭或返回上游不可用，不得切换到原 4090 LMateLab。

## 8. 恢复受控停止

在 4090 删除明确的 maintenance 普通文件，然后立即执行守护：

```bash
unlink /home/Pwjb/.config/lmatelab-107cup-proxy/state/maintenance
/bin/bash /home/Pwjb/.config/lmatelab-107cup-proxy/bin/ensure-forward.sh
```

第一次通常返回 `submitted` 或 `waiting`。候选 Slurm Job 发布健康状态后，下一次守护返回 `ready` 或 `switched`。最终同时验证：

```text
107 service-state.json
107 scontrol/squeue
4090 forward-state.json
4090 recovery-status.json
4090 127.0.0.1:18733 live/ready
Windows 127.0.0.1:21763 live/ready
公网 222.195.94.37:18733 live/ready
```

## 9. 故障处理

- `scheduler_unavailable`：不提交。只检查 Slurm；不得删除状态文件规避失败。
- `service_ownership_mismatch` 或 `candidate_ownership_mismatch`：不提交、不取消，保留文件和 `scontrol` 原始输出。
- `retry_budget_exhausted`：检查三个候选 Job 的 `.out/.err`，修复原因后由 Operator 备份并重置恢复状态；不得直接循环 `sbatch`。
- `unknown_existing_forward`：现有 `18740` 身份未被采纳，禁止猜测取消参数；先核对现有 forward，再执行 `--adopt-current`。
- `candidate_unavailable` 或 `candidate_identity_mismatch`：旧 `18740` 保持不变。
- `forward_rollback_failed`：公网入口按失败关闭处理，停止自动操作并人工核对 SSH master 上的 forward。
- `ssh_authentication_required`：运行二次验证脚本；不得复制密码、验证码或私钥到 cron、仓库或状态文件。

## 10. Stage 3 完成证据

Stage 3 只有同时保存以下证据后才能改为 `DONE`：

- 107 构建 Job 和新 release manifest；
- 首次健康服务状态原子发布；
- 4090 cron 保留其他条目且唯一安装本项目标记块；
- 受控停止期间计算节点端口和公网入口确实不可用；
- 移除 maintenance 后只提交一个候选 Job；
- 新 Job 健康后 `18742 -> 18740` 切换成功，旧转发没有在候选失败时被破坏；
- Windows、4090 内部和公网入口返回同一 Job、node、commit 和 manifest；
- 登录节点没有 LMateLab 常驻进程；
- SSH 失效场景明确记录为需人工二次验证。
