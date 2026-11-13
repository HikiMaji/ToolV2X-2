# 评分修订实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 按任务实施和独立审核，用户已授权连续执行，无需重复请求开始。

**Goal:** 按冻结规程完成新fit攻击、数据支持判断及可估方案的混合/双向族迁移试验。
**Architecture:** 复用旧原生前端、正常概率核及统计规则，只新增准备适配与可分解判别头。新输出独立，不改原run_001。
**Tech Stack:** Python3.8数值、Python3.10原生runtime，numpy/scipy，现有AVstack。
**Spec:** `docs/REALLY_MAYBE/rq1_score_revision_2026_11_13/SDS.md`，上位为冻结protocol/config。

## Global Constraints

- 不修改旧scripts/rq1_temporal源码或冻结规程/hash，不变26个任务、seed、14父split、W10及主政策。
- 保留全部失败、标签未知、模型不可估和共同分母，短轨迹不删。
- source-only的训练和校准均排除目标族，normal折外排除held父包括rho选择。
- 未报系数非负，基础头7系数，offset增量仅一参数，无中心RMS，无额外截距。
- 原生和数值任务均限制Numba/BLAS/OMP单线程，独立job可并行。原始数据不重盘点，静态hash仅阶段边界一次。
- 关键实现/审核使用gpt-6.1-sol high，编写者不自行派生审核agent。保留ledger和工作树。

## Review Focus

- 旧三车检测路径含parent的train层，不调用只适配新四父的recording_spec错误路径。
- 单个假实体的跟踪碎片不能使数据门槛虚增。
- 迁移方案的cal筛选与fit筛选必须一致，不能用目标族挑门限。
- normal折外数据与头scaler分别隔离，当前事件不得提前更新p。
- 不可估方案和单父cell区间支持不足不能变成通过或被删除。

### Task 1: 训练攻击准备与支持门槛

**Files:** Create `scripts/rq1_score_revision/prepare.py`, `test_prepare.py`。
**Interfaces:** 提供SDS中的read_config、iter_rows、support_summary及prepare CLI。输入冻结config和旧run；输出新manifest、26个job状态和support.json/prepare.complete.json。
- [ ] 用小fixture固定实体碎裂计数、sourceIDs/frame对应、原子恢复和失败保留。
- [ ] 实现旧三车sender+GT+检测路径适配及四车scan复用，调用原native构造/回放/标签函数。
- [ ] 完成必要fixture与原生导入检查，提交并写报告，不自行运行研究批次。
- [ ] 独立审核通过后，由主会话启动26个任务并汇总支持门槛；旧输入只读。

### Task 2: 数值头、折外流程与三方案报告

**Files:** Create `scripts/rq1_score_revision/heads.py`, `run.py`, `test_heads.py`, `test_run.py`。消费Task1只读接口，不修改已运行prepare。
**Interfaces:** CLI `python -m scripts.rq1_score_revision.run --stage features|fit|score|report --out ... --workers ...`。按SDS及冻结规程输出folds/features、每方案模型、评分、cal门限、六格与裁决。阶段可恢复但不覆盖完成产物。
- [ ] 实现并检验正常侧表征、7系数拟合、固定offset增量、组平均及来源分解。
- [ ] 实现父折外缓存、三方案隔离、支持/可估状态、原口径校准、family/k与配对时效及c区间分支。
- [ ] 必要小型端到端fixture通过后提交并写报告；不自行跑真实拟合或评分。
- [ ] 独立全分支审核后，主会话只运行满足数据支持的方案；全部不足时直接形成未能检验报告。

### Task 3: 本批裁决与归档

**Files:** 新out报告、REALLY结果/REALLY_MAYBE后续边界、当前方案与STATUS。
- [ ] 独立重计核心六格、风险与判据，核对真实分母与缺失层。
- [ ] 给出评分、联合、迁移、覆盖分别结论，不把工程通过写成方法有效。
- [ ] 记录代码与输入来源、实际完成/不可构造任务，保留全部产物；不因结果不足加seed或换参数。
