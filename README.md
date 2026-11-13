# ToolV2X 研究点一

面向目标真实性核验的观测条件与多源依赖证据建模。

当前协作分支`experiment/rq1-score-revision-2026-11-13`。最新gamma=0常数约束数值实现b0572cd已完成三个方案及独立重计，生产差异0。**D_zero有局部改善，但反向迁移真实采纳损失超标，整体不替换旧方法。** D_old保留研究对照，D_zero保留改进候选，尚无已验证的完整联合主方法。

## 当前入口

[此前两轮改动汇总](docs/REALLY/上次GitHub推送后改动汇总_2026-11-13.md)记录214a956至f4109ba的14个实质提交；其中未推送状态是整理当时的历史记录。本分支包含这些修改和后续讨论材料。

外部AI优先阅读[数据与方法瓶颈及四个审查问题](docs/REALLY_MAYBE/数据与方法瓶颈_后续取舍及外部AI审查问题_2026-11-13.md)，再按下列入口核对方法和证据。

1. [当前方案](docs/研究点一_当前方案.md)
2. [最新结果与方法决定](docs/REALLY/只未报来源常数约束_开发结果与方法决定_2026-11-13.md)
3. [冻结规程](docs/REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/protocol.md)及[SDS](docs/REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/SDS.md)
4. [独立结果评审](docs/evidence/rq1_no_miss_constant_2026_11_13/execution_2026_11_13/result_review.md)
5. [上一轮评分修订结果](docs/REALLY/判别评分修订_开发结果与方法决定_2026-11-13.md)
6. [协作交接](docs/COLLABORATION.md)

mixed下D_zero真实采纳58.04%、假拒绝89.48%、CD73.76%，CD比旧D高2.38个百分点，但假采纳由0升到0.37%。反向迁移F1/k3假采纳6.67%降至2.22%，真实采纳却58.91%降至53.51%，超过预定2个百分点损失上限。mixed首窗真采纳47.04%降至26.29%，该不利分层不能被总体平均掩盖。

## 实现与复核边界

新增模块`scripts/rq1_score_revision/no_miss_constant.py`复用原模型特征及统计，不更改旧生产模块。主Python3.8.10、numpy1.24.2、scipy1.10.1。新增合同测试命令

```bash
python -m unittest scripts.rq1_score_revision.test_no_miss_constant -v
```

本次实际完成初轮10项及两轮定点修复测试，随后代码审核和207.94秒真实运行；没有机械重跑旧全套。fixture不等于方法效果。新输出在`docs/evidence/rq1_no_miss_constant_2026_11_13/`，源评分修订与更早时序结果完整保留。

Git只归档小型参数、来源、统计和独立重计。原始数据、完整特征/预测、检测与消息缓存及runtime仍在主服务器，异地不能仅凭小型归档重跑。当前批次全部结束，不恢复run_001或基于已见结果追加调参。首次prepare状态格式故障发生在拟合前，其error/log为历史，实际完成状态以run.complete及审核记录为准。

47段资产范围不变，14父是本批开发选择。已见eval、F3缺失、多控单父及源族cal覆盖少等限制仍在，不提供部署或一般攻击保证。此前`research/rq1-current-2026-11-12`入口是旧快照，后续协作以本分支为准。
