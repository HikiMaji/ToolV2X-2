# ToolV2X 研究点一

面向目标真实性核验的观测条件与多源依赖证据建模。

当前协作分支`experiment/rq1-score-revision-2026-11-13`。**汇报前完整实验已完成，D_zero与当前联合头在三个方案中均未通过预定保留条件。** 这次交付是完整实现、扩大开发评价、明确方法取舍及PPT图表，不是已验证的最终算法。

## 当前入口

1. [最新完整结果与方法决定](docs/REALLY/汇报前完整实验_结果与方法决定_2026-11-13.md)
2. [六页PPT文案与图表](docs/研究点一_汇报PPT文案_2026-11-13.md)
3. [当前方案及已检验算法](docs/研究点一_当前方案.md)
4. [冻结规程](docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/protocol.md)、[实施规格](docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/SDS.md)
5. [独立结果复核](docs/evidence/rq1_report_freeze_2026_11_13/execution_2026_11_13/result_review.md)
6. [协作交接](docs/COLLABORATION.md)

## 最新结果

六个额外开发父、九方法、三个方案全部完成。30任务中25完成、5不可构造，19个明确假实体；主分母9878真时刻、784假时刻。它们是额外开发评价，不是盲终测。

mixed下D_zero真采纳60.02%、假拒绝92.90%、CD76.46%，但假采纳5.40%、F2/k2层21.59%超过5%门槛。F1训练/F2评价总体假采纳19.89%；反向真实采纳相对D_old损失5.12个百分点。联合对同边际基础头的CD增量为+0.179、-0.658、+0.100个百分点，均未达1个百分点。

独立重计237610条方案化预测，最终生产差异0。代码和统计通过不等于研究判据通过。全部正负结果保留，不自动追加调参或新实验。

## 代码、产物与复现边界

数值实现`4b90295`，新增模块位于`scripts/rq1_report_freeze/`，原实验运行约61.39分钟。native回放用既有Python3.10环境，数值拟合/评价用原Python3.8环境。运行来源、测试和独立审核在execution目录。

报告完整性修正`7c380ea`仅区分合法无分数Unknown与计算故障。原分数、门限、决策、六格、CD和时效不变。正式解释使用[report_corrected](docs/evidence/rq1_report_freeze_2026_11_13/run_001/report_corrected/summary.md)，原report及run.complete保留为来源。报告修正命令为`python -m scripts.rq1_report_freeze.report_integrity --out <已完成run>`，不是重跑模型。

[归档清单](docs/evidence/rq1_report_freeze_2026_11_13/archive_manifest.json)列出小型参数、来源、统计、审核、PNG/SVG/CSV。原始数据、完整扫描、逐帧事件、特征、预测和runtime仍留服务器，异地不能只凭此快照完整重跑。当前批次已经结束，不恢复旧prepare/fit。

此前`research/rq1-current-2026-11-12`是旧快照，后续协作以本分支为准。[早期两轮改动汇总](docs/REALLY/上次GitHub推送后改动汇总_2026-11-13.md)只记录当时的历史范围。
