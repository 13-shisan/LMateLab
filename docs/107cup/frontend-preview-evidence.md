# 107 前端完整形态预览验收证据

本文记录合并提交 `7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8` 在 107 上的隔离预览验收。该预览固定使用 `demo` 数据，只证明前端形态、只读边界和隔离部署链路；其中的 MoS2 工作流、Job ID、BAND/DOS 和失败记录均为演示内容，不是真实 Slurm/VASP 计算结果。

## 1. 验收结论

- PR #14 已合并到受保护的 `main`，合并提交为 `7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8`。
- 107 通过 Slurm 完成合并提交的前快照、隔离构建、独立预览服务和后快照。
- Windows Playwright 直接访问 Slurm Job `36641` 提供的实际 107 前端，三个固定视口 `3/3` 通过。
- 三个视口的 3D Canvas 均有非空彩色像素，控制台问题和业务写请求均为 `0`。
- 预览 Job 停止后 `anode01:20641` 不可达；稳定 `current`、正式 SQLite、稳定服务 Job 和端口未改变。
- 阶段 5 至 8 仍为 `PENDING`。本次验收没有实现真实工作流模型、Slurm 控制、VASP 四步计算或真实结果入库。

## 2. 固定提交与发布

| 项目 | 证据 |
|---|---|
| Gitea `main` 合并提交 | `7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8` |
| 合并主题 | `Merge pull request 'fix(107cup): close frontend preview acceptance gaps' (#14) from codex/107cup-frontend-preview-qa-fix into main` |
| 107 预览发布 | `/home/scc/pb23030683/lmatelab-107cup/previews/7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8` |
| 发布 manifest SHA-256 | `837e85822cb74a24134423356b6d385505e0fb0fe51d1e80cd85adbb5edd789d` |
| 发布类型 | `preview` |
| 数据模式 | `demo` |

预览发布目录当前权限为 `0700`，`manifest.sha256` 为 `0600`。构建没有创建或切换稳定 `current`。

## 3. 107 Slurm 验收

### 3.1 前快照

| 项目 | 证据 |
|---|---|
| Job | `36637` |
| 节点 | `anode16` |
| 验收时观察状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8/before-36637` |
| `manifest.txt` SHA-256 | `04edea4be9faec55ee2d93f2c61f89aa19e3f13c45e58c1c13d767a8cc4d1ffa` |

### 3.2 预览构建

| 项目 | 证据 |
|---|---|
| Job | `36638` |
| 节点 | `anode02` |
| 验收时观察状态 | `COMPLETED/0:0` |
| 运行时间 | `00:02:23` |
| 后端测试 | `44/44` |
| 前端测试 | `104/104` |
| Vite 构建 | 转换 `1857` 个模块，`7.01s` 完成 |
| 构建 stdout SHA-256 | `95ef7112a33275923fc45b860aa8fd8c6e0de6e7f1ff8107e5a3c6c9b468e2e8` |
| 构建 stderr SHA-256 | `6e32b5e772c78ba74fa8210006ec0d0cffe87ab8d26029c8a7fac071192c3375` |

日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/preview-build-36638.out
/home/scc/pb23030683/lmatelab-107cup/logs/preview-build-36638.err
```

### 3.3 独立预览服务

| 项目 | 证据 |
|---|---|
| Job | `36641` |
| 节点与端口 | `anode01:20641` |
| 提交 | `7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8` |
| 健康元数据 | `release_kind=preview`、`data_mode=demo` |
| 最终观察状态 | `CANCELLED/0:15` |
| 运行时间 | `00:27:32` |
| 关闭行为 | Uvicorn 完整优雅关闭 |
| 关闭后端口 | `anode01:20641` 不可达 |
| 服务 stdout SHA-256 | `9d2f4b667a2cb2405d9bdea2c92520a69ed5518a610c8d630cd78e53ac138f34` |
| 服务 stderr SHA-256 | `0a70da004c677400d556121f321ac9f77f2bd7800f0556202ba4230bdf5cd88e` |

