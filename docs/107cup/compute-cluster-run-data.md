# 107 杯算力集群运行数据说明

统计快照：`2026-09-05T10:56:22+08:00`

只读复核：`2026-09-05T11:29:49+08:00` 再次查询 107，根日志仍为 `374` 个文件、`187` 个唯一根 Job ID，队列中仍只有服务 Job `54176`，没有新增 LMateLab 作业；本次复核没有执行 `sbatch`、`scancel` 或服务变更。

本文是“算力平台赛道必须另附 Slurm 作业日志、资源使用、排队及运行时间等算力集群运行数据说明”的项目交付件。逐作业明细见 [`artifacts/slurm-job-ledger.csv`](./artifacts/slurm-job-ledger.csv)，本地日志附件包见第 9 节。

## 1. 结论

LMateLab 107 杯项目从首次环境探测到本次快照共确认 `218` 个真实 Slurm Job ID：

| 来源 | 作业数 | 说明 |
|---|---:|---|
| 项目根 `logs/` | 187 | 构建、服务、快照、测试、预检和验收作业 |
| Stage 6 smoke 子作业 | 4 | `38625-38628`，日志位于 Stage 6 私有证据目录 |
| 正式数据库 VASP attempt | 26 | 6 条工作流的 Relax/SCF/BAND/DOS attempt |
| Stage 7 证据目录专属作业 | 1 | 只读核验 Job `40274` |
| **合计** | **218** | Job ID 去重后无交叉 |

Slurm 终态分类为：

| 调度分类 | 数量 | 解释 |
|---|---:|---|
| `completed` | 138 | 作业到达成功终止标记；证据等级见 CSV |
| `failed` | 32 | 包含真实缺陷、故意失败探针和 1 个 VASP 调度失败 |
| `cancelled` | 47 | 其中 44 个是服务切换后的受控停止，不能算项目失败 |
| `running` | 1 | 快照时稳定服务 Job `54176` |
| **合计** | **218** | 与来源总数一致 |

这里的 `completed` 只表示 Slurm/批脚本层结束成功，不自动表示 VASP 科学结果有效。VASP 科学门禁单独统计为 `21` 个 accepted、`4` 个 rejected、`1` 个因调度失败未进入科学验收。

## 2. 统计口径

满足以下条件之一才计入总账：

- 根日志文件名包含项目专属真实 Job ID；
- Stage 6 保存的 `scontrol --json` 记录给出真实 Job ID；
- 正式 `workflow_attempts.slurm_job_id` 有值，并有保存的调度观察；
- 项目证据目录和验收文档共同固定了真实 Job ID、节点与终态。

明确排除：

| 标识 | 排除原因 |
|---|---|
| `38285` | `sbatch --test-only` 输出，不产生真实作业 |
| `73001` | 单元测试 Fake Slurm Job ID |
| `30121/30147` | 当前 `sacct` 返回的其他作业，不属于 LMateLab |
| 调度前 `422/403` | 输入或权限门禁在 `sbatch` 前拒绝，没有 Job ID |
| `cancelled_before_start` | 未创建 attempt、未调用 `sbatch/scancel`，因此不是 Slurm 作业 |

每个作业同时保留三种不同结论：

1. `scheduler_result`：Slurm 层 `completed/failed/cancelled/running`；
2. `functional_result`：构建、服务、测试、取消或解析目标是否实现；
3. `scientific_result`：只用于 VASP 的 `accepted/rejected/not_evaluated`。

这使故意失败 Job `38626` 可以同时记录为“Slurm failed”和“适配器失败分支验收通过”，也使 Slurm `COMPLETED/0:0` 但科学门禁未通过的 VASP 作业不会被伪报为成功结果。

CSV 同时提供两套证据定位：`remote_evidence_files` 是 107 上以 `/home/scc/pb23030683/lmatelab-107cup` 开头的完整绝对路径，便于登录服务器后直接核对；`attachment_files` 是解压评审 ZIP 后相对于附件根目录的可移植路径。两列均以分号分隔多个文件，不使用仅在开发者 Windows 电脑上有效的本地绝对路径。

