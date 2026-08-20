# Stage 8 结果解析与证据包验收记录

更新时间：`2026-08-20`

## 1. 当前结论

- Stage 8 功能实现、107 计算节点构建、真实只读解析、稳定服务发布和三处健康入口已经通过。
- 本次复用 Stage 7 的固定成功/失败工作流，没有创建或重跑任何 VASP 作业。
- 用户已在登录浏览器中确认结果列表、成功详情、失败详情、VASP 数据库和五种下载均正常；该人工确认与既有 Viewer/Operator API 验收共同关闭浏览器门禁。
- 旧服务 Job `40273/40309/40786` 已核对归属后停止，临时转发 `18741` 已撤销；清理后正式入口仍返回 Job `40832`。
- Stage 8 状态为 `DONE`。

## 2. 源码与合并记录

| 内容 | PR | 合并结果 |
|---|---:|---|
| 真实结果 API、解析、下载和确定性证据包 | `#42` | 合并提交 `6c6d228d94933278a36e17fa90ce61c8d690ad58` |
| 独立验收脚本注册 `models.User` | `#43` | 合并提交 `2735dd6e93333121e6934819182dd27754153a10` |
| ASE CIF 导出改用二进制缓冲区 | `#44` | 合并提交 `db05369fe3d0b86844d1242d5ec7a37195cf37e4` |
| Stage 8 首轮验收证据 | `#45` | 合并提交 `d32aafd57a8a5032d52c1edab81e0802e332a967` |
| 区分源码和运行 release | `#46` | 合并提交 `d2e86de0e36515e25a3b3b62364cdebc513925f8` |
| 补齐资源、输出哈希和二维结构展示 | `#47` | 合并提交 `9793ed2cb89a326b13995d16f6834bbcaacc02c5` |
| 在成功和失败结果页提供证据包下载 | `#48` | 合并提交 `6242132c30e8772288e31d9fb5eec930d2f44962` |

Stage 8 当前运行 release 固定为：

```text
6242132c30e8772288e31d9fb5eec930d2f44962
```

Windows 本地 `main`、Gitea `main` 和 107 只读 checkout 已同步到 PR `#48` 合并提交且工作树为空。最终状态文档合并后只同步 checkout，不重建或重启上述不可变 release。

## 3. 构建与测试

最终构建 Job：

```text
Job ID: 40831
Partition/Node: P107-RTX5090/anode01
State/ExitCode: COMPLETED/0:0
Backend: 458 passed, 4 platform skips
Frontend: 126 passed
Vite: 1857 modules transformed
Release manifest entries: 561
```

发布清单：

```text
/home/scc/pb23030683/lmatelab-107cup/releases/6242132c30e8772288e31d9fb5eec930d2f44962/manifest.txt
SHA-256: 627b8c0409758e7226b58d5ba198fbc6f69f3140ab799ea3273b0110ca072e8c
```

构建日志保留在：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/build-40831.out
/home/scc/pb23030683/lmatelab-107cup/logs/build-40831.err
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
Service Job: 40832
Partition/Node: P107-A100/anode18:18731
State: RUNNING
Commit: 6242132c30e8772288e31d9fb5eec930d2f44962
Manifest SHA-256: 627b8c0409758e7226b58d5ba198fbc6f69f3140ab799ea3273b0110ca072e8c
```

以下三处 `live/ready` 已返回同一 Job、节点、提交和 manifest：

- 4090 内部：`127.0.0.1:18740 -> 11.11.10.18:18731 (anode18)`；
- 公网入口：`http://222.195.94.37:18733`；
- Windows Operator：`http://127.0.0.1:21763`。

用户完成人工浏览器验收后，旧 Job `40273/40309/40786` 均确认属于 `pb23030683`、作业名为 `lmatelab-web`、命令为本项目 `service.slurm`，随后受控停止并显示 `CANCELLED`。临时 `18741 -> anode19:18731` 已撤销，4090 仅保留正式 `18740` 监听。清理后 4090 内部、Windows Operator 和公网入口仍返回 Job `40832`，结果页 HTTP 状态均为 `200`。

## 9. 完成门禁

- [x] Viewer/Operator API 角色合同通过，用户在当前登录浏览器中确认 `/dashboard/results` 正常显示。
- [x] 成功详情 `/dashboard/results/4b566547-961b-4e10-a8d0-99431f2e2229` 的结构、BAND、DOS 和 CIF、POSCAR、BAND、DOS、证据包五种下载正常。
- [x] 失败详情 `/dashboard/results/db9c793d-cf8f-4207-823b-5943d825f21d` 保持失败证据视图并提供证据包下载。
- [x] `/dashboard/database/vasp` 的真实只读记录正常显示。
- [x] 旧 Job `40273/40309/40786` 已停止，临时 `18741` 已撤销，三处正式入口保持 Job `40832`。
- [x] Windows `main`、Gitea `main` 和 107 checkout 均已固定到 PR `#48` 合并提交 `6242132c30e8772288e31d9fb5eec930d2f44962`。

上述门禁全部完成，Stage 8 为 `DONE`。Stage 9 另行覆盖恢复、安全、竞态和恶意输入，不把其尚未执行的内容倒算为 Stage 8 缺口。
