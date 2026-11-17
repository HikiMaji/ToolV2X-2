# 按父并行侧录审核

**Approved，可以运行。** 本次仅把相互独立的父录制分给多个进程，当前具体清单和实现不改变 Task 1 的数学、数据角色、I 匹配问题或主键。未发现 Critical 或 Important。

审核对象为 `docs/REALLY_MAYBE/rq1_trusted_receiver_2026_11_17/parallel_sidecars.py`，源为 `docs/evidence/rq1_trusted_receiver_2026_11_17/run_001`，目标为独立新 run。未运行真实 I/F、未改 Task 1 代码、未中断任何进程，仅新增本报告。

## 实际核对

- 源清单有 23 父，其中 6 fit、5 cal、12 eval，共 69 个唯一 job。父缓存目录编码也有 23 个唯一值，未发生 `/` 替换造成的碰撞。已通过只读配置分组确认 17 个非 fit 分片对非 fit jobs 精确覆盖一次，每个子配置都保留全部 6 fit。
- `run_001/method_inputs.json` 与其 `prepare.config.json` 的 JSON 值相同。23 个完整 receiver 缓存文件均存在。既有 shape 的计数为 6 fit 父、198 条局部轨迹、14391 次观测，采用父、轨迹、时刻均衡权重。
- 已将源 snapshot 的 `__init__.py`、`local.py` 和 `run.py` 与 `git show b5aa3ca` 逐字节比较，三者全部一致。并行入口 `:25-26` 导入这个冻结 snapshot，不调用正在扩展的 live runner。

## 拆分不改变计算的原因

- `parallel_sidecars.py:30-32` 只按父选择原有完整 jobs，不拆 job 内的行，不修改 parent、split、receiver、frame 或 query。因而仍由冻结 `prepare` 对每个 job/frame 的全部查询计算双向唯一匹配，不会把不同 job 的查询合并。
- `:34-38` 为每个父分片链接完整 fit receiver 缓存和源 shape。冻结 `prepare` 见到完整 receiver/shape 后只读复用，不重建 tracker、不在子集上重新估形体。完整 fit 权重和参考尺寸保持。
- 每个父的 F 缓存原本就在该父的单帧范围内。冻结入口的 job/frame 循环保持，按父拆分不减少同帧共享，也不引入跨帧或跨父缓存。

## 写入与完成语义

- `:47-49` 拒绝源目录与目标目录相同或互相包含，旧串行输出及 partial 不作为新输出写入目标。
- `:58-69` 在启动进程池前写完整配置绑定并链接全量 receiver/shape。子进程只写 `parent_shards/<独立父>/`，没有共享的 `.partial` 文件。此次真实清单的父目录和 job ID 已确认唯一。
- `:38-42` 先等待该父冻结 `prepare` 完成，再将完整原子侧录链接至新 root 的 jobs。`link_same` 在目标已存在时检查 inode 一致，不覆盖其他产物。链接 receiver/shape 后，冻结入口只读取它们，没有原地写入路径。
- `:77-82` 检查 job 重复与全量覆盖，只有所有 future 成功后才在 `:83-91` 发布总 `prepare.complete.json`。任一子任务失败不会发布整体完成标记。
- `:53-57` 记录原 method inputs、shape、snapshot 来源、并行驱动文件和 worker 数，完整 method inputs 与 prepare config 保留原 JSON 值，子配置另存在各自 shard。

## 边界

该批准针对单个新目标 run 的一次驱动，使用现有不可变源缓存。运行完成前下游应继续以 root `prepare.complete.json` 为入口。未验证并行提速数值或真实方法效果；没有为证明数学等价而重跑已验收测试或真实点云。

原串行 child 的受控中断由主会话按实时 PID、命令和启动来源核实后执行。本审核没有扩展终止范围，也没有执行终止操作。
