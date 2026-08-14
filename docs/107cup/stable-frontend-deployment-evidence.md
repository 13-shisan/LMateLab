# 107 杯稳定前端部署证据

记录日期：`2026-08-14`

## 1. 范围与结论

本次只把已经实现并通过阶段 5 验收的竞赛前端部署为 107 稳定服务。没有开始阶段 6，没有提交普通 Slurm 控制作业或 VASP 作业，也没有增加 Agent、机器学习或其他功能。

稳定运行状态：

- Gitea PR：`#24`
- 固定提交：`bec82bc9fed3ad9355235b965f5bf8cdba152a60`
- 正式发布：`/home/scc/pb23030683/lmatelab-107cup/releases/bec82bc9fed3ad9355235b965f5bf8cdba152a60`
- 正式服务：Job `37715`，`P107-RTX5090/anode02:18731`
- 公开入口：`http://222.195.94.37:18733`
- 健康元数据：`release_kind=stable`、`data_mode=live`
- 4090 仅转发网络流量；源码、发布、数据库、服务与计算运行态均位于 107。

## 2. 源码与部署前快照

Windows `main`、Gitea `main` 和 107 detached checkout 均固定到 `bec82bc9fed3ad9355235b965f5bf8cdba152a60`，107 工作树为空。

部署前快照：

- Job：`37703`
- 节点：`anode16`
- 状态：`COMPLETED/0:0`
- 证据目录：`/home/scc/pb23030683/lmatelab-107cup/evidence/previews/bec82bc9fed3ad9355235b965f5bf8cdba152a60/before-37703`
- 证据 manifest SHA-256：`fc60d5051ebe8025ca3abfd4b5794d5b8690dc1fbd5d7d77ddbd0478bc26e94e`
- 当时稳定服务：Job `36597`，`anode01:18731`，提交 `1bba72d0ade2bb7024081d384584524a9c9d1c69`

## 3. 候选构建与页面验收

候选构建 Job `37704` 在 `anode01` 以 `COMPLETED/0:0` 结束：

- 后端：`126/126`
- 前端：`111/111`
- Vite：`1857` modules transformed
- preview manifest：`483` 项
- preview manifest SHA-256：`89e43dec23c9d6cbb3382354ba07be6bdd67ee28cee434e7c9efe3dbb31728ea`
- stdout SHA-256：`2fdeebeb0f9a18765c319a44e0eb354511b8e6e8e399ad3c85e6a704f458e0e7`
- stderr SHA-256：`12849aec5707ae5de218e3098aac13316aa060393af2bb118e2ac8956f0cfd29`

候选服务 Job `37707` 在 `anode01:21707` 启动，健康响应固定为提交 `bec82bc9`、`preview/live`。运行态验证通过：

- Alembic head：`107c0ffee001`
- 六张表：`workflow_runs`、`workflow_steps`、`workflow_attempts`、`workflow_events`、`workflow_files`、`workflow_templates`
- 候选验收前工作流数：`0`
- SQLite integrity：`ok`
- ready：`200`

Browser 插件不可用，因此使用仓库已安装的 Playwright `1.54.2`。目标流为：登录候选服务 -> 五个导航入口 -> 七条受保护路由 -> live 空状态与交互检查。

验收结果：

- 视口：`1440x900`、`1024x768`、`390x844`
- 导航入口：工作台、新建计算、工作流、结果、VASP 数据库
- 受保护路由：`7`
- 页面截图：`21`
- 相关控制台问题：`0`
- 页面错误：`0`
- 失败请求：`0`
- 意外业务写请求：`0`
- 横向溢出：`0`
- 工作流、结果与 VASP 数据库：`data_kind=live` 的真实空集合，没有回退 demo

补充 Canvas 门禁等待结构加载完成后再截图：

- Desktop：`1676/339320` 非空彩色像素
- Mobile：`2708/122040` 非空彩色像素
- 两个视口的 console/page/request failure 均为 `0`

Windows 外部证据目录：

`D:\Documents\matflow项目\LMateLab-107Cup-evidence\stable-frontend-deploy-bec82bc-job37707`

Manifest 覆盖 `29` 项受控载荷；目录共 `31` 个文件，另含 `evidence-manifest.txt` 和 `evidence-manifest.sha256`。`evidence-manifest.txt` SHA-256 为 `0a2bd6c091c8f5a432333f53a70a6e067edc9483a0fbd83a6be4baa8e11245b6`。凭据只通过环境变量进入 Playwright 进程，没有写入脚本、截图、JSON 或 manifest。

## 4. 正式构建

正式构建 Job `37711`：

- 节点：`anode01`
- 状态：`COMPLETED/0:0`
- 运行时间：`00:01:39`
- 正式构建脚本自身后端部署专项：`54/54`
- 前端：`111/111`
- Vite：`1857` modules transformed
- 正式 release manifest：`491` 项
- 正式 manifest SHA-256：`d953c0a6339e3ba68ab8f7709096770c6eb397cd441040719e62073ddf62495b`
- stdout SHA-256：`da45d3f2f4213c7855d75f23390e4916eb43e26b76e474e27631ef11cf3bb3b8`
- stderr SHA-256：`9ef815391cac4653164dc4240fe3a3a2d92cdd9e1a1c1db9152446327a52ebe4`

