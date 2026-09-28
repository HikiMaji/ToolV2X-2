**2026-09-28（审计修复已实现）：** 坐标/actor原点、start→decision时间、完整多目标context、来源与Subset样本身份已修正；v2 adapter改为相对空证据残差及LeakyReLU，旧检查点明确拒绝。已有检测完成两路线22个decision的AB3DMOT/P准备与栅格复算，route28全部当前P栅格为空（6帧无第三方，5帧第三方在范围外），不再把receiver本车作为P。无真实数据训练/新检测/MTR/planner/闭环运行，合成优化仅用于单元回归；未证明协作收益。最终轻量447项（10跳过）零失败，模型10/10、独立复核8/8通过。验证和边界见[修复记录](codriving_native_fix_2026_09_28.md)。

**2026-09-28（P adapter 审计更正，优先于下方历史）：** 已确认坐标与时间绑定错误：P/F 比官方 planner 时刻早4帧/0.8s，route05_28 的11个 P anchors 正确还原后全是 receiver 本车（平均距离0.0784m）。已保存 P adapter 在14个检查样本上 evidence body全零，P清零或换帧均不改变修正输出；旧route11改善不能归因于P，跨route恶化也不能据此判定P泛化。完整peer-context F、同容量empty-P及独立split仍缺。保留CoDriving底座与全部原失败产物；本轮仅审计、冻结adapter前向和更正报告，无实现修复或新训练。见[审计证据与修复顺序](codriving_input_audit_2026_09_28.md)。

**2026-09-27（最小有效规划通路）：** 保留官方 CoDriving 主干，新增零初始化 `ToolEvidencePlanner` residual adapter；无 sidecar 时与 Single planner 精确等价，模型环境 adapter 8/8、官方 checkpoint 前向零残差等价且非零证据可改变输出；route11真实官方planner batch已接入，零残差delta=0.0；base冻结并保持eval；20步adapter短训L1 0.484042→0.312683；route11多窗口诊断held-out ADE/FDE 0.1164/0.3218 vs base 0.1513/0.3836，尚非独立论文结果；同预算消融为 Ego 0.1513/0.3836、P 0.1085/0.2958、F-CV 0.1174/0.3140、F-MTR 0.1151/0.3171、PF 0.1164/0.3218；route11训练的P adapter在route05_28跨recording恶化至0.7277/1.7142（base 0.5108/1.1794）。route11 两车连续21帧独立LiDAR检测已跑通，source/receiver ego过滤后形成真实第三方P历史；冻结CMP MTR的真实F与同锚点F-CV配对探针已完成（一个目标F-MTR与CV差异1857像素，另一个目标越界保留为无效）；尚未训练 adapter，不能宣称P/F改善ADE/FDE。完整资源独立回归414项通过（跳过8项无torch）。见[适配与真实探针](codriving_tool_effective_adapter_2026_09_27.md)。

**2026-09-27（后续批）：原生v3 P/F协议完成契约验证。** 原生history/十点时间轴、付费motion anchor、F-only→F-CV、receipt/ledger兼容已实现；406项资源独立测试通过。旧v1接口不变。尚无真实Town05 P/F整链、MTR原生历史适配或planner输入消费，无训练。见[本批记录](native_task_2026_09_27.md)。

**2026-09-27：CoDriving Stage 2 续接。** 已购ledger→BEV规范记录接口完成，94项受影响回归通过；Town05-11采集配置及本车运动支持0.2秒/保存帧。旧wire历史固定0.1秒、F无速度锚点仍需版本化适配；真实CoDriving P/F链及planner消费未完成。无训练/模型运行。见[本批记录](codriving_ledger_bev_2026_09_27.md)。

**09-26 CoDriving Stage2表示层已实现：** 已核对原版公开子集3560样本结果；新增纯数据P五通道、top-1 F及同目标F-CV，192×96/0.25m同网格和10点batch侧输入。11项定向及389项资源独立通过，四组原栅格函数几何核对通过。planner主干/原6通道输入不改；新增sidecar尚不被原forward消费，真实receipt→CARLA历史→MTR连接和训练未完成。10点对应物理秒数需绑定采集时标，不能直接继承旧3s wire。见[Stage2记录](codriving_pf_bev_stage2_2026_09_26.md)。

**09-24 横向修复B完成有限诊断：** 空间前视/静止参考切向已实现，S2静止转向0.8→0.000182；S2/L2横向、航向和走廊门槛通过，命令交付420/420对应、无碰撞。完整两项仍FAIL：沿程最大2.128/3.474m；L2原生速率与位置差分差0.0654>0.05m/s。40定向/378资源独立通过，纵向/PID/参考/评分保持；各场景一次，无训练/RP/PF。服务清理，未提交推送。下一项为纵向和速度反馈口径诊断。见[完整结果](backbone_lateral_b_results_2026_09_24.md)。

**09-23 修复A已实测：** 控制命令改同步确认→单tick→回显绑定，同一S2的150/150转换通过独立审计，float32逐项错位8→0。驾驶仍FAIL：最大沿程误差2.0565m、加速度7.2294m/s²，静止大转向不变；不宣称性能提升。36定向/378资源独立回归通过，初始化20/1/9、PID、参考及评分冻结；只跑一次S2，服务清理，无RP/PF/训练，未提交推送。下一层为静止/低速横向参考语义修复B。见[实施与结果](backbone_command_sync_results_2026_09_23.md)。

**09-23 S2原因复核新增发现：** 150次纵向PID计算与已存状态重算全部吻合（最大差2.98e-8），但next-frame控制回显有7处超1e-6错位，可匹配再前一帧；官方apply_control为异步，建议先建立同步提交/单tick确认。另确认停车近零目标距→约77度方向误差、速度环无沿程位置反馈；匀速40tick有12次油门/制动切换。仅离线诊断，无修复实跑，不能将全部误差归因Kp。见[原因与修复顺序](tracking_failure_diagnosis_2026_09_23.md)。

**09-23 初始化v2通过，原PID首格跟踪FAIL：** 用户批准20/1/9修订后已实施并实跑；真实手动一挡→自动9tick保持一挡、独立初始化复算PASS。随后S2完成150次PID/151帧，无碰撞，但沿程最大误差2.10m、加速度峰值6.19m/s²，按首格失败停批，其他七格未运行。静止近零目标距导致大转向已定位，纵向失配尚未完全辨识；两项float32审计边界误报另记，仍有7项真实失败。32项定向/378项资源独立检查通过，未调PID/阈值、未接RP/PF或训练、未提交推送，服务清理。见[实施与结果](backbone_initialization_v2_results_2026_09_23.md)。

**09-23 初始化修订待审阅：** 已独立复算现有30帧，确认全为gear=0、尚无PID跟踪格；官方源码支持显式手动选挡后交回自动的候选。新稿建议20 tick静置+1 tick手动一挡+9 tick自动读回，总3s、零油门，保留PID/参考/阈值。仅新增审阅稿和离线复算证据，未实施或实跑；接续已有RP+CARLA组合，不重复选型。见[初始化审阅稿](backbone_initialization_review_2026_09_23.md)。

**09-23 CARLA 0.9.15 已安装并实启：** 完整检查用户下载包后，真实服务/客户端、固定地图、车辆几何和8条参考预检通过；S2初始化返回挡位0，未达到一挡要求，按规则停在 `PREFLIGHT_FAIL / gear_not_one`。执行了静止标定和初始化，尚无有效PID控制/跟踪格，不能判跟踪能力通过或失败。本批只修正启动连接时机及专属进程组清理，定向25项、资源独立378项通过；未调PID/训练/接RP或PF。全部尝试已保留、服务已清理；下一步先审阅挂挡初始化协议修订，不重复本批。见[执行记录与停止点](backbone_tracking_gate_run_2026_09_23.md)。下条“服务端缺失”为09-22准备时状态，已被本条更新。

**09-22 共同底座控制门槛准备：** 用户确认设计后，已实现 CARLA 0.9.15 独立给定轨迹跟踪入口、8条解析参考及落盘复算器；定向24项通过、名义几何静态8/8通过。Python3.10/同版客户端已安装，但本机缺8.39GB的0.9.15服务端包，真实跟踪为 PREPARED_NOT_EXECUTED，未训练/调PID/启动CARLA。RP/F接入仍在控制门槛之后；原工作区修改与失败记录保留。见[实施、验证与资源缺口](backbone_tracking_gate_implementation_2026_09_22.md)。

**09-22 用户要求重新设计，停止试改：** 新PDM项目适配两批共六臂均FAIL，不能作为主实验底座；378项轻量/33项定向测试PASS只证明代码契约。新候选已隔离到scripts/probe_pdm_project_adapter.py，原probe精确恢复v4；旧v4仍有起步/稳定停车限制。当前停止实现与新增实跑，先厘清参考轨迹、内部执行预测和CARLA控制的职责，形成完整适配/替换判断再由用户审阅。不能再局部改动后用运行结果追认设计。见[设计重置与停止点](pdm_adapter_design_reset_2026_09_22.md)。全部失败产物保留、无训练/PF、未提交推送、运行进程已清理。

