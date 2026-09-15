# QMOF v18 正式接入证据

更新时间：`2026-09-15`

## 1. 结论

107 已正式安装 QMOF Figshare v18 的 `20372` 条索引和 `20372` 个 relaxed CIF。权威来源是 Figshare
DOI `10.6084/m9.figshare.13147324.v18`；Pzxp 只是旧 `18755` 服务的运行用户，不是该公开数据集的人工
数据作者。正式数据位于：

```text
/home/scc/pb23030683/lmatelab-107cup/data/qmof/v18
/home/scc/pb23030683/lmatelab-107cup/data/qmof/current -> v18
```

4090 只在107无法解析下载域名时短时中继已经核对哈希的公开归档。安装成功后，临时 HTTP 服务、端口
`18757` 和4090上的 `392088304` 字节副本均已删除；107保留原始归档、CSV、内层 CIF 归档、解压 CIF、
SQLite、逐 CIF 清单和 provenance。

## 2. 固定来源

| 项目 | 固定值 |
|---|---|
| 版本 | Figshare v18 |
| DOI | `10.6084/m9.figshare.13147324.v18` |
| Figshare file ID | `59573735` |
| 许可证 | CC BY 4.0 |
| 外层归档大小 | `392088304` |
| 外层归档 MD5 | `0d89aaf66f2c306e86e47fd91cb1346e` |
| 外层归档 SHA-256 | `97d23c0b4f9e5a30888e53dc16222b90443ad7167c3284d2258615d9f44eceef` |
| `qmof.csv` SHA-256 | `9991b2d51d71a6cc4c97affd8ca36ac18d5b75554b4f3f1ac9ebb35bc9995f26` |
| `relaxed_structures.zip` SHA-256 | `c7b18fbb042900a91fc481405dabda81196f88eff004c3a092ecaff393521211` |

固定镜像 revision `24fc459339583e2f7b876296b6daec8d6d0a22a5` 的大小、MD5 和 SHA-256 与
Figshare 文件完全一致。正式 provenance 如实记录本次实际从
`http://222.195.94.37:18757/qmof_database-v18.zip` 传输；该 URL 已下线，不能作为运行依赖。

## 3. Slurm 作业

| Job | 节点/资源 | 结果 | 说明 |
|---|---|---|---|
| `63107` | `anode03`, build profile | 构建通过 | 首版 QMOF 代码；后续由传输修复 release 取代 |
| `63109` | `anode17`, 1 CPU, 8 GiB | `FAILED/6:0`, 12 s | 计算节点无法解析镜像域名；归档写入前失败 |
| `63111` | `anode17`, 1 CPU, 256 MiB | `COMPLETED/0:0`, <1 s | 固定临时中继 HEAD 为 `200`、长度正确 |
| `63116` | `anode01`, build profile | 构建通过 | 加入实际传输 URL provenance |
| `63125` | `anode17`, 1 CPU, 8 GiB | 失败 | curl 仍强制 HTTPS；归档写入前失败，调度记录已过期 |
| `63127` | `anode01`, build profile | 构建通过 | 最终协议修复 release `a083e457...` |
| `63129` | `anode17`, 1 CPU, 8 GiB | `COMPLETED/0:0`, 1 m 28 s | 正式安装和二次全量复核 |
| `63133` | `anode17`, 2 CPU, 8 GiB | 失败 | 与旧 Web 同节点端口冲突，未发布状态并完整关闭 |
| `63134` | `anode16`, 2 CPU, 8 GiB | `RUNNING` | 新 Web，公网 `18733` 已切换 |
| `63135` | A100 profile, 1 CPU, 2 GiB | 失败 | 验收预估 Mn 为718，真实返回723；数据未修改 |
| `63136` | `anode17`, 1 CPU, 2 GiB | `COMPLETED/0:0`, 1 s | 后端总数、Mn筛选和 CIF 解析通过 |
| `63137` | `anode17`, 1 CPU, 2 GiB | `RUNNING` | 新 Agent Worker，与 Web 同 commit/manifest |

Job `63129` 于 `12:21:11` 提交、`12:21:12` 开始、`12:22:40 +08:00` 结束，排队约1秒。运行中
`sstat` 观测 `MaxRSS=86600K`、读 `1017041636` 字节、写 `745840948` 字节；这是运行中快照，不冒充
最终峰值。`sacct` 对 `63129/63135/63136` 返回空，因此以保存的 `scontrol`、stdout/stderr 和数据哈希
为准，不把缺失字段估算为零。

## 4. 产物与日志哈希

| 产物 | SHA-256 |
|---|---|
| `structures.sqlite` | `3da603e0ed8f4b5be6c393dbfafb13fc34284377df73599a8cf01fe7fb854f02` |
| `provenance.json` | `ee98efb18e8fb685566c3b9428a2ad7afa26d81092d2c9ce3fb8a45ede106873` |
| `cif-manifest.sha256` | `56c1d3f232483befa56228c58462b5d0e283f14e78d81813ea0d35b071c9fa9b` |
| `qmof-library-63129.out` | `cd670a32511df86eb3b5dd8e23ee1b9da5739e687c58f83eb0c11997b42c6099` |
| `qmof-library-63129.err` | `e3b0c44298fc1c149afbf4e8996fb92427ae41e4649b934ca495991b7852b855` |
| `qmof-runtime-acceptance-63136.out` | `86f358c68b26de66f832aba76001c50e6e3d04d2353ac4cc2eb6222c2de7ecdd` |
| `qmof-runtime-acceptance-63136.err` | `e3b0c44298fc1c149afbf4e8996fb92427ae41e4649b934ca495991b7852b855` |

失败日志也保留为 `0600`：`63109.err` 为
`dd48c9b191c2f0a6a676e0b19d62d237f5bedf7254440a973a17fc22fcb4f9f2`，`63125.err` 为
`a84309cb14cf5ec3ddf1739d9964f6a27ae739911dcf1f32e3442c63ba577466`，`63135.err` 为
`32459b873addd1df8d11d7e4853758fb9fac9cb2ddff4e0bfe23bed7eac90fa1`。失败没有被覆盖成成功。

## 5. 运行验收

安装 Job 两次完整验证官方归档哈希、CSV/CIF ID 集合、逐 CIF 清单、SQLite `integrity_check` 和记录数。
运行时 Job `63136` 再经正式后端读取：

```json
{"atoms": 50, "mn_records": 723, "record": "qmof:qmof-0000295", "structure_loaded": true, "total": 20372}
```

公网 `http://222.195.94.37:18733/api/health/live` 返回 Web `63134/anode16`、commit
`a083e4573e78ea001afe1550d58cc5b48168a369`、manifest
`8a0dec827061ec080e0872472bf80611b23d17b7245217ef4fcadcbbb37a7de9`；ready 返回 `ready`。新 Worker
`63137/anode17` 的 commit/manifest 完全一致。旧 Web `62952` 和 Worker `62954` 在归属及活动 Agent 队列
检查后受控停止；最终队列只保留新 Web/Worker，没有操作同一共享账号下的其他作业。

已登录浏览器对列表、元素筛选、详情和三维结构的人工复核仍保留为最终 UI 门禁；后端实际数据接入已完成，
不能用尚未点击页面否定已经通过的安装与运行时证据，也不能反过来用后端证据替代人工页面验收。
