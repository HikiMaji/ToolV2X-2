# 2026-09-28 最新审查范围

当前发布目标为 `HikiMaji/ToolV2X-2` 的 `main`，保留项目历史。先读 [09-28 修复报告](codriving_native_fix_2026_09_28.md) 与 [审计报告](codriving_input_audit_2026_09_28.md)。最新源码入口为 `codriving_native_inputs.py`、`codriving_causal_context.py`、`codriving_tool_adapter.py`，以及 `scripts/prepare_codriving_native_probe.py`。

审查重点：原生 sensor/world/actor 坐标；start/decision/label 自洽；receiver 只排除返回、不截断完整 F context；predictor 不得原地裁剪输入；P 不预测；同导航空证据中心化修正；旧 adapter 权重拒绝；recording 隔离。真实数据训练和效果评价尚未执行，不应把合成优化测试写成论文收益。完整 paid receipt 链在 CoDriving 上仍未实跑。

轻量复核：`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python scripts/check_review.py`，依赖 `requirements-review.txt`。模型环境与外部资源检查另行运行。精选验证证据见 `docs/evidence/codriving_native_fix_2026_09_28/`；旧审计数值见 `docs/evidence/codriving_input_audit_2026_09_28/`。

以下为历史审查记录。

---

# GitHub 审查入口

**最新研究（09-19，底座选型）：** 本批仅新增研究报告、官方资源与小样本核验记录，并更新文档入口；推荐PDM-Closed＋V2Xverse双车，CoDriving为学习式备选。没有生产代码改动、模型执行、数据迁移或训练。审查应区分官方原有能力、拟适配接口与尚未验证的效果，特别注意原PDM默认恒速占据、CARLA地图/时标、多模式F以及MTR跨域质量。见[选型报告](backbone_selection_2026_09_19.md)和[证据摘要](evidence/backbone_selection_2026_09_19/README.md)。本批未提交/推送；下方为历史审查快照。

**当前状态（09-16，一次协作诊断已完成）：** 39个完整开发帧、156个真实归档任务、500/0/3200冻结检查点完成2460次模型前向（192秒），3042组六点输出独立复算通过，62项定向测试通过。主检查点收到P/F/PF后平均轨迹位移仅0.061/1.223/0.884毫米；同源内容比较排除完全重复，未证明远端更准。直接换回恒速基底未改善，故未实施该修复。生产驾驶器与P/F不变，零训练/新工具调用；后续LLM调度主方案已确认但尚未实现。下一项聚焦驾驶器证据使用与相关目标质量，不能继续相同训练或将本批当方法收益。见[诊断报告](single_cooperation_diagnostic_2026_09_16.md)与[可复查证据](evidence/single_cooperation_diagnostic_2026_09_16/README.md)。

**最新研究（09-15，导航接入）：** 已核对参考源码、现有 3,095 条准备记录及 3 条原生导航样本；建议局部路线目标点通过普通 MLP token 接入共同驾驶器。导航尚未实现或训练，先完成来源/坐标绑定；小样本训练退化排查后置。见[导航方案与边界](navigation_research_2026_09_15.md)。本次发布包含验收修复、训练预检/结果和导航研究的代码或文档及精简证据；下方未推送等表述保留各历史阶段状态。

**最新训练结果（09-15，数值 v2 20 轮）：** 原 16 训练帧/4 开发帧已完成 1280 次更新并独立核验，已停止。开发 got_prefix_L2_avg 从初始 0.397169 米变为最终 0.528012 米，选模仍为第 0 步；无全量扩帧或新远端采集，不支持方法收益结论。见[训练结果与证据](structured_driver_20ep_fit_2026_09_15.md)。

**最新训练（09-15，数值v2一轮小批适配）：** 现有20帧四条件归档完成1轮/64次更新，128条训练实际覆盖Ego/P/F/PF，32条既有开发阶段行单独验证；0/64步完整权重保留，选模为第0步。模型和原任务独立核验完成，已停止，不自动追加轮次或全量采集。此为小样本固定证据适配，不是ToolV2X方法收益验证。见[结果与证据](structured_driver_small_fit_2026_09_15.md)。未提交/推送。

