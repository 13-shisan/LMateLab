# 107 杯恢复、安全与回归运行手册

## 1. 目的与边界

本手册只适用于 107 杯仓库 `107-team/LMateLab` 的 Stage 9。目标是在不破坏正式服务和 Stage 7/8 科学证据的前提下，验证服务重启、Slurm 失联、数据库失败、取消竞态、网关失效、发布回滚和恶意输入均失败关闭。

固定边界：

- 正式服务 Job `40832`、正式端口 `18731`、正式数据库和正式 `current` 不用于故障注入。
- Stage 7 成功/失败 VASP attempt 及 Stage 8 证据包只读，不重跑 VASP。
- 所有故障注入使用假 Slurm、临时 SQLite、临时 workflow root 或独立 Slurm Job。
- 107 登录节点只执行短时 `git`、`squeue`、`sacct`、`sbatch` 和有超时的健康检查。
- 测试、构建、回滚 smoke 和隔离服务运行在 Slurm 计算节点。
- 4090 只验证转发和白名单，不保存数据库、输入、输出或证据。
- 不使用 Docker，不加入 Agent、机器学习、任意材料或任意命令功能。

## 2. Stage 9 验收矩阵

| 场景 | 隔离方式 | 自动化门禁 | 通过条件 |
| --- | --- | --- | --- |
| 服务重启对账 | 假 Slurm + 临时 SQLite | `test_competition_recovery.py` | 新协调器只对账，不重复 `sbatch` |
| Slurm 暂时不可用 | 假 Slurm | `test_competition_recovery.py`、`test_competition_slurm.py` | 保留最后可信 `queued/running`；记录 `stale_since`；不推进 |
| 作业身份不匹配 | 假 Slurm | `test_competition_security.py` | 状态降为 `unknown`；不能 `scancel`；不读取为可信作业 |
| 数据库写入失败 | 临时 SQLite | `test_competition_recovery.py` | 当前 attempt 保持可恢复；下一阶段 attempt、事件和输出行均不存在 |
| 取消/完成竞态 | 假 Slurm + 临时 SQLite | `test_competition_recovery.py`、既有协调器测试 | 以最终调度状态和已提交取消意图收敛，不执行科学验收或下一步 |
| 网关目标失效 | 假健康端点 | `test_competition_security.py`、`verify-runtime.sh` | 公网 live/ready 与计算节点身份不一致时非零退出，不自动换到其他服务 |
| 发布回滚 | 独立 release 指针和 SQLite | `test_competition_security.py`、`rollback-smoke.slurm` | 正式 `current` 不变；历史 attempt 行和证据包字节不变 |
| 路径、符号链接和注入 | 临时目录 | `test_competition_security.py` 及既有输入/Slurm/结果测试 | 在文件读取或调度命令前拒绝 |
| 超大日志和非法文件名 | 临时目录 | `test_competition_security.py` | 日志只返回固定字节尾部；控制字符、路径和超长文件名拒绝 |
| 非 LMateLab 作业隔离 | 假 Slurm，真实 Slurm 只读快照 | 归属四元组检查 | 必须同时匹配 Job ID、名称、工作目录、comment 和用户，才允许取消 |

## 3. 状态恢复合同

### 3.1 服务重启

协调器启动后按数据库账本发现活动 attempt：

1. `preparing` 重新校验不可变执行范围并恢复输入物化。
2. `submitting` 只允许从该 attempt 私有目录中的固定 Job receipt 恢复，不再次提交。
3. `queued/running/cancelling` 查询 Slurm 并核对作业归属。
4. `awaiting_acceptance` 只在成功调度证据完整时执行科学验收。
5. 任一恢复步骤失败时停止该工作流本次 tick，不提交下一阶段。

重启验收必须比较重启前后：attempt 数、Job ID、receipt、事件 sequence 和 `submitted_steps`。任一新增重复 Job 即失败。

### 3.2 Slurm 失联

`squeue/scontrol/sacct` 均无法给出可信记录时：

- attempt、step 和 workflow 保留最后可信业务状态；
- `scheduler_observation.stale=true`；
- `stale_since` 固定为首次失联时间，重复轮询不得向后漂移；
- `observed_at` 记录本次探测时间；
- 不产生成功、失败、科学验收或下一阶段提交。

若返回的是作业身份不匹配而非单纯失联，则状态必须降为 `unknown` 并记录 `scheduler_ownership_mismatch`。

### 3.3 数据库失败

数据库 commit 结果不明确时不得用内存状态继续：

- Slurm 已接收提交时保留固定 receipt，后续从 receipt 恢复；
- 科学验收 commit 失败时不生成验收事件、输出文件行或下游 attempt；
- 发布目录和恢复 journal 保留，不能把不确定状态清理成“未发生”。

### 3.4 取消竞态

