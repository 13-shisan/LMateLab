# 107 阶段 6 Slurm 适配器验收证据

本文记录受保护 `main` 合并提交 `93465522424ce0db24dabdfca04efe22fc523fa7` 在 107 上的真实 Slurm 验收。验收只运行固定的短时普通探针，没有运行 VASP，也没有启动阶段 7。

## 1. 当前结论

- PR #27 已把 Slurm spool 启动修复合并到 `main`，合并提交为 `93465522424ce0db24dabdfca04efe22fc523fa7`；107 只读 detached checkout 固定到相同提交且工作树干净。
- 前快照 Job `38620`、正式构建 Job `38621`、Stage 6 smoke Job `38623` 和后快照 Job `38629` 均成功结束。
- smoke 创建的成功、故意失败、受控取消和非归属控制作业分别为 `38625`、`38626`、`38627` 和 `38628`；适配器拒绝取消 `38628`，随后 smoke harness 只清理了它自己创建的该控制作业。
- `sbatch --test-only` 没有留下作业；一次受控调度拒绝没有产生 Job ID；新建 reconciler 对象和数据库会话能够继续对账成功、失败和取消状态。
- 稳定服务 Job `37715`、正式数据库、公开入口和非 Stage 6 环境均未被改变。正式 `current` 按构建合同从旧候选发布切换到新发布，但正在运行的稳定服务没有重启。
- 历史失败 smoke Job `38598` 及日志继续保留，用于证明修复前的真实失败边界。
- 本证据分支尚未合并，因此阶段 6 继续为 `PARTIAL`。只有证据 PR 合并后，Windows、Gitea `main` 与 107 再次同步到同一提交，才可通过后续状态提交改为 `DONE`。

## 2. 固定提交与构建

| 项目 | 证据 |
|---|---|
| Gitea `main` / 107 checkout | `93465522424ce0db24dabdfca04efe22fc523fa7` |
| 合并主题 | `fix(107cup): resolve stage6 smoke release under slurm`，PR #27 |
| 修复提交 | `e784b19de1746bd7c011d86480ced6d20f85d174` |
| 正式发布 | `/home/scc/pb23030683/lmatelab-107cup/releases/93465522424ce0db24dabdfca04efe22fc523fa7` |
| 发布 manifest 条目 | `516` |
| 发布 manifest SHA-256 | `ae7e8772b2d24c394a5862762693ffb196c1b2967c06c4ee04fb93e95a096623` |

构建 Job `38621` 在 `P107-RTX5090/anode01` 以 `COMPLETED/0:0` 结束，耗时 `42` 秒。后端测试 `165/165`、前端测试 `111/111` 通过，Vite 转换 `1857` 个模块并生成正式发布。

| 构建日志 | SHA-256 |
|---|---|
| `logs/build-38621.out` | `fc74bd911436f13e75ae251163f739f873cdbf292a17850eec04cb5e047e3bed` |
| `logs/build-38621.err` | `f86c55408cc0ef62dd215f49560102261da2fde238d5cd9a92b9461540396042` |

## 3. 前后快照

### 3.1 前快照

| 项目 | 证据 |
|---|---|
| Job | `38620` |
| 节点 | `anode16` |
| 状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/93465522424ce0db24dabdfca04efe22fc523fa7/before-38620` |
| `manifest.txt` SHA-256 | `476ebc4a1175419dfb1b115451f5ad0743c5abc04dd2d039dc1067851d895171` |

### 3.2 后快照

| 项目 | 证据 |
|---|---|
| Job | `38629` |
| 节点 | `anode16` |
| 状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/93465522424ce0db24dabdfca04efe22fc523fa7/before-38629` |
| `manifest.txt` SHA-256 | `4bb663dca35f6d92f02f54177b279fc8e4f467c2e008f5436f765e000ea876a4` |

后快照使用部署脚本的 standalone snapshot 模式，因此保留目录名仍为 `before-38629`；Job ID、时间和对比对象用于区分前后，不把目录名改写为未实际生成的 `after-*`。

前后快照的稳定对象对比如下：

| 稳定对象 | 前后结果 |
|---|---|
| `eln.db` SHA-256 | `de6176f960e6b7cbe4e44254585b23a8032e7ca146236cab7ec2eea736c6ce86`，一致 |
| `digests.db` SHA-256 | `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969`，一致 |
| 两套 SQLite | `PRAGMA integrity_check=ok`，前后均通过 |
| 稳定服务 | Job `37715`、`anode02:18731`、运行提交 `bec82bc9fed3ad9355235b965f5bf8cdba152a60`，一致 |
| 公开入口 | live、ready 和 Dashboard 均为 HTTP `200` |
| 队列终态 | Stage 6 子作业清理后只保留稳定 Job `37715` |

