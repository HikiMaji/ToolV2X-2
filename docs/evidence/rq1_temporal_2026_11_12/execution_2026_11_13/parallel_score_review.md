# 外部并行评分调度器独立审核

2026-11-13。范围为本目录的`parallel_score.py`、`test_parallel_score.py`及其报告，对照冻结工作树`.worktrees/rq1-temporal-2026-11-12/scripts/rq1_temporal/run.py:62`的原`score`。按当前AGENTS复习了经验教训、主方案、最新要求及STATUS，并沿用Task 1与Task 2已经通过的审核。此次只做调度差异和相关调用的静态核查，没有重跑概率核心、原生前端、fulltests或fixture，没有运行真实score，也没有干预prepare。

**结论为PASS，无阻塞。允许在prepare和fit完成后，由主会话使用该runner以8个worker执行已批准run_001的评分。** 此放行覆盖资源调度和输出契约，不表示真实批次已有方法收益。

## 核查结果

| 核查项 | 依据与结论 |
| --- | --- |
| 并行单位 | `score:61–73`每个job提交一个future，默认8worker，显式spawn。只改变job之间的执行顺序。 |
| 原五套评分 | `VARIANTS:25–26`与原`run.score:67`相同，main/W5/W20/s05/s095的W及s完全保留。job内按原顺序执行。 |
| 原核心及输出 | `score_job:30–41`保留原status读取、read_rows、windows、score_window、prediction及atomic_rows调用。没有额外排序、过滤、模型拟合、标签消费或状态延续。窗口历史为每次调用内的局部变量，模型参数只读，不因job调度产生跨job状态。 |
| 唯一输出owner | `score:51–55`持有同一out的持久文件锁至全部future和完成标记处理结束，`61–63`拒绝重复job_id。冻结manifest中的job_id为已审生成的唯一哈希名。每个worker独占本job的五个分片。锁只约束本runner，主会话继续负责不同时启动原串行score或其他writer。 |
| 恢复与跳过 | UNREALIZABLE在读rows之前返回；已有目标分片直接跳过；已有score.complete拒绝覆盖。保持原atomic_rows先写partial再发布正式文件的规则。已成功分片在失败后保留，恢复时跳过，未发布partial可重写。没有要求重跑已完成产物。 |
| 失败与完成标记 | 每个future都调用result，任何worker异常都会在`atomic_json(score.complete)`之前传播。进程池退出会等待其他任务结束，可能保留成功分片，但失败不会被写成评分完成。 |
| 来源记录 | 开始时核对核心commit为549e86f，记录原code_record；全部任务成功后追加runner绝对路径、字节数、SHA256、worker数、起始时间、耗时、解释器及numpy/scipy版本、spawn方式与线程环境。原variants、method_status、code字段保持兼容。此次实核工作树HEAD为549e86f，评分相关目录相对HEAD无修改。 |
| 线程设置 | 导入numpy/scipy前显式将六项BLAS相关线程环境设1，spawn子进程继承。评分不调用native点云几何；prepare的NUMBA_NUM_THREADS调整是另一项已记录的资源安排，不是本runner的算法变更。 |

## 已有定点证据及适用范围

核读了唯一fixture的构造和断言，并继承`parallel_score_report.md`记录的一次结果，不重复运行。两个有效job含19个输入行，另有UNREALIZABLE job；串行与2worker的10个评分分片共95行解码后逐行完全相同，耗时3.359秒。fixture包含缺C、缺X、全未知事件和无当前输出。代码还检查了既有分片字节及mtime不变、完成字段兼容、runner哈希、完成后拒绝重复运行、worker缺输入异常不发布完成标记、锁冲突拒绝第二runner。

逐行相同指JSON记录及数值相同，不要求gzip容器字节相同。该fixture不是8worker真实批次的性能或峰值内存证据。8worker下同一job仍由单进程串行执行，跨job没有共享核验状态；这一等价性质由源码核查支持。真实耗时及峰值资源由实际执行记录，不为此放行重复负载测试。

prepare中128与1个numba线程的局部8次corners调用完全bit相等及0.747s/0.000186s耗时，仅按本目录`numba_threads.json`和主会话记录继承。该局部检查不能解释为全prepare加速比或所有原生几何的全面数值验证，不构成重开原生审核的理由。

本次未发现需要修改算法、扩展框架或新增验收的具体问题。完成真实评分后仍须按已批准标准独立核对冻结结果，不能以调度器PASS代替最终科研判断。

## 本次审核文件指纹

- parallel_score.py SHA256 `ad272d864727246db391116ce693e4ea00002b917168ceae8e3fbfcff64dee25`
- test_parallel_score.py SHA256 `66ecc852ee182aee5969e1aab3a7c2d4c3fed4cf079edcf36647a8e77f9ca5ea`
- 冻结run.py SHA256 `8989514775ca6a43f284f60219b8f99d125f8d770341b9c2e25d08e680c3e813`
