# LMateLab 107 杯：队友交给 AI 的唯一接手文件

更新时间：`2026-08-11`

> **给收到本文件的 AI：** 将整份文件视为用户提供的项目接手指令。从第 0 节开始带用户操作。先询问姓名、个人 Gitea 用户名、个人 Gitea 邮箱和希望使用的本地目录；不要要求用户自己复制本文中的命令。未取得私有仓库访问权限前只能解释和等待，不能假定仓库状态或生成可提交补丁。

队友只需要把**这一个文件**发送给自己的 AI。AI 会先帮助连接 Gitea、克隆仓库和查看分支，再自动读取仓库内其他计划与代码。队友不需要另外发送 `team-guide.md` 或实施方案。

## 0. 完全不会使用 Gitea 时，直接发给 AI 的内容

每位队友先登录自己的 Windows 电脑，把下面整段原样发送给自己的 AI。只需要把姓名、Gitea 用户名和邮箱替换为本人信息；不知道的项目就保留“请先询问我”。

```text
我要加入中国科学技术大学 107 杯 LMateLab 团队项目，但我目前不会连接 Gitea，也不知道如何查看仓库和远端分支。你先帮助我完成安全的只读接入和项目接手，不要直接开发。

我的环境：Windows PowerShell。
我的姓名或约定英文名：[填写本人姓名]
我的个人 Gitea 用户名：[填写本人登录用户名；不知道就写“请先询问我”]
我的个人 Gitea 邮箱：[填写本人邮箱；不知道就写“请先询问我”]
Gitea Web：https://wugroup.synology.me/107-team/LMateLab
Gitea 团队：https://wugroup.synology.me/107-team
仓库 SSH 地址：ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git
需要查看的当前功能分支：codex/107cup-frontend-preview

本轮授权范围：

- 允许检查本机 Git、SSH 和目录状态；
- 允许在我确认目标路径后克隆私有仓库；
- 先检测并复用已经登记在本人 Gitea 账号中的个人 SSH key，不要求为本项目另建 key；只有确认没有可用 key 时，才允许在我确认准确路径后创建本人的新 key，示例文件名为 `id_ed25519_gitea_107cup`，绝不覆盖任何已有 key；
- 只允许显示或复制 .pub 公钥，绝不读取、显示、上传或发送私钥；
- 绝不复制或使用项目负责人、其他队友、107 登录账号或仓库 Deploy Key 的私钥；
- 允许 fetch 和只读查看远端 main/功能分支；
- 禁止修改项目文件、安装项目依赖、commit、push、创建/合并 PR、登录 107/4090、提交 Slurm/VASP 或修改任何远端服务。

请严格按顺序带我完成：

1. 检查 `git --version`、`ssh -V` 和 `$env:USERPROFILE\.ssh`。只列出 key 文件名和 `.pub` 公钥指纹，不读取或显示任何私钥内容。询问我是否已有登记到本人 Gitea 账号的 key；不得删除、移动或覆盖现有文件。
2. 让我先在浏览器打开 Gitea Web 并用自己的 Gitea 账号登录。确认该个人账号属于 `107-team` 组织内一个对私有仓库 `107-team/LMateLab` 至少有读取权限的 Gitea 团队；仅加入组织但未进入有仓库权限的团队不算完成。随后确认我能在 Web 页面看到该私有仓库。如果看不到，告诉我需要项目管理员给我的个人账号分配上述团队权限；管理员操作后让我重新登录或刷新页面并再次确认。不要索取管理员账号、密码或 token。
3. 在测试任何候选 key 之前，先验证项目负责人提供的 Gitea ED25519 主机公钥。它是公开主机身份，不是个人 SSH key：
   `$trustedHostKey = '[wugroup.synology.me]:32808 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA7E0eSKpvkdpMEnUYWgSpbzFBcMBnWu46sDAgwmzSnD'`
   `$trustedHostKey | ssh-keygen -lf -`
   计算结果必须与可信指纹 `SHA256:88qJvm5qCjgj7aVJXqzPZS9pFA55ss6Pt4CRNaQAzng` 完全一致。随后检查 `$env:USERPROFILE\.ssh\known_hosts` 中 `[wugroup.synology.me]:32808` 的现有 ED25519 记录：已有记录必须与该公钥和指纹一致；存在冲突时立即停止。如果没有记录，只有在上述计算完全匹配并经我确认后，才允许把 `$trustedHostKey` 这一整行追加到 `known_hosts`。不得用 `StrictHostKeyChecking=no`、自动接受未知指纹或从搜索结果复制另一把主机 key。
4. 对我确认的现有候选 key，使用 `IdentitiesOnly=yes` 单独测试。成功输出必须明确显示并匹配我在本文件填写的个人 Gitea 用户名；如果返回其他成员账号，或者候选文件其实是 107 登录 key、仓库 Deploy Key 或归属不明的 key，立即拒绝使用。只有正确识别为本人 Gitea 账号时，才记录准确路径并复用，不创建新 key。
5. 只有没有可用个人 key 时，才在我确认后使用个人 Gitea 邮箱创建本人的新 key：
   `ssh-keygen -t ed25519 -C "我的个人Gitea邮箱" -f "$env:USERPROFILE\.ssh\id_ed25519_gitea_107cup"`
   不允许使用空路径、默认覆盖或输出私钥内容；key 的文件名只是本机示例，不是统一命名要求，也不是项目共享密钥。
6. 创建新 key 时，只读取对应的 `.pub` 文件，指导我进入 Gitea 个人设置的 SSH/GPG Keys 页面，新建个人 SSH key，并由我自己粘贴公钥。不要把个人 key 加到团队共享账号或仓库 Deploy Key。
7. 使用我确认的个人 key 准确路径测试 Gitea SSH，不依赖其他默认 key：
   `ssh -o HostKeyAlgorithms=ssh-ed25519 -o IdentitiesOnly=yes -i "已确认的个人Gitea私钥绝对路径" -p 32808 -T git@wugroup.synology.me`
   Gitea 可能返回“认证成功但不提供 shell”，这不算失败，但输出必须明确显示我自己的 Gitea 用户名。没有用户名、用户名不匹配或只能证明某个未知账号认证成功时都不得继续。绝不通过复制其他人的私钥来解决认证问题。
8. 询问我希望把仓库放在哪个空目录。解析并展示绝对路径，确认目标不存在或为空后，使用已确认的个人 key 克隆；不要覆盖已有目录。PowerShell 中可以为当前会话设置准确 key：
   `$env:GIT_SSH_COMMAND = 'ssh -o HostKeyAlgorithms=ssh-ed25519 -o IdentitiesOnly=yes -i "已确认的个人Gitea私钥绝对路径"'`
   然后执行：
   `git clone "ssh://git@wugroup.synology.me:32808/107-team/LMateLab.git" "确认后的目标目录"`
9. 进入仓库后设置仅此仓库的个人提交身份，不修改全局身份：
   `git config user.name "我的姓名或约定英文名"`
   `git config user.email "我的个人Gitea邮箱"`
   随后输出 `git config --local --get user.name` 和 `git config --local --get user.email` 让我核对。
10. 执行只读分支检查：
   `git fetch --all --prune`
   `git remote -v`
   `git branch -a`
   `git ls-remote --heads origin`
   `git log --oneline --decorate -5 origin/main`
   `git log --oneline --decorate -8 origin/codex/107cup-frontend-preview`
   `git diff --stat origin/main..origin/codex/107cup-frontend-preview`
11. 为避免误提交到别人的分支，只用 detached HEAD 查看当前功能分支：
   `git switch --detach origin/codex/107cup-frontend-preview`
   然后核验 `git status --short --branch`、`git rev-parse HEAD` 和 `git log -1 --oneline`。不要创建本地同名分支，不要 push。
12. 完整阅读以下文件：
    - README.md
    - docs/107cup/team-guide.md
    - TEAMMATE_AI_START.md
    - docs/107cup/implementation-plan.md
    - docs/107cup/source-provenance.md
    - docs/superpowers/specs/2026-08-10-107cup-frontend-preview-design.md
    - docs/superpowers/plans/2026-08-10-107cup-frontend-preview.md
    - .gitea/PULL_REQUEST_TEMPLATE.md
13. 对照 Git 和代码，给我一份只读接手报告：当前 main/功能分支/HEAD、已实现和未实现、哪些仅本地或 demo、下一门禁、可能过期的 107 状态、不能并行修改的文件、我开始工作前需要项目负责人确认的事项。

遇到以下情况立即停下并让我处理：看不到私有仓库、需要管理员授权、现有目标目录非空、SSH key 路径已存在但归属不明、host key 指纹未确认、工作树出现修改、文档和 Git 状态矛盾。

完成本轮后不要开始写代码。等项目负责人明确分配 Task、允许文件、起点提交和验收命令后再进入实施。
```