正式构建按既定发布合同把 `current` 从 `releases/74fb0b45d69dbc56ba6bb8f4ef27f27106d51ff2` 切换到 `releases/93465522424ce0db24dabdfca04efe22fc523fa7`。这是预期的发布变更；稳定 Job `37715` 仍运行原发布和原数据库，没有因 Stage 6 验收重启。

## 4. Stage 6 smoke

smoke Job `38623` 在 `P107-RTX5090/anode01` 以 `COMPLETED/0:0` 结束，耗时 `8` 秒。证据目录为：

```text
/home/scc/pb23030683/lmatelab-107cup/evidence/stage6/job-38623
```

独立 SQLite `stage6-smoke.sqlite` 的 `PRAGMA integrity_check` 为 `ok`。`manifest.sha256` 覆盖 `54` 个文件，作业内 `sha256sum -c` 全部通过；清单文件自身 SHA-256 为 `dec0f89f1ad317d996286b72563973dad5f38ce2fcfabd5f52f641b6d60437f4`。smoke 的 stdout 和 stderr 均为空文件，SHA-256 均为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

### 4.1 子作业状态

| Job | 用途 | 适配器终态 | 调度证据 |
|---|---|---|---|
| `38625` | 成功探针 | `succeeded` | `COMPLETED/0:0`，`anode01` |
| `38626` | 故意失败探针 | `failed` | `FAILED/42:0`，`Reason=NonZeroExitCode` |
| `38627` | LMateLab 自有取消探针 | `cancelled` | `CANCELLED`，先保存取消前快照再调用 `scancel` |
| `38628` | smoke 自建的非归属控制作业 | 适配器拒绝 | `cancellation_ownership_mismatch`；harness 随后精确清理，最终 `CANCELLED` |

`38628` 不是共享账号下既有的他人作业，而是本 smoke 为归属门禁专门创建的控制作业。适配器没有越权取消它；清理由 smoke harness 使用已知 Job ID 单独完成，没有枚举或操作其他共享账号作业。

### 4.2 提交、对账与事件

- `sbatch --test-only` 返回码为 `0`，测试 JobName 为 `lmatelab-2137f3ef-relax-a1`，队列中没有残留 test-only 作业。
- 受控调度拒绝生成一条 `submission_failed` ledger 记录，但没有 Job ID，也没有残留作业。
- smoke 使用新的 reconciler 对象和数据库会话继续观察终态，证明对账不依赖原提交进程的内存状态。
- ledger 事件计数为：`submission_accepted=3`、`submission_failed=1`、`scheduler_state_changed=5`、`cancellation_requested=1`。
- 完整 workflow ID、attempt ID、原始状态、退出码、reason、payload hash 和事件序列保存在 `summary.json`、SQLite 及 `scheduler/` 原始文件中。

107 的 `sacct` 仍因 `localhost:6819` 连接被拒绝而不可用。验收期间保留的结构化 `scontrol` 记录是短时作业终态的权威来源；后续短作业从 `scontrol` 清理后返回 `Invalid job id specified` 是平台既有行为，不推翻已哈希保存的原始记录。适配器在既无在线记录又无记账终态时仍按 `unknown/stale` 失败关闭。

## 5. 保留的修复前失败

历史 smoke Job `38598` 针对 PR #26 合并提交 `74fb0b45d69dbc56ba6bb8f4ef27f27106d51ff2` 运行，在任何子作业提交前以 `FAILED/1:0` 结束，错误为 `competition backend source is unavailable`。根因是 Slurm 将 Python 批脚本复制到 spool 路径后，`__file__` 不再位于发布目录。

| 日志 | SHA-256 |
|---|---|
| `logs/stage6-smoke-38598.out` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `logs/stage6-smoke-38598.err` | `36d0f6242943582f438e2bc061f49b0bb9abeb448eac151ae7f7a6c6766a64c3` |

该失败没有创建子 Job、没有修改数据库，也没有被删除。PR #27 改为通过固定完整提交定位 `releases/<commit>/source/backend` 和同一发布内探针；Job `38623` 是该修复合并后的首次完整成功闭环。

## 6. 状态边界

本轮证明阶段 6 的真实运行门禁已经执行，但证据文件尚在待合并分支。因此：

- 阶段 6：`PARTIAL`，等待本证据 PR 合并和三端固定提交同步验证。
- 阶段 7：`PENDING`，没有运行 `relax -> SCF -> BAND -> DOS` 或任何 VASP 作业。
- 阶段 8：`PENDING`，没有产生 VASP 结果解析或证据包。
- 稳定网页仍可访问，但它运行的是 `bec82bc9...` 发布；不得把 `current` 已更新误写成稳定服务已热加载新代码。
