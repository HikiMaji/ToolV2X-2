# Task 1 实施报告

状态 DONE，等待主会话独立代码审核。未运行真实prepare、拟合、回放或新增评价。

新增 `scripts/rq1_report_freeze/{__init__,prepare,run,test_report_freeze}.py`。旧生产模块未改。实现统一prepare/fit/evaluate/all入口，冻结30任务、六额外父、九方法和三方案。默认4进程，最大6，各数值库单线程。

prepare复用recording_spec/preprocess_new/construct_attack/replay_online/attach_labels。clean用全扫描，attack最多80扫描。公开扫描经旧_public去标签且None FOV变空表。仅在本批进程添加额外eval角色。技术失败保存error并退出非0，恢复沿用原attack.json和原任务；UNREALIZABLE单列。任务标记全部终结后才写prepare.complete。

fit仅读取旧fit/cal、原模型和政策。旧fold和完成任务定义文件清单，检查六fit与五cal父。Count直接使用n_plus与实际n_minus，五列自由系数；G_zero仅固定原d项为0；CountQ/Q_zero固定offset并使用原平方增量函数。逐方法单D槽校准避免八旧槽容纳九方法，逐行decide避免apply_policies全METHODS遍历。旧五方法模型、政策和cal分数/决策复现，保留具体缺层与整类不可估区别。

evaluate在三方案参数和政策均保存之后生成一次共享特征。主分母保留Unknown及数值失败。逐父/窗口/源族k六格、配对时效、转移、物理job+target实体支持、构造失败和无明确query分别报告。裁决保存value/limit/status/denominator，整类缺失为不足，数值失败不能通过。run.complete仅表示执行和报告完成。

## RED 与 GREEN

1. 先新增7项语义fixture，命令 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_report_freeze.test_report_freeze`。缺少run/prepare模块导致setUpClass ImportError，符合缺实现的RED预期。
2. 最小实现后，测试属性名与unittest.run冲突、过度套用旧job_id公式暴露。修正测试属性，并直接保留冻结config的原30 job_id，7项GREEN。
3. 新增完整临时目录fixture，使用合成旧fit/cal和已保存新feature fixture，贯穿fit/evaluate及恢复，旧五方法cal分数/政策/决策一致。未读取任何真实新评价数据。
4. 整类缺失断言先RED，发现estimable检查使缺类状态误记not_retained。修正后为evidence_insufficient。技术故障恢复fixture确认保留error、没有伪造complete、后续仅恢复同job。
5. 最终本批命令同上，9项通过，2.220秒，退出0。测试覆盖Count真实未报、自由系数、G固定d、源族隔离、固定平方offset、旧五方法与九方法独立、单方法失败隔离、加权六格、实体与epoch区别、无query/新生/未知/不可构造、失败和不足、全流程恢复与all解释器调度。

`python -m scripts.rq1_report_freeze.run --help` 和 `/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m scripts.rq1_report_freeze.run --help` 均退出0。实际解释器分别为Python3.8.10、Python3.10.19。all的调度fixture确认先用data.RUNTIME执行prepare子进程，之后调用当前主解释器的fit/evaluate。真实all未启动，因此未宣称native数据适配或实际数值阶段已验证通过。

只运行本批新增测试，按SDS及主会话要求未机械重跑旧全套。未增加新依赖、方法、任务、种子或门限。实现完成与方法有效严格分开。独立代码审核及真实完整实验由主会话接续。

## 独立审核后定点修复

审核发现主分母中的unavailable和缺分数没有直接阻止通过。旧score_feature在finite=False时可以将D_zero/I_zero/J_zero记为unavailable，因此不能只检查numeric_failure或依赖Count旁支阻挡。此问题属实，现仅修改新包装器的统计和裁决，旧score、政策、decide及主分母均保持。

新增 `method_score_coverage[method].primary`，字段为 `n_total`、`n_missing_score`、`n_failed`、`states`。primary严格沿用original.primary的真假主分母。`n_missing_score`计None和非有限分数，`n_failed`计finite=False或逐行状态不为ok/reference，两个数可以重叠，不相加作为实体数。

每个适用候选及必要比较方法增加 `primary_missing_score/{method}`、`primary_failed/{method}` 和 `required_model/{method}` 检查。全部在risk_utility_status快照之前加入，主风险效用和最终裁决均不能靠缺分数降低经验风险后误过。主候选检查D_old；mixed另检查MATE_policy和Count/CountQ。联合检查I_zero/G_zero/Q_zero，mixed另检查MATE_policy。无完整主类、校准类或任务条件时仍记不足。无分数行继续Unknown且保留主分母。

先写定点fixture，基准合成结果可正常retained，然后分别使D_zero/J_zero候选或D_old/MATE_policy/I_zero/Count/CountQ/G_zero/Q_zero必要比较方法的一条主假样本unavailable。修复前10个subcase均在risk_utility_status断言RED，证明旧缺陷；修复后风险效用和最终状态均不再retained，240条假主分母不变。另验证整类缺失时两种状态均为evidence_insufficient。

本轮只执行相关3项测试，未重复无关全套。

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_report_freeze.test_report_freeze.Contracts.test_primary_unavailable_blocks_candidate_and_required_comparisons scripts.rq1_report_freeze.test_report_freeze.Contracts.test_weighted_cells_physical_entities_fail_and_insufficient scripts.rq1_report_freeze.test_report_freeze.Contracts.test_frozen_five_and_nine_method_policy_and_failure_isolation`