## 3. 按功能分类

| 功能类别 | 总数 | Completed | Failed | Cancelled | Running |
|---|---:|---:|---:|---:|---:|
| 构建与不可变发布 | 49 | 40 | 9 | 0 | 0 |
| 网页服务与预览服务 | 48 | 0 | 3 | 44 | 1 |
| 快照与溯源 | 38 | 34 | 4 | 0 | 0 |
| VASP 真实计算 | 26 | 25 | 1 | 0 | 0 |
| Stage 10 交付验收 | 11 | 11 | 0 | 0 | 0 |
| 访问与角色 | 7 | 7 | 0 | 0 | 0 |
| VASP/VASPKIT 预检 | 6 | 5 | 1 | 0 | 0 |
| Slurm 适配器 | 6 | 2 | 2 | 2 | 0 |
| VASP 工作流控制/诊断 | 5 | 2 | 3 | 0 | 0 |
| 环境探针 | 5 | 3 | 1 | 1 | 0 |
| 测试与诊断 | 5 | 3 | 2 | 0 | 0 |
| 回滚与恢复 | 4 | 2 | 2 | 0 | 0 |
| 结果与证据包 | 4 | 2 | 2 | 0 | 0 |
| Slurm 底层诊断 | 2 | 1 | 1 | 0 | 0 |
| 未开始工作流取消 | 2 | 1 | 1 | 0 | 0 |

## 4. 失败作业

全部 `32` 个 Slurm 失败按用途归类如下，原始 stdout/stderr 均保留：

| 类别 | 数量 | Job ID |
|---|---:|---|
| 构建与发布 | 9 | `32598, 33979, 37391, 37689, 40053, 40096, 41039, 41064, 46098` |
| 网页服务端口冲突 | 3 | `37713, 40079, 40784` |
| 快照与溯源合同 | 4 | `36592, 36596, 40087, 41680` |
| 工作流控制/诊断 | 3 | `40253, 40269, 40270` |
| Stage 8 结果验收 | 2 | `40304, 40306` |
| 回滚演练 | 2 | `33998, 34001` |
| 通用工作流合同测试 | 2 | `46092, 46093` |
| Slurm 适配器 | 2 | `38598, 38626` |
| 环境/Slurm 探针 | 2 | `32599, 40054` |
| VASP 调度失败 | 1 | `40090` |
| VASPKIT 通用预检 | 1 | `46081` |
| 未开始工作流取消包装 | 1 | `50529` |

这些失败不是被删除的试错记录。典型闭环包括：

- `33979` 缺少 manifest，失败发布未切换 `current`；后续 `34005` 回滚 smoke 成功。
- `38598` 暴露 Slurm spool 下 `__file__` 定位错误；修复后的 `38623` 及子作业完成成功、故意失败、取消和归属拒绝闭环。
- `40090` 在排队 `520.915 s` 后以 `FAILED/1:0` 终止，没有伪造 VASP 科学结论；同一工作流经受控修复和新 attempt 最终完成四步。
- `40163/40191/40213/40265` 虽然 Slurm 为 `COMPLETED/0:0`，仍分别因 VASPKIT 版本、POTCAR 标题、费米能级和电子不收敛被科学门禁拒绝。
- `46081/46092/46093/46098` 分别暴露 VASPKIT 推荐赝势、shell、8 KiB 边界和通用结构合同问题；后续修复作业保留独立新 Job ID。

## 5. 取消作业

`47` 个取消作业不能合并解释：

| 类型 | 数量 | 结论 |
|---|---:|---|
| 已健康服务受控停止 | 44 | 新候选健康、relay 切换并核验归属后执行；功能层为 `passed_then_controlled_stop` |
| Stage 6 自有取消探针 `38627` | 1 | 预期取消成功，验证 `scancel` 和终态对账 |
| Stage 6 非归属控制 `38628` | 1 | 适配器正确拒绝越权；smoke harness 只清理自己创建的控制作业 |
| 环境探针 `32601` | 1 | 完成前取消，不算功能成功 |

