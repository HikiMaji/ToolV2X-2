# prepare与fit外部调度独立复审

2026-11-13。本次审核`parallel_prepare.py`、`fit_ready.py`、两份mock测试及`prepare_fit_helpers_report.md`。继承549e86f核心与数据入口已通过的审核，只核查调度、数据依赖、写入范围及恢复规则。未改冻结模块，没有重跑两个fixture、核心或原生测试，没有启动真实prepare/fit，也没有操作正在运行的进程。

**结论为PASS，无阻塞。允许主会话确认原prepare及其writer均已停止后，启动3worker父级prepare，并同时启动fit_ready。** fit_ready仍须通过全部fit任务完成检查。原prepare/fit不使用helper锁，执行方需保证不另启原writer。这是现有唯一写入者要求，不新增研究设计审批。

## prepare核查

- `parallel_prepare.py:41–64`要求现有manifest和native_runtime存在，通过原data.manifest检查冻结来源。legacy必须全COMPLETE且全部join缓存存在，native fit不能仍待处理。由此各父worker进入原native_adapter.prepare时，native_runtime和legacy两处共享入口均只读取、跳过，不会重复创建。
- job_id先去重，pending按父集合归并，再按原NEW_PARENTS顺序分配。固定3worker和spawn，每父只提交一次。`prepare_parent:24–31`仅在子进程内临时收窄NEW_PARENTS，finally恢复，不筛选或重建全70任务manifest，不改变split、输入、攻击或原函数。
- 原native_adapter中，每父的scans/provenance和job目录不同。replay_online每job重置TrackBase.ID_counter，攻击候选使用局部RandomState(0)，没有因父执行顺序变化而共享ID或随机状态。所有既有complete任务跳过，原子发布的scans及provenance共同存在时直接复用；缺provenance时走原恢复分支，未完成partial沿用原覆盖恢复规则。
- `73–82`逐个future.result，任何异常都会阻止最终run.prepare。全部任务标记和所有父扫描缓存齐备后才调用原run.prepare。此时原prepare_legacy立即返回，native子过程只复用父缓存并跳过完成job，最后仍由原函数发布全量prepare.complete及原汇总字段。没有删减UNREALIZABLE或成功任务分母。
- 持久fcntl锁阻止本helper多实例并写。启动记录含runner路径及SHA256、父范围、worker数、spawn、解释器与NUMBA/BLAS线程环境。它不约束原串行writer，因此主会话先停止原writer的执行顺序必须保持。

## fit提前启动核查

`fit_ready.py:36–42`检查manifest中全部split=fit任务为COMPLETE，包含随后会被clean筛选排除的fit攻击，落实了原all_rows先读status的实际调用关系。未完成cal/eval不阻止fit，也不被读取。已完成job在原prepare中跳过，rows先原子发布、complete后写，因此fit不会读取仍写入的fit行。

`50–56`与原run.fit保持相同的数据选择、顺序及输出。保留clean中的无query及未知标签历史，原样调用fit_rho_oof(W=10)、fit_models和method_status，models.json的字段、code_record及n_input_rows不变。OOF和模型函数仅消费已读fit行，不依赖cal/eval准备结果或全prepare.complete。因而移除全prepare屏障只改变执行时间，不改变监督总体、模型或科学判断条件。

模型锁覆盖就绪检查、读取、计算及原子写出，已有models拒绝覆盖。prepare不读写models.json，fit不改job、父缓存或manifest，两个helper的启动记录名称也不同。主会话保持不另启原run.fit即可避免未参与协作锁的第二模型writer。score仍调用原require_prepare，不能因models提前存在而提前评分。

## 定点证据和边界

沿用实施者报告的一次prepare mock，1项测试0.224秒，检查三个父各提交一次、六个job唯一owner、成功后汇总及manifest不变。沿用一次fit mock，1项测试0.222秒，检查fit攻击未完成时拒绝、只消费clean fit并保留未知标签历史、模型字段一致、已有模型拒绝覆盖及原score屏障。

已核读两份测试断言。它们使用mock池或mock拟合，未验证真实native计算、实际3进程性能或峰值内存。future异常阻止汇总、父路径隔离及已有缓存避免重算的判断来自源码。无需为此次有限调度放行补跑真实数据等价实验，也不把mock通过表述为方法有效或开发批次已完成。

实核冻结工作树HEAD为`549e86fbc2b6fae0bf608cb6344253466f4f6e7c`，相关源码目录相对HEAD无修改。两份helper指纹与送审值一致。

- parallel_prepare.py SHA256 `94cf623b70f3f00a1e80ce21f0b2dcecdda686334b24f4ca397ef1fad025e06c`
- fit_ready.py SHA256 `ed3c926075d26fe854aed66f8f8341ccc156a4e2ff085570e1625e2d1367fddd`

本次只形成调度代码通过结论。真实批次完成后仍按已批准标准核对最终统计与保留决定，不重新打开未改变的算法及数据设计。
