# 剩余native job并行调度

2026-11-13。新增parallel_prepare_jobs.py，不改正在运行的parallel_prepare.py或549e86f冻结核心。默认8worker，spawn方式，复用父helper设置NUMBA及BLAS线程为1、设置每worker的data.NEW_PARENTS并调用原native_adapter.prepare。

原native_adapter直接读取磁盘manifest，不能通过替换data.manifest筛选。因此按主会话确定的目录视图方式，保留`out/_job_views/<job_id>/manifest.json`。该副本保持正式manifest的metadata，仅将jobs限制为当前一个job，并加入execution_view说明及正式manifest的路径/hash。它只是执行筛选副本。正式完整manifest仍是唯一研究入口，不修改、不筛选。视图下jobs、parents、native_runtime.json为指向正式out的符号链接。已有相同视图可复用，有冲突则拒绝；视图不删除。

前置检查包含正式manifest源码hash、全部四父scan及provenance、native_runtime、legacy完成及join缓存、全部fit job COMPLETE。每个pending native job只分派一次，每job写自己的正式输出目录。原replay_online逐job重置TrackBase ID，算法、攻击构造、标签、窗口及来源顺序不变。父扫描缓存与runtime已存在，worker不会写这些共同文件。与父helper共用`.parallel_prepare.lock`。全部future成功且所有正式job完成后，调用原run.prepare(out)汇总。旁路parallel_prepare_jobs.<timestamp>.json记录wrapper及父helper路径/hash、完整pending job名单、正式manifest hash、线程环境、解释器和worker数。

唯一轻量mock测试

```bash
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/test_parallel_prepare_jobs.py
```

结果 `Ran 1 test in 0.232s`、`OK`。同父双job分别只有一个写入owner，视图输出落正式目录，正式manifest字节不变。模拟第二worker失败时没有汇总及完成标记；恢复后只提交剩余job，两个正式job均完成后才在原out汇总。测试使用mock executor及mock native，未运行实际原生数据或核心suite。

独立审核并停止原父helper后，由主会话执行下列命令。本次未执行，也未操作真实run_001或任何现存进程。

```bash
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/parallel_prepare_jobs.py --out /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/run_001 --workers 8
```

共享锁约束两个外部prepare helper，但不约束未使用该锁的原prepare。主会话必须确认旧helper及其worker全部停止，避免两个执行世代同时写job。已完成分片沿用原native恢复规则，partial保留。本测试不能证明真实加速比、8worker峰值内存或真实输出数值等价；它只检查任务筛选、路径、owner和完成条件。本批不再扩展调度框架。