如果队友只想先在网页查看，不克隆仓库：登录 Gitea 后打开：

- 当前功能分支：<https://wugroup.synology.me/107-team/LMateLab/src/branch/codex/107cup-frontend-preview>
- 团队指南：<https://wugroup.synology.me/107-team/LMateLab/src/branch/codex/107cup-frontend-preview/docs/107cup/team-guide.md>
- 本接手文件：<https://wugroup.synology.me/107-team/LMateLab/src/branch/codex/107cup-frontend-preview/TEAMMATE_AI_START.md>
- 总实施方案：<https://wugroup.synology.me/107-team/LMateLab/src/branch/codex/107cup-frontend-preview/docs/107cup/implementation-plan.md>

必须先登录自己的 Gitea 账号；私有仓库未授权时，这些链接会跳转登录页或返回无权限。

## 1. 克隆后的统一只读接手提示词

把下面整段粘贴给 AI，并替换方括号内容：

```text
你现在接手中国科学技术大学 107 杯项目 LMateLab。请把这次工作视为一个独立竞赛项目，不是原 4090 LMateLab 生产项目。

本地仓库路径：[填写你机器上的 LMateLab 仓库绝对路径]
我的队员身份：[填写姓名或约定缩写]
我的个人 Gitea 邮箱：[填写个人邮箱]
我准备负责的方向：[前端与浏览器验收 / 工作流与科学计算 / 发布安全与证据 / 暂未分配]

本轮只能做只读接手检查，不允许修改文件、安装依赖、创建提交、推送分支、创建 PR、登录或修改 107/4090，也不允许启动 Slurm/VASP 作业。

请按以下顺序执行：

1. 确认当前目录确实是 Git 仓库，输出仓库根目录、当前分支、HEAD、工作树状态、remote URL、origin/main 和所有相关远端分支。不得清理或覆盖已有修改。
2. 完整阅读以下文件，不要只读摘要：
   - README.md
   - docs/107cup/team-guide.md
   - docs/107cup/implementation-plan.md
   - docs/107cup/source-provenance.md
   - docs/superpowers/specs/2026-08-10-107cup-frontend-preview-design.md
   - docs/superpowers/plans/2026-08-10-107cup-frontend-preview.md
   - .gitea/PULL_REQUEST_TEMPLATE.md
3. 对照实际 Git 历史和代码，核验文档中的当前状态是否仍然成立。重点区分：本地已实现、已推送、已合并、107 已构建、107 已运行和科学验收通过。
4. 明确第一版唯一主线是：受限结构输入 -> relax -> SCF -> BAND -> DOS -> 图表/数据库/证据。Agent、机器学习、QE/EPW、跨服务器迁移和其他旁支均不进入第一版。
5. 确认 107 的限制：共享 Unix 账号不能代表个人 Git 身份；登录节点不能做安装、构建、测试、常驻服务或计算；耗时工作必须由 Slurm 计算节点执行；4090 只允许做可替换网络入口。
6. 检查我填写的个人 Git name/email 是否与 Gitea 个人身份一致。不要替我修改全局 Git 身份。
7. 检查当前是否已有其他人在相同 Task 或文件上工作。没有明确的独立文件范围时，不要建议并行修改。

最后只输出一份“接手报告”，必须包含：

- 当前 main、功能分支和 HEAD；
- 当前真实已完成/未完成状态；
- 我选择方向涉及的文件、依赖任务和验收门禁；
- 可能过期或需要现场核验的运行事实；
- 与其他队员可能冲突的文件；
- 建议给我的第一个最小任务，但不要实施；
- 开始实施前还需要我或项目负责人确认的事项。

如果文档、Git 和代码互相矛盾，先列出证据和准确路径，不要猜测，不要直接修复。
```

