# Stage 9 恢复、安全和回归验收记录

更新时间：`2026-08-21`

## 1. 当前结论

- Stage 9 的恢复合同、安全边界、107 隔离回滚、真实结果只读复核和浏览器 Viewer 验收均已通过。
- 故障注入没有使用正式 SQLite、正式 `current` 或 Stage 7/8 attempt；没有创建或重跑 VASP 作业。
- 功能 PR `#50` 与验收证据 PR `#51` 已合并；固定功能提交为 `7a2c2d62f7368436a9c1f03d9df9ea044d41d011`，功能合并提交和当前运行 release 为 `551ba97fbfca3093c19ef4e98e636bcaa9b88fef`。
- 正式服务已更新为 Job `40917`，运行在 `P107-A100/anode17:18731`；4090 内部、Windows Operator 和公网入口均返回该 Job 的同一健康身份。
- Stage 9 状态为 `DONE`。Stage 3 仍为 `PARTIAL`：服务和 4090 转发自动恢复是后续独立门禁，本阶段没有把人工切换等同于自动恢复。

## 2. 源码、构建与测试

最终构建 Job：

```text
Job ID: 40860
Partition/Node: P107-RTX5090/anode01
State/ExitCode: COMPLETED/0:0（作业运行时记录）
Release: 551ba97fbfca3093c19ef4e98e636bcaa9b88fef
Manifest SHA-256: 163b52ad998f947f575589df07e1bafa36423e122e3eab00ba2008e0d031a58d
```

正式 107 杯发布门禁结果：

| 环境 | 结果 |
|---|---|
| Windows 后端正式 allowlist | `470 passed`，`27` 项仅 POSIX 环境可运行的测试跳过 |
| 107 Linux 后端正式 allowlist | `470 passed`，`4` 项环境相关测试跳过 |
| 前端 Node 合同测试 | `129/129 passed` |
| Vite 生产构建 | `1857 modules transformed`，成功生成静态发布 |
| 部署脚本与仓库检查 | Bash 语法和 `git diff --check` 通过 |

107 日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/build-40860.out
/home/scc/pb23030683/lmatelab-107cup/logs/build-40860.err
```

补充执行的完整旧后端发现共发现 `509` 项测试，其中 6 项因 Windows、Docker 或旧生产监控环境缺失失败。它们不属于 `deploy/107cup/build.slurm` 固定的竞赛发布 allowlist，也没有被用来替代正式门禁；该环境差异按原样保留，不写成全量旧系统通过。

## 3. 自动化恢复与安全合同

PR `#50` 新增或强化的自动化覆盖：

- 新协调器恢复 `preparing/submitting/queued/running/awaiting_acceptance` 时只对账，不重复 `sbatch`。
- Slurm 暂时不可用时保留最后可信 `queued/running`，固定首次 `stale_since`，不推进或伪造终态。
- 作业身份不匹配时降为 `unknown`，不能读取为可信作业、不能取消、不能进入科学验收。
- 数据库接受结果写入失败时不创建下游 attempt、事件或输出账本。
- 已提交的取消意图在“取消与完成”竞态中优先阻断科学验收和后续提交。
- 网关指向旧 Job、错误 commit 或错误 manifest 时，`verify-runtime.sh` 非零退出且不自动切换目标。
- release 指针变化不修改历史 attempt、`release_commit` 或证据包字节。
- 路径穿越、符号链接逃逸、参数注入、非法/超长文件名和超大日志均在读取或调度前失败关闭。
- 取消前同时核对 Job ID、作业名、工作目录、comment 和用户，不能操作同一 Unix 账号下的其他作业。

关键测试文件：

```text
backend/tests/test_competition_recovery.py
backend/tests/test_competition_security.py
frontend/tests/competitionWorkflowE2E.test.mjs
deploy/107cup/verify-runtime.sh
```

## 4. 107 隔离回滚演练

演练链：

| Job | 用途 | 结果 |
|---:|---|---|
| `40910` | 正式状态前快照 | `current`、两库哈希、服务身份和 manifest 自检通过 |
| `40911` | 独立回滚 smoke | `anode17:18732` 启动旧 release `6242132...`，独立两库迁移、live/ready 和受控关闭通过 |
| `40913` | 正式状态后快照 | 输出 `stable state matches before snapshot` |
| `40923` | 最终正式状态快照 | 作业运行时记录为 `COMPLETED/0:0`，全部快照文件自检通过 |

回滚 smoke 只使用：

```text
/home/scc/pb23030683/lmatelab-107cup/rollback-smoke/40911
/home/scc/pb23030683/lmatelab-107cup/evidence/rollback/40911
```

`40911` 的 `SUCCESS.txt` 证明正式 `current` 前后均为：

