# No-miss-constant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the single coding task; independent review precedes real execution.

**Goal:** 实现gamma=0的评分约束并完成一次有界开发比较。
**Architecture:** 新增小模块复用冻结的特征、logistic头和校准/统计。旧源码、模型与输出只读。
**Tech Stack:** Python3.8.10、numpy1.24.2、scipy1.10.1、stdlib、单线程数值库。
**Spec:** 同目录protocol.md、config.json、SDS.md。

## Global Constraints

- 只新增no_miss_constant.py和test_no_miss_constant.py；不得修改旧生产源码。
- D_zero为主；I_zero/J_zero次要；I_cut仅诊断；不追加Delta00或新攻击。
- L2=.005，常量阈值1e-6，L-BFGS-B零初始化/maxiter500/ftol1e-10/gtol1e-6。
- 源族筛选先于scaler/拟合/校准，fit假仅旧26尝试中明确新注入目标，clean真不重复。
- 固定政策、原分母和缺失规则；异常不可估留Unknown/不足，不能删父或靠全Unknown通过。
- 真实实验只在独立代码审核后运行，一次结束，无调参/扩训/新构造/推送。

## Review Focus

- d置0在拟合和评分、逐源分解间一致，原d仍用于共同资格。
- I_cut只去gamma*n0，必须保留原beta并转换标准化系数。
- 局部八列映射不改旧全局METHODS，不把支持数m和有效来源d互换。
- source-only不接触目标族fit/scaler/cal；缺模型/层不虚构通过。
- 原分数/门限/决策复算一致；恢复拒绝新代码/配置和旧输出路径，partial不算完成。

### Task 1: Constrained heads and bounded runner

**Files:** Create scripts/rq1_score_revision/no_miss_constant.py and test_no_miss_constant.py.
**Consumes:** 冻结source run、config/SDS、heads和旧run统计接口。
**Produces:** fit_zero、score_feature、evaluate、run以及上述持久化文件。

- [ ] 写新增行为fixture，先运行确认预期缺实现失败。
- [ ] 实现SDS接口；结构约束通过d输入副本置0复用fit_base，不改旧源。
- [ ] 测试gamma严格0、增加低p只未报来源贡献近0且在a_minus>0时高p更负；I_cut精确保留beta；源族权重/scaler；八列六格与延迟；不利/缺失数据及恢复。
- [ ] 运行`python -m unittest scripts.rq1_score_revision.test_no_miss_constant -v`及必要定点测试，记录命令结果。
- [ ] 自查差异并提交两新增文件，写任务报告。
- [ ] 独立规格与质量/整项接口审核，必要修复后定点复审。

### Task 2: Authorized run and independent result audit

- [ ] 主会话记录最终代码与配置来源，运行CLI新out一次，记录时长。
- [ ] 独立结果审核者从保存预测/原参数重新计算六格、风险、时效、约束和逐项裁决；不再拟合或选门限。
- [ ] 按主/次候选分别保留或撤下，更新当前方案、REALLY、STATUS，归档小型证据并本地提交。保留旧产物和本批ledger。