日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/preview-service-36641.out
/home/scc/pb23030683/lmatelab-107cup/logs/preview-service-36641.err
```

服务作业在浏览器验收结束后主动停止，因此 `CANCELLED/0:15` 是受控终止结果，不应写成 `COMPLETED/0:0`。

### 3.4 后快照

| 项目 | 证据 |
|---|---|
| Job | `36653` |
| 节点 | `anode16` |
| 验收时观察状态 | `COMPLETED/0:0` |
| 证据目录 | `/home/scc/pb23030683/lmatelab-107cup/evidence/previews/7c9d34eccc9e4efb9a533e215d52a6eb96e2e5d8/after-36653` |
| `manifest.txt` SHA-256 | `e0f1428c1d09bc167f610d1cee2b6e9b5877e4da08c0b1239b46bd78251e2cec` |
| 对比结论 | `stable state matches before snapshot` |

## 4. Windows 浏览器验收

Playwright 使用实际 107 预览服务，而不是 Windows 本地 Vite 服务。Windows 临时转发入口为 `127.0.0.1:18735`，验收后已移除。

| 视口 | 结果 | 3D Canvas 彩色像素 | Canvas 总像素 | 控制台问题 | 业务写请求 |
|---|---:|---:|---:|---:|---:|
| `1440x900` | 通过 | `2248` | `354290` | `0` | `0` |
| `1024x768` | 通过 | `2403` | `171160` | `0` | `0` |
| `390x844` | 通过 | `3125` | `121680` | `0` | `0` |

完整结果为 `3/3 passed in 14.9s`。验收覆盖工作台、新建计算、成功与失败结果、周期表/VASP 数据库、刷新、只读写控件、BAND/DOS 切换、成功/失败互斥、3D Canvas 像素和页面横向溢出。

Windows 证据目录：

```text
D:\Documents\matflow项目\LMateLab-107Cup-evidence\frontend-preview-107-7c9d34e-job36641
```

该目录包含 `15` 张截图、`3` 份验收 JSON 和 `sha256-manifest.txt`。清单包含 `18` 个条目，本次复核为 `18/18`，清单文件自身 SHA-256 为：

```text
271e377c6ab771468456af1a723d123c22a51baee890bd1c817aa3644fdf343e
```

## 5. 稳定环境隔离结论

前后快照及验收后复核得到：

| 稳定对象 | 验收后状态 |
|---|---|
| 稳定 `current` | `/home/scc/pb23030683/lmatelab-107cup/releases/1bba72d0ade2bb7024081d384584524a9c9d1c69` |
| 稳定服务 | Job `36597`，`anode01:18731` |
| 稳定服务提交 | `1bba72d0ade2bb7024081d384584524a9c9d1c69` |
| 两套稳定 SQLite | `integrity_check=ok`，前后哈希一致 |
| Windows 稳定入口 | `18733`、`18734` 保留 |
| Windows/4090 预览入口 | `18735`、`18736` 已移除 |

验收后再次只读查询时，稳定 Job `36597` 仍为 `RUNNING`，节点为 `anode01`，分区为 `P107-RTX5090`。未修改稳定发布、正式数据库或稳定服务。

## 6. 调度证据限制

107 的 `sacct` 当前不可用，前后快照已原样保存 stdout、stderr 和 `unavailable` 状态。Job `36637`、`36638`、`36641` 和 `36653` 的状态均在运行或结束时现场读取；后续复核时集群已经从 `scontrol` 清理这些短作业记录。因此本文同时保留：

- 验收时读取到的 Job 状态；
- Slurm 构建/服务日志及其 SHA-256；
- 前后快照目录及其 manifest；
- 当前仍存在的隔离发布和稳定服务状态。

这些证据不能被扩大解释为真实 VASP 运行验收。下一阶段仍须另行实现并验证工作流模型、输入校验、Slurm 适配器及真实 `relax -> SCF -> BAND -> DOS` 闭环。
