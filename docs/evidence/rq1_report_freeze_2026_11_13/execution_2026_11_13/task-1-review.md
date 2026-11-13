# Task 1 独立规格与代码质量审核

2026-11-13。审核范围为 `e1e52d4..2b71ea9` 的全部四个新增文件，共801行，以及它们实际调用的旧准备、评分、校准、权重和统计函数。本次只读审查生产代码，未改工作树生产文件、index或HEAD，未派子agent，未运行真实prepare、拟合或新增评价，也未重跑实现报告已通过的9项单测。此文件是本次唯一新增交付。

这次变更新增一个冻结批次包装器。它准备六个额外父录制的30项任务，复用旧五方法，只在旧fit/cal拟合和校准四个新对照，然后生成九方法、三方案的扩大开发报告。

## 审核结论

- **spec-compliance：不通过，需修复问题1。** 冻结范围、参数来源、阶段顺序和主要统计口径符合规格，但主分母中部分无分数记录没有完整进入不可通过条件。
- **quality verdict：fix 1 first。** 发现1项Important，无Critical，无另列Minor。修复只需发生在新增包装器的覆盖统计与裁决，不应修改旧评分实现、旧政策或冻结决策。
- **真实批次：本轮不放行。** 修复并定点复审问题1后可以执行既定唯一批次，不需要重做规格、扩大测试范围或重跑旧全套。

## 必须修复

### 1. Important：候选及必要比较方法的部分无分数记录可能未阻止通过

位置为 `scripts/rq1_report_freeze/run.py:258`、`274-281`、`301-308`。依赖分支为 `scripts/rq1_score_revision/no_miss_constant.py:96-130` 和 `scripts/rq1_score_revision/run.py:330-362`。

**实际行为。** 新metrics仅把逐行状态严格等于 `numeric_failure` 的记录计为数值失败。judge只要求候选至少有一条分数，并检查这个数值失败计数。必要比较方法同样只检查至少一条分数和零个 `numeric_failure`。它们没有检查主分母中的无分数记录或 `unavailable` 状态。

旧 `zero.score_feature` 的真实行为不能支持这个假设。若上游旧评分因有限性失败而令 `old['finite']=False`，D_zero和I_zero跳过评分，但其拟合状态原为ok，最后转为 `unavailable`。J_zero也因I_zero不可用而转为 `unavailable`。这三项不是 `numeric_failure`。新包装器保持这一旧行为本身符合冻结要求，问题在于新裁决未完整识别这些失败。

**定点证据。** 本次只读加载真实mixed旧模型，对一条内存合成特征设置 `finite=False` 和非有限正常概率错误。实际调用新增 `score_feature` 后，D_old和MATE_policy为 `numeric_failure`，D_zero、I_zero、J_zero均为 `unavailable`，五项分数均为空。随后单独调用judge的内存fixture保留所有科学判据通过，只把D_zero覆盖设为299/300、状态为299条ok和1条unavailable。实际返回 `main.status='retained'`，其 `numeric_failures` 检查为pass、value为0。这个fixture验证的是裁决缺口，不是新评价效果。

**具体后果与边界。** 普通的正常特征全局失败通常还会让新增Count/CountQ失败，现有比较项可能间接把整体裁决挡为不足。因此上述单行输入并不证明真实整批一定误判retained。但候选自身的数值检查和 `risk_utility_status` 仍可能显示通过。旧评分发生逐行异常、而新增计数评分仍能成功时，间接保护也不成立。SDS第47、53行明确要求主分母无分数记录记不可估或不足，并禁止数值失败宣称通过，不能依靠另一方法恰好同时失败来满足此要求。

**最小修改。** 在新增metrics中按方法单独统计主分母中空分数、有限性失败和逐行失败状态，保留正常Unknown与评分不可用的区别。judge对候选及该项结论依赖的比较方法检查这些覆盖数，存在缺分数或失败时，将相关判据记失败或不足。比较D_old、I_zero、MATE_policy的效用差时也需要检查对应比较分数可用性。全部记录仍保留在原六格主分母中，旧分数、旧状态和旧决策原样保留。

