# 最后一次完整实验实施规格

2026-11-13。用户已明确“不用管，先做完整实验”。按已审protocol及config连续实施、审核、运行、统计复核与PPT更新，不再请求开始。本文只落实接口，不更换研究方案。

## 1. 工作位置、文件和阶段

使用现有隔离工作树`/root/autodl-tmp/ToolV2X/.worktrees/rq1-score-revision-2026-11-13`。新增目录`scripts/rq1_report_freeze/`，不修改旧rq1_temporal、rq1_score_revision及rq1_real_cue生产模块。允许新增`prepare.py`、`run.py`、必要单测及空`__init__.py`。准备和评价可分文件，避免复制整套旧框架。

命令统一为`python -m scripts.rq1_report_freeze.run --stage prepare|fit|evaluate|all --config <config.json> --out <new_output> --workers 4`。prepare使用已安装native runtime；fit/evaluate使用相同解释器或已核对的主Python3.8数值环境。每个数值库线程1，进程池只并行独立父或独立任务。首次完整运行默认4进程，最多6，调度不影响方法。

输出使用config.new_output。存`binding.json`、`manifest.json`、`parents/{parent}/scans.jsonl.gz`、`jobs/{job_id}/{attack.json,online.jsonl.gz,rows.jsonl.gz,entity_coverage.jsonl.gz,complete.json}`、`models/{regime}.json`、`calibration/{regime}.json`、`features/eval/{job_id}.jsonl.gz`、`predictions/{regime}/{cal,eval}.jsonl.gz`、`report/{regime}.json`、`report/metrics.json`、`report/summary.md`及阶段完成标记。配置与小型直接依赖代码只在阶段入口绑定一次；不逐帧读取全registry/hash原始PCD。

## 2. prepare接口

`prepare.prepare(config: dict, out: Path, workers: int=4) -> dict`返回manifest，并写`prepare.complete.json`。manifest包含原30项job、每父spec/scan_path及实际来源ID，不添加或替换任务。

每父调用旧`native_adapter.recording_spec(parent)`、`preprocess_new(out,spec)`。仅在本批进程追加`data.SPLITS[parent]='eval'`；旧角色不变。缓存FOV全部可用时不读PCD，GT来自原注释。原始父有多余尾帧时以同步检测帧为准，核对FOV帧对应。

每job的来源为spec.source_ids，受控来源取排序前k，normal_source取索引k，seed和提案算法沿用旧construct_attack。所有攻击构造在评价分数产生前冻结为attack.json。不可构造保存`UNREALIZABLE`，不回放、不补提案。

公开回放只使用`score_revision.prepare._public(scans)`（它移除GT/echo并将缺FOV的None转为空列表），调用旧replay_online。保留其epoch与fresh匹配语义。回放完成后调用旧attach_labels附加标签，并保存entity_coverage。每物理假实体按job_id+role识别，不能把多个中央query epoch算为多个注入实体。

clean用全扫描，attack用前80帧。COMPLETE行按当前data.compact结构，包含job_id/key/epoch/来源事件/X/C/groups/标签。补origin='report_freeze'以便追溯，不改变primary选择。方法特征阶段用旧run._feature_rows读取这些行。

原30任务的完成状态必须全列。技术异常保存error及退出非0，不静默降为不可构造；恢复时跳过已有完整阶段，只续原任务。全体job完成或明确UNREALIZABLE才标prepare完成。不得通过忽略失败父继续声称完整评价。

## 3. fit及旧模型接口

`run.fit(config,out) -> dict`只读取旧features/fit、旧features/cal、源模型和政策，不读新增eval标签、特征或分数。旧fold清单和旧prepare完成任务定义输入，不以glob缺文件结果充当完整输入。源fit有6父，cal有5父，检查一次不变。

三个regime分别执行。fit监督用旧`supervision(rows,fit_false)`和`training_weights`。cal的mixed使用旧源配置的F0/F1/F2，F1_only只F1、F2_only只F2，clean真均保留。目标族不进入源族fit/scaler/cal。cal存在缺层照原规则记录not_calibrated_for_missing_layers，不伪称该层已校准，也不临时改旧门限；整类缺失则对应分支不可估。