**09-22 v3诊断与v4有限复测：** 320次PDM原始重放精确复现，另240次固定状态干预支持纵向PID配置是原停走波动的主要因素。仅Kp从1.0降至0.2，空路/前车均通过原门槛；前车末速0.4061m/s、间距2.721m，近零停后再起步4→0。但起步加速度9.275m/s²，末两秒并未持续低于0.5m/s，新增诊断FAIL；仍不能称稳定停车/底座全面通过。未训练/接P/F，已按一轮上限停止。下一项诊断起步与低速转角/全零评分。见[完整诊断与对照](pdm_closedloop_diagnosis_2026_09_22.md)。原工作区修改及v1–v4均保留，未提交/推送。

**09-22 本车闭环验收：** 原生单车LiDAR→原V2Xverse检测→AB3DMOT→原PDM→原CARLA PID已真实闭环。修正后空路行驶21.20m、无碰撞；前车臂最小间距2.17m，但末速0.5033m/s且存在停走波动，预声明停车验收FAIL。不能宣称底座全面通过。未训练/未接P/F；下一项先诊断已保存末段，不扩大训练。见[完整记录](pdm_closedloop_2026_09_22.md)。下方为此前阶段快照。

**09-22 本车真实链路：** 原生双车LiDAR各30帧已完成独立检测、本车排除、AB3DMOT跟踪和本车PDM输入检查；26/30时刻对移除障碍诊断有响应。尚未做P/F协作或闭环驾驶，未训练。见[结果和限制](lidar_tracking_pdm_2026_09_22.md)。

**09-22 检测接入试验：** V2Xverse官方单车预训练检测器已在双车各5帧真实点云上独立运行，严格加载194项参数；发现疑似本车框，尚未做跟踪、PDM障碍接入或协作效果评估。零训练。见[结果与边界](v2xverse_detector_2026_09_22.md)。

**09-22 更新：** 原PDM核心已部分接入；CARLA 0.9.10.1已安装，Town03与双车同帧LiDAR实测可用，真实地图/标定到PDM数值检查通过。尚未完成检测/MTR、完整方法循环或闭环效果验收，未训练。见[运行记录](carla_runtime_2026_09_22.md)。

# ToolV2X 项目状态（给后续 agent 的交接文档）

**最新选型（09-19，研究完成、接入未执行）：** 针对研究点一，推荐PDM-Closed＋V2Xverse纯双车作为主PLAN/环境，CoDriving原规划器作为学习式备选。已核对官方源码链和公开资源，实读两车4个LiDAR/measurement小样本；未执行检测、预测、PLAN或训练。该建议涉及主数据与评价口径调整，尚未实际迁移。CARLA地图/时标适配、MTR跨域质量和多模式F接入仍需验收，不能宣称底座已经有效。下一项是限定规模的原PDM接入与共同驾驶器验收，不恢复原配置长训练。详见[选型报告](backbone_selection_2026_09_19.md)与[资料核验](evidence/backbone_selection_2026_09_19/README.md)。下方“尚待选型”等为此前快照。

**当前方向（09-19，研究点一独立投稿）：** 以用户指定的 [9-19.md](9-19.md) 为最新设计，只推进有效协作，不推进研究点二。主线为LLM请求决策＋共享数值PLAN＋真实P/F反馈；现有自建driver降为可保留的诊断/消融候选，主PLAN尚待选型和效果验收。已完成新方案与代码的范围核对，发现STOP、首步continuation/oracle、导航与多模态输入、对照归因需明确。下一步交付可靠PLAN的具体复用/接入方案，不继续原配置长训练。见 [投稿范围与证据计划](research_point_one_paper_scope_2026_09_19.md)。09-18目标质量脚本运行未完成、没有结果；本轮无代码改动或新实验。下文为各批次历史状态。

**当前状态（09-16，一次协作诊断已完成）：** 39个完整开发帧、156个真实归档任务、500/0/3200冻结检查点完成2460次模型前向（192秒），3042组六点输出独立复算通过，62项定向测试通过。主检查点收到P/F/PF后平均轨迹位移仅0.061/1.223/0.884毫米；同源内容比较排除完全重复，未证明远端更准。直接换回恒速基底未改善，故未实施该修复。生产驾驶器与P/F不变，零训练/新工具调用；后续LLM调度主方案已确认但尚未实现。下一项聚焦驾驶器证据使用与相关目标质量，不能继续相同训练或将本批当方法收益。见[诊断报告](single_cooperation_diagnostic_2026_09_16.md)与[可复查证据](evidence/single_cooperation_diagnostic_2026_09_16/README.md)。

**最新研究（09-15，导航接入）：** 已核对参考源码、现有 3,095 条准备记录及 3 条原生导航样本；建议局部路线目标点通过普通 MLP token 接入共同驾驶器。导航尚未实现或训练，先完成来源/坐标绑定；小样本训练退化排查后置。见[导航方案与边界](navigation_research_2026_09_15.md)。本次发布包含验收修复、训练预检/结果和导航研究的代码或文档及精简证据；下方未推送等表述保留各历史阶段状态。

**最新训练结果（09-15，数值 v2 20 轮）：** 原 16 训练帧/4 开发帧已完成 1280 次更新并独立核验，已停止。开发 got_prefix_L2_avg 从初始 0.397169 米变为最终 0.528012 米，选模仍为第 0 步；无全量扩帧或新远端采集，不支持方法收益结论。见[训练结果与证据](structured_driver_20ep_fit_2026_09_15.md)。

**最新训练（09-15，数值v2一轮小批适配）：** 现有20帧四条件归档完成1轮/64次更新，128条训练实际覆盖Ego/P/F/PF，32条既有开发阶段行单独验证；0/64步完整权重保留，选模为第0步。模型和原任务独立核验完成，已停止，不自动追加轮次或全量采集。此为小样本固定证据适配，不是ToolV2X方法收益验证。见[结果与证据](structured_driver_small_fit_2026_09_15.md)。未提交/推送。

**最新预检（09-15，数值 v2 真实小批训练）：** 20帧/80任务导出160阶段行，128训练/32开发验证，8/2录制隔离；连续4步与2+2步恢复均完成，两支线合计8次更新；检查点参数/优化器/RNG精确加载，但独立CUDA支线在中断前已有微小参数差，不宣称逐位续跑对照通过。真实P历史/F预测梯度非零，所选阶段32/32合法，但4步开发误差未改善，选模仍为0步。归档与周期检查点的正式规模超出现有存储，先调整存储表示和训练日程；未全量采集/长训、未提交推送。见[预检结果与后续边界](structured_training_preflight_2026_09_15.md)。

**最新修正（09-15，排除原因审计）：** 新派生字段明确区分 ego 过滤、实体容量和预测集合容量，并分别记录间接依赖与完全排除。80 个旧任务、160 个阶段复核确认原有审计字段和任务文件不变；补充 P→F / F→P 的角色转换及 prior 依赖回归。见[实现与验证](admission_reason_fix_2026_09_15.md)。本批无训练、新生成或重新采集，未提交/推送。

**最新执行（09-15，数值驾驶 v2 修复）：** 同一预声明 20 帧初始轨迹 20/20 合法，Ego/P/F/PF 共 80/80 任务及归档审计通过；实际 160 次数值驾驶、40 P＋40 F 请求，全部 60 个协作任务有远端字段入模。完整轻量 347 项、受影响模型/交互 83 项通过。新模型使用因果运动基准与积分残差，仍为未训练 seed7，真实优化步骤为 0；本批已停止，未启动全量采集/长训练。旧 v1 浮点异常未逐一复现，新 v2 统一角度计算并保留严格校验。见[修复与结果](structured_driver_fix_2026_09_15.md)；本次 GitHub 发布包含修复、测试与验收证据；下方保留历史阶段记录。

**2026-09-15 Stage B 已按上限停止：** 已执行冻结 20 帧的初始/复核及三轮短启动后验收，共 400 个固定任务；实际短启动为一条训练谱系的 3 轮/24 步，完整检查点保留。最后 0/20 初始轨迹合法、0 次 P/F 请求，尚未通过共享四条件驾驶基础的采集门槛。首批及第一次预训练校验有间歇性张量重建错误，根因未定位；后续严格校验通过不等于修复。未修改生产代码、未启动正式长训练或3095帧全量采集、未提交/推送。当前应读[结果、证据与建议](structured_driver_acceptance_2026_09_15.md)，不要自动续到第4轮或20轮正式训练；下方 Stage A 未执行措辞是历史快照。