结果3项通过，1.817秒，退出0。git diff --check通过。真实批次仍未启动。

## 运行期间隔离新增的报告语义修正

依据新规格 `docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/report_integrity_revision.md`，只新增 `report_integrity.py` 和独立 `test_report_integrity.py`。没有修改正在运行的run.py、prepare.py或旧模块，没有读取本批新eval数值，没有在真实run_001执行修正。

本修正接受预先明确的两类合法无分数Unknown。共同前提为全局ok/reference、finite=True、分数键明确存在且为None、行状态unavailable、无显式error和保存决策unknown。第一类为两个共同资格都明确False，记录 `no_common_decision_eligibility`。第二类仅MATE_policy全局reference，output_present=False、native_mean键明确存在且为None、native_adopted=False，记录 `expected_reference_abstention`；不受reject资格影响。两个条件同时满足时按第一类计数，不重复计数。

保留每方法原primary的n_total/n_missing_score/n_failed/states，另加 `expected_unknown_by_reason`、`n_missing_score_blocking`、`n_failed_blocking`。cal和eval均更新这些新增统计。原raw主分母计数先与保存预测复核，差异报错。显式error即使配合ok行状态也不能消除阻塞。

只替换eval retention的primary_missing_score/和primary_failed/检查中的value/status。原status=insufficient保持，其他判据和其数字及denominator保持。risk_utility_status使用原快照范围（排除CD_gain_over_增量检查），最终裁决使用全部原检查重新导出。required_model、estimable等其他可用性约束不放宽。

CLI为 `python -m scripts.rq1_report_freeze.report_integrity --out <已完成的原run目录>`。没有原run.complete则拒绝且不建立修正目录。只向 `report_corrected/` 写各方案JSON、metrics.json、summary.md、source_manifest.json及revision.complete.json；原report与run.complete保留。修正来源manifest绑定原报告、预测、binding和run.complete的字节哈希，数值代码继续标记4b90295，报告版本单列rq1_expected_unknown_v1并记录修正代码及规格哈希。只复用旧summary格式化，不拟合、不求新分数、不选门限。

先写四项定点fixture，缺少新模块时ImportError构成缺实现RED。实现后以下命令GREEN，4项通过、0.214秒、退出0。

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_report_freeze.test_report_integrity`

覆盖两类合法Unknown、其他方法有资格却缺分数、MATE正常状态仍有数值时、缺显式字段、finite=False、numeric_failure、显式error（含空字符串）、NaN/Inf、全局unestimable和决策不为unknown。保留原insufficient，并验证其他estimable失败不能被本修正释放。临时目录完整CLI核心fixture确认源预测、报告、政策、六格/CD、时效、支持数和其他原输入字节全部不改，且修正可重复核对。`--help`退出0。`git diff 4b90295 -- scripts/rq1_report_freeze/run.py scripts/rq1_report_freeze/prepare.py`为空。本轮不重跑此前无关测试。

正式批次仍由主会话运行，新增差异须独立审核后才由主会话决定执行真实修正CLI。