旧D_old/I_zero/J_zero/D_zero/MATE_policy从source_original_scores和source_zero_scores加载；调用旧no_miss_constant.score_feature可一次重建既有分数，取所需五项，不重新拟合。政策从source_zero_scores/calibration/{regime}.json的policies逐项原样复制。核对旧cal中对应五项分数与决策，发现差异先修接口，不能视为效果。

四个新增对照按protocol拟合。Count五输入来自未分组D_head的n_plus、sum(n_minus)及context[w,d,m]。newborn的既有零特征与空n_minus按原零上下文处理。非finite或缺必要特征的已选监督不能静默删除，受影响方法不可估。

Count为5列标准化后加截距的logistic，所有系数自由；使用protocol指定损失、正则、常量规则和优化设置。输出mean/scale/coef/intercept和来源计数，函数可直接复用旧base_score对通用维度计算。G_zero复用G的6列，将d列置0后调用旧fit_base，保留m和组信息。CountQ与Q_zero调用旧fit_increment(joint=False)，分别固定Count和旧I_zero，平方增量无截距、不中心化。

新对照使用旧cal数据按同一程序选门限。可将一个新方法的score映射到旧ReportRows的D列，逐方法调用original.calibrate；不改旧METHODS或固定dtype全局，不让九方法挤进八个旧别名造成覆盖。calibration_sufficient区分整类可估与具体family/k未覆盖。

models和calibration包含九方法映射、来源和状态，全部保存后写fit.complete。阶段顺序强制在evaluate前检查三套models/calibration完成，且复用方法与旧源完全相同。

## 4. evaluate、分母和裁决

`run.evaluate(config,out,workers=4) -> dict`只对prepare成功的原任务生成旧窗口特征一次，复用原normal模型和rho，三个regime共享这一特征。保留全部行及数值失败行。生成每regime九方法分数、共同资格、三态决策及必要逐源分解。

真假主分母用旧original.primary，真仅clean的真实预查询，假仅attack的明确target假预查询。攻击回放正常背景、未知GT、新生、无query、不可构造均另记覆盖。不因Unknown、失活模型或无分数删主分母；其输出Unknown，裁决记不可估或不足。

统计复用original.weights、primary、decide、旧_paired与_transitions的语义；六格可在通用字典逐方法计算，或逐方法映射旧表调用six_cells。配对时效至少D_zero/D_old及J_zero/I_zero，两个候选都报告。真假、family/k、逐父和各窗口分层各自按旧规定权重归一化。检查空层不出现假100%或假0%保证。

单方法row失败不应令其他模型丢行。已有旧score_feature将其依赖失败处理为finite=False的行为沿用并明确记录；新增Count/G/Q失败不得篡改冻结五方法的输出。

每family/k支持数分别为明确假query出现的父数、物理注入job数和query epoch数；前两者用于3父/3实体操作门槛。所有3方案分别判断总体及非空层风险、主TA/CD/时效代价、Count增量、联合对I/G/Q增量。报告必须保留通过、失败、不足三种状态；有任一数值失败可报告失败，覆盖不足同时单列，绝不能宣称通过。至少一类缺失或主要任务不完整则整体不足。

汇总判据逐项列value、limit、status、分母。不为已经失败的旧k3重选阈值。新增结果与旧开发数据分表。report/summary.md给九方法六格、首窗、逐父及最终决定，数值同时留metrics.json。run.complete只表示原任务执行和报告结束，不表示科学门槛通过。

## 5. 必要检查和结束

只写本次新增语义的fixture：Count真实未报计数而非缺失补0、源族隔离、Count系数自由/G的d固定、平方增量offset不重估、旧五方法与政策不变、九方法无别名覆盖、无query/不可构造/数值失败不算成功、物理实体不等于epoch、加权六格与至少一个裁决失败及不足、技术恢复同任务。旧全套不机械重跑。

正式运行前独立代码审核通过。完成后另开统计审核，只读预测及参数按标准库独立核算主要六格、逐层风险、来源支持、旧模型政策和门槛裁决，不重拟合或重校准。随后更新唯一主方案、REALLY、STATUS和PPT第6页，保留第5页历史不利结果。无正结果也结束本次实验。
