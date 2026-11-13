# 合法Unknown与评分故障的报告语义修正

2026-11-13。正式批次数值代码4b90295保持运行，不热改、不重拟合、不重选门限。发现本问题时仅检查了旧cal预测，尚未查看新增评价分数或效果；当时prepare已完成，fit.complete尚未出现。此修正落实原方案中Unknown保留与数值故障区分，不修改经验风险或增益门槛。

## 依据

旧mixed cal中MATE_policy缺分数211条，其中主分母12条，10真、2假。12条均finite=True、status=unavailable、decision=unknown。9条两个共同决策资格均False。另3条有拒绝资格，但当前output_present=False、native_mean=None、native_adopted=False、error=None。

native_adapter.py按hook.trust_tracks中是否存在query ID获取分布。独立审查进一步确认CentralizedTrustEstimator以当前central对象ID调用init_new_tracks，updater.py删除不在当前track_ids中的信任分布。因此上一帧预测query仍存在、当前central对象已移除时，MATE没有当前分数是定义内的弃判，不是数值异常。共同拒绝资格为True也不强制MATE具有该对象的信任状态。

此前4b完整性补丁把所有主分母unavailable当故障，过于宽泛。先前防止真正计算失败伪装成Unknown的要求继续成立，但必须把设计允许的无分数Unknown单列。

## 固定的例外条件

先要求方法全局状态ok/reference，行finite=True、score明确为None、逐行状态unavailable、无error、保存决策unknown。实际NaN/Inf不属于此例外。在此前提下仅允许两种情形。

1. 两个共同决策资格均False，政策不依赖分数即已确定Unknown。
2. 仅MATE_policy，方法全局为reference，当前output_present=False、native_mean明确None、native_adopted=False。此为expected_reference_abstention，不受reject资格影响，不能套用到其他模型。

任何finite=False、numeric_failure、显式error、模型全局不可估、有资格却异常缺分数的其他模型，仍阻止对应候选或必要比较通过。无分数原记录及Unknown继续计入原主分母。规则不按真假类别、攻击族或新效果挑选记录。

## 实施方式

只新增事后报告修正模块和定点fixture，不修改运行中的run.py或prepare.py。等原批次完整结束后，读取保存预测，重计主分母合法无分数Unknown及阻塞缺分数/失败量。保留原始n_missing_score、n_failed，同时新增expected_unknown和blocking字段。只更新完整性检查与由其导出的裁决。

全部分数、门限、决策、六格、权重、CD、时效、覆盖与其他判据数值保持原样。原report目录和run.complete完整保留，修正版另存report_corrected及revision.complete，记录源报告及代码。独立统计复核修正版，并核对原、新报告的主要效用统计不变。这不是第二次方法实验。
