# 107 阶段 5 工作流与输入校验验收证据

本文记录受保护 `main` 提交 `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` 在 107 上的隔离 live 验收。验收使用正式 SQLite 的私有副本，只证明工作流模型、输入物化、角色边界和 `sbatch` 前校验；没有调用 Slurm 作业适配器或 VASP，也没有产生计算 Job ID。

## 1. 验收结论

- PR #21 已合并到受保护 `main`，107 只读 detached checkout 固定到相同提交。
- Slurm 前快照、构建、私有预览服务和后快照均运行在计算节点，登录节点没有构建或常驻 LMateLab 服务。
- 内置 MoS2 与上传 POSCAR 两条工作流均进入 `validated`，并持久化完整发布提交；四步均为 `waiting`，attempt 与 Job ID 为零。
- Viewer 三个写路由均为 `403`；六类恶意或非法输入均为 `422`，且没有增加工作流、attempt 或 Job ID。
- Windows Playwright 对实际 107 live 预览执行三个固定视口，`3/3` 通过；控制台、页面错误、失败请求、意外写请求和横向溢出均为零。
- 预览停止后计算节点端口和双层 SSH 转发消失；前后快照证明稳定发布、服务和正式数据库未改变。
- 运行门禁已经闭合，独立证据 PR #22 已合并为 `3cf9b44f0b55a11e43f0a4960dc689cf0607ced2`，阶段 5 状态为 `DONE`。阶段 6 至 8 均未开始。

## 2. 固定提交与构建

| 项目 | 证据 |
|---|---|
| Gitea `main` | `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` |
| 合并主题 | `Merge pull request 'fix(107cup): persist workflow release provenance' (#21)` |
| 107 检出 | 同一固定提交，detached checkout，验收前工作树干净 |
| 预览发布 | `/home/scc/pb23030683/lmatelab-107cup/workflow-previews/46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` |
| 发布类型 / 数据模式 | `preview` / `live` |
| manifest 条目 | `482` |
| manifest SHA-256 | `ed0df15a583bc2fdf2b3174b14b7c8e1abaf93ffb4aa16f46aa79bde07728824` |

构建 Job `37594` 在 `P107-RTX5090/anode01` 现场观察为 `COMPLETED/0:0`。后端测试 `126/126`、前端测试 `111/111` 通过，Vite 转换 `1857` 个模块并生成不晋升的 live 预览。构建日志为：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-build-37594.out
/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-build-37594.err
```

| 日志 | SHA-256 |
|---|---|
| stdout | `210e7a378061f973d7a6396f4b23b3e1902bfdf18f91b0b115ceb3e729d933a7` |
| stderr | `8bf78747b1d1a543ebd6b90c53d75d6c9008c2d4f1c9872a21d5b36646db0130` |

构建保留已有的 Browserslist、3Dmol `eval`、大 chunk 警告，以及 pip 选择 yanked `numpy 2.4.0` 的解析器警告；测试和运行验收均未因此失败。本阶段不扩大范围修改依赖，后续若实际运行失败再保留现场处理。

## 3. Slurm 与快照

### 3.1 前快照

| 项目 | 证据 |
|---|---|
| Job | `37593` |
| 节点 | `anode16` |
| 状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7/before-37593` |
| `manifest.txt` SHA-256 | `9b206afd6239d687da6b058e7be00d0e9a55fba371f7105f773d1dabf3e1b643` |

### 3.2 最终私有预览服务

| 项目 | 证据 |
|---|---|
| Job | `37611` |
| 节点与端口 | `anode01:21611` |
| 健康提交 | `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` |
| 健康模式 | `release_kind=preview`、`data_mode=live` |
| 最终状态 | `CANCELLED/0:15` |
| 运行时间 | `00:04:24` |
| 关闭行为 | Uvicorn 完整执行 shutdown 并结束进程 |
| stdout SHA-256 | `8bd10f544d20c6c8cce134a34cc353bcdd2315a676401398f0a9474c678dee0f` |
| stderr SHA-256 | `667f879a31c4b2d686d385af3cf5fd266ab4753cc4c80909778b04dc526e3b11` |

服务日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-service-37611.out
/home/scc/pb23030683/lmatelab-107cup/logs/workflow-preview-service-37611.err
```

`CANCELLED/0:15` 是浏览器验收完成后的受控终止结果，不是运行失败。运行时验证器在停止后重新校验完整发布 manifest，并确认 `anode01:21611` 不可达；4090 和 Windows 的临时 `127.0.0.1:18736` 转发也已精确撤销。

### 3.3 后快照

| 项目 | 证据 |
|---|---|
| Job | `37614` |
| 节点 | `anode16` |
| 状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7/after-37614` |
| `manifest.txt` SHA-256 | `8c977bff11e224b32e90a7fcf7112dd9409ba5236e94ff562d2803b0a9978629` |
| stderr | `0` bytes |
| 对比结论 | `stable state matches before snapshot` |

第一次服务 Job `37597` 已完成 API、SQLite 和浏览器验收，但整理证据时发现临时 API 套件没有单独发送数值越界请求。该 Job 随后受控停止并由后快照 Job `37608` 证明稳定环境未变。最终 Job `37611` 使用同一不可变发布和全新私有数据库，补入越界请求后完整重跑全部 API、SQLite 和三视口验收；本文只把 Job `37611` 作为最终业务验收对象。

