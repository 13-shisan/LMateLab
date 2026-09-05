# LMateLab

107杯参赛项目

本仓库是独立的 107 杯项目；应用、环境和运行数据部署在 107，原 4090
LMateLab 生产环境不属于本项目运行边界。

团队成员请从 [`docs/107cup/team-guide.md`](docs/107cup/team-guide.md) 开始；需要把项目交给各自 AI 时，只发送
[`TEAMMATE_AI_START.md`](TEAMMATE_AI_START.md) 这一个文件；阶段状态和下一门禁只以
[`docs/107cup/implementation-plan.md`](docs/107cup/implementation-plan.md) 为准。

比赛交付证据：

- [`docs/107cup/compute-cluster-run-data.md`](docs/107cup/compute-cluster-run-data.md)：Slurm 作业、资源、排队和运行时间说明；
- [`docs/107cup/artifacts/slurm-job-ledger.csv`](docs/107cup/artifacts/slurm-job-ledger.csv)：逐 Job 总账；
- [`docs/107cup/artifacts/lmatelab-107cup-compute-cluster-run-data-20260905.zip`](docs/107cup/artifacts/lmatelab-107cup-compute-cluster-run-data-20260905.zip)：经逐文件哈希验证的脱敏原始日志附件。

## Agent、Qoder 与演示数据库

本分支新增的 Agent 工作区包含普通问答、文献检索与 PDF 索引、VASP 计算目录分析、
结构库检索、计算规划和受控 Qoder 接口。API Key、Qoder 登录状态和用户上传内容只保存在
部署机私密目录，不写入 Git。

仓库内置以下可公开同步的演示数据：

- `frontend/src/features/competition/data/demoFixtures.js`：只读 MoS2 工作流和 VASP 数据库演示记录。
- `backend/competition_examples/dawn5/`：两个已脱敏的 Dawn5 SCF 结果示例。仅保留分析所需的小文件，
  不包含 POTCAR、WAVECAR、CHGCAR、调度脚本或服务器绝对路径。
- `backend/competition_templates/vasp-incar-library/`：INCAR 模板库与文献索引元数据。

安装应用依赖：

```bash
cd backend
python -m pip install -r requirements.txt

cd ../frontend
npm ci
```

Qoder CN 是可选能力。Linux 发布在构建阶段固定安装大陆版 SDK；启用
`LMATELAB_QODER_MANAGEMENT_ENABLED=1` 后，Agent 设置中的“一键安装”只校验版本和内置
`qoderclicn`，不会在 Web 或 Worker 运行期间安装软件。手动安装同一版本的命令为：

```bash
python -m pip install qodercn-agent-sdk==1.0.14
```

LLM API Key 优先通过 HTTPS 或直达 107 计算节点 Web 服务的 `127.0.0.1` SSH 隧道保存。比赛期间的
公网 HTTP 入口仅在 4090 Nginx 精确来源 IP 白名单和 Operator 应用权限同时通过时允许保存，并持续提示
传输未加密；普通公网来源仍被拒绝。API URL 和模型不含密钥，可从已授权入口更新。

公开 QMOF 全量结构和 CIF 文件体积较大，不随 Git 仓库分发。请从
[QMOF 官方仓库](https://github.com/arosen93/QMOF) 下载数据集，使用仓库提供的 CSV 导入脚本建立只读索引：

```bash
python backend/scripts/import_qmof_structure_index.py \
  /path/to/qmof_database.csv \
  /path/to/structures.sqlite
```

部署时设置 `LMATELAB_STRUCTURE_LIBRARY_DB=/path/to/structures.sqlite`；如需在详情页读取 CIF，另设
`LMATELAB_QMOF_CIF_ROOT=/path/to/qmof_cifs`。CSD 数据受许可证约束，不在仓库中提供；只能由合法
CSD 用户在部署机上配置个人数据目录或后续导入适配器。