**2026-09-15 Stage A完成：** 成本、证据审计、v2训练/验证/恢复和四条件准备包均已完成，独立整批审查无待修复项；完整轻量346/346、模型环境448/448通过。见[实施记录](driver_readiness_stage_a_2026_09_15.md)和[准备规格](structured_driver_readiness_2026_09_15.md)。本批没有真实训练、采集、模型生成或新方法实验；B–D尚未执行，不自动推送。下面的旧训练启动和322/416等均为原批次快照。 本批已同步本地main，尚未推送GitHub。

**当前批次（09-15，结构化数值驾驶基础）：** 输入、网络、交互、监督/恢复四项实现、独立审查及修复复审全部完成；轻量 322/322、本地 main 完整模型环境 416/416 通过。已同步本地 main，尚未推送 GitHub。已下载小于 100 MB 的官方 UniV2X/VAD 参考源码；本批没有真实数据训练、新模型生成或方法效果实验。最新状态以 [实现记录](structured_driver_implementation_2026_09_15.md) 和 [审查记录](structured_driver_review_2026_09_15.md) 为准。下方旧训练/实验条目均是带日期的历史记录。

**最新完成（09-14，共同 receiver v2 + 原两帧联调）：** 用户批准两步一起做。已新增 opt-in `toolv2x_receiver_v2` 的 source/track 轮询；v1 默认、预算、P/F/ledger/策略不变。冻结 GoT epoch01/MTR epoch09，在 g5526/g7007 对两版本各跑 Ego/alternating/one_shot，修正数据根环境后 12/12 任务完成、24 次实际 GoT。旧 v1 全阶段提示与答案精确复现旧 T9；v2 两帧 P 后修订均影响实际第二次 F(change)，返回由新请求真实执行。g5526 工具臂误差增大，g7007 减小但仍差于 Ego，不能宣称序贯或 receiver 收益。轻量 302/302、完整模型环境 358/358、定向与独立原始产物核验通过。第一次错误数据根造成 12 次输入失败、0 GoT/0响应，保留在新运行 v1；有效运行 v2 保留完整成本和因果链。见 [实现说明](receiver_round_robin_implementation_2026_09_14.md) 与 [实际结果](receiver_round_robin_smoke_2026_09_14.md)。没有训练、扩帧、分支枚举、缓存重建或自动推送，停在本批。

**最新完成（09-14，9-13-3）：** A1/A2 已复现并修复；bundle 公开训练入口恢复原始 sample/recording/role/fold 并在拟合前拒绝 validation，alternating 监督从实际 prefix/terminal 方案、独立标签及原 utility 重新计算。完整轻量 300/300、CPU 合成契约 10/10、旧 160 条回答复算通过。B 使用已有两帧六任务，全部 12 个 plan stage 提示/token/Z 复算一致，保存 64 行 unit 明细；两臂最终都被 admission 压到同一目标的两份不同 context 预测。共同轮询仅作 token 模拟，多覆盖 1 个目标，未生成新轨迹。本批不改 receiver、不实际训练/采集/推理、不重建缓存，完成后停止。见 [完整回复](review_9_13_3_response.md) 与 [逐 unit 审计](t9_admission_audit_2026_09_13.md)。本批尚未推送；下面 T9 准备和真实联调两批已在此前更新发布到 main，旧“未推送”保留当时含义。

**最新批次（09-13，T9 两帧真实联调）：** 已完成 g5526/g7007 各 Ego、诊断交替与诊断单轮，6/6 真实任务成功、12/12 GoT 输出有效；完整模型环境回归 345/345，逐任务评价与独立审计一致。交替两帧均真实 P→GoT 修订→F(change)，单轮在一个 bundle 内 P→条件 F(current)；无训练、无价值拟合、无扩帧或缓存重建。第一帧改善、第二帧变差；两种调用轨迹最终投影到完全相同的 GoT 提示与轨迹，接收端预算只保留同一目标的两份不同 context 预测。下一步先检查已保存证据的 admission，不自动训练或采集。见 [T9 真实联调报告](t9_real_smoke_2026_09_13.md)。T9 准备已本地提交，本批未推送 GitHub，当前停止在本次联调。下文“尚未提交／未真实执行”等是此前批次状态。

**最新批次（09-13，T9 准备）：** 已发布 T6 审查修复＋T7＋T8 到 `origin/main`。本地新增显式价值 checkpoint 入口、完整冻结运行规格、独立单轮真实首返回分叉采集及原始终态监督核验，完整轻量 290/290、专门 CPU 10/10、独立复审 18/18 通过；本批 T9 共 17 个文件已同步本地 main，尚未提交/推送。只使用合成契约/小型 CPU 测试，没有真实 GoT/MTR 执行、真实分支/策略训练或缓存重建；不宣称完成 T9 效果验证。详见 [T9 准备记录](t9_preparation_2026_09_13.md)。下文“未推送/停在 T8”等保留各批次当时含义。

**最新执行（09-13，T8）：** 普通请求价值模块、分组末步教师、首末步共享回归及部署 callable 已完成代码和 CPU 合成验证。新增 71 维因果状态＋动作编码的小 MLP，固定 STOP=0、可行动作屏蔽、规范化/教师的物理录制隔离及完整 checkpoint/resume；独立单轮 continuation 使用发送候选和真实首返回，不能复用 alternating 标签。新增 21 项检查：完整轻量 271/271，专门 CPU 9/9；旧 160 条回答复算及 8 个 v1 AST 核对通过。补充 v2 教师具体来源、首步终态费用重绑定、实际 provider/预算绑定和共同效用/底座的训练比较。真实 branch/价值训练/strong one-shot 公平拟合均未运行，未运行 GoT/MTR、未重建缓存、未推送，停在 T8。CLI 仍为诊断入口，真实运行需显式接入 Python policy API。见 [T8 实施记录](t8_implementation_2026_09_13.md)。

**最新执行（09-13，T7）：** 合法分支采集与末步/首步监督接口已完成代码和契约验证。复用初始/首响应真实前缀、隔离兄弟服务缓存与读取审计；按真实动作绑定分支终态，离线重建教师可见状态，计算实际前缀之后的净收益。新增 22 项，完整轻量 259/259、旧 160 条回答复算与 v1 AST 核对通过，独立复审通过。初始失败保留分母；教师按物理录制折隔离，路径/加载时间不作语义身份。仅新增 `collect-method` 入口，未执行真实模型/分支采集/训练或缓存重建，停在 T7，不自动进入 T8。真实首步标签仍等待 T8 冻结末步教师。见 [T7 实施记录](t7_implementation_2026_09_13.md)。

**最新修复（09-13，9-13-2 复审）：** 已修复单轮全文摘要挤爆默认请求预算、控制计时混入 decision 保存、策略前未过滤不可支付动作三项问题。新增版本化摘要与 `per_rpc` / `episode_aggregate` 预算配置；聚合模式保留同原语上限和同 episode 总双向预算。旧无版本控制时间保留诊断、可信总计算成本标为未知。新增 11 项，完整轻量 237/237、旧 160 条回答复算通过；独立定向复审通过。未训练、未真实模型执行、未重建缓存，停在 T6 修复，不自动进入 T7。见 [修复记录](t6_review_fixes_2026_09_13.md)。下文是各批次当时记录；T6 原成本范围和单轮配置以本次修复为准。

**最新执行（09-13，T6）：** 关键对照代码已完成：冻结反馈、old/union、同证据 repeat/refinement、强单轮条件委托执行接口、共同 v2 receiver 的旧五策略与 Ego-max-context。真实首轮分支绑定实际 features 和同一 driver；refinement 从前缀预留同槽。新增 35 项轻量测试，完整 226/226、原 tokenizer/planner 契约 2/2 和旧 160 条回答复算通过。T5 已区分外部往返/内部原语及非重叠控制成本。CLI 仍为诊断策略，尚未拟合 strong one-shot/价值模块；未训练、未真实模型推理、未做新方法效果实验或缓存重建。停在 T6，不自动进入 T7。见 [T6 实施记录](t6_implementation_2026_09_13.md)。下文早期“停在 T3/T4/T5”等是当时批次记录，当前状态以本条为准。

**最新执行（09-13，T5）：** 已新增 v2 离线任务/阶段评价，累计全部 driver 尝试与非重叠的已测成本，保留缺失/失败预期分母及未知费用；有冲突的归档保留诊断、从可信均值排除。完整轻量 191 项、定向 23 项与原 160 条回答便携复算通过，旧三个 v1 评价函数保持原样。执行端仅补输入构造失败的同区间计时事件。没有训练、真实模型推理、新方法效果实验或缓存重建；停止在 T5，T6 以后未实施。成本范围明确排除未测 policy/控制/I/O/网络开销，不宣称端到端实时性。详见 [T5 实施记录](t5_implementation_2026_09_13.md)。