## 4. API 与 SQLite

最终私有数据库在验收前从正式 SQLite 复制并迁移，迁移证据为：

| 项目 | 结果 |
|---|---|
| Alembic revision | `107c0ffee001` |
| 工作流表 | `workflow_runs`、`workflow_steps`、`workflow_attempts`、`workflow_events`、`workflow_files`、`workflow_templates` |
| 验收前工作流 | `0` |
| `PRAGMA integrity_check` | `ok` |

Operator 创建且确认的最终工作流为：

| 来源 | 工作流 ID | 状态 | 发布提交 |
|---|---|---|---|
| built-in MoS2 | `6977c76a-73b9-4c07-b842-d7d2cfd766d5` | `validated` | `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` |
| uploaded structure | `12a7ab55-c839-4110-8904-14b493456d19` | `validated` | `46f2f0d6f96d937d2d5a42129aba2cbbb11b9be7` |

SQLite 终态为两条 run、八个 step、四个事件、`33` 个文件记录和零 attempt。每条工作流的步骤固定为 `relax`、`scf`、`band`、`dos`，状态全部为 `waiting`；API 中的 `latest_job_id`、step `job_id`、`attempt_dir` 和 `slurm_state` 全为空，attempt 值全为 `0`。

角色和非法输入门禁：

| 检查 | HTTP 结果 |
|---|---:|
| Viewer 读取两条工作流 | `200` |
| Viewer 上传结构 | `403` |
| Viewer 创建草稿 | `403` |
| Viewer 确认工作流 | `403` |
| `../POSCAR` 路径文件名 | `422` |
| 请求额外 `owner_id` 字段 | `422` |
| `ENCUT="520; touch owned"` | `422` |
| `ENCUT=700.1` 越界 | `422` |
| 超过 `1 MiB` 的结构 | `422` |
| POSCAR 元素顺序 `S Mo` | `422` |

拒绝响应不包含 `/home/`、运行目录、Traceback 或凭据。六类拒绝后工作流总数仍为 `2`。Results 返回 `{"items":[],"total":0,"data_kind":"live"}`，VASP Database 同样返回 `data_kind=live` 的空集合，不回退到 demo 数据。

## 5. Windows 浏览器验收

浏览器插件在当前会话不可用，因此使用仓库已有 Playwright `1.54.2`。浏览器通过临时双层 SSH 转发直接访问 Job `37611`，不是 Windows 本地 Vite 服务。

| 视口 | 结果 | API 响应 | 截图 | 控制台问题 | 页面错误 | 失败请求 | 意外写请求 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `1440x900` | 通过 | `14` | `7` | `0` | `0` | `0` | `0` |
| `1024x768` | 通过 | `14` | `7` | `0` | `0` | `0` | `0` |
| `390x844` | 通过 | `14` | `7` | `0` | `0` | `0` | `0` |

覆盖路径为 Operator 登录、工作台、新建计算来源切换、工作流列表、两条详情、Results 真实空状态和 VASP Database 真实空状态。三个视口均确认页面标题和内容非空、无框架错误覆盖层、无 demo 标记、发布提交完整、四步可见且没有 Job ID，页面级 `scrollWidth <= innerWidth + 1`。

Windows 外部证据目录：

```text
D:\Documents\matflow项目\LMateLab-107Cup-evidence\stage5-workflow-46f2f0d-37611
```

目录包含 `21` 张截图、`3` 份视口 JSON、`api-acceptance.json`、`sqlite-acceptance.json` 和 `sha256-manifest.txt`。清单包含 `26` 个条目，清单自身 SHA-256 为：

```text
8913d249ce53bfef8f946017ea349a1c2a2838c8d3cffbc840ac727148b0ed1b
```

凭据只从 107 的 `0600` Job 私有文件读入进程环境，验收后清除；没有写入 Git、JSON、截图或清单，最终证据目录的凭据值扫描为零命中。

## 6. 稳定环境与边界

| 稳定对象 | 最终状态 |
|---|---|
| `current` | `/home/scc/pb23030683/lmatelab-107cup/releases/1bba72d0ade2bb7024081d384584524a9c9d1c69` |
| 稳定服务 | Job `36597`，`anode01:18731` |
| 稳定服务提交 | `1bba72d0ade2bb7024081d384584524a9c9d1c69` |
| `eln.db` SHA-256 | `cd5d639bccfa35414769901f444bf64b867826ce20962d5098a0dac8e07f135a` |
| `digests.db` SHA-256 | `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969` |
| 两套正式 SQLite | `integrity_check=ok`，前后哈希一致 |
| 最终预览端口 | `anode01:21611`、4090/Windows `18736` 均不可达 |

107 的 `sacct` 后端仍不可用，快照已保存 stdout、stderr 和降级状态；短构建 Job `37594` 随后也已被集群从 `scontrol` 清理。因此 Job 完成结论同时依赖现场状态记录、原始 Slurm 日志、日志 SHA-256、不可变发布 manifest 和前后快照，不把后续查询不到短 Job 误写为未运行。

本次没有实现阶段 6 的 `sbatch/squeue/sacct/scancel` 控制链，也没有执行阶段 7 的 `relax -> SCF -> BAND -> DOS`。证据 PR #22 合并后阶段 5 已改为 `DONE`；是否开始阶段 6 继续等待用户明确确认。