```text
/home/scc/pb23030683/lmatelab-107cup/releases/551ba97fbfca3093c19ef4e98e636bcaa9b88fef
```

隔离 SQLite 的两次 `PRAGMA integrity_check` 均为 `ok`，旧 release 的 live 元数据返回 Job `40911`、节点 `anode17` 和端口 `18732`；Uvicorn 记录完整 shutdown。正式数据前后哈希保持：

```text
eln.db:     29cf102884c1b36f6cef8c251bb569aa6cebd837b4d3957989a6efaa8a96ddbc
digests.db: 2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969
```

平台会迅速从 `scontrol/sacct` 清除已结束的短作业，当前查询这些历史 Job 已为空。因此文档保留运行时捕获的终态、批作业日志、Job 专属目录和自检清单，不把后来空白的 `sacct` 伪写成可恢复记录。

## 5. 真实 VASP 与 Stage 8 证据只读复核

Job `40916` 在 `anode17` 对固定 Stage 7/8 数据执行只读验收，输出终止标记：

```text
STAGE8_ACCEPTANCE_OK
```

复核结果：

```text
成功工作流: 4b566547-961b-4e10-a8d0-99431f2e2229
VASP Jobs: 40212 / 40250 / 40251 / 40252
SCF total energy: -21.85260744 eV
Band gap: 1.6919 eV
成功证据包: a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4

失败工作流: db9c793d-cf8f-4207-823b-5943d825f21d
VASP Jobs: 40264 / 40265 / null / null
失败证据包: 7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e
```

该 Job 没有调用 `sbatch` 创建 VASP 作业，没有修改工作流、attempt 或原始输出。证据位于：

```text
/home/scc/pb23030683/lmatelab-107cup/evidence/stage8/acceptance-40916
/home/scc/pb23030683/lmatelab-107cup/logs/stage8-acceptance-40916.out
```

## 6. 正式服务与入口

当前正式服务：

```text
Service Job: 40917
Partition/Node: P107-A100/anode17:18731
State: RUNNING
Commit: 551ba97fbfca3093c19ef4e98e636bcaa9b88fef
Manifest SHA-256: 163b52ad998f947f575589df07e1bafa36423e122e3eab00ba2008e0d031a58d
```

三处 live/ready 均返回同一身份和 HTTP `200`：

- 4090 内部：`127.0.0.1:18740 -> 11.11.10.17:18731`；
- Windows Operator：`http://127.0.0.1:21763`；
- 公网只读入口：`http://222.195.94.37:18733`。

旧 Job `40832` 在核对用户、作业名、命令和日志路径均属于本项目后受控停止，终态为 `CANCELLED/0:15`，Uvicorn 日志记录完整 shutdown。临时转发 `18741` 已撤销，正式转发 `18740` 已切换到 `anode17`。

## 7. 浏览器验收

由于 Chrome 控制插件运行时不兼容，本次使用隔离 Playwright Viewer 会话执行真实页面验收。浏览器控制台错误为 0，并确认：

- Viewer 的新建计算入口和写操作均禁用。
- 成功工作流显示四个真实 Job ID、attempt、文件哈希、受限日志、结构、BAND 和 DOS。
- BAND 与 DOS 画布均非空且正确成图。
- 失败工作流明确显示 SCF `electronic_not_converged`，BAND/DOS 为零 Job、零 attempt。
- Viewer 的取消和重试控件禁用。
- VASP 数据库显示固定的两条真实记录。

浏览器只读操作也记录在 `service-40917.out`，对应结果、工作流、日志和 VASP 数据库 API 均返回 `200`。Stage 10 将另行生成正式桌面、移动截图和演示素材，本阶段截图不替代最终交付物。

## 8. 九项完成门禁

- [x] 服务重启对账不重复提交。
- [x] Slurm 失联保留可信状态和固定 stale 时间。
- [x] 数据库失败阻断下一阶段。
- [x] 取消/完成竞态按持久化意图和最终调度状态收敛。
- [x] 网关错误目标失败关闭。
- [x] 隔离回滚不修改正式 `current`、SQLite、attempt 或证据包。
- [x] 路径、符号链接、参数、日志和文件名恶意输入均拒绝。
- [x] 非 LMateLab 作业不能被信任、读取敏感日志或取消。
- [x] 后端、前端、假 Slurm、107 真实 Slurm、真实 VASP 只读复核和浏览器六层门禁通过。

上述门禁全部有自动化或真实环境证据，Stage 9 为 `DONE`。下一阶段是 Stage 10 比赛交付验收；不得把 Stage 10 的演示复跑、交付文档、截图视频和三人复核倒算为 Stage 9 缺口。