**最新预检（09-15，数值 v2 真实小批训练）：** 20帧/80任务导出160阶段行，128训练/32开发验证，8/2录制隔离；连续4步与2+2步恢复均完成，两支线合计8次更新；检查点参数/优化器/RNG精确加载，但独立CUDA支线在中断前已有微小参数差，不宣称逐位续跑对照通过。真实P历史/F预测梯度非零，所选阶段32/32合法，但4步开发误差未改善，选模仍为0步。归档与周期检查点的正式规模超出现有存储，先调整存储表示和训练日程；未全量采集/长训、未提交推送。见[预检结果与后续边界](structured_training_preflight_2026_09_15.md)。

**最新修正（09-15，排除原因审计）：** 新派生字段明确区分 ego 过滤、实体容量和预测集合容量，并分别记录间接依赖与完全排除。80 个旧任务、160 个阶段复核确认原有审计字段和任务文件不变；补充 P→F / F→P 的角色转换及 prior 依赖回归。见[实现与验证](admission_reason_fix_2026_09_15.md)。本批无训练、新生成或重新采集，未提交/推送。

**最新执行（09-15，数值驾驶 v2 修复）：** 同一预声明 20 帧初始轨迹 20/20 合法，Ego/P/F/PF 共 80/80 任务及归档审计通过；实际 160 次数值驾驶、40 P＋40 F 请求，全部 60 个协作任务有远端字段入模。完整轻量 347 项、受影响模型/交互 83 项通过。新模型使用因果运动基准与积分残差，仍为未训练 seed7，真实优化步骤为 0；本批已停止，未启动全量采集/长训练。旧 v1 浮点异常未逐一复现，新 v2 统一角度计算并保留严格校验。见[修复与结果](structured_driver_fix_2026_09_15.md)；本次 GitHub 发布包含修复、测试与验收证据；下方保留历史阶段记录。

**最新真实执行（09-15，Stage B）：** 先读[20 帧验收及有限短启动结果](structured_driver_acceptance_2026_09_15.md)和[机器可读证据](evidence/structured_driver_acceptance_2026_09_15/summary.json)。初始/复核/三轮后共 400 个固定任务全部保留；短启动累计 24 步，最终 0/20 初始轨迹合法、0 次远端请求，按 3 轮上限停止。没有启动正式长训练，没有共享四条件驾驶能力或方法收益结论；初始间歇性一致性错误未定位。此次只新增运行记录与文档，生产代码/冻结规格未修改，未提交/推送。下方为此前审查快照，不能用历史测试 PASS 代替此次真实启动结果。

**当前审查批次（09-15，Stage A）：** [要求核验](review_9_15_1_response.md)、[实施记录](driver_readiness_stage_a_2026_09_15.md)、[准备规格](structured_driver_readiness_2026_09_15.md)、[批准计划](superpowers/plans/2026-09-15-driver-readiness.md)及[独立审查/验证证据](evidence/driver_readiness_stage_a_2026_09_15/README.md)。四项和整批审查完成，完整轻量346/346、模型环境448/448通过。准备包不是真实训练/集成完成结果；本批不自动推送GitHub。 本批已同步本地main，尚未推送GitHub。

本批重点：全部实际请求决策的计费与未知费用；真实receipt-acquired和receiver-derived分别统计，direct字段以真实tensor location/mask为准；v1兼容、v2所选阶段监督/固定帧条件权重、严格失败分母/验证选模/精确恢复；3095帧既有因果索引与录制组、20帧固定验收、单轮总预算、四条件诊断入口和未执行边界。普通数值驾驶网络与本批工程准备均不包装为ToolV2X创新。