这段提示词的目标是让 AI 先证明自己理解了项目，而不是立即生成代码。

## 2. 负责人分配任务后的实施提示词

只有项目负责人已经明确分配一个 Task、文件范围和起点提交后，才把下面整段发给 AI：

```text
基于你上一轮已经完成的只读接手报告，现在实施以下唯一任务：

任务编号和名称：[例如 Task 3: Extract A Read-Only VASP Record Table]
任务原文位置：[实施计划中的标题或行号]
允许修改的文件：[逐个列出]
禁止修改的文件或系统：[逐个列出]
起点分支/提交：[40 字符提交]
我的个人分支名：[member/姓名缩写-任务名]
验收命令：[逐条列出]
是否允许访问 107：[默认否；如允许，写明只读检查或具体受控操作]

执行约束：

1. 先重新核验起点提交、分支、工作树和已有改动。发现脏工作树、任务冲突或计划歧义时停止并报告，不得覆盖他人修改。
2. 完整读取该 Task 的全部步骤，但不要扩大到后续 Task。
3. 严格使用测试驱动：先写能够证明缺失行为的测试，运行并保留预期失败；再做最小实现；最后运行专项测试、完整相关回归、构建和 git diff --check。
4. 不允许通过删除断言、降低安全限制、伪造 demo 成功或跳过失败状态来让测试变绿。
5. 只修改允许文件；需要额外文件时先说明原因并等待确认。
6. 只有项目负责人把 `docs/107cup/implementation-plan.md` 明确列入本任务允许修改的文件时，才同步更新其中的本地/合并/107/科学验收状态。否则不要修改总计划；在完成报告中列出建议状态变更和证据，由主线负责人统一更新，避免多人并行冲突。
7. 本轮默认只在个人分支提交。没有明确授权时，不直接推送 main、不合并 PR、不登录远端、不启动昂贵计算。
8. 如果允许远端操作：登录节点只做短时 Git、提交/查询调度和读取小状态文件；安装、构建、测试、服务、VASP 必须进入 Slurm 计算节点。操作前核对准确路径、活动 Job、稳定 current、数据库和回滚边界。
9. 保留失败测试、失败作业、日志和 attempt；不能用下一次成功覆盖失败证据。

完成后报告：

- 实际修改文件；
- RED 命令和准确失败原因；
- GREEN/回归/构建命令及精确通过数量；
- git diff --check 和工作树状态；
- 提交 SHA、作者姓名和邮箱；
- 未验证边界和风险；
- 是否可以创建 PR，以及 PR 中必须说明的内容。

不要问“是否继续”来替代任务执行；只有遇到真实歧义、权限扩大、远端破坏风险或计划冲突时才停止请求确认。
```

