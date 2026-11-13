# 常数约束实施接口

规程已独立审核通过，方法以[protocol.md](protocol.md)为准。本SDS只确定接口，未运行新效果。

## 一个新增生产模块

新增`scripts/rq1_score_revision/no_miss_constant.py`与`test_no_miss_constant.py`。旧生产文件不编辑。不另造概率核、通用配置系统或数据准备框架。复用同包heads的fit_base/base_score/raw_parameters/decompose/fit_increment，run的supervision/training_weights和原temporal.run的primary/weights/decide/ReportRows/calibrate/six_cells_many。禁止修改被导入模块的全局METHODS或使用mock替换真实生产函数。

公开`fit_zero(rows, old_fitted, families) -> dict`，只拟合D_zero、I_zero和J_zero。传入完整fit特征，先用旧supervision筛对应族，再检查原支持与所有6父可用，不将不可估行/父删除后继续。D/I各自按可用合同提取特征，d列的副本置0再调用原fit_base。记录原列方差、结构置0列、其余scaler、权重总量、监督父、false_cells、方法状态及自由度。不可估方法保存原因，旧基线仍能输出，判据不得因此通过。J零增量不增加新截距。

公开`score_feature(row, old_fitted, fitted) -> dict`。方法为D_old/I_old/J_old/D_zero/I_zero/J_zero/I_cut/MATE_policy。旧分数从原模型及原缓存特征计算；J_old保留原增量。I_cut用`heads.raw_parameters(oldI)['coef'][4]`精确扣除gamma*(d-m)，不把标准化coef当gamma。保留原context/d/m/w、key、标签、资格和有限性等必要元数据；保存新基础逐源与全局贡献、I_cut移除量。避免把整模型状态及训练父清单重复塞入每行，方法状态在模型/报告中记录；行级缺失原因仍可追溯。合法分数数值异常按旧规则保留Unknown，不删分母。

公开`run(source: Path, out: Path) -> dict`。CLI `python -m scripts.rq1_score_revision.no_miss_constant --source <old_run> --out <new_run>`。默认路径取同目录冻结config.json；临时fixture可显式传路径。默认输出与旧输出相同、嵌套或祖先关系均拒绝。原完成标记/配置/模型先确认一次，后读取已存在特征，不调用features/normal/prepare。

## 评分与统计的八列映射

使用新模块内局部映射D_old:D、I_old:B、J_old:C、D_zero:T、I_zero:Jind、J_zero:J、I_cut:G、MATE_policy:MATE_policy。报告适配时将源d映射旧表m、源m映射supports、源w映射n_frames。原table固定宽度支持恰好八方法。所有校准和六格在一个方案/split内复用同一ReportRows，避免按行重复重建。

cal/eval job按旧manifest和对应方案假族选择，clean共用。先验证旧方法重新计算的A/R与原cal保存值数值一致（abs1e-10）；再验证旧方法逐条score/decision与旧预测一致（score abs1e-9，缺失一致、decision严格），同时校对key/主标签/资格；不匹配即停，避免把接入差异误认成效果。每源输入只读一次即可，不反复hash完整gzip。

`evaluate(rows, policies, cal_layers)`输出主六格、family/k（F0/F1/F2/F3×1/2/3空层明确未测）、逐父、w三档（1、2..9、10）、m和n0实际离散层、coverage、候选对对应旧方法的转移。配对时效只用主真实epoch；从未采纳按父/epoch，延迟按双方共同曾采用集合重加权，中位数取累计首次>=.5。I_cut固定旧I政策的六格另列，不覆盖重校准的I_cut结果。

逐条输出score与decision，简短报告写本批开发判据及边界。保留三方案未检验状态。依据config中冻结数值逐项裁决主D_zero与次I_zero/J_zero，不复用旧“联合须比G高1pp”的另一研究命题判据。

## 持久化与恢复

新out保存binding.json（配置、源小文件来源hash、依赖代码hash、特征清单）、models/{regime}.json、scores或predictions/{regime}/{cal,eval}.jsonl.gz、calibration/{regime}.json、report/metrics.json及summary.md、run.complete.json与stage_times.json。不必同时保存完全重复的scores和predictions，最终含分数的predictions即可。绑定配置及实际依赖不一致拒绝恢复。原子发布；已完成方案可以复用但必须有相应完成标记，残留partial不算完成；失败保留error及已完成独立产物。一个运行锁防止同out双进程，避免覆盖旧产物。

## 验收与任务顺序

先写少量新增测试覆盖结构约束、正确原尺度cut、三方案筛选/常量列/失败状态、八列映射/手算六格/配对延迟、完整临时fixture及恢复/源路径保护。fixture调用实际优化与校准，但不需要真实normal拟合。只执行新增测试及明确被影响的定点回归；不重复旧57项或安装完整模型环境。

本批只有一个编码任务，独立代码审核同时检查新增模块与旧直接接口的整项集成。审核通过才运行真实run。主会话调度，另一个独立结果审核者从保存预测、旧预测与参数重计主六格、分层风险、配对时效和保留判据，禁止重新选门限或拟合。结束后更新REALLY、当前方案和STATUS，保存小型证据与本地提交，不自动推送GitHub。
