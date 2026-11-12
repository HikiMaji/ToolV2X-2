# ToolV2X 研究点一

面向目标真实性核验的观测条件与多源依赖证据建模。

当前本地实验分支为`experiment/rq1-temporal-2026-11-12`。算法冻结于549e86f，2026-11-13完成14父开发比较和独立重计。**局部点估计有增量，整体保留条件未通过。** 当前结果不是独立未见终测或发表保证。

## 当前入口

1. [当前方案](docs/研究点一_当前方案.md)
2. [结果与方法决定](docs/REALLY/时序条件联合核验_首轮开发结果与方法决定_2026-11-13.md)
3. [未实施的修订重点](docs/REALLY_MAYBE/时序核验首轮后_修订重点_2026-11-13.md)
4. [实施规格与审核](docs/REALLY_MAYBE/rq1_temporal_2026_11_12/SDS.md)
5. [独立结果评审](docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/result_review.md)

## 代码与小型证据

- `scripts/rq1_temporal/`为当前冻结数值核、拟合、数据接入和评价实现。
- `scripts/rq1_real_cue/`保留公开查询的几何输入。
- `docs/evidence/rq1_temporal_2026_11_12/run_001/`包含参数、总manifest、完成摘要、六格、敏感性和预定实例。
- `execution_2026_11_13/`包含独立任务调度、等价检查记录、结果重计与事后描述图。调度变化不作算法贡献。
- 旧静态/受控代码和证据保留用于追溯。

主实现使用Python3.8.10、numpy1.24.2、scipy1.10.1；原生AVstack处理使用既有Python3.10环境。核心和小型fixture可运行：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_temporal.test_temporal scripts.rq1_temporal.test_data -v
```

fixture不代表真实效果。完整实测仍需要服务器上的OPV2V、检测/消息缓存、原生runtime和完整预测；本分支只保存必要结果与来源，不是可脱离这些资产运行的完整数据包。异地审核可以先核读源码、参数和独立统计记录。重新运行必须使用新输出位置，不能覆盖已完成run_001。

主点J正确明确率59.43%，T58.79%，但J相对同政策MATE真采纳少20.18个百分点。F3全部未能构造，多控eval只有一个父录制。完整六格和限制见结果入口，不能只摘选综合分数。
