# 实施规格独立审核

2026-11-13。本审核只读检查protocol、config、SDS、implementation_plan与现有真实依赖代码，并读取旧模型和校准小型产物。未修改生产代码，未拟合模型，未运行真实回放或效果实验。用户已经授权直接完成实验，不新增审批。

## 结论

spec-compliance为通过。implementation-readiness为可以进入编码及必要fixture审核，未发现需要更改研究方案或冻结任务表的阻塞。此结论仅表示接口存在且规格可落实，不表示实现已通过、数据可构造或实验将产生正结果。

机器清单静态核对为6个额外父、30个唯一job_id、9个方法及3个方案。每个父恰有clean与F1/F2的k1/2四个攻击任务，新增父与旧14父角色无交集。旧5方法模型和政策的读取位置实际存在。旧fit、cal分别保持6父与5父。

## 编码必须落实的三项重要边界

1. 数值环境需要按阶段分开。主会话已核对native runtime使用Python3.10.19、numpy1.25.2、scipy1.11.4，旧数值环境为Python3.8.10、numpy1.24.2、scipy1.10.1。统一all入口应由旧数值环境顺序启动native prepare子进程，再完成fit/evaluate。prepare模块不要被数值入口在native缺失时提前导入并执行。旧cal重建与旧产物比较应继续使用旧数值环境。SDS第9行允许这条路径；不能把另一套数值库产生的微小差异当作旧模型变更。

2. 九方法使用逐方法D槽或通用统计，必须保留逐方法状态。真实original.ReportRows的dtype在导入时按旧METHODS固定，original.apply_policies又遍历全部旧METHODS。SDS第39及49行提出的逐方法original.calibrate与six_cells可行，但不能直接将只有一个D政策的字典交给apply_policies。采用original.decide逐行处理，或为旧全部槽准备明确禁用政策后仅取D槽。不得修改旧globals，也不得让新增方法失败将冻结五方法的finite改为False。

3. 保留实际校准缺层。本次只读旧calibration产物确认，mixed缺F1/k1、F2/k1、F2/k2，F1_only缺F1/k1，F2_only缺F2/k1和F2/k2。三方案仍有真假两类，故不等同于整类不可估。新对照沿用同一旧cal选择门限并逐项列missing_layers，旧五方法政策原样复制。新增评价即使覆盖这些层，也只形成固定门限下的经验评价，不能写成这些层已受校准保证。若实施时发现整类缺失，保持对应分支不可估，不用零错误值补齐。

以上属于现有规格的具体落实，不改变科学参数，不要求追加实验。

## 已核实的关键接口与分母

- `score_revision.prepare._public`真实移除GT/echo并将None FOV变为空列表；`native_adapter.replay_online`接受公开扫描，标签在`attach_labels`中后附加。攻击构造沿用原64提案、前80扫描及20至59活动范围，来源由spec排序固定。clean必须单独保留全同步扫描，不能复制旧攻击worker对所有任务截80帧的行为。
- `heads.window_features`真实保存逐源n_minus以及未分组D_head第3列n_plus。Count可从这些量与context提取5列，不能用窗口乘来源数补未报。`heads.fit_base`强制6列并限制前两项非负，只适用于G_zero，不适用于Count；Count需有界新增自由系数5列拟合，base_score可复用。G_zero第5列置零后拟合，预测沿用原G特征时该列系数必须严格为零。
- `heads.fit_increment(joint=False)`支持固定offset、平方增量、RMS不中心化和无新增截距。CountQ固定Count，Q_zero固定已保存I_zero。三方案筛选先于尺度与拟合，mixed cal允许F0/F1/F2，而两个源族方案只使用对应源族cal。不能直接把config内fit_false当作mixed的cal_false。
- `no_miss_constant.score_feature`可重建冻结五方法；它调用旧score_row并保留旧依赖数值失败语义。新增方法状态必须在新字典内处理，不能改写该返回对象后影响旧输出。
- `original.primary`真实只把clean真实预查询和attack明确target假预查询计入六格。Unknown仍在这些主分母中。无query、newborn、GT未知及不可构造另列覆盖。`weights`按真假各自的family/k、父、query epoch、时刻归一化。`_paired`与`_transitions`可用于通用方法名称，须在各自相同总体上调用。
- `attach_labels`的entity_coverage按每扫描每role记录，因此coverage行数和中央query epoch数都不是实体数。3父/3实体门槛应从明确假query所在父与唯一job_id加target角色计算，并同时列构造成功实体及无query实体，不能用构造数替代有明确监督的实体数。

## 实施验收范围

同意SDS现有必要fixture范围。代码审核重点检查上述三项、任务全集恢复、旧五方法cal分数/政策/决策复现，以及不可估和覆盖不足不能判通过。审核通过后连续运行既定完整批次，效果失败不修改门槛或追加任务。