**定点验收。** 增加一个失败状态为unavailable、仍有其他有效记录的fixture，确认候选不能通过。再覆盖一个必要比较方法的部分缺分数，确认不能认领相应增量。已有新方法失败隔离断言应继续成立。不要求重跑旧全套或修改已冻结旧模块。

## 已核实符合规格的部分

1. **范围与角色。** config固定六额外父、30个唯一job、九方法及三方案。validate_config检查旧6 fit、5 cal、3 eval角色、额外父不重叠以及每父五任务。prepare仅在本批进程注册新eval角色，没有修改旧data文件。额外六父的检测同步帧与现有FOV缓存逐帧完全相等，数量分别为98、147、134、102、141、104。此核对只读取现有清单与缓存，未运行预处理。

2. **准备与标签时序。** parent_worker复用recording_spec和preprocess_new。clean保留全部扫描，attack截取80扫描。构造先保存attack.json，恢复读取同一个文件，UNREALIZABLE单列。replay_online仅收到_public后的扫描，GT和echo已移除，缺FOV的None转为空表。attach_labels在回放结束后运行。未发现标签进入在线评分的新增路径。

3. **任务全集与恢复。** manifest保留原30项任务。技术异常保存error并抛出，不能伪装UNREALIZABLE或COMPLETE。完整任务恢复会检查必要产物，非终结任务仍在pending中。prepare完成标记要求每项均为COMPLETE或UNREALIZABLE。evaluate再核对任务集合、逐任务完成标记及准备产物。未发现通过漏掉整项任务取得完整状态的新增路径。

4. **新对照及源族隔离。** fit仅读取旧fit/cal特征和旧参数，输入文件来自旧fold及完成任务，不靠glob推断完整性。supervision先按源族选择，再计算训练尺度和权重。Count使用真实n_minus与未分组D_head的n_plus，五列系数自由。G_zero拟合时把d列置0，并确认其系数严格为0。CountQ和Q_zero分别固定Count、旧I_zero，复用无截距、无中心RMS平方增量拟合。未发现目标族进入源族标准化、平方尺度或门限的新增路径。

5. **旧五方法和九方法映射。** 旧参数及政策逐项复制，冻结五方法分数由旧zero.score_feature计算。新cal重建与旧cal按key、分数、决策和资格元数据核对。九方法校准和统计逐方法映射到旧D槽，没有修改旧METHODS、dtype或全局别名；决策直接逐行调用decide。新增Count/G/Q异常只更新其自身状态，没有修改冻结结果的finite或资格。

6. **阶段顺序与解释器。** all先用data.RUNTIME执行prepare子进程，再由当前主解释器运行fit/evaluate，没有递归持有同一锁。evaluate要求fit.complete及三方案模型、校准和cal预测产物存在后，才生成共享新评价特征。绑定不包含解释器差异字段，因此native准备与主3.8数值阶段不会仅因解释器不同产生绑定冲突。本次没有验证真实native运行是否成功。

7. **主分母及统计。** 六格调用原primary与权重，Unknown及无分数行仍保留在主分母。真假整类缺失时比例为None，不能当零错误。逐父、窗口和family/k各自重新归一化。两个候选均有配对时效和转移。明确假实体按job_id加target角色计数，query epoch另列，不把同一实体多个epoch当多个实体。构造失败和已构造无明确query单列。missing cal layer与整类不可估有区分。

8. **报告与结束语义。** 新旧开发结果分表，summary同时显示总体和首窗，完整九方法分层数据保留JSON。逐项裁决保存value、limit、status和denominator。run.complete明确仅表示执行完成。旧k3与迁移失败保留，未发现新增门限、seed、任务或效果驱动重跑路径。

