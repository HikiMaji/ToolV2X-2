# 研究点一协作交接

2026-11-13。最新常数约束批次已经结束，无后台任务待恢复。方法只维护[当前方案](研究点一_当前方案.md)。本地分支`experiment/rq1-score-revision-2026-11-13`，最新数值实现b0572cd；GitHub此前协作入口尚未在本轮同步。

## 当前共同起点

先读AGENTS、研究经验教训、当前方案、user_requirements和STATUS，再读[最新结果与决定](REALLY/只未报来源常数约束_开发结果与方法决定_2026-11-13.md)。不恢复旧K1、手工Q_F、Delta00或已结束的prepare/fit任务。既有缓存、代码和所有负结果保留。

本批固定gamma=0，D/I最多6参数，保留条件反证和支持信息；J只重估原联合增量，I_cut用于固定参数诊断。三方案全部完成，独立统计生产差异0。

D_zero mixed CD增加2.38个百分点，两个方向假拒绝均提高；但F2训练/F1评价真实采纳损失5.40个百分点，超过预定2个百分点。I_zero/J_zero损失6.31/6.28个百分点，同样不保留。mixed首窗真采纳下降、1/10条假采纳必须报告。gamma的结构约束生效，不等于完整真实性方法已经有效。

D_zero保留为有正负证据的改进候选，不直接替换全范围方法。原D是研究对照，也不宣称已满足全部迁移风险要求。下一实质设计需针对跨域风险和真实采用权衡，不能在已见eval上调门限求通过；当前没有冻结或实施下一算法。

## 文件与分工

- 新模块`scripts/rq1_score_revision/no_miss_constant.py`和定点测试；原概率核和旧评分文件不改。
- [规程](REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/protocol.md)、[SDS](REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/SDS.md)、[代码审核](REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/code_review.md)。
- [指标](evidence/rq1_no_miss_constant_2026_11_13/run_001/report/metrics.json)、[独立结果评审](evidence/rq1_no_miss_constant_2026_11_13/execution_2026_11_13/result_review.md)。

主服务器AI负责实验与整合；外部AI以明确commit领取有限设计/审查任务，独立分支提交，双方避免修改同一机制。旧分支并未自动含本次提交。当前资料足以审查方法和汇总，不等于异地能够逐条重算；完整特征/预测及runtime仍在服务器，需另行明确最小导出范围。

47段录制仍是资产范围，14父不是永久限制。已反复查看的数据始终标开发；新实验须另设输出和冻结规程。多受控eval仅一父、F3缺失、F2源族cal仅一实体等限制继续保留。