**当前审查准备（09-15，数值驾驶分支）：** 先读 [实现记录](structured_driver_implementation_2026_09_15.md)、[源码映射](structured_driver_source_mapping_2026_09_14.md)、[计划](superpowers/plans/2026-09-14-structured-driver.md) 和 [审查记录](structured_driver_review_2026_09_15.md)。四项实现、独立审查与修复复审完成；轻量 322/322、本地 main 完整模型环境 416/416 通过。代码已同步本地 main，尚未推送 GitHub。以下旧条目是当时快照，不代表新分支已经训练或执行过真实数据。

新分支审查重点：

- `structured_inputs.py` 的共同坐标、源内实体身份、歧义/远端独有目标、合法 history 和 receipt/派生/实际入模依赖。
- `structured_driver.py` 的位置历史和 F 多模态实际入网、共享数值头、真实 prior、mask 和同信息等价。
- 共用 episode/control/query/evaluation 的新版本分支、真实反馈、相同证据对照、单轮委托、全部成本和失败保留。
- 数值监督的独立标签、物理录制隔离、渐增证据/同证据修订、完整可恢复状态；禁止 target-as-prior。
- 标准关联/融合/数值头是共同基础；新机制收益、闭环表现和与论文误差直接比较均尚未成立。

只读审查可运行资源无关检查；模型环境测试仅做既定合成/归档回归。不要自动启动训练、真实模型生成或新采集。

**当前审查批次（09-14，共同 receiver 轮询与两帧实际对照）：** 先读 [实现说明](receiver_round_robin_implementation_2026_09_14.md)、[真实结果](receiver_round_robin_smoke_2026_09_14.md) 和 [批准的执行范围](superpowers/plans/2026-09-14-receiver-round-robin.md)。变更仅为共享 receiver 可选版本、稳定目标轮询、原 GoT 版本校验及对应测试/审计 helper 复用；旧 v1 默认保留。轻量 302 项、完整模型环境 358 项通过，冻结两帧旧/新 receiver 共 12 任务与 24 次真实 GoT 完成。请核对新 τ1→实际第二请求→provider 返回→最终 Z 与轨迹、所有生成成本、固定预算/共同规则和失败保留；不要把两帧诊断策略当成训练后的 ToolV2X 或公平 strong one-shot 效果试验。首次输入根目录失败与有效运行分目录保存，未训练或扩帧。本批尚未推送；下方审查文字是历史状态。

**当前审查批次（09-14，9-13-3，本地）：** 先读 [本批要求](9-13-3.md)、[修复与审计回复](review_9_13_3_response.md) 和 [admission 明细](t9_admission_audit_2026_09_13.md)。A1/A2 修复原始 role 与真实方案/标签监督绑定；B 只读重放已有六任务的 tokenizer/admission，receiver 算法不变。完整轻量 300 项与 CPU 合成契约 10 项通过，没有实际策略拟合、GoT/MTR 新执行或扩帧；本批尚未推送。下方 T9 准备和真实联调现已发布到 main，T8 的 271 项/尚缺接口等均为历史快照。

```text
请只读审查 9-13-3 本批修改，不启动训练、模型生成或新采集。
核对 bundle 原始 selected_index/task 的 sample、physical recording、role、fold 是否在 normalization/optimizer 前验证；核对 alternating target 是否从实际 source/terminal 方案、独立 labels 和 frozen utility 复算，保留 failure/STOP/增量成本。
核对 admission CSV 的请求来源阶段与返回后可见阶段、provider rank/field ref/context、实际与模拟 token 成本和预算，以及是否与旧 T9 保存的 Z/prompt 完全对应。
运行 python scripts/check_review.py；CPU 合成组及原日志见本批回复。区分合成拟合测试、token 模拟与真实研究效果。receiver v2 仅候选，不在本批实现；一般边界问题做最小修复，不据此扩采集、重建缓存或增加训练。
```