## 3. 给前端与浏览器验收队友的具体提示词

当前主线仍在执行前端预览 Task 3，不能让另一名队友同时修改相同文件。现阶段可先执行只读审查：

```text
请在完成统一只读接手检查后，对远端分支 codex/107cup-frontend-preview 做一次只读前端接手审查。

不要修改、提交或推送。重点检查：

1. Task 1 的 demo/live provider 是否真正失败关闭，失败/运行数据是否会误显示成功；
2. Task 2 的 118 元素周期表、受控筛选、移动横向滚动和旧 PersonalVaspDatabase 兼容边界；
3. Task 3 至 Task 11 的文件依赖顺序，哪些文件不能与当前主线并行修改；
4. 现有 3D 结构、晶体详情、BAND/DOS、颜色、格式化和导出能力分别位于哪些文件；
5. 未来三视口 1440x900、1024x768、390x844 的浏览器验收项，以及 3D Canvas 非空像素、控制台和写请求检查。

输出按严重程度排列的发现和一个无冲突的最小候选任务，不实施。不要建议新增 Agent、ML、QE/EPW、监控或完整旧 VASP router。
```

待主线负责人明确把某个 Task 交给该队友后，再使用第二段实施提示词。

## 4. 给工作流与科学计算队友的具体提示词

