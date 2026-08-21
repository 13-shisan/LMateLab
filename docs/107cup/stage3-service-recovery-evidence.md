# Stage 3 网页服务与转发自动恢复验收记录

更新时间：`2026-08-21`

## 1. 结论

- Stage 3 已完成：网页服务运行在 107 Slurm 计算节点，4090 只提供可替换的用户态网络入口；服务受控停止后，守护只提交一个候选 Job 并恢复三处访问入口。
- 当前稳定发布为 `e565851ff3ac67d8c143331b4dee175d82b6d04c`，服务为 Job `41044`、`P107-A100/anode16:18731`。
- 4090 `127.0.0.1:18740`、Windows `127.0.0.1:21763` 和公网 `222.195.94.37:18733` 返回同一 Job、node、commit 和 manifest。
- 本阶段没有运行 VASP，没有修改工作流、结果解析或数据库模型，也没有改写 Stage 7/8 科学证据。

## 2. 源码和构建

自动恢复实现经 PR #52 合并，首次正式构建 Job `41039` 保留为失败证据：485 项后端测试中唯一失败是 runtime verifier 夹具缺少新要求的 `service-state.json`。失败构建没有切换 `current`，旧 Job `40917` 和正式转发继续健康运行。

夹具热修复经 PR #53 合并，固定提交为：

```text
e565851ff3ac67d8c143331b4dee175d82b6d04c
```

发布前快照 Job `41041` 的两层清单通过，证据目录和清单 SHA-256 为：

```text
/home/scc/pb23030683/lmatelab-107cup/evidence/previews/e565851ff3ac67d8c143331b4dee175d82b6d04c/before-41041
02f658a0bccf73674d64855c3cf7a627297627fb582a4149ef578b34e7670dcf
```

正式构建 Job `41042` 在 `P107-RTX5090/anode01` 完成：

```text
Backend: 485 tests run, 4 platform skips, no failures
Frontend: 129/129 passed
Vite: 1857 modules transformed, built in 7.60s
Release manifest entries: 581
Release manifest SHA-256: 98364dd3df1224f536007925f1624345e2e76157ac56b3f6d7c1565e269537a4
```

构建作业已离开 `squeue`，日志终止于测试和清单全量通过，`current` 原子指向新 release；平台随后对该短作业返回空 `sacct` 表，因此不额外伪造调度终态。原始日志位于：

```text
/home/scc/pb23030683/lmatelab-107cup/logs/build-41042.out
/home/scc/pb23030683/lmatelab-107cup/logs/build-41042.err
```

## 3. 首次发布和 4090 安装

- 4090 从 107 固定 checkout 复制四个 relay 文件，逐文件 SHA-256 与源文件一致；安装后私有临时目录已删除。
- 安装器先收养旧 Job `40917/anode17` 的健康 `18740` 转发，没有在安装时重绑端口。
- 用户 crontab 中本项目 BEGIN/END 标记各恰好一个；原有服务器监控、六小时采集和原 LMateLab runtime recovery 项均保留。
- 首个新服务用固定 `service.slurm` 提交为 Job `41043`，并以 `--exclude=anode17` 避免和旧服务发生端口冲突。Job 在 `anode16` 通过本机 live/ready 后才原子发布 `service-state.json`。
- 4090 先通过临时 `18742` 验证 Job `41043` 身份，再将正式 `18740` 从 `anode17` 切到 `anode16`；临时端口随后关闭。旧 Job `40917` 经完整归属核对后停止。

## 4. 受控停止和唯一候选恢复

4090 创建权限 `0600` 的普通 `maintenance` 文件后，守护状态为：

```json
{"reason":"operator_requested","status":"maintenance"}
```

Job `41043` 经用户、JobName、Command、WorkDir、Account、Partition 和 QOS 全部匹配后停止。停服期间：

```text
107 anode16:18731: connection failed
4090 127.0.0.1:18733: HTTP 502
Windows 222.195.94.37:18733: HTTP 502
squeue -u pb23030683: no jobs
```

这证明入口失败关闭，没有回退到原 4090 LMateLab。maintenance 期间再次执行守护仍返回 `maintenance`，没有提交作业。

移除 maintenance 后，cron 只提交一个候选 Job `41044`，日志只出现一次：

```json
{"job_id":"41044","reason":"service_missing","status":"submitted"}
```

Job `41044` 在 `anode16` 发布健康状态后，既有 `18740` 因目标节点未变直接恢复为 `ready`，未产生第二个候选。候选失败时保留旧转发的合同由 107 Linux 全量构建中的 `test_failed_probe_keeps_old_forward_untouched` 覆盖。

## 5. 最终一致性和不可变性

最终 `service-state.json`、`forward-state.json` 和 `recovery-status.json` 一致：

```text
Job ID: 41044
Node: anode16
Port: 18731
Commit: e565851ff3ac67d8c143331b4dee175d82b6d04c
Manifest: 98364dd3df1224f536007925f1624345e2e76157ac56b3f6d7c1565e269537a4
```

恢复后快照 Job `41045` 两层清单通过，清单 SHA-256 为 `716784e371d960bc7a77fb518c149bf6d4fd1f02f89ae41b6f32eca9f62ea1ff`。Job `41041` 与 `41045` 的数据库哈希完全一致：

```text
eln.db:     29cf102884c1b36f6cef8c251bb569aa6cebd837b4d3957989a6efaa8a96ddbc
digests.db: 2c1069bb4768fa81707623fa80e72f616e313b809d7b1a1b7da4d203ef56b969
integrity_check: ok / ok
```

Stage 7 `preflight-40039` 以及 Stage 8 `acceptance-40308`、`acceptance-40916` 的既有 manifest 均原地复核为 `OK`。没有创建新的 Stage 7/8 验收目录。

`verify-runtime.sh` 最终验证 Job、release manifest、计算节点 live/ready、两套 SQLite 完整性及登录节点无 LMateLab 常驻进程，并输出：

```text
verified_job_id=41044
verified_node=anode16
verified_commit=e565851ff3ac67d8c143331b4dee175d82b6d04c
verified_manifest_sha256=98364dd3df1224f536007925f1624345e2e76157ac56b3f6d7c1565e269537a4
```

从 107 登录节点直接探测公网入口时，IP 白名单按设计返回 `403`；公网身份由 Windows 和 4090 两侧分别验证，不能把该 `403` 误记为服务失败。

## 6. 二次验证边界

- 当前 `/home/Pwjb/.ssh/cm-107cup` ControlMaster 有效，权限和专用密钥路径不进入仓库。
- 守护检测到主连接失效时只写 `ssh_authentication_required`，不尝试绕过二次验证，不保存验证码、密码或私钥内容。
- 为避免主动破坏当前可用连接，本次没有强制关闭 ControlMaster；实现将主连接检查失败固定映射为 `ssh_authentication_required`，运行手册给出唯一恢复入口。真实失效后必须由 Operator 在 4090 交互终端运行 `reauth-control-master.sh` 并输入一次验证码。

## 7. 完成判定

Stage 3 的构建、健康状态原子发布、唯一 cron 块、候选先验转发、受控停服失败关闭、单候选自动恢复、三层入口一致性、登录节点无常驻进程和二次验证失败关闭均已有证据，因此状态更新为 `DONE`。