## 验证范围

已完整阅读本次diff、四个新增文件、brief、实施报告、protocol、config、SDS、sds_review，以及AGENTS要求的当前研究文件。已追踪本批调用的原prepare公开化、native准备和标签附加、正常特征、评分、校准、三态决策、六格权重、配对时效和裁决代码。

实施报告中的9项测试结果作为已有执行证据读取，未把它当作本次独立复跑结果。本次新增执行为小型内存分支检查、旧模型参数只读检查及六父FOV/同步帧定点读取，没有真实新评价数据评分，没有拟合任何模型，没有改旧产物。本报告不评价方法是否有效或是否达到论文贡献要求。

## 问题1修复定点复审

2026-11-13。仅审核 `2b71ea9..4b90295` 的修复diff和直接上下文，并核对实际HEAD为 `4b90295c48abdf73c5e42855e05f930fc2fbdc2a`。没有重做全变更检查，没有重跑已通过测试，没有启动真实批次。

**问题1为ADDRESSED。当前spec-compliance通过，quality verdict为Ship。阻塞列表为空，可以执行既定唯一批次。** 本节取代上文初审的不放行结论，初审问题及证据保留。

具体依据如下。

1. 新增score_coverage沿用原primary判定主分母，按方法保存空分数或非有限分数数、finite=False或逐行状态异常数及状态分布。正常Unknown不会因决策为unknown而被误计为评分失败；unavailable会进入失败计数。
2. judge对候选及实际结论依赖的比较方法加入零缺分数、零失败及模型状态完整性检查。主候选检查D_old，mixed另检查MATE_policy、Count、CountQ。联合检查I_zero、G_zero、Q_zero，mixed另检查MATE_policy。所需方法与现有各方案的比较范围一致。
3. 新检查在risk_utility_status快照之前加入。因此同一缺分数不能再让风险效用状态或最终状态通过。两类或校准类不完整、任务未完成时，这些检查仍记不足，没有把整类缺失改判为零错误成功。
4. 修复没有修改score_feature、旧评分、政策、decide、六格或Unknown分母，也没有修改模型拟合、源族筛选、阶段依赖或准备恢复。未发现修复引入直接破坏。
5. 新增fixture先构造可retained的基准，再逐项覆盖两个候选及全部必要比较方法的10个部分unavailable子例，并断言240条假主分母不变和整类缺失为不足。已读取实施报告记录的修复前RED及修复后3项测试GREEN，未冒称本次独立复跑。

本次通过只对应实现规范与这项失败判据修复。真实prepare兼容性、完整数值执行和科研门槛是否通过仍须由正式批次及之后独立统计核对回答。

## 合法免分数Unknown的语义澄清

记录时间为2026-11-13 12:18:43 UTC。主会话报告正式批次仍在prepare，尚无本批新模型或新eval分数。本次只读取旧mixed cal预测和已审核代码，没有查看新eval，也没有修改任何运行代码。以下规则在本次新结果产生前记录。

**4b的完整性检查过宽，确需区分政策已确定的Unknown与评分失败。** 上次复审确认unavailable能够阻止通过，但没有进一步区分合法不需分数的Unknown。这一点需要纠正。修正只影响报告完整性字段及其裁决，不修改分数、门限、资格或三态决策。

旧 `source_zero_scores/predictions/mixed/cal.jsonl.gz` 的独立只读统计为MATE_policy缺分数211行，其中12行属于原primary主分母。12行均finite=True、逐行状态unavailable、保存决策为unknown。其中10条真、2条假；9行两个eligibility都False，另外3行reject_eligible=True。两个已给示例 `[8d87c21350a7bb56,177,3]` 和 `[8d87c21350a7bb56,309,9]` 均无输出、无native_mean、无error且两个资格都False。

