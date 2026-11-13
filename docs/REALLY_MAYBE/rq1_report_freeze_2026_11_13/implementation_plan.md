# 最后一次完整实验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。用户已批准直接执行，按项目AGENTS采用编码与独立审核，主会话连续推进。

**Goal:** 完成冻结的6父、30任务、9方法、3方案比较，交付已核实结果及PPT文案。

**Architecture:** 在现有隔离工作树新增有界包装器，复用冻结前端、正常特征、模型、校准和统计语义。旧产物只读，新对照只用旧fit/cal。prepare、fit、evaluate可恢复但不能按效果改动。

**Tech Stack:** Python3.8、numpy、scipy及既有AVstack/MATE runtime，无新增依赖。

**Spec:** 同目录protocol.md、config.json和SDS.md。

## Global Constraints

- 仅一次固定比较批次，30任务、9方法、3方案；不新增父、seed、算法或工作点。
- 使用已有分支与工作树，不改旧生产文件，不覆盖旧数据。
- 所有新增对照的fit/cal完成后才允许产生新eval分数。
- 来源及目标族隔离、Unknown分母、失败记录和旧政策必须保留。
- 用户要求完整实验，技术故障修复后续原任务，效果失败不补跑。

## Review Focus

- 新旧固定方法映射与政策必须一致，九方法不能共用旧别名造成覆盖。
- clean全帧及attack前80帧、缺FOV公开化和GT后附加边界。
- Count不把机会未知当未报，单模型失败不删监督或评价行。
- 物理实体按注入job计，不能按多query epoch扩分母。
- 部分任务、源族缺层及类缺失必须报告不足，不获得通过。

### Task 1: 实现有界准备、拟合和报告

**Files:** 新增scripts/rq1_report_freeze/{__init__,prepare,run,test_report_freeze}.py，可将必要单测分文件。禁止修改旧生产模块。

**Interfaces:** SDS第2至4节的prepare.prepare、run.fit、run.evaluate和统一CLI。所有阶段接受冻结config及新out。

- [ ] 先写SDS第5节新增语义fixture并确认缺实现失败。
- [ ] 实现最小prepare及run，复用已有函数；不先运行真实数据。
- [ ] 跑本批必要单测，记录命令、结果及已知边界。
- [ ] 提交仅新增实现和单测，写task-1-report.md；由独立审核检查规格与代码质量。

### Task 2: 执行、独立重计和汇报更新

**Files:** 新输出docs/evidence/rq1_report_freeze_2026_11_13/{run_001,execution_2026_11_13}，既有PPT文案与当前状态。

**Interfaces:** 审核通过的CLI、完成标记、预测、metrics。主会话运行，独立统计agent只读产物。

- [ ] 冻结数值提交和输入来源，完整运行一次all，保存时间及日志。
- [ ] 如技术失败，仅定点修复并恢复同一run；不热改运行进程。
- [ ] 一次独立重计主六格、支持、风险与裁决，不复算已验证旧训练。
- [ ] 依据结果更新PPT和研究决定，保留全部正负结果，不扩大结论。