**最新执行（09-13，T4）：** 用户授权“继续下一步”后，已接通初始 GoT → 参数化 P/F → 实际返回 → T3 E/derived/Z → 同一 GoT 修订 → 第二请求或 STOP。新增独立 `interact`、逐阶段原子快照及已终态样本前缀复用；旧五策略和 prepare/generate 保留。18 项 T4 契约、174 项轻量审查及 5 项原 tokenizer/driver 适配回归通过；模型生成与预测只用测试替身，没有启动真实推理、训练、数据缓存重建或新方法实验。诊断策略不等于正式价值策略；T5 及以后未执行。详见 [T4 实施记录](t4_implementation_2026_09_13.md)。

最后更新：2026-09-13。

**最新实施（09-13）：T3 已完成，停在 T3。** 已实现已购 E、独立本地派生、远端回执 manifest、共同 receiver/Z、完整字段到提示位置的映射和失败账本。完整 P 增加随付费响应返回的最小上下文证明；同信息去重核对实际输入顺序/dtype、冻结 predictor 绑定及六模式数值，不能靠版本字符串。原 compact 与 v1 路径保留。轻量回归 156/156、独立针对性 77/77、新增原 tokenizer 检查通过；测试 predictor 均为契约替身，未训练、未真实 MTR/GoT 生成、未重建数据缓存。详情见 [T3 实施记录](t3_implementation_2026_09_13.md)。T4 实际驾驶修订和第二请求/STOP 尚未接通，不自动继续。