**本地下一批（T9，尚未推送）：** [准备记录](t9_preparation_2026_09_13.md) 对应 `bundle_data.py`、`method_run_spec.py` 和实际入口/成本/绑定补充。独立复审已完成，真实模型/分组策略训练与方法效果仍未执行。下面的 271 项及“尚缺接口”描述专指已发布 T8 快照。

**09-13 审查快照：T6 修复＋T7＋T8。** 先读 [9-12-1](9-12-1.md)、[9-12-2](9-12-2.md)、[9-13-2](9-13-2.md) 及 [T6 修复](t6_review_fixes_2026_09_13.md)、[T7 实施](t7_implementation_2026_09_13.md)、[T8 实施](t8_implementation_2026_09_13.md)。方法与因果规格以材料一为主，材料二约束 Tool 语义。T1–T8 的模块和合成契约已实现；真实方法训练/rollout 尚未执行。

```text
请只读审查这次 T6 修复、T7 分支监督和 T8 价值模块，不修改代码、不启动训练或真实模型推理。
重点追踪 src/planning/{method_episode,method_controls,query_data,query_value}.py、src/tools/{vehicle,control_bundle}.py 和对应测试：
1. P 无 MTR、F 完整 context 后排序；实际回执去重与 acquired/derived/admitted 分离，旧 v1 保留。
2. 第一返回、driver 修订、第二请求/STOP 的真实因果关系；不能把多一次生成本身当机制收益。
3. first 目标使用按物理录制折隔离的冻结续策略；教师具体 fit/step、规范化和外层留出隔离；终态与增量成本真实绑定。
4. ordinary MLP 的在线输入、动作 mask、STOP=0、首末步共同训练与精确 checkpoint/resume。
5. single-round bundle 的预算/真实 provider 绑定、独立 STOP 基准，以及 frozen feedback、same-evidence 对照和全部 driver 费用。
运行 python scripts/check_review.py（当前 271 项）；需要 torch 的 T8 CPU 契约组见实施记录。不要将测试替身或旧 32 帧效果混作新方法结果。
区分阻断方法有效性的实现缺陷、未验证研究假设和已声明后置内容。一般边界问题给最小修复，不据此建议重建缓存、增加模型训练或暂停全部推进。
```

当前尚缺正式运行命令的价值策略选择、独立 bundle 分支监督采集及真实有限验证，这些属于下一批 T9 接入。已上传历史证据保持不变。以下入口及数值是早期发布记录。

**最新发布范围：** 先读 [09-12 更新说明](github_update_2026_09_12.md)、[第一轮评价](epoch01_quick_evaluation_2026_09_12.md) 和 [主线候选](mainline_innovation_search_2026_09_12.md)。当前训练已按用户要求停止；160 条实际轨迹与离线标签已随精选证据上传，可运行更新说明中的标准库复算。候选机制尚未实现，不把研究报告当现有算法。下文保留历史审查入口和核验记录。

当前审查重点为 [完整框架实现与真实联调](framework_baseline_results.md)，发布范围见 [本轮更新](github_update_framework_2026_09_11.md)。新增 `planning/context.py`、`episode.py`、`run_framework.py`、`train_driver.py`、`evaluation/framework.py` 与两项 `scripts/prepare_framework_training.py` / `run_framework_baseline.py` 入口，连通真实查询、更新/停止、统一驾驶、训练恢复与评价。GitHub 的进度是带时间的发布快照；之后本机核对发现原全量准备中断，当前在新目录续接，见 [9-11-2 核实与恢复记录](review_9_11_2_response.md)。本轮本地修改尚未再次发布。

本轮精选归档包含全部 20 次验证生成及其原始任务、4 条独立离线标签、2 个训练帧的提前停止实例。`check_review.py` 能在没有模型和完整数据的环境里重建提示、重算 ADE/FDE 和实际通信字节，并核对退化答案没有被删除。它不替代 GPU 训练、全量评价或学习查询机制检验。原始任务索引包含 100 项，只有上述 22 项完整 JSON 被发布；未上传的特征、其他任务和重复源码快照仍需本机资源。

