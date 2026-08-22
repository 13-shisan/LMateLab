# 107 杯最终验收记录

更新时间：`2026-08-22`

## 1. 当前结论

Stage 10 状态：`PARTIAL`。

四季首页可读性整改已通过 PR #66 合并并部署为固定提交 `4f652db91bdfb1dc28fea0daed4d12b0d9d57215`。正式构建 Job `41672/anode01`、服务 Job `41673/anode16` 和只读验收 Job `41676/anode16` 已完成；4090 relay、Windows Operator 和公网入口均返回该新身份，旧服务 `41648/anode18` 在完整归属核对后停止且旧端口不可达。公开首页桌面和移动浏览器复跑已通过，但全新认证态 Viewer/Operator 全流程复跑及三名成员独立复核仍未完成，因此状态继续为 `PARTIAL`。

Stage 10 验收期间不得提交新的 VASP 计算。固定成功/失败链通过只读方式复核；如确实需要新算例，必须由用户另行明确授权，且不能覆盖既有 attempt 或证据。

既有认证态 Viewer/Operator 截图与 `422.04` 秒视频继续只绑定 `4f81d727...`，不能证明当前 `4f652db9...` 发布的认证态页面。本次只读机器验收和公开首页验收均不改写这一外部门禁。

## 2. 固定发布身份

以下字段只能在 PR 合并并从新 `main` 构建后填写，不能引用 Stage 10 开始前的 Job `41044` 冒充最终发布：

```text
Merged main commit: 4f652db91bdfb1dc28fea0daed4d12b0d9d57215
Build Job ID / node / final state: 41672 / anode01 / scheduler record unavailable; successful logs, release directory and manifest self-check preserved
Release manifest SHA-256: 616b86b1460debd7570d6ba59ccfd19b68d103019fa99c5049ef7e021d55d9ca
Service Job ID / node / port: 41673 / anode16 / 18731
Stage 10 acceptance Job ID / node / final state: 41676 / anode16 / scheduler record unavailable; preserved log ends with STAGE10_ACCEPTANCE_OK and stderr is empty
Stage 10 evidence manifest SHA-256: 488e809e2b43dee581c34c73182b1cbf2a4954e235a4dfbdd376936db34a96c7
Stage 10 summary SHA-256: ff92d05d388db5f9a992e0805ba45413a354ce5484daf14567bd8ec4477712b7
```

## 3. 六层测试门禁

| 层级 | 当前状态 | 最终证据 |
|---|---|---|
| 1. 单元测试 | 通过 | Job `41672` 后端共运行 `494` 项并为 `OK`，其中 4 项环境跳过；前端 `143/143` |
| 2. 假 Slurm 集成 | 通过 | Job `41672` 的后端回归包含 `test_competition_slurm` 全状态、取消和归属门禁 |
| 3. 107 真实 Slurm | 通过（后快照范围不匹配已留证） | 发布前快照 `41670`、构建 `41672`、服务 `41673` 和只读验收 `41676` 均完成；`41676` 日志为 `STAGE10_ACCEPTANCE_OK`。发布后误用预览不变性快照的 Job `41680` 因 `current` 按设计切换而失败，未伪报成功 |
| 4. 真实 VASP | 通过只读复核 | 成功 `40212/40250/40251/40252`，失败 `40264/40265/null/null`；两份确定性证据包哈希未变，没有提交新 VASP |
| 5. 浏览器端到端 | PARTIAL | 当前四季首页桌面/移动、四张资源请求和登录往返通过；全新认证态 Viewer/Operator 全流程仍需针对当前发布重做 |
| 6. 最终演示复跑 | PARTIAL | 既有 Viewer/Operator 截图和连续视频只绑定旧发布；当前发布演示素材和三名成员独立复核待完成 |

任何一层失败都不能被下一层成功替代。机器门禁输出 `STAGE10_ACCEPTANCE_OK` 只表示发布、服务、数据库、路由和固定科学数据的只读核对通过，不代表浏览器和三人复核自动通过。

合并前本地预检（`2026-08-21`）：Stage 8/10 合同测试共 `6/6` 通过，前端 Node 测试 `129/129` 通过，107 Cup live Vite 构建完成 `1857` 个模块转换。额外运行的全仓库 ESLint 仍有既存 `36 errors / 22 warnings`，命中注册、Agent、QE/EPW、监控等未由本阶段修改且不进入 107 Cup 运行面的旧源码；不能把这次 lint 写成通过，也不在 Stage 10 中扩大范围修复。合并后的 107 Slurm 正式构建仍必须重新执行后端和前端门禁。

PR #55 合并提交 `db03e360b450b41f483fa98e62157ec6c993f6ba` 的首次正式构建 Job `41064` 在 `P107-RTX5090/anode01` 失败关闭。后端运行 `489` 项，结果为 `1 failure + 4 skipped`；唯一失败是仓库交付清单在 Windows 生成时对既有 `implementation-plan.md` 的 CRLF 字节计算哈希，而 Git 和 107 检出为 LF。失败发生在前端和发布目录生成之前，旧 `current`、服务 Job `41044`、数据库和固定工作流均未改变。热修复只把固定 UTF-8 文本规范化为 LF 后计算清单，不能删除文件校验或改写旧证据。

