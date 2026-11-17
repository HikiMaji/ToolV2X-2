# grouped acceptance 开发评价入口独立审查

2026-11-17。结论为可以执行冻结规程中的一次开发比较。未发现需要先修复的实现问题。本结论只针对评价入口是否忠实应用已选门限及执行原裁决，不预判评价风险或效用会通过。

## 审查范围

已读取 `grouped-eval-review.diff`、`grouped-eval-implementation.md`、实际 driver 与测试，并沿调用检查 `core.decide`、`core.measurements`、`core._judge`、原 `primary/weights`、表格转换和 `_check/_verdict`。已复习当前经验教训、主方案、最新用户要求、状态及 grouped_acceptance_protocol.md。此前 cal-screen 的真实通过状态以主会话提供的结果为前提，本次不重算。

未打开真实 cal/eval 预测、门限或新统计产物。未运行 driver、未重跑已报告通过的四项测试、未改实现，也未新增数值反例。静态检查没有发现需要定点运行才能裁定的明确问题。

## 核心要求核对

| 要求 | 实际代码与判断 |
| --- | --- |
| 仅执行 go-regimes | driver 第113至130行只从 screen.json 取得 go_regimes，并验证重复及合法名称；第141行仅遍历该集合。未通过配置不加入预测读取清单。无 go 时不打开源预测，保存空报告及 NO_GO。 |
| 源 cal 与 policy 绑定 | 第122至136行检查 screen 绑定的 source_run，与源目录一致；对当前 go 配置的原 calibration JSON 和 cal.jsonl.gz 重新取得来源记录，并与 screen 的来源记录完整比较。config 直接来自原 evaluate.binding.json，没有重设域、评价层或标准。 |
| 仅提高 tauC | 第20至27行要求 Local policy 完全相同，两个远端方法除 tauC 外全部字段相同，tauC 不得降低。第145行 Local 来自原 policy 的深拷贝。没有校准、重训或按 eval 选门限。 |
| 原候选、分数和分母保持 | 第30至50行逐条保留输入行，仅替换决定、原因及 local_state，附保存旧决定；检查重复主键，没有过滤或添加候选。scores、C/R/I/F、标签、父身份、时间与资格字段保持原值。第152至160行完整读取相应 split，再交原 measurements 统计。 |
| 只允许采纳转未知 | 第39至46行先复现原决定和原因，再应用新 policy，并逐条禁止除 accept 转 unknown 外的变化。原 decide 先本地分支，再消息拒绝，最后比较 tauC，因此既有本地决定和拒绝不受提高 tauC 影响。 |
| 六格与完整权重 | 第53至69行的自身旧新比较用原 primary 及完整类 weights，未知和拒绝不退出分母。core.measurements 仍用原六格、首窗、父、域、时效及轨迹统计，没有改成消息支持子集上的率。 |
| 相对新 Count 的原标准 | 第88至103行取 core._judge 对新 LocalCond 相对新 LocalCount 的原检查，保留 CD、真实采用代价、时效、全局风险、逐层风险及父/实体覆盖标准。没有把旧 Count 的较宽门限作为新候选的弱对照。 |
| 两方法各自相对旧版代价 | 第93至101行分别要求新 LocalCount 和新 LocalCond 相对自身旧版的完整评价 TA 损失不超过0.02，并各自保留严格正质量的远端真实采纳。还为 Count 明确检查全局 TR、全局 FA 及逐层 FA。缺失统计进入 insufficient，不能通过。 |
| Local 只作基线描述 | 虽然 core._judge 会生成 Local 与 LocalCond 两个结果，driver 只取 LocalCond 的 checks。最终合并裁决不包含 Local 的相对增益失败项，并注明 descriptive_only。 |
| 最差父组与未知代价 | 第72至85行按每个实际 family/k/parent 的完整主假组报告旧新风险和未知增加，并列最差组。第161至163行另存各域自身旧新比较，没有将校准组约束称为新评价父的保证。 |
| 旧 budget 与新 cal 分开 | 第15至17、118、163行明确注明 policy budget 复制自 run_002，不是新 tauC 的重新估计。新 cal 实际结果另存 report/REGIME/cal.json，不用源 budget 冒充新风险。 |
| 原运行保留 | 第107至112行禁止输出与源目录重叠及已有输出。全部写入 screen/evaluation，源文件只读。源 run_002 的门限、决定和 not_retained 裁决不改写。 |

四项测试静态上覆盖无 go 不读预测、policy 限制与原行保持、自身采用损失阻断且 Local 失败不污染候选，以及完整入口输出隔离和源文件保持。本次不将实施者报告的通过结果冒称为独立重跑。

## 执行与解释边界

可以执行实施报告中的 driver 命令一次。没有需要在此之前新增的通用检查或实现修补。运行后以各 regime 的 verdict 和逐项 checks 解释保留状态，顶层 COMPLETE 只表示计算完成。

若风险、采用损失或其他原条件失败，按规程保留失败并停止相应候选，不依据评价重新选 tauC、放宽标准或补种子。若通过，也只是已看过开发评价中的经验结果，不是新的盲测，不提供新父录制风险保证。门限修正的收益只能解释为降低采纳风险及其集中程度，须同时报告真实采纳转未知的代价，不能称为新的观测信息或多车依赖贡献。
