# 外部并行评分调度器定点检查

2026-11-13。仅新增 `parallel_score.py` 与 `test_parallel_score.py`。核心来自冻结工作树 `.worktrees/rq1-temporal-2026-11-12` 的提交 `549e86fbc2b6fae0bf608cb6344253466f4f6e7c`。

调度器以 spawn 方式创建 ProcessPoolExecutor，默认8个worker，每个job独立执行。job内保持main/W5/W20/s05/s095原顺序，直接调用原read_rows、windows、score_window、prediction和atomic_rows。输入行与来源顺序、窗口、模型、rho、缺失、三态和统计未作改动。BLAS相关线程环境显式设为1。全部future成功后才写原兼容score.complete.json，并追加runner路径、sha256、worker数及运行环境。已有分片跳过，UNREALIZABLE跳过，已有完成标记拒绝覆盖。同一out使用持久fcntl锁，避免本调度器多实例并写。

唯一合成fixture定点测试命令

```bash
/root/miniconda3/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/test_parallel_score.py
```

结果为 `Ran 1 test in 3.359s`、`OK`。两个有效job共19个原始行，另有一个UNREALIZABLE job。原run.score串行与本调度器2worker生成的全部10个评分文件共95行逐行完全相同。fixture包含缺C、缺X、全未知事件和无当前输出。原有一个完成分片的字节与mtime保持不变。完成标记的variants、method_status、code均与原实现相同，附加runner哈希和线程环境已检查。重复完成调用被拒绝。缺输入造成真实worker异常时没有score.complete.json。锁被占用时第二个runner被拒绝。

风险与边界

- fcntl是协作锁，只防止本脚本多实例并写。原run.score未使用该锁，执行方必须保证不同时启动原串行评分或其他writer。
- 失败可能留下已成功的分片或原atomic_rows的partial文件，沿用原断点恢复规则。恢复时已完成分片跳过，partial重新写入。
- 本次仅验证调度等价与完成契约，未测真实批次加速比或8worker峰值内存。未运行实际run_001评分，未重跑核心、原生或full report，未干预prepare。等待独立审核后由主会话调用。