PR #56 将跨平台清单修复合并为 `4e79c07b198b34e54be332638868e82249357d1f`。发布前快照 Job `41138` 通过；正式构建 Job `41139` 通过后端 `489/489`（另有 4 项环境跳过）、前端 `129/129`、Vite `1857` 个模块和 `595` 项 release manifest，自检后的 release manifest SHA-256 为 `33891563e9e69232b60661176cf132c9e9f4524a88515a61693f59e1d841cac3`，`current` 已切换到该固定提交。

候选服务 Job `41142` 曾在 `P107-A100/anode18:18731` 运行，通过固定内部地址 `11.11.10.18` 访问时 live/ready 均正确返回新 Job、commit 和 manifest。旧恢复器因登录节点不能解析 `anode18` 而报告 `service_not_ready`，4090 relay 正确拒绝切换并继续保留旧入口；这段失败关闭证据未被删除。

地址修复通过 PR #57 合并。发布前快照 Job `41477` 为 `COMPLETED/0:0`；正式构建 Job `41478/anode01` 通过后端 `492/492`（另有 4 项环境跳过）、前端 `129/129` 和 release manifest 自检。服务 Job `41479` 在 `P107-A100/anode19:18731` 运行，4090 relay 使用内部地址 `11.11.10.19` 完成受控切换。旧服务 Job `41044/41142` 在核对项目归属后受控停止，旧端口随后不可达。

发布后快照 Job `41481` 确认两套 SQLite 的 SHA-256 与发布前完全一致，完整性均为 `ok`。只读验收 Job `41482/anode16` 重新核对发布、路由、数据库、结构、BAND、DOS 和固定成功/失败证据包，日志结尾为 `STAGE10_ACCEPTANCE_OK`。其证据目录为 `/home/scc/pb23030683/lmatelab-107cup/evidence/stage10/acceptance-41482`，文件权限为 `0600`；当前 `scontrol`/`sacct` 记录已过期，最终状态以当时保存的 Job 结果、空 stderr、成功日志和证据清单共同固定。

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

- [x] 源码固定为合并后 `main`，发布目录、`commit.txt` 与服务 commit 相同。
- [x] Python/Node 环境、SQLite、服务、工作流、attempt、VASP 输出和证据均位于 `/home/scc/pb23030683/lmatelab-107cup`。
- [x] 服务运行在 Slurm 计算节点，107 登录节点无 LMateLab 常驻进程。
- [x] 4090 只保存网络转发状态，不保存竞赛业务数据库或运行 FastAPI/VASP。
- [x] Windows Operator 隧道与公网 Viewer 返回同一 Job、node、commit 和 manifest。
- [x] 原 4090 LMateLab 未被本阶段停止或修改；其存在不能成为竞赛服务运行条件。

“原 4090 LMateLab 停止时仍运行”属于生产影响操作，没有用户明确停机授权时不得主动执行。最终可用现有架构证据、107 直连和转发失败关闭测试证明业务独立，并把未做真实生产停机演练的边界写清楚。

## 6. 功能范围门禁

- [x] 竞赛 API 仅挂载认证、健康检查和竞赛工作流固定 allowlist。
- [x] 前端导航只包含 Dashboard、新建计算、工作流、结果和 VASP 数据库。
- [x] Agent、聊天、RAG、机器学习、QE/EPW、跨服务器迁移、服务器监控、报告和其他旁支不可访问。
- [x] Viewer 无提交、取消、重试、修改和敏感日志权限。
- [x] Operator 只能通过固定模板和固定 Slurm 适配器执行受限主线；全新 Operator 浏览器已完成只读复跑且未触发提交、取消、重试或其他写请求。

仓库保留的旧源码不等于竞赛运行面。最终核对以 `main_107cup.py` 实际路由、前端生产 bundle、浏览器导航和网络请求为准。

## 7. 浏览器与素材记录

```text
Viewer fresh-session evidence directory: /home/scc/pb23030683/lmatelab-107cup/evidence/stage10/browser-4f81d727-20260822
Operator fresh-session evidence directory: /home/scc/pb23030683/lmatelab-107cup/evidence/stage10/browser-4f81d727-20260822/operator-desktop
Desktop viewport(s): Viewer 1440x900 passed; Operator 1440x900 passed
Mobile viewport(s): Viewer 390x844 passed
Console error count: Viewer desktop 0; Viewer mobile 0; Operator desktop 0
Structure/BAND/DOS non-white pixel ratios: Viewer desktop 0.0116 / 0.0259 / 0.0838; Viewer mobile 0.0230 / 0.0897 / 0.1719; Operator desktop 0.006547 / 0.027192 / 0.083188
Viewer screenshot manifest SHA-256: fdd5b0c047be047e325675661001b3714bdbee976cfff7f14c86bdd899fb59c5
Viewer summary SHA-256: d7525956e580acb9dde71cbdaeb1c57407156cb36bd2938555abb0b382967d8a
Operator evidence manifest SHA-256: 6edcebe75ebb995e5534234809acd8c402e47a4b7ce47d8f1f4e0a14205d1596
Operator summary SHA-256: 40bf967125c6acd89f6cdd7267a4d0b1f63e38fe020352817b7c7dda5500249e
Video material path and SHA-256: operator-desktop/operator-stage10-demo.webm / e752d36a311a1a31e56ce42da588db2e64e9a634ac51f1cb1c13fd8c39cec2ab
```