原decide明确规定，采纳和拒绝分别需要对应资格。若两个资格都False，不论任何有限分数取值，决策都是Unknown。这时MATE_policy因native_mean不存在而没有分数，不构成对这一既定决策的数值失败。用这类记录使整个mixed对MATE比较不可用没有决策语义依据。

最小修正规则固定如下，适用于候选及该结论所需比较方法。

1. 合法免分数Unknown必须同时满足finite=True、accept_eligible=False、reject_eligible=False、score为None、逐行status为unavailable、记录没有显式error，且保存decision为unknown。相应全局模型仍须满足required_model的ok或reference要求。
2. 仅上述记录可从阻塞完整性的缺分数与逐行失败计数排除。保留原始缺分数数，另列合法免分数Unknown数量，不修改原六格、Unknown或主分母。
3. finite=False、逐行numeric_failure、实际NaN/Inf或显式error仍是失败，即使两个资格都False也不能豁免。其他异常状态不能借此例外消失。
4. 只要有任一决策资格，缺分数仍阻止该候选或所需比较结论通过。全局模型unestimable仍由required_model阻止。这个例外不依据真假标签、A/R是否关闭或新评价表现决定。
5. 旧cal中其余3条有拒绝资格的缺分数记录不能被一并豁免，分别为clean的 `[60b528984765d9ec,267,123]`、F1/k2的 `[343d46fc7b709925,205,211]` 和F1/k3的 `[f0282c7c0945698d,205,212]`。它们说明修正不保证最终裁决会转为通过。

按照主会话明确安排，不热改或重跑当前批次。原批次结束后，仅从保存预测按上述预先记录规则另存修正后的报告完整性字段及裁决，保留原报告，完整记录规则版本。评分、门限、决策及效果门槛均保持。本次语义审核认可这一处理路径；后续报告修正实现仍须定点核对，不能把本节当作已经完成了修正。

## MATE参考定义内弃判的补充复核

记录时间为2026-11-13 12:22:01 UTC。本次仍仅读取旧cal和真实依赖代码，没有查看新eval或正式结果，没有修改运行代码。上一节“另3条有拒绝资格的缺分数记录不能豁免”的判断撤回。共同决策资格不等于每个参考方法必有目标状态，不能由补丁的完整性要求倒推这个假设。

决定性代码依据如下。

- `native_adapter.py:293-311`先从上一中央对象形成query，再处理当前central输出。因此query仍存在但当前output已经不存在是合法状态。
- 实际导入的 `avstack-trust/avtrust/estimator.py` 中，CentralizedTrustEstimator使用当前tracks_cc的ID调用init_new_tracks。`avtrust/updater.py:129-133`随后显式删除不在当前track_ids中的信任分布。
- `native_adapter.py:317-318`对信任数组没有该query ID的情况保存native_mean=None。旧score_row仅在native_mean存在且有限时定义MATE_policy分数，否则保留None；原decide将其定义为Unknown。

所以，当前central对象消失后，MATE参考不再有该对象的信任分数，是实际算法对象域决定的合法弃判。窗口的共同拒绝资格可以仍然为True，但它不使MATE恢复已删除状态，也不要求MATE给出拒绝。完整三态比较应保留该Unknown及其代价，不能把它变成全体比较不可用。

再次只读核对上一节3条旧cal记录，均满足finite=True、output_present=False、identity_ok=False、native_adopted=False、native_mean=None、score=None、逐行unavailable、无error、保存决策unknown。这三条也可豁免完整性阻塞，依据是MATE定义内弃判，而非无共同决策资格。旧cal的12条primary缺分数因此均有已确认的合法弃判依据，但这不推断新eval具有同样情况。

最小规则增加一个仅限MATE_policy的 `expected_reference_abstention` 判定，与上一节已接受的通用无资格Unknown例外分开记录。