候选构建的 `126/126` 与正式构建的 `54/54` 都是同一固定提交的真实证据，但属于不同脚本的门禁数量，不相互替代。

## 5. 并行服务启动与保留失败证据

首次尝试通过环境变量 `SBATCH_EXCLUDE=anode01` 排除旧节点，但当前 Slurm 没有把该环境覆盖转换为排除参数。Job `37713` 仍分配到 `anode01`：

- 状态：`FAILED/1:0`
- 阶段 5 migration 已运行
- 直接失败：`[Errno 98] ... 18731: address already in use`
- 旧 Job `36597` 在失败前后持续返回原提交健康响应
- stdout SHA-256：`74837bb3b4d65b9d52f22a14437d523f3616618ca62e4cb323302f1851fae590`
- stderr SHA-256：`ad7d726590202f1842d961ea3e06fc1227736427719657fecfdb381fafb6385e`

该失败没有删除或覆盖；后续显式执行：

```bash
sbatch --parsable --exclude=anode01 \
  /home/scc/pb23030683/projects/LMateLab-107Cup/deploy/107cup/service.slurm
```

Job `37715` 的 `scontrol` 明确记录 `ExcNodeList=anode01`，最终运行于 `anode02:18731`。直接验证结果：

- live：`200`，Job `37715`、提交 `bec82bc9`、正式 manifest 哈希、`stable/live`
- ready：`200`
- `eln.db` integrity：`ok`
- `digests.db` integrity：`ok`
- 登录节点没有 Uvicorn、Vite、Celery 或 Redis 常驻进程

## 6. 入口切换与旧服务停止

先创建临时 `127.0.0.1:18737 -> anode02:18731` 并验证 Job `37715`，再将稳定 `127.0.0.1:18734` 从 `anode01:18731` 切换到 `anode02:18731`。Nginx 配置和 IP 白名单没有修改：

- Nginx config SHA-256：`0c011ea9442733daf5d3277d4632a662264083ff0432b9abdfaad5b5828c99c8`
- 4090 内部 `18734`：返回 Job `37715`
- 4090 公共 `18733`：返回 Job `37715`
- Windows 从白名单地址直连公共入口：返回 Job `37715`

公共入口 HTTP 门禁：

| 请求 | 状态 |
|---|---:|
| `GET /login` | `200` |
| `GET /dashboard` | `200` |
| `GET /api/health/ready` | `200` |
| 未认证 `GET /api/competition/workflows` | `401` |
| 空 `POST /api/auth/login` | `422` |
| `POST /api/auth/register` | `403` |
| `POST /api/competition/workflows` | `403` |

新入口通过后才停止旧服务：

- 旧 Job `36597`：`CANCELLED/0:15`
- Uvicorn：完整 shutdown
- `anode01:18731`：不可达
- 旧服务 stderr 最终 SHA-256：`6e75a4e1a833cc175c8b364b4f803e85add771213640416dae894d555ec811a5`
- 停止旧服务后公共入口仍返回新 Job `37715`

候选 Job `37707` 随后受控停止；Uvicorn 完整 shutdown，`anode01:21707` 不可达。Windows `18736` 与 4090 临时 `18736/18737` 均已移除，只保留稳定 `18734`。

## 7. 部署后快照与数据库变化

部署后使用同一只读快照收集器生成当前状态快照。由于该脚本的 `after` 模式专门要求稳定状态与部署前完全相同，本次正式发布不能误用 `after`；因此以新的 `before-37718` 目录保存部署后的独立状态，而不执行错误的相等比较。

- Job：`37718`
- 节点：`anode19`
- 状态：`COMPLETED/0:0`
- 目录：`/home/scc/pb23030683/lmatelab-107cup/evidence/previews/bec82bc9fed3ad9355235b965f5bf8cdba152a60/before-37718`
- manifest SHA-256：`2a9a3446a234fd97039586b5339f217cc41caf4163052ed4dd3520242156a9b7`

数据库前后对比：

| 数据库 | 部署前 SHA-256 | 部署后 SHA-256 | 结论 |
|---|---|---|---|
| `eln.db` | `cd5d639bccfa35414769901f444bf64b867826ce20962d5098a0dac8e07f135a` | `de6176f960e6b7cbe4e44254585b23a8032e7ca146236cab7ec2eea736c6ce86` | 阶段 5 migration 产生预期变化；完整性 `ok` |
| `digests.db` | `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969` | `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969` | 未改变；完整性 `ok` |

## 8. 验收边界

- 正式服务没有创建临时明文账号，因此完整五入口/七路由的认证浏览器证据来自同一固定提交和 live 正式数据库副本的候选 Job `37707`；正式 Job `37715` 由 release manifest、健康元数据、ready、数据库完整性和公共入口门禁证明运行的是同一提交的 stable/live 发布。
- 当前页面中的工作流、结果和 VASP 数据库允许为空；空状态不是数据缺失错误，也不能伪装为真实 VASP 成功结果。
- 阶段 6、阶段 7 和阶段 8 仍为 `PENDING`。本次没有提交普通 Slurm 控制作业，没有运行 VASP，也没有生成 BAND/DOS 真实结果。
- 服务 Job 与 4090 SSH 转发尚未自动恢复，因此阶段 3 保持 `PARTIAL`。