**最新修复（09-13）：复审四项 v2 边界问题已处理。** 数值数组拒绝混合 bool，请求限定 JSON 原生结构，F predictor 必需字段限定 NumPy 数组并在缓存前校验，有效历史尺寸要求为正；缺失历史零占位和合法 F 缓存保留。新增 9 项测试，针对性 52/52、轻量回归 135/135 通过，旧 v1 函数保持不变。详见 [实施记录第 6 节](t1_t2_implementation_2026_09_13.md#6-09-13-复审边界补丁)。本批只修复，不进入 T3、不重建缓存、不增加模型训练或生成；这些局部问题不构成暂停整体方法推进的理由。

**最新实施（09-13）：T1/T2 完成，按用户要求停在 T2。** 见 [实施与验证记录](t1_t2_implementation_2026_09_13.md)。已增加版本化 ExecutionSpec、current/change 确定性检索、独立 v2 P/F 服务、provider 真实返回字段回执与最终 UTF-8 报文预算；P 不执行 MTR，F 在排序前保持完整合法上下文。新增 36 项契约测试，主工作区针对性 43/43、轻量回归 126/126 通过，旧 v1 行为保留。本批没有训练、GoT 新生成或真实新方法实验；T3 的 acquired/derived/Z ledger、实际驾驶修订循环、价值模块与关键对照均未实施。后续不得因本计划存在而自动推进 T3 或恢复训练。下面各条是当时的历史记录。

**最新机制深化（09-12）：** 用户要求继续深化核心机制并先判断主线是否保留，已形成 [核心机制 v0.1](core_mechanism_v0_1_2026_09_12.md)。结论为主线符合原定义、可继续；候选新颖性仍偏弱，不能宣布方法成立。首版收敛到一个 ego 请求价值模块、固定 peer 检索、实际 GoT 交替；首轮 3 动作、次轮最多 5 动作，current/change 是 P/F 的请求参数。peer 可学习排序、额外归因头暂后置。接收端当前距离重排/截断及 P_local/F 重复字段必须与请求链一起处理，调用收益以实际入模后生成的轨迹计。普通 MLP 本身是首版价值实现，不虚设同构弱对照；change 请求须对比等候选数量的普通方案检索和公平单轮委托。本轮仅设计、源码/文献核对和两位 agent 复核，没有新模型执行或训练，训练仍停止。

**停训后评价已完成（09-12 傍晚）：** [第一轮 32 帧诊断报告](epoch01_quick_evaluation_2026_09_12.md) 保存全部口径、配对表与对照图。Ego/P/F/PF/规则共 160 次生成均有效，ADE 分别为 1.7412/1.9374/1.8213/1.7223/1.6413 米，恒速直行参考 1.5327 米；逐帧 ADE/FDE 已独立复算。PF/规则的小幅均值改善依赖少量大收益，去掉各自最大收益帧后均变差，此检查仅说明均值敏感性，不删除正式统计样本。两个录制组差异明显，无稳定协同收益或新机制结论。训练和本次推理均已结束，不自动续训；下一步先诊断已保存案例。

**最新执行（09-12 18:24，UTC+8）：用户要求停止训练，先评价已保存模型。** 已核对并终止管理/训练 PID 3906/3986，确认进程退出、GPU 释放；不自动恢复训练。第一轮完整训练及 540 行验证已经完成，检查点 `framework_baseline_restart_v1/training/checkpoint-epoch01` 保留，验证答案交叉熵为 0.260499；最新可恢复周期点为 step1925。停止前日志为 step1941，1925 之后尚未保存的更新不计入恢复状态。本次用第一轮检查点，对两个验证录制组各均匀抽 16 帧、五策略共 160 次实际生成做初步轨迹评价，目录 `outputs/framework_epoch01_quick_eval_2026_09_12/`。复用已保存的因果输入和实际工具响应，只有驾驶推理与离线评价，不重新查询或训练。原始停止证据在旧运行 `user_stop.json`；下方“训练继续”等均为历史记录，当前不再适用。

**新增主线创新筛选（09-12，承接用户允许合理新增机制）：** [综合报告](mainline_innovation_search_2026_09_12.md) 及三份独立评议已形成候选。发现 MATE 已有本车候选轨迹的远端私有评价后，推荐收窄为“第一次 P/F 返回与 ego 本地证据融合，实际修订 GoT 方案，再用旧/新方案关系组织第二次能力请求”；保留初始 STOP/P/F。上下文计算/历史增量监督作为支撑，条件化单轮委托作为强对照。核心增量尚未验证，尤其必须超过只用新方案的查询、同输入普通模型与公平的一轮 bundle。完整两调用路径通常含三次 GoT，必须计入真实成本；本轮只有研究和文档，没有新模型执行、效用标签生成或训练改动。当前创新建议以该综合报告为准，旧候选的作用范围见下文。

**最新主线确认（09-12）：** 用户明确“创新需要符合我们的主线”。ToolV2X 继续研究本车根据当前驾驶任务与已有证据按需调用邻车 P/F 能力，并利用返回结果调整后续调用；初始 STOP/P/F 保留，调用顺序不固定，序贯价值需要验证。[原始定义](../start.md)、[已批准框架](framework_design.md) 和 [用户约束](user_requirements.md) 是后续创新设计的依据。预测补证已校正为局部候选，不能替换总体研究问题；具体算法仍未锁定。本次只校正文档，未修改当前训练或工具接口。

**此前创新设计候选（09-12 下午，定位已校正）：** [预测补证与配对收益学习](innovation_design_2026_09_12.md) 及三份独立评议，研究已收到 F 后选择预测细化或目标级 P 历史补充的局部分支，并给出四种输入监督的价值分解版本。此前将它推荐为整体主线的定位已撤回，设计与近邻分析保留供筛选。去重、adapter、普通工具选择不单列创新；该分解必须对比直接 P、完整 P＋本地 MTR、完整 F、同监督普通 AFA/多任务模型和单轮打包。第四种联合输入只是离线辅助监督，不突破在线最多两次调用。方案尚未锁定或实现；此前调研只查论文、源码和 15 个训练片段的已保存证据，未启动新模型任务、改 P/F 或改运行训练。

**新增论文路径调研（09-12 下午）：** 用户目标为 CCF-B/C 正式研究论文，会议/期刊均可，今年或明年均可。已完成九篇重点论文的正文、公开代码/数据边界和投稿方向对照，主报告见 [从当前实验到论文的路径](paper_path_review_2026_09_12.md)。现有共享驾驶 SFT 是可复用基础；具体新颖机制仍未确定。后续不能默认继续训练 P→F：完整 P 已默认本地 MTR 重算，需要先检查第二次调用的新增内容及场景相关质量—成本差异。以主报告的收缩顺序为准，附录中的可选实验不自动扩成任务清单。本轮只新增研究文档/元数据核查，没有修改训练；14:51 核对到 step956、周期点950、PID3906/3986均存在，实时进度仍以运行目录与进程为准。

**最新运行核对（13:14，UTC+8）：重跑训练正常。** 管理/训练 PID 3906/3986 均在运行，GPU 100%；当前第 493 步、3944/14935 条训练行，第一轮 26.4%。最新完整周期恢复点为 step475，保留最近两份周期恢复点，未出现错误退出；本次核对元数据和所需文件存在，未重复加载整个权重。最近 100 步平均约 12.66 秒/步（含周期保存），训练 loss 均值约 0.204；尚未到首轮验证，不据此判断驾驶质量。原配置继续，预计第一轮训练行约 18:03 完成，之后还需验证。核对快照在 `outputs/framework_restart_2026_09_12/status_check_1313.json`，历史启动/恢复记录见下文。

**保存、重载及周期保存均已实际验证（11:36）：** 第 1 步完整检查点约 4.15 GB、保存 5.37 秒；退出重载后，模型参数、优化器和四类 RNG 全部逐项一致。第 25 步自动检查点也已发布，保存 4.71 秒，独立读取核对 452 组优化器状态全部为 step25、448 个 adapter 张量及 projector 数值有限。管理/训练 PID 3906/3986 正常，最新核对到第 34 步/272 条样本，约 12.4 秒/步。后续每 25 步继续保存，周期点保留最近两份；没有实测到明显 GPU 提速。证据在 `outputs/framework_restart_2026_09_12/periodic_checkpoint_check.json`，实时进度读取新运行目录。

**最新执行：已于 11:28 重启原适配，并修复周期性保存。** 用户在确认中断后重新授权加速重跑，取代此前取消安排。新目录 `outputs/framework_baseline_restart_v1/`，管理 PID 3906；直接复用既有准备/导出，原 GoT 初始化，未保存的旧 875 步不计入新训练。第一步完整保存退出后重载继续，此后每 25 步和验证前保存，保留最近两份周期恢复点；实际首次恢复仍需核对 `training/resume_verification.json` 和后续进度。完整 131 项回归与独立复审通过。三种加速候选实测均未达到采用门槛，因此原 BF16/FlashAttention 2 配置保持，不能宣称已显著提速。详见 [重跑和实测记录](training_restart_2026_09_12.md)。

实时状态以新目录为准，勿重复启动；下面“尚未重启/取消提效/原训练继续”等是此前各时刻记录。

**最新核查（2026-09-12 11:09–11:12，UTC+8）：原训练已中断，当前没有训练进程。** 最后记录为 02:55 的第 875 步、7000/14935 条训练行（第一轮 46.9%）。原管理/训练 PID 3013/4824 均不存在，GPU 空闲；原 status.json 的 running 已过期。没有轮末检查点、training_state.pt 或验证结果，loaded_adapter 只是原初始化权重的链接，不能恢复这 875 步更新。当前容器 PID 1 约于 11:02 启动，环境有过重新启动；确切退出原因未确定，当前 OOM 计数不能排除旧容器中的事件。提效交接仍为 cancelled_by_user，未启动优化续训。核查证据见 `outputs/framework_training_interruption_2026_09_12/audit.json`。

下一步应先增加周期性完整状态保存，再复用现有准备数据从原 GoT 初始化重跑；本次只核查并记录状态，没有改训练实现或重新启动训练，提效安排继续取消。下面“原训练继续”的表述是 01:16 时的历史记录。

**最新决定：按用户要求取消本次训练提效，原训练继续。** 2026-09-12 01:16（UTC+8）仅停止了等待自动测速/切换的进程 PID 7895；原管理/训练 PID 3013/4824 身份不变，训练未暂停、未重启。取消时已完成 406 步、3248 条样本，继续原 BF16/FlashAttention 2 配置和最多三轮流程。`outputs/framework_baseline_efficiency_v1/` 未创建，没有执行新路径的真实 7B 测速或切换。取消记录在 `outputs/framework_efficiency_handoff_v1/cancellation.json`，该目录状态为 `cancelled_by_user`，不得按此前计划自动重启交接。候选代码和已完成检查保留，未启用。

实时状态继续读取 `outputs/framework_baseline_resume_v1/status.json`、`training/progress.json` 并核对实际进程。当前工作是完成原共享驾驶适配、生成和评价，不再推进本次提效安排。

**最新完成：全量五策略准备、导出与独立核查。** 23:48（UTC+8）准备正常退出，3095 帧/15475 个任务，失败 0；23:50 导出正常退出，14935 条训练行、540 条无答案验证输入和 540 条独立验证损失行。逐行身份、提示、共用本车输入、录制组隔离、离线标签和断点排除检查通过。全量训练侧完整重复为 297/14935（1.99%），全部 Ego=rule；验证侧 0。内容重合另报，不直接去重或修改训练权重。细节见 [全量准备与训练启动](framework_baseline_results.md)，证据在 `outputs/framework_full_audit_v1/`。

**正式共享驾驶适配启动记录。** `outputs/framework_baseline_resume_v1/` 自动进入 train，管理 PID 3013，训练子进程初始 PID 4824。23:54 实际核对到 13 次优化器更新、104 条样本，观察到的 loss/梯度范数均有限。启动核对快照在 `outputs/framework_full_audit_v1/training_start_verification.json`。最新运行及提效取消决定见顶部；保持同一套最多三轮配置，不重复准备数据或从头训练，本轮不训练查询器。

**此前反馈核实：** [9-11-2 方案回复](review_9_11_2_response.md)已对照真实任务核查。20 帧联调的完整重复输入为 2/100；旧全量运行的 1718 帧完整前缀为 219/8590，均为 Ego=rule。其全量统计已在上条补齐。Ego 释放远端预留的 tokenizer 容量实测为 2.65→5.65 个对象；尚未新增 Ego-max 驾驶生成或训练消融。续接改动完整 118 项、轻量 90 项检查通过。

**此次续接来源记录：** 原 `outputs/framework_baseline_v1/` 管理/准备进程已退出，最后完整进度为 1718 帧，下一帧有 4 行部分任务；无异常栈，原因未确定。2026-09-11 23:04（UTC+8）在新 `outputs/framework_baseline_resume_v1/` 启动续接，经源码、配置、因果索引、任务身份/输入/提示校验后引用旧 8590 个完整任务，重跑 g3597 并完成原 3095 帧集合；原目录保持不变。续接准备已经完成，最新训练阶段见顶部。

**此前 GitHub 发布核验：** 完整框架代码、文档和精选真实文本已整理，见 [更新范围](github_update_framework_2026_09_11.md)。新增两项真实归档检查后，本机完整 117 项与轻量 89 项通过；从 Git 暂存树导出的无模型、无外部数据副本也通过 89 项。GitHub 仅记录 [当时进度](../outputs/framework_baseline_v1/progress_at_github_update.json)，本轮反馈回复及续接改动尚未提交推送。

**最新完成：完整基础框架实现与真实联调。** 见 [结果、边界和当前运行](framework_baseline_results.md)。Ego/P/F/PF/rule 统一走实际查询、证据更新、继续/STOP、共享输入、原 GoT 驾驶与评价。20 个预选帧的 100 个任务完成；80 条训练行完成一轮 10 次更新，验证 20 条，保存状态逐项恢复一致，重载后生成 20 条可解析六点轨迹。完整 115 项、轻量 87 项测试及独立算术核对通过；独立审查的两项 P1 已修复并复审关闭。轨迹质量尚不合格，含一条六点重合输出，小样本训练明确不是正式适配。

**首次全量启动记录（已中断）：** 2026-09-11 19:03（UTC+8）启动 `outputs/framework_baseline_v1/`，原管理 PID 8392。配置为清理后的 3095 帧五策略 → 14935 条训练行与 540 条验证输入 → 原 GoT 初始化训练最多三轮 → 验证损失选检查点 → 108 个开发验证帧五策略生成和评价。该次停在准备阶段，旧进度不是当前运行状态；续接位置见顶部。继续同一配置，不启动 2×2 选型矩阵、RSU/I 或新的学习策略训练。

**推进依据：用户要求先补齐完整可训练框架。** [完整框架对照](framework_completeness_review_2026_09_11.md) 和 [实现规格](framework_implementation_v1.md) 已落实到上述运行链。当前规则仅是可执行基线，具体学习查询机制尚未确定。下面固定 F 数据准备和旧历史下一步描述不能替代当前计划。

**此前完成：收缩方案第一步，Ego / 固定 F 配对训练数据。** 2987 个训练帧和 108 个开发验证帧的冻结 MTR 证据已全部生成，导出 5974 条训练样本和 216 条验证输入；两条件共用本车特征及相同本车文字块，报告见 [配对数据结果](paired_driving_data.md)。当时完整 101 项、轻量 75 项测试通过，3095 帧原数组/标签/提示核对及导出文件独立检查通过。该次准备没有驾驶参数更新或 Q9 生成。数据和历史 [收缩方案](scope_reset_2026_09_11.md) 保留，后续顺序以顶部完整框架推进为准，不展开此前 2×2 选型矩阵。

用户要求每一步都判断目的与做法、优化空间、方案一致性及后续研究和论文价值。本次因此修正了 F 挤占本车记录和 compact 共享字段改变本车文字的问题，仍保留固定距离选择与全部六模态。文字容量限制明显：训练帧平均保留 2.49 个本车和 2.96 个邻车目标；结果只用于固定输入条件比较，不称充分优化的 Ego 基线。

**最新完成：64 帧输入核查与 512 次真实 Q8。** 八个训练录制组各八帧，冻结 MTR 的 Ego/P/F/PF 证据、JSON/compact 容量账本、独立历史/标签坐标复算和 12 张中文鸟瞰图均已完成，见 [结果及下一步](training_evidence_audit_results.md)。GoT Q8 256/256 可解析，但 254 次为 fast/straight；V2V-LLM 0/256 可解析，全部原文保留。此轮没有驾驶参数更新或 Q9 生成。

**核查发现及其边界保留。** g2760→2761 的原始 pose 平移 67.34 米，框架按名义 0.1 秒理解；新配对驾驶数据已统一停用跨此断点的 40 个候选窗口，并保存完整清单，验证 108 帧没有此类断点。旧 64 帧核查样本仍原样保留。原始传感器时间/片段衔接原因未核实，原数据和 MTR 训练集未重建，冻结权重的历史限制不因窗口停用而消除。PF 重复表示和近自车原点候选身份问题仍保留记录，不展开为当前并行项目。

运行目录 `outputs/training_evidence_audit_v1/`；本机图集 `offline/gallery.html`。63 帧实际执行原 MTR 前向，1 帧两源为空；旧 prepare 无条件写原 MTR 已执行的元数据已修正，并用空帧真实回归确认四动作证据不变。历史 64 帧文件保留，实际模型活动以逐目标调用记录为准。下面此前 MTR 训练/冻结和入口检查的执行结果仍成立，其数据质量边界现在需结合这次新发现理解。

**已完成：MTR 六组训练与冻结选择。** 按 [固定协议](mtr_stability_plan.md) 完成 full/alternating × seed 20/21/22，每次 10 轮、每轮 996 次有效更新，六组共 59,760 步，逐组独立审计均通过。按末三轮的门槛选中 full，并冻结预先指定的 seed20 第 9 轮权重：`outputs/mtr_stability_v1/full_seed20/best_model.pth`，验证 top-1 ADE5 为 4.841 米。交替方案 seed20 的末三轮均值未优于原初始化；两方案曲线仍明显波动，不能称稳定性已解决。详见 [完整结果](mtr_stability_results.md) 与 `outputs/mtr_stability_v1/frozen_model.json`。第 5 组中断尝试完整保留，重跑结果才进入六组比较。

该冻结权重已做 P/F 工具接口复核：30 个邻车目标的完整 P 本地重算与 F 各数组逐项一致，含 27 个原 MTR 目标和 3 个短历史回退；没有执行驾驶生成。记录在 `outputs/mtr_full_seed20_connection_v1/independent_array_check.json`，该检查在最终选模前以候选身份完成，不参与选模。

**驾驶训练入口已通过实际更新与重载：** GoT/V2V-LLM × direct/Q8→Q9 四组，各在同一训练帧的四动作上累计损失后执行一次真实更新；全部 452 个可训练张量发生变化，并保存、独立重载及实际生成，见 [训练入口结果](driving_training_readiness_results.md)。原长 P 样本反向失败已通过本地 head_dim128 限定的 FlashAttention 2 构建解决，两次零更新失败保留。此检查使用旧 MTR 证据和旧 GoT 父回答；正式共享驾驶适配、同预算 2×2 选型与多帧四动作质量比较仍未完成。真实原 7B 零样本接入的 16 次动作尝试另见 [诊断](driving_decoder_results.md)。安装内核后完整 91 项、轻量 66 项检查通过。

**最新执行：原 CMP MTR 首轮因果适配已完成。** 用户已授权标签、原损失训练、适配前后评价及已有 Q8/Q9 基础诊断。使用原 no-coop MotionTransformer、固定因果跟踪窗口、独立未来监督；训练 8 个录制组、验证 2 个录制组，本轮未读取测试数据。训练 10 轮、9,960 步后按既定 patience=5 停止，选中第 5 轮；完整上下文验证组平均 top-1 ADE5 为 21.519 → 5.874 米。保存权重重载指标差为 0。完整结果、波动与覆盖边界见 [mtr_adaptation_results.md](mtr_adaptation_results.md)。`history_valid` 继续表示跟踪输出可用，包含因果 KF 维持状态，不改成检测匹配位。

完整集成 82 项、轻量审查 63 项通过。原始/适配预测各 7,256 条目标/上下文记录已经独立公式复算；选中检查点有 456 个参数张量相对初始化改变。`outputs/mtr_adapted_connection_v1/` 用新权重完成现有工具及原 projector 重放，完整 P 重算与 F 在 30 个邻车目标上路径/分数一致，没有执行 7B 生成。已完成的旧 Q8/Q9 诊断见 [planning_quality.md](planning_quality.md)：三个旧运行的 12 个动作回答、两个不同决策帧。

完整/ROI 按轮次交替属于首轮适配设置，不等于 P/F 或查询机制收益。训练曲线明显波动；首轮 ROI 同目标下完整上下文没有更低的平均预测误差。已按六组协议冻结权重并完成驾驶参数更新入口检查；下一步以顶部 64 帧核查发现及修正顺序为准。查询策略和闭环继续后置。所有新输出保存在新目录；此前 GitHub 内容与完成边界见 [更新说明](github_update_2026_09_11.md)。

## 此前阶段记录（保留当时的完成边界）

**当前本地修复：** 已处理网页版审查后本机确认的五项缺陷：运行器资源根目录、Q8→Q9 预算/失败记录、报文逐字节核对、adapter 相对路径，以及 MTR/回退计算计数。当前工作分支为 `fix/review-2026-09-10`，尚未提交或推送这些修复；验证范围和结果见 [review_9_10_fixes.md](review_9_10_fixes.md)。新增 Q8 预算可能改变目标保留数；下面的生成结果属于原运行。正式 MTR 适配前仍需明确跟踪状态有效位和检测匹配位的使用方案。

**GitHub 首版已发布：** [HikiMaji/ToolV2X](https://github.com/HikiMaji/ToolV2X)，当前为公开仓库，分支 `main`。仓库提供源码、原框架依赖源码/配置、当前文档和精选运行文本；权重、完整数据、点云特征、缓存及重复运行快照留在工作站。审查入口见根目录 [README](../README.md) 和 [github_review.md](github_review.md)。本次核心资源路径适配后，62 项本机集成测试、隔离导出副本的 51 项轻量检查通过；原 MTR 对旧验证帧 21 个目标的重算与归档数组完全一致。详见 [准备核验记录](github_preparation_validation.json)。本次没有新 7B 生成或训练；下面历史实验报告的快照和绝对路径仍属于原运行。

**最新推进：紧凑证据与适配训练入口已实现。** 见 [evidence_adaptation.md](evidence_adaptation.md)。同信息紧凑格式在原 7B 上四动作均可解析；相同预算可保留记录数由 5/4/5/4 增至 19/9/19/8，但 P 增加目标后只输出五点，故默认仍是 JSON。较大压缩收益依赖当前两位小数舍入后近重合的 MTR 模态，不能泛化成一般压缩率或规划收益。

3027 个训练帧、108 个验证帧的因果输入索引和独立原 Q8/Q9 标签已落盘；未读取测试数据。另一个真实训练帧物化了四动作共 8 条监督样本，实际原模型监督前向 loss 均有限，提示/证据/点云位置均屏蔽损失。58 项测试与独立复核通过，优化器步数为 0。产物在 `outputs/adaptation_data_v1/` 和 `outputs/adaptation_forward_v1/`。下一步先适配原 MTR，再物化全量工具证据并训练共享驾驶模型；完整 SFT 数据和训练优化器尚未完成。

**此前完成的 JSON 接入基线。** 用户批准设计后，已实际执行 CMP 原 MTR、独立 P/F 报文、P 本地重算、源分离接收，以及完整原 V2V-GoT 7B + LoRA 的 Q8→Q9。在一个真实验证决策帧上，Ego/P/F/PF 四动作均输出可解析行为和六点轨迹；当时的 48 项测试及落盘独立复核通过。完整报告见 [planning_connection.md](planning_connection.md)，运行产物在 `outputs/framework_connection_v3/`。

**当前未完成适配训练、正式规划质量评价、学习查询策略和闭环。** 接通和监督前向不能宣称方法有效。完整 P 历史本地重算与 F 在 30 个邻车目标上预测/分数完全一致；这只验证同信息计算等价。MTR 权重元数据 epoch=1、it=6，训练来源及算子适配与原 CUDA 的一致性未核实；V2V-GoT 也未针对新证据训练。默认 JSON 在该验证帧保留 4–5 条目标记录，紧凑候选增加至上面的数量，完整账本与舍弃项均已保存。

紧凑表示和监督边界已按上条推进，训练与质量对照尚未完成。两车 P/F 继续作为实施范围，RSU/I 后置，最终机制未确定。恒速/岭回归只保留为历史诊断或简单对照，其结果不能否定原模型方向。

新 agent 阅读顺序：

1. [user_requirements.md](user_requirements.md)：用户授权与最新下载分工。
2. [evidence_adaptation.md](evidence_adaptation.md)、[planning_connection.md](planning_connection.md)：最新表示/训练准备及此前实际接入记录。
3. [framework_design.md](framework_design.md)、[planning_implementation.md](planning_implementation.md)：已批准的目标设计与已完成接入范围。
4. [resource_downloads.md](resource_downloads.md)：当前资源。完整 LLaVA/CLIP 已从本机缓存链接并成功离线加载，无立即下载缺项。

用户允许 GPT-5.6-Luna Max 资源子 agent；github.com、githubusercontent.com、githubassets.com、huggingface.co 相关下载交给用户。不要重复下载已存在的模型，也不要通过镜像/跳转绕过分工。

维护原则：**只写已核实的事实和已做出的决定**。下面是 2026-09-09 及早期推进的历史正文，其中“CMP 单仓库 + 自建规划器”“用小模型 oracle 决定方向生死”“路由已经确定”“尚无权重/规划推理”等均不能当作当前设定；旧四配置训练脚本也仍有未解决的 GT/协议问题，不能直接启动为正式实验。以本文顶部和新接入报告为准。

---

## 0. 一句话现状

方案已从「V2V-GoT 底座 + 异构能力路由」调整为「**CMP 单仓库流水线（CoBEVT 检测 → AB3DMOT 跟踪 → MTR 预测）+ 自建 LLM 规划器**，在 V2V4Real 上验证 P/F 路由」。
当前阶段：**数据/环境准备**。目标是先跑出一个**不需要 LLM 的 oracle 实验**（见 §5），用它决定方向生死。

---

## 1. 已确定的研究设定（经过多轮评估后的结论）

- **叙事**：不讲「远端节点能力异构」（V2V4Real 只有两辆同构车，讲不通），改讲「**规划驱动的协作消息抽象层级选择**」——P（远端感知，回答"现在有什么"）与 F（远端预测，回答"未来会怎样"）是同一远端节点的两个抽象层级，差异在带宽、时延、灵活性、对远端模型质量的依赖。
- **必须有显式 cost**（字节数/时延），主实验报 cost–accuracy Pareto 曲线，否则 Always-PF 就是上界、路由无存在理由。
- **路由不用 prompt 让 LLM 自由选**，改为在 LLM 规划 hidden state 上接小 routing head，oracle 标签监督；同时必须报强 Rule-based 基线（置信度 + 预测熵阈值）。
- **第一版路由空间**：{STOP, P, F, PF}，P/F 独立可调用，不强制 P→F。Sequential（P 结果决定是否调 F）用 oracle 数据先做相关性分析再决定是否保留。
- **对照组**：Ego-only / Always-P / Always-F / Always-PF / Rule-based / ToolV2X / V2V-GoT（固定多阶段 LLM 协同推理）。
- **强度判断**：oracle 实验正面 → CCF-C 有把握，冲 CCF-B 需要 cost 曲线 + occlusion-critical 子集 collision rate。
- **V2X-Real + RSU** 只作为后续增强，不进第一版（见 §6）。

---

## 2. 底座选型的核实记录（避免重复踩坑）

| 候选 | 核实结果（2026-09-09） | 结论 |
|---|---|---|
| **V2XPnP** (github.com/Zewei-Zhou/V2XPnP) | 克隆后只有 15 个 py（OpenCOOD 工具函数），`datasets/__init__.py` 引用的 5 个 dataset 文件不存在，无 yaml/模型/权重。README 的 "2025/12 Codebase 1.0" 未勾选。**代码未发布**，假定不会更新。 | ❌ 不可用 |
| **TurboTrain** (ucla-mobility) | 只有 README | ❌ |
| **QuantV2X** (ucla-mobility) | 300 py / 80 yaml，完整；支持 V2X-Real(VC/IC/V2V/I2I)、OPV2V、DAIR-V2X；**只做检测，无 V2V4Real 加载器，无预测** | 仅用于后续 V2X-Real 的 P |
| **V2V4Real 官方** (ucla-mobility/V2V4Real) | 81 py / 10 yaml，OpenCOOD 分支，检测可用 | 已包含在本机 V2V-GoT/DMSTrack/V2V4Real 内 |
| **CMP** (github.com/tasl-lab/CMP) | GitHub API 确认顶层含 `AB3Dmot/ DatasetPreprocess/ MTR/ Plotter/ opencood/ preprocessed_data/ docs/ environment.yml`。论文：检测 = 修改版 CoBEVT，跟踪 = AB3DMOT（无需训练），预测 = MTR，历史 1.0s / 未来 5.0s，含 SinBEVT 无协作基线（V2V4Real minADE6@5s: SinBEVT 5.0250）。**未见预训练权重声明**。 | ✅ 主底座 |
| **V2V-GoT** | 本机已跑通（见 §3） | 保留：waypoint 生成参考 + 对照 baseline |

近邻工作边界见 `docs/analysis_report.md`、`docs/literature_screening.md`；PDF 在 `docs/papers/`。

---

## 3. 本机资源盘点（2026-09-09）

### 硬件 / 环境
- GPU：**1× RTX 4090 24GB**，空闲。
- 磁盘：`/root/autodl-tmp` 185G，剩 ~79G（2026-09-09 清理后）。`/` 剩 9G。
- conda 环境（`/root/autodl-tmp/conda-envs/`）：
  - `dmstrack`：py3.7.16, torch 1.12.0+cu113, spconv-cu113 2.1.25, numpy 1.21.6, open3d 0.17, filterpy, numba, shapely。**GPU 可用**。用于 OpenCOOD / AB3DMOT / 数据处理。
  - `llava`：torch 2.1.2+cu118, transformers 4.37.2。**GPU 可用**。用于 LLM 训练推理。
  - 另有 `/root/miniconda3/envs/{LangCoopCarla, tcp_codriving}`，与本项目无关。
- 网络：GitHub / HuggingFace 需 `source /etc/network_turbo`，**用完立刻 `unset http_proxy https_proxy`**（代理会拖慢其他网络）。

### 数据（全部在 `/root/autodl-tmp/V2V-GoT/`，已解压）
**V2V4Real 原始点云不在本机**（找不到 .pcd），但 **V2V-GoT 已落盘了 5 种检测配置的逐帧输出**，这就是我们的 P 原料：

| 目录 | 含义 | 在 ToolV2X 中的角色 |
|---|---|---|
| `no_fusion_keep_all/npy/{ego,co_llm,1}` | 单车检测（test） | **Local P** |
| `cobevt/npy/{ego,co_llm}` | CoBEVT 协作检测（test） | **Remote P**（与 CMP 同检测器，对比干净） |
| `early/`, `attfuse/`, `v2xvit/` | 其他协作检测（test） | 备选 Remote P |
| `train_*` 同名目录 | 训练集版本 | 训练 MTR / routing head 用 |
| `*/net_epoch60.pth` | 各检测器权重 | 已有，不需重训检测器 |
| `*/{eval,short_eval,middle_eval,long_eval}.yaml` | 0.6–2.9MB，内容待盘点 | — |

每帧文件：`XXXX_{gt, gt_object_id, lidar_pose, pred, pred_score, projected_lidar, transformation_matrix}.npy`，`co_llm/` 下另有 `XXXX_detection_box_score.npy`。
test 帧数：`no_fusion_keep_all/npy/ego` 约 1993 帧（15947 文件 / 8 类）。**shape / 坐标系 / 帧-场景映射待盘点（后台 agent 正在做，结果写入 `docs/data_format_v2vgot_npy.md`）**。

其他：
- `V2V-GoT/DMSTrack/`：含 `AB3DMOT/`、`DMSTrack/`、`V2V4Real/`(OpenCOOD 分支)。
- `V2V-GoT/LLaVA/`（45G）：LLaVA 1.5 + V2V-GoT 微调 checkpoint。
- `V2V-GoT/dataset_processed_features_and_gt.zip`（21G）与 `.root-partial.zip`（9.5G）：已解压，**可删以腾空间**（root-partial 疑为不完整重复下载；删前请用户确认）。
- `V2V-GoT/dataset_jsons.zip`：V2V-GoT-QA / V2V-QA。

---

## 4. 待办与分工

| # | 任务 | 状态 | 产出 |
|---|---|---|---|
| 1 | 克隆 CMP，摸清 MTR 输入格式、config、AB3DMOT I/O、聚合模块、权重 | ✅ | `docs/cmp_repo_notes.md`；仓库在 `/root/autodl-tmp/CMP` |
| 2 | 盘点 V2V-GoT npy 格式、帧-场景映射、waypoint GT 代码 | ✅ | `docs/data_format_v2vgot_npy.md` |
| 3 | 验证 dmstrack / llava 环境 GPU | ✅ | 本文 §3 |
| 4 | 统一读取层 + AB3DMOT 世界系跟踪脚本 | ✅ | `src/common/v2v4real_meta.py`, `src/tracking/run_ab3dmot.py` |
| 5 | 跑 6 组跟踪（no_fusion / no_fusion_cav1 / cobevt × test / train） | ✅ 6 组全部完成 | `outputs/tracks/{split}/{config}_world.pkl`，日志 `outputs/logs/track_all.log` |
| 6 | **决定 MTR 是否需训练** | ✅ 自训（§4.1） | — |
| 7 | tracks.pkl → CMP MTR 轨迹 pickle 适配器 | ✅ test 集 4 份已生成 | `src/prediction/tracks_to_cmp.py`；产出统计见 `pipeline_spec.md §3.2` |
| 8 | 新建 `cmp` conda 环境 | 🔄 后台安装中 | `conda-envs/cmp`，日志 `outputs/logs/setup_cmp_env.log`，脚本 `outputs/logs/setup_cmp_env.sh`；末尾出现 `ENV_DONE` 即成功 |
| 9 | MTR 四个 cfg + 去 BEV feature 依赖 | ✅ | `CMP/MTR/tools/cfgs/toolv2x/{local_f_egoP, local_f_coopP, remote_f_egoP, remote_f_coopP}.yaml`；CMP dataset 打了一个小补丁（`ALLOW_MISSING_FUSED_FEATURE`，缺 BEV 时喂全零），`cd CMP && git diff` 可见 |
| 10 | V2V4Real 目录骨架（空 yaml，替代原始点云） | ✅ | `src/prediction/make_v2v4real_stub.py` → `outputs/v2v4real_stub/` |
| 11 | MTR 训练 / 测试一键脚本 | ✅ 未运行 | `src/prediction/run_mtr_stage.sh {prepare|train|test}` |
| 12 | 生成 train 集轨迹 pickle | ✅ | `outputs/cmp_trajs/*/train/`（no_fusion 1027 objs / cobevt 1322 / cav1 1069），合并目录 `remote_egoP`, `remote_coopP` 各 64 文件 |
| 13 | 训练 4 个 MTR（顺序：local_f_* → remote_f_*） | ⏳ | `run_mtr_stage.sh train <cfg>`，ckpt 在 `CMP/MTR/output/<cfg>/default/ckpt/` |
| 14 | oracle 分析脚本（规划器 + 四配置对比 + 四个判据数字） | ✅ 已写好并用 GT 输入 smoke test | `src/oracle/oracle_analysis.py`，等 #13 的推理结果后运行，输出 `docs/oracle_results.md` |

### 4.0.1 一个重要的数据事实：GT 里包含 CAV 自身
V2V4Real 的 GT 框包含 ego 自身（距 ego 原点 <1.5m 的框，test 集 80% 的帧都有）和 CAV1。做规划碰撞检测时必须排除，否则 ego 永远"撞上自己"。`oracle_analysis.cav_self_ids()` 用 ego 原点与 CAV1 位置（`1/<t>_transformation_matrix.npy` 的平移）半径 1.5m 内的 GT id 排除。排除后，用 GT 他车做规划，27 个抽样帧里 26 帧选择全速沿 GT 路径，平均 waypoint 误差 0.2m，规划器行为正常。

### 4.0 MTR 四个 cfg 与四配置的对应

| cfg | 感知输入（pred_traj_dir） | 聚合器 | 对应 ToolV2X 配置 |
|---|---|---|---|
| `local_f_egoP` | ego 单车跟踪 | None | **Ego-only** |
| `local_f_coopP` | cobevt 协作跟踪 | None | **+P** |
| `remote_f_egoP` | ego 单车跟踪 + CAV1 单车跟踪（`remote_egoP/` 合并目录） | Transformer | **+F** |
| `remote_f_coopP` | cobevt 跟踪 + CAV1 单车跟踪（`remote_coopP/`） | Transformer | **+PF** |

GT 统一用 `outputs/cmp_gt_radians/`（CMP 的 cav0 GT 文件复制为 cav0 与 cav1 两份，全部弧度，规避 CMP 原 cav1 文件的度数问题）。remote_f_* 的 `PRETRAINED_MOTION_TRANSFORMER` 指向对应 local_f_* 的 epoch 30 ckpt，与 CMP 的两阶段训练一致。

### 4.1 关于"是否需要训练 MTR"——结论：**自训**（已决定）

- CMP 仓库内无 `.pth`；官方权重在 Google Drive，**本机两种网络方式都不可达**。
- 即便拿到权重也不兼容：CMP GT pickle yaw 单位不一致（cav0 弧度、cav1 度，跟踪结果度），且聚合器依赖需原始点云生成的 BEV feature。详见 `pipeline_spec.md §3, §6`。
- 自训规模：test 集 MTR 可用样本 1.3–1.7 万 (obj,t) 对，train 集约 4–5 倍；BATCH 1 × 30 epoch，4090 单卡预计每个 cfg 数小时到半天，四个 cfg 顺序跑（remote 依赖 local ckpt）。

### 4.2 磁盘
用户已清理，`/root/autodl-tmp` 现剩 ~79G（两个大 zip 已删）。

---

## 5. 第一个决定性实验：oracle 路由（不需要 LLM）

对 test 集每帧跑 4 配置：Ego-only / +P / +F / +PF，用**同一个简单规划器**（先用 V2V-GoT 已有 waypoint 逻辑或规则规划器）生成 ego waypoint，计算：

1. **Oracle 上界**：逐帧取 4 者最优 vs Always-PF vs Ego-only。若 oracle 相对 Always-PF 提升可忽略且 Always-PF 相对 Ego-only 也微小 → **停止该方向**。
2. **P/F 可分性**：P-only 最优、F-only 最优的样本占比及误差差距分布。**低于 10–15% → 核心假设不成立**。
3. **成本节省空间**：oracle 下 STOP / 单工具比例 → 带宽节省。
4. **Sequential 是否值得**：P 结果（新增检测数、置信度变化）与"F 是否有帮助"的相关性；弱则砍掉 sequential。

若方向被证伪，已搭好的 CMP 流水线转做「协作预测对 LLM 规划器的增益」。

---

## 6. 后续增强路径（不进第一版）

V2X-Real 有 2 CAV + 2 RSU（路口场景四者同时在线，走廊场景只有 2 CAV），RSU 传感器（Ouster 40m 俯视）与车载（RoboSense 200m）真实异构。VC 子集 = ego 是车、协作者含 RSU。
- P：QuantV2X（代码完整，原生支持 V2X-Real）
- F：V2XPnP-Seq **数据**已放出（68 场景轨迹 + 地图，UCLA Box），把 CMP 的 MTR 迁到该轨迹数据上训。
- 原版 V2X-Real 无跟踪 ID / 预测 / 规划标注；LLM 层无任何现成工作，需自建。

---

## 7. 文件索引

- `docs/STATUS.md`（本文）— 交接总览，**新 agent 先读这个**
- `docs/pipeline_spec.md` — 四配置定义、数据流、CMP 轨迹 pickle 格式（含 yaw 单位 bug 记录）、序列号对照表、MTR 环境与权重问题、oracle 实验设计
- `docs/data_format_v2vgot_npy.md` — V2V-GoT npy 每类文件的 shape/坐标系/公式、帧-场景映射、waypoint GT 代码位置、可运行示例
- `docs/cmp_repo_notes.md` — CMP 仓库结构、MTR dataset/模型/训练入口、AB3DMOT 修改点、最少改动清单（注意：其中"cav0 GT yaw 为度"的说法不准确，以 pipeline_spec §3 为准）
- `docs/user_requirements.md` — 用户原始需求
- `docs/analysis_report.md`、`docs/literature_screening.md` — 文献与边界分析
- `docs/papers/` — 近邻论文 PDF 与文本
- `docs/evidence/v2v_got_inference_source.py` — V2V-GoT 推理源码摘录
- `start.md` — 早期完整方案设想（部分叙事已被 §1 修正，以 §1 为准）
- `src/common/v2v4real_meta.py` — 唯一的数据读取入口（路径、len_record、角点→中心、ego↔world、ego 未来 waypoint）
- `src/tracking/run_ab3dmot.py` — 跟踪脚本，用法见文件头
- `outputs/tracks/` — 跟踪结果 pkl；`outputs/logs/` — 运行日志
- `/root/autodl-tmp/CMP` — CMP 仓库克隆（浅克隆，含 `preprocessed_data/v2v4real/gt_multiego_speedless` GT 轨迹）

## 8. 运行约定

- 数据处理 / 跟踪：`/root/autodl-tmp/conda-envs/dmstrack/bin/python`（不要 `conda activate`，直接用绝对路径）。
- 网络：只在访问 GitHub / HuggingFace 时 `source /etc/network_turbo`，之后立即 `unset http_proxy https_proxy`。Google Drive 两种方式都不通。
- 不修改 `/root/autodl-tmp/V2V-GoT/` 下任何文件；所有新产物放 `ToolV2X/outputs/`。
