# ToolV2X 研究点一

面向目标真实性核验的观测条件与多源依赖证据建模。

当前本地分支`experiment/rq1-score-revision-2026-11-13`。数值实现563b1d0已完成冻结开发比较和独立重计，生产统计差异0。**监督评分改善，但当前联合项和双向攻击族迁移均未通过预定条件。** 保留D开发底座，不认领稳定联合贡献。

## 当前入口

1. [当前方案](docs/研究点一_当前方案.md)
2. [本轮结果与方法决定](docs/REALLY/判别评分修订_开发结果与方法决定_2026-11-13.md)
3. [冻结规程](docs/REALLY_MAYBE/rq1_score_revision_2026_11_13/frozen_protocol.md)
4. [SDS与实施接口](docs/REALLY_MAYBE/rq1_score_revision_2026_11_13/SDS.md)
5. [独立结果评审](docs/evidence/rq1_score_revision_2026_11_13/execution_2026_11_13/result_review.md)
6. [协作交接](docs/COLLABORATION.md)

mixed下D真采纳57.55%、假拒绝85.20%、CD71.37%；J分别57.11%、80.99%、69.05%，假采纳均0。J对同边际I的CD只增0.174个百分点，低于预定1个百分点。反向族迁移的F1/k3假采纳13.33%，不能只展示混合训练结果。已见开发资料不能改称未见终测。

## 实现与证据范围

新代码在`scripts/rq1_score_revision/`，复用冻结`scripts/rq1_temporal/`和几何输入。主Python3.8.10、numpy1.24.2、scipy1.10.1，原生AVstack使用已有Python3.10 runtime。相关fixture命令为

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_score_revision.test_prepare scripts.rq1_score_revision.test_heads scripts.rq1_score_revision.test_run -v
```

fixture不等于实测。新证据在`docs/evidence/rq1_score_revision_2026_11_13/`，包括来源manifest、支持覆盖、参数、逐项裁决和独立重计。完整行级预测、检测/消息缓存、原始数据和runtime保留主服务器，不在Git小型归档内，异地不能只靠这些文件重跑真实批次。所有阶段已结束，不恢复已完成run_001。

旧时序549e86f及其正负结果继续保留。47段录制仍是资产范围，14父只是本批选择。F3仍缺失，多受控eval仅一父。此前GitHub协作入口`research/rq1-current-2026-11-12`尚未在本轮更新，本地新分支未推送。
