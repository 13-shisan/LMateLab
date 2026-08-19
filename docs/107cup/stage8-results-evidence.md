# Stage 8 结果解析与证据包验收记录

更新时间：`2026-08-20`

## 1. 当前结论

- Stage 8 功能实现、107 计算节点构建、真实只读解析、稳定服务发布和三处健康入口已经通过。
- 本次复用 Stage 7 的固定成功/失败工作流，没有创建或重跑任何 VASP 作业。
- Chrome 登录态控制当前未能建立，因此结果列表、成功详情、失败详情、VASP 数据库和浏览器下载仍缺最终人工验收。
- 在浏览器门禁完成前，Stage 8 保持 `PARTIAL`；旧服务 Job `40273` 和临时验证转发 `18741` 保留为回滚路径，不提前清理。

## 2. 源码与合并记录

| 内容 | PR | 合并结果 |
|---|---:|---|
| 真实结果 API、解析、下载和确定性证据包 | `#42` | 合并提交 `6c6d228d94933278a36e17fa90ce61c8d690ad58` |
| 独立验收脚本注册 `models.User` | `#43` | 合并提交 `2735dd6e93333121e6934819182dd27754153a10` |
| ASE CIF 导出改用二进制缓冲区 | `#44` | 合并提交 `db05369fe3d0b86844d1242d5ec7a37195cf37e4` |

当前固定 release commit：

```text
db05369fe3d0b86844d1242d5ec7a37195cf37e4
```

107 只读 checkout、Gitea `main` 和运行 release 均已核对到该提交；107 checkout 工作树为空。

## 3. 构建与测试

最终构建 Job：

```text
Job ID: 40307
Partition/Node: P107-RTX5090/anode02
State/ExitCode: COMPLETED/0:0
Backend: 457 passed, 4 platform skips
Frontend: 125 passed
Vite: 1857 modules transformed
Release manifest entries: 560
```

发布清单：

```text
/home/scc/pb23030683/lmatelab-107cup/releases/db05369fe3d0b86844d1242d5ec7a37195cf37e4/manifest.txt
SHA-256: e12ad90ba9bb8e4af00c90926bf9ba834267828db9fafde84e1fb7b0139a4007
```

