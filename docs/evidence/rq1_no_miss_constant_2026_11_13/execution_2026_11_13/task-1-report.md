# Task 1 实施报告

2026-11-13。编码任务完成，待主会话安排独立代码审核。没有运行真实fit/run。没有修改旧生产源码、旧数据或旧输出。

提交 `5e89769`，基线 `22195637d1c67615f5f119f282eb5620bcf6e3b6`。本提交只新增两个文件。

- `scripts/rq1_score_revision/no_miss_constant.py`，439行。
- `scripts/rq1_score_revision/test_no_miss_constant.py`，262行。

## 实际实现

`fit_zero`先复用原supervision筛选源族，再检查原六父和对应normal可用性，按原training_weights求权重。D/I在输入副本中将d置0，保留六列并调用原fit_base。记录原d均值、方差、标准差、结构固定列、其他scaler、class_weight、总权重、监督父、false_cells与实际自由度。J只调用一次原fit_increment并以I_zero作固定offset。缺Delta不删除监督行后继续拟合，保存不可估原因。delta_uninformative保持原状态。

`score_feature`复用旧score_row，以保留旧基线异常合同；新增基础分解复用decompose。I_cut精确使用原尺度coef[4]扣除gamma*(d-m)。行级状态只留status/reason，没有复制完整训练父清单或覆盖报告。

报告通过本模块局部八列映射复用ReportRows，不改旧全局METHODS。每方案每split只建立一次表，校准/六格/分层复用该表。输出主六格、CD、原始计数、family/k完整空层、逐父、w三档与实际w/m/n0层、context计数、转移、主真epoch配对时效、I_cut旧I政策六格，以及预声明首窗和六条错误描述。三候选分别按本规程裁决，D_zero标为primary，不使用旧联合保留判据。全部Unknown及缺类、不可估、未检验不能通过。

runner只读已完成source特征、模型、cal与旧predictions。每次入口做一次小依赖/源小文件绑定及特征清单核对，不hash完整特征gzip，不调用normal、features或prepare。旧方法A/R、逐条score/decision、key、主标签、资格、context及时间戳不一致即停止。

输出包含binding、模型及完成标记、calibration、含分数predictions、各方案报告及完成标记、metrics/summary、run.complete与stage_times。一个运行锁、原子发布、partial不算完成。完成方案复用需对应方案标记；模型原子完整状态可恢复生成其紧邻完成标记。已有独立产物不会静默覆盖。失败保留error。

## 验证

先写测试，首次执行下面命令因生产模块缺失出现预期ImportError，未执行真实数据。随后实现并随新增边界补足fixture。最终汇总命令为

```bash
python -m unittest scripts.rq1_score_revision.test_no_miss_constant -v
```

最终结果 `Ran 10 tests in 1.813s`，`OK`。全部拟合与校准均为临时合成fixture，调用真实head优化器与真实校准函数，未mock生产函数。

覆盖如下。

1. 源族筛选先于scaler，两个source-only方向排除目标族扰动，gamma严格0，五列scaler保持，输入不变，class_weight各0.5，自由度最多6。
2. 当a_minus>0，低p未报贡献接近0，高p未报更负。
3. 标准化参数转回原尺度的I_cut精确扣gamma*n0并保留beta，基础贡献分解加总一致。
4. 缺父、缺Delta、非有限监督使对应方法不可估，Unknown保留原分母，旧基线仍能输出。
5. 无信息Delta保持delta_uninformative和0增量，无新截距。
6. 八列映射不修改旧全局，手算六格、空family/k层、短窗、转移及配对延迟一致。
7. 三方案临时完整run与已完成恢复，模型完整发布后但标记未写时的中断恢复，不重拟合模型，不改预测文件。
8. 绑定改变拒绝恢复，source同路径、子路径、祖先路径拒绝。
9. 残留partial不当完成，旧门限不一致停止并保留error，旧score/decision/key/标签不一致分别停止。
10. 缺特征停止，不静默删任务；未检验源方案明确不足；单方案不利风险失败不能被其他方案抵消；全部Unknown不能通过。

其他实际命令

```bash
python -m py_compile scripts/rq1_score_revision/no_miss_constant.py scripts/rq1_score_revision/test_no_miss_constant.py
git diff --cached --check
git status --short
```

均退出0。提交后工作树干净。本报告位于项目已忽略的.superpowers目录，不计入生产提交。按照用户限定，没有重复旧57项测试或全项目外部模型测试。

