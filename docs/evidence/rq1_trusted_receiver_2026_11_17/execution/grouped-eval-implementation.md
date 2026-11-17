# 组约束候选开发评价入口实施报告

已新增execution/evaluate_grouped_acceptance.py及4项定点测试，没有修改core方法、校准、分数、PCD或已有结果。尚未运行真实开发评价，也未读取任何真实eval。

## 接口与范围

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python /root/autodl-tmp/ToolV2X/.worktrees/rq1-score-revision-2026-11-13/docs/evidence/rq1_trusted_receiver_2026_11_17/execution/evaluate_grouped_acceptance.py --source /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/run_002 --screen /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/grouped_acceptance_001
```

输出固定为screen/evaluation，要求新目录。只取screen.json中的go_regimes，未通过regime不读源预测。无go时仅保存空报告与NO_GO完成标记，不打开源预测。go时读取候选policy、对应run_002原policy和保存cal/eval预测，config来自run_002/evaluate.binding.json以复用domains、criteria及声明层。源路径必须与筛查绑定相同；对应原cal预测和policy还须匹配screen绑定的来源记录。

Local保持源policy。另两方法严格比较整个policy，除了tauC只能提高，其余字段必须相同。重新调用现有公共decide，不重算任何分数或特征。每条原决定先与源policy复现，再应用候选，并验证只允许accept转unknown。原scores、主键、标签、时间、候选分母完整保留，previous_decisions和previous_decision_reasons保存旧决定。任何不符停止，源文件不覆盖。

输出同格式calibration、predictions、report和evaluate.report.json/evaluate.complete.json，另有evaluate.binding.json。统计复用core.measurements，保留完整六格、首窗、父与域、本地状态、配对采用和决定转移。额外own_comparison报告两方法各自旧新真假三态、TA损失、正质量远端真采纳及未知增加；domain_own_comparison按原3、额外6、追加3配置映射提供同类比较。by_group列每个实际family/k/parent完整假组的旧新误采和未知增加，并指出最差评价组。

原policy的budget诊断字段仍来自run_002，校准JSON不冒充新风险估计。顶层及cal/eval报告明确注明，新cal实际统计在report/REGIME/cal.json。组约束只对应cal经验，评价父组无风险保证。

## 裁决

只复用_judge中的LocalCond相对新LocalCount条件，不把Local参照自身增量失败当候选失败。保留原CD、TA损失、时效、全局与攻击层风险和数据支持检查。另要求两新方法各自相对run_002的完整评价TA损失不超过0.02，并各自保留严格正质量远端真采纳。Count对照的全局和逐层风险也保留，不能削弱对照制造条件增益。最终由这些条件共同裁决，不从评价重新选择门限。

## 定点验证

native Python运行`python -m unittest discover -s docs/evidence/rq1_trusted_receiver_2026_11_17/execution -p test_evaluate_grouped_acceptance.py`，4项通过，0.248秒。CLI help和git diff空白检查通过。

1. 无go且源目录不存在时，read_rows守卫不允许任何预测读取，仍正常输出NO_GO。
2. 仅提高tauC通过，改tauR或降低tauC拒绝；源内存行不变，分数和主键逐项保持，任何变化只能采纳转未知，已有拒绝不变。
3. 构造原相对新LocalCount判定通过但Count自身TA损失3个百分点，附加检查将其判失败。损失0时，即使Local参照增量判定失败，候选仍能通过。
4. 临时目录贯穿driver，生成所需报告和域/父组结果，逐字确认源文件未变；再次调用已有输出拒绝覆盖。

没有新增不确定参数或需要用户裁决的问题。真实一次开发比较由主会话在独立审核后执行，本任务不启动。