日期：2026-09-10。目标仓库：HikiMaji/ToolV2X。首次仓库用于审查实现、协议和训练准备；当前没有正式方法收益结论。

2026-09-11 本地补充：原 MTR 因果适配已完成，见 [实验结果](mtr_adaptation_results.md) 和 [Q8/Q9 质量诊断](planning_quality.md)。新增审查入口为 `src/prediction/{supervision,prepare_mtr,train_mtr}.py`、`src/evaluation/` 及 `tests/verify_mtr_*.py`。重点区分离线 GT 监督与在线因果输入、相同目标的原始/适配对照、验证选模与独立测试、完整/ROI 训练设置与真正的 P/F 方法收益；最新大体积产物和权重仍在本机。

最新补充：MTR 六组等预算训练及冻结选择见 [mtr_stability_results.md](mtr_stability_results.md)，驾驶初始化/解码真实接入见 [driving_decoder_results.md](driving_decoder_results.md)。`check_training.py` 与原 builder 的可训练 LoRA 路径已完成四组合一次真实更新、独立重载与生成，见 [训练入口结果](driving_training_readiness_results.md)；这些检查与正式适配必须分别核实。权重和完整缓存仍留在工作站，精选文件范围见 [本次更新说明](github_update_2026_09_11.md)。

## 审查入口

| 关注点 | 当前代码 |
| --- | --- |
| 当前/过去 Ego 特征、输入字段白名单、回答解析 | `src/planning/inputs.py` |
| 原 MTR 22 通道输入、缺失历史、完整上下文与预测输出 | `src/prediction/cmp_adapter.py`、`vendor/cmp_mtr/` |
| P/F 请求与响应、解码、P 本地重算、来源与模式保留 | `src/tools/vehicle.py` |
| 原 projector、上下文预算、原 7B 的 Q8→Q9 / direct | `src/planning/v2vgot.py`、`vendor/v2vgot_llava/llava/` |
| 固定四动作执行和访问/通信账本 | `src/planning/run_connection.py` |
| 离线标签、训练样本、实际生成的 Q8 父上下文 | `src/planning/adaptation_data.py` |
| 原监督前向、特征/提示损失屏蔽、一次真实参数更新检查 | `src/planning/check_adaptation.py`、`check_training.py` |
| 同信息编码对照 | `src/planning/compare_evidence.py` |
| 五策略实际查询、证据更新、继续/STOP、部分失败账本 | `src/planning/episode.py`、`run_framework.py` |
| 本车块固定、已购邻车块、训练与生成共用提示 | `src/planning/context.py`、`paired_inputs.py` |
| 完整监督导出、录制级验证、检查点恢复 | `scripts/prepare_framework_training.py`、`src/planning/train_driver.py` |
| 预期任务覆盖、失败分母、轨迹与总调用成本 | `src/evaluation/framework.py` |
| 从代码副本顺序执行完整单配置流程 | `scripts/run_framework_baseline.py` |

`src/probe`、`src/oracle` 和旧 CMP 四配置脚本保留历史实现。不要把这些代码运行过等同于当前主线已验证，也不要仅凭文件夹名称删除当前仍引用的校验函数。`vendor/cmp_mtr/reference/` 中原 dataset 只供参考测试；正式在线适配器不调用该 GT 驱动 dataset。

## 上传的运行证据