## 审核边界

当前测试只证明新增接口在合成输入上的数值、统计与恢复合同。真实source的旧结果复现、实际拟合状态、时长和方法效果仍没有运行证据。下一步是主会话安排独立代码及整项接口审核，通过后才运行真实有界批次。c区间不计算，F3缺失、多控单父和已见开发资料的外推限制继续保留。

未发现已知阻塞问题。没有扩展通用恢复框架、新数据构造或新调参入口。

## I1 定点修正与验证

2026-11-13。独立审核指出部分监督在available筛选时被删后，虽然六父仍齐全，仍会重算权重/scaler并继续拟合。已核对该判断。原实现对监督失效合同的处理不完整，本修正不改变规程。

修正提交 `2cfbca4cb26d5b4cccbd6e09eb32d5a54e0472f1`，基线 `5e89769c956f6371acd3ff357a40ec62fafa781f`。生产只增加两行检查。在权重和scaler前，若available未覆盖全部selected，就把对应基础头记为unestimable，原因中记录不可用数目、方法和非有限/缺特征原因。已有coverage继续保存72条监督、71条可用及完整六父，不使用71条重新估计。D局部失效只禁用D_zero，I局部失效禁用I_zero和J_zero。

先新增一项含三子情形的定点测试，然后运行确认修正前均失败。有限性失效、单D_head特征None、单I_Jmargin特征None的三子情形均复现72减为71且错误保存ok。随后增加检查，运行下列限定验证。

```bash
python -m unittest scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_single_unusable_supervision_disables_only_affected_heads scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_missing_parent_and_missing_delta_preserve_unknown_denominator scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_temporary_runner_resume_binding_and_protected_paths -v
git diff --check
git diff --cached --check
```

结果为 `Ran 3 tests in 1.224s`，`OK`。两项差异检查退出0。新增测试确认同父仍有其他有效行、所有六父仍齐全时，对应头不可估，其他头仍使用全部72条；失败方法在独立评价中保留4条真和8条假Unknown，旧基线仍有分数，保留判据标不足且不能retained。临时fixture完整三方案run及恢复仍通过。

本轮没有重复全部11项新增测试、旧测试或真实批次，没有改规程或旧生产文件。提交仅包含原两个指定文件的定点修改。独立审核者产生的未跟踪code_review.md保持原样，未纳入编码提交。待主会话安排I1定点复审。

## 真实prepare完成状态接入修正

2026-11-13。主会话首次真实启动在输入校验阶段停止，根因是旧prepare保存大写COMPLETE，而原fixture使用了小写complete。已核对真实prepare源码第412行和源标记，原实现及fixture的协议假设错误。本次没有改规程、评分、绑定保护或旧产物。

修正提交 `b0572cd40d0fa83ecded41954e6d0f42e9e7db69`，基线 `2cfbca4cb26d5b4cccbd6e09eb32d5a54e0472f1`。按阶段精确判断：prepare仅接受COMPLETE，后四阶段继续接受原complete/not_tested_data_support，不新增其他放行状态。临时fixture改为prepare的实际大写完成状态，jobs保留COMPLETE、rows和origin。

新增状态协议测试先运行，修正前按预期在prepare完成检查失败。修正后只运行以下三个相关测试。

```bash
python -m unittest scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_source_stage_status_matches_prepare_protocol scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_temporary_runner_resume_binding_and_protected_paths scripts.rq1_score_revision.test_no_miss_constant.NoMissConstantContracts.test_partial_ignored_and_old_mismatch_stops -v
```

结果 `Ran 3 tests in 1.334s`，`OK`。新测试逐阶段确认pending、PARTIAL、FAILED均拒绝，也拒绝prepare的小写complete/not_tested_data_support及其他阶段的大写COMPLETE。原临时完整run/恢复及失败旧门限检查保持通过。

按主会话授权，仅调用一次`_inputs(Path(read_config()['source']), read_config())`做真实源入口只读验证，输出

```text
read_only_input_status: COMPLETE
completed_features: {'fit': 6, 'cal': 33, 'eval': 16}
```

此验证未读取特征gzip内容、拟合或评分，未写newout/binding或结果。此前newout/error.json及旧日志未改。`git diff --check`与`git diff --cached --check`均退出0。提交仅包含两个指定文件的定点diff，待独立复审后由主会话重新启动真实run。