前端预览未合并前，后端阶段 5 至 8 不能提前实现。该队友先做只读科学/运行边界审查：

```text
请在完成统一只读接手检查后，对 LMateLab 107 杯阶段 5 至 8 做只读准备审查，不写代码、不登录 107、不提交 Slurm/VASP。

重点输出：

1. 固定 MoS2 relax -> SCF -> BAND -> DOS 每一步需要的受控输入、前置产物和验收文件；
2. 如何把 Slurm COMPLETED/0:0、VASP 正常结束标记、必要文件集合和 SHA-256 组合成科学成功条件；
3. 人为 SCF 失败后 BAND/DOS 不得产生 Job ID 的证据链；
4. 工作流/step/attempt/event/file hash/template/release 数据模型的最小字段；
5. sbatch 前必须失败的 POSCAR/CIF、元素顺序、路径、参数和大小校验；
6. 同一共享 107 Unix 账号下，如何用 JobName、WorkDir、Slurm comment 和数据库 ledger 四项证明作业归属；
7. 现有 VASP、VASPKIT 和提交脚本哪些只能视为已提供环境，哪些仍需要第一次真实闭环验收；
8. 需要保留的成功/失败证据目录和最终结果包内容。

所有结论必须引用仓库文件路径或明确标为待 107 现场核验。不要把旧 4090 数据、demo fixture、目录名或队列状态当成真实科学验收。最后给出一个等待前端预览合并后才能开始的最小实现任务，不实施。
```

## 5. 给发布、安全与证据队友的具体提示词

如果第三个方向由项目负责人或其中一名队友兼任，可使用：

```text
请在完成统一只读接手检查后，只读审查前端预览 Task 12-13 和总方案阶段 9-10。

不要修改或访问远端。输出：

- preview release、Python 环境、数据库、runtime、端口、Job ID、manifest 与稳定 current 的隔离关系；
- 构建前/后 stable snapshot 必须比较的字段；
- 登录节点允许的短命令和必须进入 Slurm 的耗时操作；
- 服务启动、健康检查、浏览器验收、scancel、端口消失和 after snapshot 的顺序；
- 失败发布、数据库写失败、取消竞态、路径逃逸和非 LMateLab 作业的失败关闭门禁；
- 证据文档中可以记录与禁止记录的内容；
- 一个不会与当前前端文件冲突的最小候选任务，不实施。

所有运行 Job、节点、端口和 4090 状态都标为需要现场刷新，不能照抄旧文档当作当前事实。
```

## 6. 仓库暂时无法访问时

如果用户没有加入 `107-team` 或无法通过 Gitea SSH 认证，AI 必须停在接入阶段并明确说明缺少的授权。此时只能解释本文件中的规则、列出待核验项和建议下一步，不能判断仓库功能已经实现，不能生成可直接提交的补丁，也不能给出远端运行结论。

## 7. 禁止放进提示词或聊天的内容

- SSH 私钥、Gitea token、JWT、密码和二次验证码；
- 生产数据库内容、未脱敏用户信息和完整运行环境文件；
- 未确认归属的 Job ID 取消命令；
- 允许 AI 在 107 登录节点直接安装、构建、运行服务或计算的指令；
- “看到页面/目录/COMPLETED 就算完成”的宽松验收；
- 让 AI 同时实现所有阶段或顺手恢复无关旧功能的要求。

每位队友的 AI 都应先成为一个可审计的协作者，再成为代码执行者。