服务 Job 的 Slurm `CANCELLED` 与服务故障不同。44 个服务都先出现 Uvicorn 正常启动/健康请求，再有 slurmd 的明确取消记录和完整 shutdown；3 个真正失败的服务 Job 则是端口冲突，列在上一节。

## 6. VASP 计算数据

### 6.1 数量与科学结论

正式数据库共保留 `26` 个 VASP attempt，覆盖 `6` 条工作流：5 条完成四步闭环，1 条故意在 SCF 科学失败后阻断 BAND/DOS。

| 材料 | Job 数 | 科学通过 | 科学拒绝 | 调度失败 |
|---|---:|---:|---:|---:|
| MoS2 | 18 | 13 | 4 | 1 |
| WS2 | 4 | 4 | 0 | 0 |
| BN | 4 | 4 | 0 | 0 |

| 步骤 | Job 数 | 科学通过 | 科学拒绝 | 调度失败 |
|---|---:|---:|---:|---:|
| Relax | 9 | 6 | 2 | 1 |
| SCF | 7 | 5 | 2 | 0 |
| BAND | 5 | 5 | 0 | 0 |
| DOS | 5 | 5 | 0 | 0 |

五条完整成功链为：

- MoS2：`40212 -> 40250 -> 40251 -> 40252`
- MoS2：`41899 -> 41900 -> 41901 -> 41902`
- MoS2：`46049 -> 46050 -> 46051 -> 46052`
- WS2：`46334 -> 46335 -> 46336 -> 46337`
- BN：`50820 -> 50821 -> 50823 -> 50824`

故意失败链为 `40264 -> 40265 -> null -> null`；SCF 原因为 `electronic_not_converged`，BAND/DOS 没有 attempt、Job ID 或资源消耗。

### 6.2 资源、排队和运行

每个 VASP Job 的固定请求为：

```text
partition=P107-RTX5090
nodes=1, ntasks=1, cpus-per-task=16
gres=gpu:RTX5090:1
memory=32G
time-limit=06:00:00
```

26 个 VASP Job 的时间覆盖完整：

| 指标 | 已知数 | 合计 | 平均 | 最大 |
|---|---:|---:|---:|---:|
| 排队时间 | 26 | `624.809 s` | `24.031 s` | `520.915 s`，Job `40090` |
| Slurm 运行时间 | 26 | `949 s` | `36.500 s` | `65 s`，Job `41901` |
| VASP `/usr/bin/time` wall | 25 | `934.170 s` | `37.367 s` | `64.620 s`，Job `41901` |
| 进程树峰值 RSS | 25 | - | `2.250 GiB` | `2.441 GiB`，Job `46051` |

Job `40090` 在 runner 建立 `runtime-time.txt` 前失败，因此只有 Slurm 时间，没有 VASP wall/RSS。排队时间用数据库 `submission_accepted` 事件减 Slurm `StartTime`；Slurm 起始时间只有秒精度，绝对值小于 1 秒的负偏差按 `0` 记录，不伪造亚秒排队值。

## 7. 其他资源配置

当前受控 Slurm 脚本的资源合同如下。它说明当前/最终提交合同，不替代已经清理的历史 `sacct` 实际用量：

| 作业类型 | 分区 | CPU | 内存 | GPU 请求 | 时限 |
|---|---|---:|---:|---:|---:|
| 正式构建/预览构建 | `P107-RTX5090` | 4 | 12 GiB | 无 | 45 min |
| 正式网页服务 | `P107-A100` | 2 | 8 GiB | 无 | 4 d |
| 预览网页服务 | `P107-RTX5090` | 2 | 8 GiB | 无 | 8 h 或 2 d |
| 快照/Viewer provision | `P107-A100` | 1 | 2 GiB | 无 | 5 min |
| Stage 6 子探针 | `P107-RTX5090` | 1 | 256 MiB | 无 | 3 min |
| VASP/VASPKIT 预检 | `P107-RTX5090` | 1 | 1-2 GiB | 无 | 5 min |
| Stage 8/10 只读验收 | `P107-A100` | 2 | 8 GiB | 无 | 20 min |
| VASP | `P107-RTX5090` | 16 | 32 GiB | 1 x RTX5090 | 6 h |

