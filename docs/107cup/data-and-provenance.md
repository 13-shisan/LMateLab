# 107 杯数据与溯源说明

更新时间：`2026-08-21`

## 1. 数据边界

竞赛版 LMateLab 使用独立源码、环境、数据库和工作流目录，不导入原 4090 LMateLab 的生产数据库、上传文件、用户数据或 Agent 记忆。4090 只转发网络流量。以下业务数据全部以 107 路径为准：

| 数据 | 107 权威位置 | 证明方式 |
|---|---|---|
| 固定源码和前端 | `releases/<git-commit>/source`、`frontend-dist` | `commit.txt`、`manifest.txt`、`manifest.sha256` |
| Python/Node 环境 | `envs/python`、`envs/node-*` | 构建 Job 和可执行文件路径 |
| 用户和工作流数据库 | `data/db/eln.db` | SQLite `query_only`、`integrity_check`、工作流 ID |
| 摘要数据库 | `data/db/digests.db` | SQLite `integrity_check` |
| 工作流输入和 attempt | `data/workflows/<workflow-id>` | 文件账本、attempt、Job ID 和 SHA-256 |
| VASP 原始输出 | 各 attempt 的固定输出目录 | OUTCAR/vasprun.xml、正常结束和科学门禁 |
| 结果与证据包 | 数据库记录、attempt、`evidence` | 确定性导出及清单 |
| 服务身份 | `runtime/service-state.json` | Job、node、port、commit、manifest 原子一致 |

路径存在本身不代表计算成功。成功必须同时满足调度终态、VASP 正常结束、阶段科学检查、必要文件和哈希；失败必须保留原因和阻断证据。

## 2. 源码与发布溯源

每次正式发布只接受 Gitea `107-team/LMateLab` 已合并 `main` 的 40 字符提交。107 使用只读 Deploy Key 拉取；开发者通过各自 Gitea 账号、提交邮箱、个人分支和 PR 区分身份。共享 Unix 账号 `pb23030683` 不能替代个人 Git 身份。

构建在 Slurm 计算节点执行，发布目录名必须与 `commit.txt` 相同。`manifest.txt` 覆盖发布内每个普通文件，`manifest.sha256` 再固定清单本身。Stage 10 的仓库交付清单位于 [`artifacts/manifest.sha256`](./artifacts/manifest.sha256)，它覆盖交付文档、关键部署/验收代码和 Stage 3/7/8/9 证据，不包含自身，因而可以确定性重建。

## 3. 固定真实成功算例

Stage 10 不重新消耗 GPU 计算，而是只读复核已经完成并锁定的真实四步闭环：

```text
Workflow: 4b566547-961b-4e10-a8d0-99431f2e2229
relax Job: 40212
SCF Job:   40250
BAND Job:  40251
DOS Job:   40252
Result: succeeded
Band gap: 1.6919 eV
SCF total energy: -21.85260744 eV
Evidence bundle SHA-256:
a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4
```

每一步具有独立 Job ID、attempt、输入、输出、资源记录和科学验收。结果页的结构、BAND、DOS 和下载内容从这组真实数据解析，不能回退到 demo fixture。

## 4. 固定人为失败算例

失败链用于证明错误不会被伪装为成功，也不会继续消耗资源：

```text
Workflow: db9c793d-cf8f-4207-823b-5943d825f21d
relax Job: 40264
SCF Job:   40265
BAND Job:  null
DOS Job:   null
Reason: electronic_not_converged
Evidence bundle SHA-256:
7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e
```

BAND/DOS 必须是 `blocked`，且零 attempt、零目录、零 Job ID。Stage 10 的只读验收会重新生成两类确定性证据包并比对上述哈希，不修改数据库或原始 attempt。

## 5. 结果可信度与限制

Stage 7 证据记录 VASP 四步科学门禁；Stage 8 证据记录结构/BAND/DOS 解析、下载和确定性证据包；Stage 9 证据记录恢复、安全、竞态和非归属作业隔离。Stage 10 只能组合并重新验证这些事实，不能用页面截图代替底层科学验收，也不能用旧阶段成功掩盖当前发布、浏览器或三人复核失败。

发布仓库仍保留原项目的部分源码作为历史开发基座，但竞赛运行面由 `competition_runtime.py` 中的固定 router allowlist 和 `main_107cup.py` 构建。Stage 10 会验证只挂载认证、健康检查和竞赛工作流路由；Agent、机器学习、QE/EPW、跨服务器迁移、监控、报告等不得出现在可访问 API 或前端导航中。这里的“未进入发布”指未进入竞赛可执行/可访问业务面，而不是重写 Git 历史删除所有旧文件。

## 6. 隐私和复核

交付清单和证据文档可以提交 Git；JWT、密码、Gitea Token、SSH key、二次验证码、完整私有数据库、运行环境文件和未裁剪日志不能提交。Viewer 下载只包含固定白名单工件和受限日志。

三名成员最终分别记录自己的 Gitea 身份、复核日期、固定 `main` 提交和 `artifacts/manifest.sha256` 文件哈希。任何一人发现哈希、Job ledger、路由范围或页面角色与文档不一致，Stage 10 保持 `PARTIAL` 并停止签字。
