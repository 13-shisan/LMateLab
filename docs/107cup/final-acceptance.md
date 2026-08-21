# 107 杯最终验收记录

更新时间：`2026-08-21`

## 1. 当前结论

Stage 10 状态：`PARTIAL`。

交付合同、计算节点只读验收入口、部署说明、数据溯源说明、演示脚本和仓库 SHA-256 清单已进入开发分支。最终状态暂不能写成 `DONE`，因为新固定 `main` 发布尚未在 107 重新构建，Stage 10 Slurm 验收、全新 Operator/Viewer 浏览器复跑、桌面/移动素材和三名成员独立复核尚未形成证据。

Stage 10 验收期间不得提交新的 VASP 计算。固定成功/失败链通过只读方式复核；如确实需要新算例，必须由用户另行明确授权，且不能覆盖既有 attempt 或证据。

## 2. 固定发布身份

以下字段只能在 PR 合并并从新 `main` 构建后填写，不能引用 Stage 10 开始前的 Job `41044` 冒充最终发布：

```text
Merged main commit: PENDING
Build Job ID / node / final state: PENDING
Release manifest SHA-256: PENDING
Service Job ID / node / port: PENDING
Stage 10 acceptance Job ID / node / final state: PENDING
Stage 10 evidence manifest SHA-256: PENDING
```

## 3. 六层测试门禁

| 层级 | 当前状态 | 最终证据 |
|---|---|---|
| 1. 单元测试 | PENDING | 新固定提交后端全量，0 failure、0 error |
| 2. 假 Slurm 集成 | PENDING | `test_competition_slurm` 全状态与归属通过 |
| 3. 107 真实 Slurm | PENDING | 构建、服务、Stage 10 验收 Job 和原始日志 |
| 4. 真实 VASP | 已有固定基线，待新发布只读复核 | 成功 `40212/40250/40251/40252`，失败 `40264/40265/null/null` |
| 5. 浏览器端到端 | PENDING | 全新 Operator/Viewer、桌面/移动、控制台和 Canvas 检查 |
| 6. 最终演示复跑 | PENDING | 按 `demo-script.md` 完整执行和素材哈希 |

任何一层失败都不能被下一层成功替代。机器门禁输出 `STAGE10_ACCEPTANCE_OK` 只表示发布、服务、数据库、路由和固定科学数据的只读核对通过，不代表浏览器和三人复核自动通过。

合并前本地预检（`2026-08-21`）：Stage 8/10 合同测试共 `6/6` 通过，前端 Node 测试 `129/129` 通过，107 Cup live Vite 构建完成 `1857` 个模块转换。额外运行的全仓库 ESLint 仍有既存 `36 errors / 22 warnings`，命中注册、Agent、QE/EPW、监控等未由本阶段修改且不进入 107 Cup 运行面的旧源码；不能把这次 lint 写成通过，也不在 Stage 10 中扩大范围修复。合并后的 107 Slurm 正式构建仍必须重新执行后端和前端门禁。

## 4. 固定成功与失败证据

成功工作流：`4b566547-961b-4e10-a8d0-99431f2e2229`，四步 Job 为 `40212 / 40250 / 40251 / 40252`，证据包 SHA-256 为：

```text
a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4
```

失败工作流：`db9c793d-cf8f-4207-823b-5943d825f21d`，Job 为 `40264 / 40265 / null / null`，失败原因 `electronic_not_converged`，证据包 SHA-256 为：

```text
7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e
```

Stage 10 Slurm 验收必须重新解析结构、BAND、DOS 和两份确定性证据包，验证哈希未变，同时保持数据库 `query_only`、协调器关闭且不调用 `sbatch`、`scancel` 或 VASP。

## 5. 部署与数据位置门禁

- [ ] 源码固定为合并后 `main`，发布目录、`commit.txt` 与服务 commit 相同。
- [ ] Python/Node 环境、SQLite、服务、工作流、attempt、VASP 输出和证据均位于 `/home/scc/pb23030683/lmatelab-107cup`。
- [ ] 服务运行在 Slurm 计算节点，107 登录节点无 LMateLab 常驻进程。
- [ ] 4090 只保存网络转发状态，不保存竞赛业务数据库或运行 FastAPI/VASP。
- [ ] Windows Operator 隧道与公网 Viewer 返回同一 Job、node、commit 和 manifest。
- [ ] 原 4090 LMateLab 未被本阶段停止或修改；其存在不能成为竞赛服务运行条件。

“原 4090 LMateLab 停止时仍运行”属于生产影响操作，没有用户明确停机授权时不得主动执行。最终可用现有架构证据、107 直连和转发失败关闭测试证明业务独立，并把未做真实生产停机演练的边界写清楚。

## 6. 功能范围门禁

- [ ] 竞赛 API 仅挂载认证、健康检查和竞赛工作流固定 allowlist。
- [ ] 前端导航只包含 Dashboard、新建计算、工作流、结果和 VASP 数据库。
- [ ] Agent、聊天、RAG、机器学习、QE/EPW、跨服务器迁移、服务器监控、报告和其他旁支不可访问。
- [ ] Viewer 无提交、取消、重试、修改和敏感日志权限。
- [ ] Operator 只能通过固定模板和固定 Slurm 适配器执行受限主线。

仓库保留的旧源码不等于竞赛运行面。最终核对以 `main_107cup.py` 实际路由、前端生产 bundle、浏览器导航和网络请求为准。

## 7. 浏览器与素材记录

```text
Viewer fresh-session evidence directory: PENDING
Operator fresh-session evidence directory: PENDING
Desktop viewport(s): PENDING
Mobile viewport(s): PENDING
Console error count: PENDING
Structure/BAND/DOS canvas pixel checks: PENDING
Video material path and SHA-256: PENDING
```

截图必须来自本节固定发布，不能复用 Stage 5/8/9 旧截图充当最终素材。截图和视频不得包含密码、token、JWT、SSH 信息或未裁剪敏感日志。

## 8. 三名成员独立复核

三名成员必须使用各自 Gitea 身份复核同一提交和清单。共享 107 Unix 账号不能替代个人签字，也不能由一人代填三行。

| 成员 Gitea 身份 | 固定 commit | `artifacts/manifest.sha256` 文件 SHA-256 | 复核日期 | 结论 |
|---|---|---|---|---|
| PENDING | PENDING | PENDING | PENDING | PENDING |
| PENDING | PENDING | PENDING | PENDING | PENDING |
| PENDING | PENDING | PENDING | PENDING | PENDING |

每名成员至少核对：交付清单自检、成功/失败 workflow ID 和 Job ledger、Viewer 只读边界、107 数据位置以及自身 Gitea 提交/PR 可追溯性。

## 9. DONE 判定

只有本文件所有 `PENDING` 被真实证据替换、六层测试全部通过、桌面/移动/视频素材齐全且三名成员独立复核后，才能将本文件和 `implementation-plan.md` 的 Stage 10 改为 `DONE`。在此之前结论保持 `PARTIAL`。