位于 GPU 分区不等于分配 GPU；只有 VASP runner 明确请求 `gres=gpu:RTX5090:1`。构建、服务、快照和只读验收均未申请 GPU。

## 8. 时间数据覆盖与限制

总账中 `38/218` 个作业有可复核排队时间，`43/218` 个作业有可复核运行时间。覆盖来源为正式 VASP 事件账本、Stage 6 保存的 `scontrol --json`、少量现场 `scontrol` 快照和项目验收文档。

107 当前 `sacct` 不能恢复 LMateLab 历史作业：早期证据记录过连接 `localhost:6819` 被拒绝，本次查询只返回无关 Job `30121/30147`。短作业也会很快从 `scontrol` 清理。因此其余作业的排队时间、实际 CPU/GPU 利用率和 MaxRSS 均写为空或 `unavailable`，没有用日志 mtime、相邻 Job ID 或脚本时限估算。

对于缺失历史记账的作业，调度分类证据分为：

- 80 个：实时/保存的 `scontrol`、数据库调度观察、slurmd 取消记录或固定验收文档；
- 138 个：成对 stdout/stderr 中的成功终止标记或明确错误终止记录。

后一类足以说明项目执行结果，但不冒充已恢复的 `sacct` 记账。CSV 的 `scheduler_evidence` 字段逐条标明证据等级。

## 9. 日志附件与完整性

仓库内提交：

- 本文；
- `artifacts/slurm-job-ledger.csv`，218 行逐 Job 总账；
- `deploy/107cup/generate-slurm-job-ledger.py`，用于从冻结快照重建 CSV；
- `artifacts/manifest.sha256`，固定上述交付件。

Windows 本地另保存评审附件目录：

```text
D:/Documents/matflow项目/LMateLab-107Cup-evidence/
compute-cluster-run-data-20260905/submission-attachment
```

附件包含：

- 187 个根 Job 的 374 个 stdout/stderr 文件；
- 4 个 Stage 6 子作业的调度 JSON 和专属日志；
- Job `40274` 的 stdout/stderr；
- 26 个 VASP attempt 的 stdout/stderr、`runtime-time.txt`、`vasp-exit-code.txt` 和 Job receipt；
- 脱敏 VASP ledger、总账副本、附件 README 和逐文件 SHA-256。

附件不包含正式数据库、JWT、密码、Gitea Token、SSH key、二次验证码、OUTCAR、WAVECAR、CHGCAR 或 POTCAR。POTCAR 尤其不得作为比赛附件再分发。

最终附件统计：

| 项目 | 值 |
|---|---|
| 附件目录文件数 | `563` |
| 附件目录未压缩大小 | `16,981,635 bytes` |
| `SHA256SUMS.txt` 覆盖文件数 | `562`（不包含清单自身） |
| 压缩包 | `lmatelab-107cup-compute-cluster-run-data-20260905.zip` |
| 压缩包大小 | `1,881,177 bytes` |
| 压缩包 SHA-256 | `17db1b8646239cec4881a3e2ba93bca4b5acd7b51eeb89c7bd9b930dc36bf997` |

压缩包自身哈希保存在同目录的 `lmatelab-107cup-compute-cluster-run-data-20260905.zip.sha256`，避免自引用；包内 `SHA256SUMS.txt` 用于逐文件复核。

## 10. 快照时运行服务

快照时唯一运行中的 LMateLab 作业为：

```text
JobId=54176
JobName=lmatelab-web
State=RUNNING
Partition=P107-A100
Node=anode18
ReqTRES=cpu=2,mem=8G,node=1
SubmitTime=2026-09-05T10:56:02+08:00
StartTime=2026-09-05T10:56:02+08:00
QueueTime=0 s
Release=c4f82c3d27a21932e2063a32910f1cdb960837f4
```

该 Job 由既有服务恢复机制在 SSH 二次认证恢复后提交，不是本次统计为制造证据而提交的作业。快照时内部 live/ready 均通过；本次审计没有取消、重启或修改它。
