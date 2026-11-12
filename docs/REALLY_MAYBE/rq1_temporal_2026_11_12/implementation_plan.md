# 时序条件联合核验实施计划

> For agentic workers: use superpowers:subagent-driven-development. 用户已批准方案并要求连续推进，无需再次询问开始。

Goal：完成可变来源时序核验原型和一次14父开发比较，裁决状态/时间/联合是否有增量。
Architecture：复用公开查询与几何；监督拟合单车代理状态；正常联合/四族假侧前向；同窗口同政策评价。
Tech：现有Python3.8、numpy/scipy、native AVstack runtime；CPU单线程、流式数据。
Spec：[SDS](SDS.md)及[完整方案](../时序条件联合核验_完整修订设计_2026-11-12.md)。

## Global Constraints

- 原始输入和旧产物只读，新目录与提交留来源；GT/攻击身份不进在线kernel。
- 当前2GiB内存、无GPU，不结束无关服务；优先冻结检测缓存，数据范围不被资源临时状态永久收窄。
- W10、s.9、rho网格0/.25/.5/.75/.9、L2 .01、clip1e-6；不得按eval追参数。
- 开发14父6fit/5cal/3eval，新增最多27攻击任务，确切名单由SDS给出。

## Review Focus

- 当前U是否被先更新后计分；完整假侧有没有被错误拆组。
- 滑窗是否隐含窗前后验；单源unknown是否丢掉事件。
- 离线Z/query GT对应是否错用output GT，坐标是否仅yaw。
- 数据和原生包装是否仍有三源硬编码，缺包是否补0。
- 六格/校准/攻击构造是否按效果筛分母或造成功标记。

## Task 1: 数值核心与拟合

Files：scripts/rq1_temporal/kernel.py、fit.py、test_temporal.py。
Interfaces：fit_models(rows)->model_dict；predict_row(row,models)->pred；score_window(window,models,rho,W,s)->scores/资格/解释量。

- [x] 按SDS写最少有辨别力的前向枚举、缺失、顺序及窗口测试。
- [x] 实现核与fit，复用scipy优化器，保存必要诊断。
- [x] 运行相关测试，提交并接受独立spec/quality审核；155799e通过，组件不可估阻塞已修复。

## Task 2: 数据适配与运行评价

Files：data.py、native_adapter.py、run.py及同一test_temporal.py必要fixture。
Interfaces：prepare(out)->manifest/per-job rows；fit(out)->models；score(out)->stream predictions；report(out)->metrics/summary/figures。

- [ ] 按data_access和SDS接入旧39个特征，补fit Z及4个多车录制；普通原生缺依赖按已有runtime解决，不改检测模型。
- [ ] 冻结F1/F2/F3构造及失败记录，生成新消息和当前查询。
- [ ] 完成cal、同政策指标和最小fixture；独立代码审核后冻结。

## Task 3: 固定开发与方法决定

- [ ] 运行prepare/fit/score/report，阶段断点、日志及峰值内存保留。
- [ ] 有界独立重计冻结预测的六格、风险和核心比较。
- [ ] 将结果及保留/简化决定写入REALLY、当前方案及STATUS；保留代码/工作树/失败产物。