取消只接受 LMateLab 账本选出的活动 attempt，不接受客户端 Job ID。执行 `scancel` 前必须用 Slurm 实时记录核对：

```text
job_id + job_name + working_directory + comment + user_name
```

若 `scancel` 与完成同时发生，重新读取最终调度状态并持久化 `cancellation_raced_terminal`。若取消意图已提交，则后续科学验收和下一阶段仍被阻断。

## 4. 网关失败关闭

`deploy/107cup/verify-runtime.sh` 首先核对计算节点 live/ready，再在设置 `LMATELAB_VERIFY_PUBLIC_URL` 时读取公开入口。两组响应必须字节语义一致，至少包含相同的：

```text
job_id
node
commit
manifest_sha256
release_kind=stable
data_mode=live
```

正式核验命令只允许短时运行：

```bash
LMATELAB_VERIFY_PUBLIC_URL=http://222.195.94.37:18733 \
  bash /home/scc/pb23030683/projects/LMateLab-107Cup/deploy/107cup/verify-runtime.sh
```

入口不可达、指向旧 Job、commit 不同或 manifest 不同均返回非零。脚本不修改 4090 Nginx、SSH 转发或 107 `current`。

## 5. 发布回滚

真实回滚前必须记录：

```bash
readlink -f /home/scc/pb23030683/lmatelab-107cup/current
sha256sum /home/scc/pb23030683/lmatelab-107cup/data/db/eln.db
sha256sum /home/scc/pb23030683/lmatelab-107cup/data/db/digests.db
```

Stage 9 默认只运行 `rollback-smoke.slurm`。它在独立 `rollback-smoke/<job-id>`、独立数据库和独立端口启动目标 release，完成 manifest、迁移、live/ready 和停止验收；正式 `current` 在前后必须相同。

禁止把历史 attempt 迁移到新 release、重写 `release_commit`、覆盖 evidence bundle 或删除失败 attempt。实际生产回滚只有在 smoke 通过且用户明确批准后才允许执行。

## 6. 安全输入门禁

必须在产生 Slurm 作业前拒绝：

- 非固定 `relax -> scf -> band -> dos` 步骤；
- 非白名单 INCAR 参数、字符串参数、非有限数和越界数值；
- UUID、Job ID、日志 stream 和文件相对路径中的注入字符；
- 绝对路径、`..`、兄弟目录前缀绕过；
- attempt、日志、receipt、输入、POTCAR 和结果文件的符号链接；
- 非普通文件、hash/size/inode 不一致和打开后的替换竞态；
- 空白、控制字符、路径分隔符、`..` 或 UTF-8 超过 255 字节的上传文件名；
- 超过 1 MiB 的结构和超过固定 64 KiB 响应预算的日志。

错误响应只能包含稳定错误码和公开说明，不得回显绝对路径、命令参数、POTCAR 内容或 Slurm 私有输出。

## 7. 六层测试

按顺序执行，前一层失败不得用后一层成功替代：

1. 后端单元与临时 SQLite：正式 `build.slurm` 中完整的 107 杯测试白名单，包含 Stage 5-9、鉴权、部署合同和健康检查；不包含依赖 Docker、生产监控器或完整 LMateLab 环境的旧系统测试。
2. 前端 Node 合同测试与 Vite build：全量 `frontend/tests/*.test.mjs`。
3. 假 Slurm 集成：恢复、安全、Slurm、协调器测试。
4. 107 真实 Slurm：正式 build Job、隔离 rollback smoke 和只读调度快照。
5. 真实 VASP：只读复核 Stage 7 Job `40212/40250/40251/40252` 及固定失败链 `40264/40265`，不重跑。
6. 浏览器：Operator 和 Viewer 的工作流、日志、结果、数据库、下载及公网只读边界。

本地快速门禁：

```bash
python -m unittest \
  tests.test_competition_recovery \
  tests.test_competition_security \
  tests.test_competition_slurm \
  tests.test_competition_coordinator -v
npm test
npm run build
```

107 全量构建必须通过 `deploy/107cup/submit-build.sh` 提交，不在登录节点直接运行测试或构建。

## 8. 证据与完成条件

Stage 9 证据至少保存：

- 合并后的 Git commit 和 release manifest SHA-256；
- build、rollback smoke 和服务 Job ID、节点、状态、ExitCode；
- 后端/前端测试计数和跳过原因；
- 网关一致与错误目标失败关闭的测试输出；
- SQLite integrity check；
- Stage 7 VASP 作业与文件哈希只读复核；
- Operator/Viewer 浏览器验收结果；
- 正式服务、数据库、`current` 和 Stage 7/8 证据未被故障演练修改的前后快照。

只有九项 Stage 9 清单全部有自动化或真实环境证据时，才能把实施方案中的 Stage 9 从 `PARTIAL` 改为 `DONE`。