- `outputs/protocol_audit/`：录制级 split manifest、帧清单和早期协议核查。物理 train/test 名称不能代替研究 train/validation/test。
- `outputs/framework_connection_v3/`：一个验证决策帧的原模型 JSON 四动作接入；30 个邻车目标的 P 本地重算与 F 等价。
- `outputs/framework_compact_v1/`：同一验证帧扩充目标的紧凑表示运行；P 的原 Q9 输出失败仍保留。
- `outputs/evidence_comparison_v1/`：相同目标集合的真实紧凑格式生成，以及单独的完整文本 token 统计。
- `outputs/framework_compact_train_v1/`：一个真实训练帧的四动作记录。
- `outputs/adaptation_data_v1/`：3027/108 帧准备摘要、8 条已物化监督样本和历史独立复核报告；完整索引/标签仍在工作站。
- `outputs/adaptation_forward_v1/forward_check.json`：8 次原模型监督前向的历史记录，优化器步数为 0。
- `outputs/logs/`：明确挑选的历史复核脚本和测试日志。

这些文件保持原内容。它们不包含完整重放所需的点云特征、窗口归档或当时源码快照。`scripts/check_review.py` 在当前仓库重算可独立检查的事实；旧复核脚本中的绝对路径、源码快照一致性检查只适用于原工作站及当时版本。

## 可以交给审查者的任务

```text
请对整个 ToolV2X 仓库做只读代码审查。先读 README.md、docs/framework_baseline_results.md、docs/github_update_framework_2026_09_11.md 和 docs/upstream_sources.md，再追踪当前规划/工具/离线监督路径以及实际调用的 vendor 源码。

优先检查：
1. 时间 t 因果性、查询前远端信息隔离、GT 标签与在线输入分离、录制级数据划分。
2. P/F 同信息对照、完整上下文与 ROI 顺序、坐标/时间、远端独有目标、多模态和实际通信成本。
3. q8_q9 模式的真实生成父回答、direct 模式无 Q8 输入且不能由缺失父回答自动切换、格式失败分母、上下文截断/舍入、监督损失掩码与原模型真实接入。
4. 规则是否只依赖本车与实际已购证据、第二次请求是否由真实第一步结果决定、调用/接收失败是否保留已付成本及任务身份、提前停止是否保持零额外读取。
5. 五种策略是否共用本车输入和训练/生成提示、保存恢复是否包含可训练参数/优化器/随机状态、训练验证是否按物理录制组隔离、是否把小样本联调误称为完整适配。
6. 评价是否核对完成标志和预期任务集合、缺失与格式错误是否被隐去、总成本是否包含两次调用及接收处理。区分可解析轨迹、物理合理性、驾驶模仿误差和最终方法收益。

运行 python scripts/check_review.py；环境允许时再按 README 运行完整集成测试，并明确哪些未运行。
不要只复述报告或把设计文档视为已完成实现。每条问题给出具体触发条件、文件位置、可观察后果和最小验证办法；区分实现缺陷、未验证假设与明确后置工作。不要将可解析轨迹或有限 loss 视为方法有效。此任务先报告发现，不修改代码、不启动训练。
```

## 本次仓库准备带来的变化

只调整核心外部资源路径、原源码/配置的仓库内位置和审查测试入口；P/F 定义、预测网络参数、提示选择规则和训练目标未调整。V2V-GoT LLaVA 与原标签文件从本机逐文件复制，CMP 原配置和 intention points 也保持内容一致。原目录没有在本轮修改。

轻量环境仅安装 `requirements-review.txt`。完整集成仍使用原模型环境和本机资源。本次不重新执行 7B 生成、不更新参数、不把旧快照复核结果转记到新代码上。

## 本次准备的核验

修改前 58 项测试通过；加入资源路径和归档证据检查后，完整本机集成 62 项通过。从实际 Git 暂存内容导出的副本，在只安装 NumPy 1.24.2 / SciPy 1.10.1、未安装 PyTorch/Transformers 且外部资源路径不可用的隔离环境中，51 项轻量检查通过。

另外，用随仓库提供的 MTR 配置/辅助资源和本机原权重重算原验证帧的 21 个自车目标；目标、状态、预测、分数、局部 GMM 和 model-used 标记与原归档数组逐项完全一致。这是路径/打包改动回归检查，未评价预测质量。详细记录见 [github_preparation_validation.json](github_preparation_validation.json)。