构建日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/build-40307.out
/home/scc/pb23030683/lmatelab-107cup/logs/build-40307.err
```

## 4. 真实只读验收

最终验收 Job：

```text
Job ID: 40308
Partition/Node: P107-A100/anode16
State/ExitCode: COMPLETED/0:0
Terminal marker: STAGE8_ACCEPTANCE_OK
```

验收器只读取 Stage 7 已存在的数据库、工作流账本和文件，不调用 `sbatch` 创建 VASP 作业，也不修改历史工作流。

### 4.1 成功工作流

```text
Workflow: 4b566547-961b-4e10-a8d0-99431f2e2229
Jobs: 40212 / 40250 / 40251 / 40252
SCF total energy: -21.85260744 eV
Band gap: 1.6919 eV
```

四步最终 attempt、Slurm `COMPLETED/0:0`、非 stale 调度观察、科学验收、文件账本及文件 SHA-256 全部满足成功合同后，才生成结构、BAND、DOS 和证据包。

### 4.2 固定失败工作流

```text
Workflow: db9c793d-cf8f-4207-823b-5943d825f21d
Jobs: 40264 / 40265 / null / null
SCF: scientific_failed/electronic_not_converged
BAND/DOS: blocked, no attempt, no directory, no Job ID
```

失败详情只提供失败证据，不生成或展示科学成功区。

## 5. 图、结构与下载工件

| 工件 | 字节数 | SHA-256 |
|---|---:|---|
| `structure-cif` | `792` | `84d21f4e65e8db6e16a90433f970ee28ec6cb3e4cf7a25d62ff06d13006d96cb` |
| `structure-poscar` | `438` | `efb660af1347e7dd8100b5e49d8354429510f3f06961fc13fd9ddfa1806c8adc` |
| `band-data` | `53449` | `7416961188bca584666488ced5e5519ed40408fd7b694c1d92c897912e428ffa` |
| `dos-data` | `13172` | `776dd344dee1339c80720fdc46f3d105946de3f165a9338311858a85f48a19ec` |

图像验收：

| 图 | PNG 字节数 | 源文件 SHA-256 |
|---|---:|---|
| BAND | `206174` | `eac9476f1512335879cdd24d6c33afe221a5ca703f26bac8c525d6e1295c4a93` |
| DOS | `115848` | `fe80385eede66f85e330b07a4aa718bbbffcf66d6f74ee3b674e0be624fbceb6` |

缺失、哈希变化、路径逃逸、Windows 风格非规范路径、符号链接、非普通文件和解析异常均由测试证明失败关闭。

## 6. 确定性证据包

```text
Success bundle SHA-256: a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4
Failure bundle SHA-256: 7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e
```

Viewer 与工作流所属 Operator 下载得到相同字节。包内保留 Git commit、release manifest、模板、参数、Job、attempt、事件序列、科学验收和文件账本；不包含密码、JWT、环境变量或服务器绝对路径。

原始证据目录：

```text
/home/scc/pb23030683/lmatelab-107cup/evidence/stage8/acceptance-40308
```

目录内 `manifest.sha256` 的 SHA-256：

```text
5b2d2caa25162d512baeb3e0e9b6de5b32502ad98fe1642e93f4495ac77448a4
```

该清单固定：

```text
7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e  failure-evidence-bundle.json
a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4  success-evidence-bundle.json
67fc7212c04c227d4af198f90dae863568804c74ff81b29bb4811e6e96efdd6c  summary.json
```

## 7. 保留的失败证据

| Job | 失败边界 | 影响 |
|---:|---|---|
| `40304` | 独立验收脚本未注册 `models.User` | 在数据解析前终止，没有运行 VASP，也没有修改工作流 |
| `40306` | ASE CIF writer 错用文本 `StringIO` | 真实详情与图已解析，但 CIF 导出失败；没有运行 VASP |

两个缺陷均先保留失败现场，再分别经 PR `#43/#44` 修复，最终由 Job `40308` 重新执行只读验收并通过。

## 8. 稳定服务与入口

```text
Service Job: 40309
Partition/Node: P107-A100/anode19:18731
State: RUNNING
Commit: db05369fe3d0b86844d1242d5ec7a37195cf37e4
Manifest SHA-256: e12ad90ba9bb8e4af00c90926bf9ba834267828db9fafde84e1fb7b0139a4007
```

以下三处 `live/ready` 已返回同一 Job、节点、提交和 manifest：

- 4090 内部：`127.0.0.1:18740 -> anode19:18731`；
- 公网入口：`http://222.195.94.37:18733`；
- Windows Operator：`http://127.0.0.1:21763`。

临时 `127.0.0.1:18741 -> anode19:18731` 仍保留用于最终页面验收。旧 Job `40273` 仍在 `anode16` 运行作为回滚候选；完成浏览器门禁并再次确认三处正式入口后，才允许核对归属并停止旧 Job、撤销临时转发。

## 9. 剩余完成门禁

- [ ] Viewer 和 Operator 浏览器登录后检查 `/dashboard/results`。
- [ ] 检查成功详情 `/dashboard/results/4b566547-961b-4e10-a8d0-99431f2e2229` 的 3D 结构、BAND、DOS 和五种下载。
- [ ] 检查失败详情 `/dashboard/results/db9c793d-cf8f-4207-823b-5943d825f21d` 不挂载科学成功区。
- [ ] 检查 `/dashboard/database/vasp` 的真实只读记录。
- [ ] 浏览器验收后停止旧 Job `40273`、撤销临时 `18741`，并复核三处正式入口不变。
- [ ] 合并本证据 PR，使 Windows `main`、Gitea `main` 和 107 checkout 再次固定到同一提交。

上述全部完成后，才把 Stage 8 从 `PARTIAL` 更新为 `DONE`。