1. 必须是MATE_policy，全局状态为reference，记录finite=True、output_present=False、native_mean字段显式存在且为None、score为None、逐行status为unavailable、无显式error、保存decision为unknown。identity_ok=False和native_adopted=False可作为与无当前对象相符的一致性条件。
2. 该参考特例不受reject_eligible是否True影响。它不填分数，不改变政策或decision，不从主分母删除记录，只另列预期参考弃判数量，并免除相应完整性阻塞。
3. finite=False、numeric_failure、显式error或实际非有限数值仍优先作为失败，不得由参考特例覆盖。当前output存在但参考分数缺失，也不借本例外自动豁免。字段缺失不能通过get默认None冒充已确认的native_mean=None。
4. 其他模型有决策资格却缺分数仍阻止对应候选或必要比较结论通过。全局模型unestimable仍由required_model阻止。通用无资格Unknown例外维持上一节边界，不将MATE的状态域特例推广到其他模型。

本更正基于旧代码的算法定义与旧记录，没有使用本批新表现选择豁免。继续遵守不热改、不重跑、原报告保留的安排。完成后按已保存预测另存修正完整性字段及裁决，并在定点复核中分别检查通用无资格Unknown、MATE预期参考弃判、真实失败三种情况。

## report-only修正实现审核

2026-11-13。仅审核 `4b90295..7c380ea` 的两个新增文件、`report_integrity_revision.md`、实施报告尾部及必要直接上下文。实际HEAD为 `7c380eae73bb91e70f7da1cfda3c46364a619187`。未复审原4b全部代码，未重跑已通过的4项测试，未读取新eval或正式效果，未执行真实修正CLI。

**结论PASS，spec-compliance通过，quality verdict为Ship，阻塞列表为空。** 可对已完成的原批次执行一次报告修正，再进入独立结果核对。这个结论仅放行报告完整性修正实现，不认定任何科学门槛通过。

已确认以下边界。

1. expected_reason只允许前述两类None-Unknown，先共同检查全局ok/reference、行finite=True、分数键明确存在且为None、逐行unavailable、无行级或方法级error、保存决策unknown。无共同资格要求两个字段明确False。MATE特例还要求全局reference、无当前output、native_mean字段明确存在且为None、native_adopted=False。它没有把该特例推广到其他有资格但缺分数的模型。
2. finite=False、numeric_failure、显式error、实际NaN/Inf均不能进入例外。显式error即使配合ok状态也计入阻塞失败。全局不可估不能进入例外，原required_model及estimable检查保持。未发现通过合法弃判名义释放真实失败的路径。
3. _coverage先按保存预测重计原primary的n_total、n_missing_score、n_failed、states并与原报告核对，差异抛错。原始字段保留，只新增按原因的预期Unknown数量和两项blocking计数。两个例外同时满足时先归入无共同资格类，不重复计数。
4. correct_report复制原报告，只改primary完整性新增字段、对应两类guard的value/status及其派生裁决。原insufficient保持，required_model和其他科学检查不变。risk_utility_status重算排除CD_gain_over项，与原4b快照范围一致。没有重计或修改六格、CD、权重、时效、政策、分数、决策或其他覆盖。
5. revise要求原run.complete且原完成产物存在，核对汇总与单方案原报告一致。只向report_corrected写新报告、来源manifest和修正完成标记。全部原报告、预测、binding与run.complete仅以只读方式访问。summary仅格式化保存统计，不拟合、不算新分数、不选择门限。来源manifest记录原文件哈希、修正代码/规格与原数值代码版本。
6. 提交范围确为2个新增文件，run.py与prepare.py相对4b没有差异。已读取实施报告中4项定点测试的既有GREEN证据及测试代码，覆盖合法弃判、真实失败、其他模型、原始计数和insufficient保留、其他失败不释放、完成前拒绝及源文件字节不改；本次没有重复执行。

正式修正后的source_manifest、原文件哈希、效果统计不变及派生裁决应由随后的独立结果审核确认。本节不把fixture中的字节保持断言冒称为真实run_001修正已经完成。
