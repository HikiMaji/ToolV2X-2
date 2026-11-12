# 父级prepare并行与fit提前启动

2026-11-13。新增两个外部helper，不改549e86f冻结模块，未操作真实run_001或当前prepare进程。

`parallel_prepare.py`只分派未完成的最多三个native cal/eval父，每父一个owner，固定3worker、spawn、NUMBA和BLAS线程均1。worker临时将进程内data.NEW_PARENTS设为该父，直接调用native_adapter.prepare，原manifest不筛选、不重建。前置要求manifest源码hash一致、native_runtime.json存在、legacy完成且join缓存存在、native fit完成。父级scan/provenance及job产物路径互不相交。replay_online原代码已逐job重置TrackBase.ID_counter，不依赖其他父的执行顺序。全部future成功、所有job和扫描缓存存在后，调用原run.prepare作汇总。已有缓存避免重新处理PCD和重放。启动记录parallel_prepare.<timestamp>.json包含wrapper路径/hash、父范围、3worker、线程环境和解释器。

`fit_ready.py`要求manifest全部split=fit job均为COMPLETE，包含fit攻击，先检查再筛clean。按原顺序调用all_rows(out,'fit')、clean筛选、fit_rho_oof(W=10)、fit_models、method_status及atomic_json，models.json字段与原run.fit一致。无query或未知标签历史不在helper中删除，不读cal/eval行。旁路fit_ready.<timestamp>.json记录wrapper路径/hash和启动时prepare是否完成。独占.models.lock且已有models拒绝覆盖。原score仍要求整个prepare.complete。

两个轻量mock fixture分别通过，未运行真实native、拟合或核心suite。

```bash
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/test_parallel_prepare.py
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/test_fit_ready.py
```

prepare检查为 `Ran 1 test in 0.224s`、`OK`，确认三父各一次、六个job各唯一owner、全部成功后才汇总且manifest不变。fit检查为 `Ran 1 test in 0.222s`、`OK`，确认fit攻击未完成时拒绝、只消费clean fit行且保留未知标签历史、字段一致、已有models拒绝、原score完整prepare门槛有效。

独立审核通过、主会话确认并停止原prepare后，在两个独立执行会话使用下列命令。以下仅列命令，本次未执行。

```bash
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/parallel_prepare.py --out /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/run_001
/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/fit_ready.py --out /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/run_001
```

风险是协作锁仅约束对应helper，不能阻止未使用该锁的原prepare/fit。执行方必须确保原prepare已停止且不另启原fit writer。父级缓存与已完成fit输入须保持只读。并行prepare与fit可互不写同一数据文件；未测真实加速比、峰值内存或实际原生结果等价，mock只支持调度与入口契约。