上述 Viewer/Operator 记录为 `4f81d727...` 的历史证据，不能作为本节当前固定发布 `4f652db9...` 的最终素材。当前发布的全新认证态截图和视频仍需重做，且不得包含密码、token、JWT、SSH 信息或未裁剪敏感日志。

Viewer 新会话通过公网白名单入口复核了 Dashboard、工作流列表、成功结果、失败结果、新建计算、VASP 数据库和元素周期表。成功结果显示四步 Job `40212/40250/40251/40252`、带隙 `1.6919 eV`、结构、BAND 与 DOS；失败结果显示 SCF `electronic_not_converged`，BAND/DOS 为依赖失败且未启动。新建计算的来源、参数、保存和校验控件均禁用，取消和重试不可用。Mo+S 的“至少含有”和“只含所选元素”筛选均返回两条固定记录。

Viewer 桌面与移动会话均为页面级零横向溢出；周期表和宽表只在自身有边界的区域内横向滚动。控制台错误与警告均为 0，已检查的认证、结果和数据库 GET 请求全部返回 `200`，没有观察到意外写请求。19 张 PNG 的 `viewer-manifest.sha256` 已在本地逐项复核并上传到上述 `0700` 私有目录，文件权限为 `0600`；目录不包含 Playwright storage state、密码、token、JWT 或 `.playwright-cli` 快照。

Operator 由用户在 Windows 隧道入口现场登录，页面确认身份为“107杯管理员 / 操作员”。连续 `422.04` 秒录屏覆盖 Dashboard、工作流成功/失败证据、结果、结构、BAND、DOS、新建计算和 VASP 数据库 Mo+S 精确筛选；13 张 PNG 与 1 个 WebM 均由 `operator-manifest.sha256` 逐项复核并上传为 `0600`。控制台错误与警告均为 0，7 个业务请求全部为成功 GET，没有 POST/PUT/PATCH/DELETE，也没有提交、取消、重试、Slurm 或 VASP 操作。录屏从已登录工作台开始，经抽帧检查不含密码、token、JWT、Cookie 或 SSH 信息；临时认证会话和抽帧接触表已删除。

四季首页固定发布 `4f652db9...` 以公网入口在 `1440x900` 和 `390x844` 复核：页面可在未认证状态打开，春、夏、秋、冬四张独立 WebP 均成功加载，公开正文不含 `MoS2`。桌面四段高度均为 `960px`，首屏摘要和区段标题计算字号分别为 `20px` 与 `48px`；移动端各区段 `scrollHeight` 与 `clientHeight` 一致。两种视口页面横向溢出、失败图片和控制台错误/警告均为 0，首页到登录页及返回首页的双向跳转通过。该公开首页证据不替代认证态复跑。

发布前快照 Job `41670` 的 manifest SHA-256 为 `b484d9d7d99ab8f96db6fabb1b77ae1d84c65526572b4134f8c848279c5a95c0`。发布后 Job `41680` 使用的是要求 `current` 和服务身份前后不变的预览快照合同，因此在比较旧 `565edfda...` 与新 `4f652db9...` 的 `current-target.txt` 时失败；失败发生在生成后快照 manifest 之前，证据目录保留但不能写成成功快照。两库发布前后完整性均为 `ok`：`digests.db` SHA-256 保持 `2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969`，`eln.db` 从 `29cf102884c1b36f6cef8c251bb569aa6cebd837b4d3957989a6efaa8a96ddbc` 变为 `018bd0e10b7e97482158bbd06a003c092b208d910795134d3e957dc8e14506e2`。变化来自此前已合并 PR #65 的 `107c0ffee001 -> 107c0ffee002` Agent 表迁移，不是首页逻辑写入；Stage 10 复核的两条固定工作流和成功/失败证据包哈希未变。没有提交 VASP。

已知 UX 问题：Operator 查看已验收或失败终态工作流时，“取消工作流”按钮仍显示为可用。源码核对确认后端在没有活动 attempt 时固定返回 `workflow_not_cancellable`，不会调用 `scancel`；本次验收没有点击该按钮，也没有发送取消 POST。该问题不突破后端归属和终态门禁，但后续前端版本应按工作流状态禁用终态取消按钮；在修复重新构建前，本节证据继续严格绑定固定发布 `4f81d727...`。

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
