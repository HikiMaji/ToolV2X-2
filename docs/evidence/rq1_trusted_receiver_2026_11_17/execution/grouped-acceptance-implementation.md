# 按校准父录制约束采纳的实施报告

实现基于已审grouped_acceptance_protocol.md。只新增grouped_acceptance.py和对应测试，未修改run.py、旧分数、旧门限或已有结果。本任务未读取真实run_002校准预测、未读取任何真实eval，也未执行正式screen。

## 接口与固定行为

`screen(source_run, out)`按固定mixed、F1_only、F2_only顺序，仅打开每个regime的`predictions/REGIME/cal.jsonl.gz`和`calibration/REGIME.json`。绑定仅这6个源文件以及本helper、公共判决和原统计/数据代码。拒绝源输出目录重叠、已存在输出目录、非cal行、重复键、缺少保存的旧决定、旧决定与冻结policy不一致、主假含非声明层。

`screen_method(rows, policy, method)`为手算测试入口。复用原primary、完整类权重与公共decide，父标识只用于离线分组，不进入公共判决。tauF/tauP/tauR和全部分数不改，候选policy深拷贝源policy，仅替换tauC；原policy中的budget等诊断字段保持源版本，新的筛查风险和采用质量以screen.json为准。

固定约束为总体、每声明family/k、每个已观察family/k/parent的完整假采纳不超过5%。每组分子包含本地采纳，分母为该完整主假组，保留其中未知及被拒绝者；组内使用原epoch/时刻权重。缺层风险为null，明确缺失，不补0。即使tauC为Infinity仍有本地风险超限时，标infeasible_local_risk。

候选包含旧tauC、原消息采纳的主真假cal行上不小于旧tauC的C边界及Infinity。先满足全部风险约束，再最大化完整正常cal真采纳，同质量取更高门限。若旧门限已经满足全部风险约束，明确保持旧门限，不做无必要收紧。没有可估/可行候选时输出关闭门限并no-go，不执行评价。

每个方法分别核查相对自身旧版本真采纳损失不超过0.02、仍有正质量远端真实采纳、风险/假层覆盖及本地风险可行。一个regime只有LocalCount与LocalCond都通过才go。逐行验证只允许accept转unknown，拒绝和其他决定必须保持；不输出新预测文件。

## CLI与产物

审核批准后由主会话执行以下命令一次，本实施任务没有执行。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m scripts.rq1_trusted_receiver.grouped_acceptance --source /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/run_002 --out /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/grouped_acceptance_001
```

仅输出binding.json、candidate_policies.json和screen.json。candidate_policies按regime/method保存候选；关闭门限沿用字符串Infinity。screen按regime/method保存旧新门限、完整normal TA、远端真采纳质量、逐组旧新FA、本地固定FA、完整分母覆盖、缺层、采用损失、逐项go条件与决定转移。顶层go_regimes只列两方法共同通过的regime。这只是cal可行性筛查，不是评价结果或总体保证。

## 定点证据

新增6项手算/临时目录测试。最终native Python运行`python -m unittest scripts.rq1_trusted_receiver.test_grouped_acceptance`，6项全部通过。CLI help与git diff空白检查通过。没有重复旧校准或Task1检查。

- 五父均衡下完整层平均5%，单父5/20为25%，新门限排除该父消息误采；完整正常TA损失为1个百分点，并保留正远端真采纳。
- 本地采纳已经造成单父10%风险，关闭远端仍超限，返回不可行no-go。
- 旧tauC=1.2且不存在对应分数边界，在已满足约束时仍保留1.2，检验旧门限显式候选及直接保留规则。
- 新增真采纳损失3个百分点、远端真采纳全关分别触发no-go。
- 缺F2/1时其风险为null且no-go；所有校准行只可采纳转未知，已有拒绝不变。
- 临时目录完整screen入口只有cal文件可供读取，read_rows守卫要求文件名为cal.jsonl.gz。LocalCond单独通过、LocalCount损失超标时regime仍no-go，输出目录恰好只有规定3个文件。

独立审查和真实cal-screen由主会话后续进行。没有需要用户裁决的新参数或信息权限问题。
