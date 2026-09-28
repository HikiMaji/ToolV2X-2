# ToolV2X研究点一：主实验底座选型

日期：2026-09-19。任务：按9-19新方案调研并确定一个主方案和一个备选。**本轮完成研究选型，不等于原框架复现、跨平台接入或效果验收完成。** 未启动训练、驾驶模型推理、CARLA或新方法实验。

## 1. 选型结论

**推荐主方案：PDM-Closed数值规划器 + V2Xverse纯车车任务 + ToolV2X已有P/F服务与反馈执行框架。**

**学习式备选：CoDriving原规划器 + 同一V2Xverse环境。** 它也可作为外部完整系统参考，但其原生通信不是本项目P/F，不能直接加入同信息策略表。

这个选择基于接口适配性与减少未经验证的驾驶网络训练，而不是宣称PDM在我们的数据上已经更好。论文创新继续归于LLM组织远端能力与反馈调用，PDM本身不作为新算法贡献。

选择意味着两项明显调整，尚未实际实施：

1. 主实验推荐转到有原生路线与双车传感器的V2Xverse；V2V4Real保留为真实数据、P/F与已有协议/模型诊断的补充。旧数据和权重不删除、不改写其结果。
2. 驾驶评价不能继续只追求复现人类轨迹的ADE。应同时报告独立环境依据下的碰撞/道路合规、进展、舒适性与通信/计算代价，ADE/FDE保留。若坚持“无地图的V2V4Real + 只用开环ADE证明贡献”，**PDM不是适合该限制的主方案**，不能硬把它接入。

本轮没有找到一个在现有V2V4Real缓存上、无需输入适配就可同时接受P状态与F轨迹的已训练可靠驾驶器。上述结论正面承认这个缺口，不以下载源码冒充解决。

## 2. 为什么优先PDM-Closed

官方PDM实现是完整的预测式数值规划流程：读取目标状态、形成未来占据、生成沿路线的多种速度/横向偏移候选、车辆动力学仿真、评分、输出方案，必要时制动。它是规则和数值计算模型，**PDM-Closed本身不需要学习式规划权重**；不要与PDM-Open/PDM-Hybrid混淆。[原论文](https://arxiv.org/abs/2306.07962)、[官方流程](https://github.com/autonomousvision/tuplan_garage/blob/main/tuplan_garage/planning/simulation/planner/pdm_planner/abstract_pdm_closed_planner.py)。

与本项目的匹配点是P/F都有明确的数值作用位置：

- P补充或更新已经关联的目标状态/因果历史，改变目标集合、速度估计及占据。
- F补充目标未来路径，改变同步时刻的占据，进一步影响前车判断、候选生成和碰撞/TTC评分。
- 相同物理时刻获得E1后重新执行同一PLAN，得到真实tau1；LLM根据tau0/E1/tau1决定下一次能力调用。

这里能保证的是“证据有明确计算入口”，不能保证“更多证据必然更好”：错误预测可能引起误刹或危险决策，准确但无关的信息也可能不改变方案。仍需报告收益、损害和STOP。

**必须指出：原版PDM并不原生接收MTR六模式F。** `PDMObservation.update`默认按当前位置、速度做恒速占据外推。选择PDM是因为已有预测占据的完整下游消费者，可在此处改接真实预测，而不是因为它已替我们实现P/F。[原观测实现](https://github.com/autonomousvision/tuplan_garage/blob/main/tuplan_garage/planning/simulation/planner/pdm_planner/observation/pdm_observation.py)。

原PDM主要沿路线中心线和有限横向偏移生成候选，不把它写成能处理任意换道、协商博弈或所有城市场景的万能规划器。

## 3. 对候选的实际核查

| 候选 | 已核实可复用内容 | 与ToolV2X的主要距离 | 本轮决定 |
|---|---|---|---|
| PDM-Closed | 目标状态→占据→IDM候选→动力学→评分的源码；无需学习式planner权重 | 原属nuPlan，需要CARLA地图/路线适配；外部多模式F并非原生接口 | 主方案 |
| CoDriving/V2Xverse | 原完整协同驾驶流程、训练/评价、导航、公开感知与规划权重 | 接收BEV特征和5帧6通道栅格，输出10点；没有独立外部F接口，P也不等于原特征通信 | 学习式备选 |
| DIPP | Theseus数值优化、外部预测和参考线接口、车辆模型与代价源码 | 依赖参考线/限速/信号、学习预测和代价；原配置10个邻车、50步0.1秒，需较多适配 | 不列主备选 |
| VAD / UniV2X | 官方源码、ego-agent/map交互、规划监督；UniV2X有公开权重链接 | 与地图/query特征及原训练链强绑定；不是给若干xy框和F即可复用完整能力，UniV2X原任务偏V2I | 保留参考 |
| OmniV2X | 新近公开的对象token规划器、源码和两种检查点 | 原为DAIR/V2I；当前对象builder默认基础设施GT，外部检测可通过入口替换；无P历史/外部F原生接口，需视觉与任务条件适配 | 不列主备选 |
| V2XPnP / CMP | 协同感知、预测基础 | 不能把perception/prediction模型当作ego PLAN | 预测服务参考/复用 |

CoDriving的网络输入、输出与接口以[原规划器源码](https://github.com/CollaborativePerception/V2Xverse/blob/main/codriving/models/planning_end2end.py)为准，原评价入口在`codriving/tools/inference_e2e.py`。虽然dataset会构造GT占据，中间评价链将检测结果渲染后覆写occupancy通道0；因此不能仅凭loader读取actors_data就声称原评价直接用GT障碍物。ToolV2X接入仍需逐通道核对，防止保留未覆盖的特权字段。[原评价源码](https://github.com/CollaborativePerception/V2Xverse/blob/main/codriving/tools/inference_e2e.py)。

DIPP的预测、参考线、状态接口和固定维度见[原planner](https://github.com/MCZhi/DIPP/blob/main/model/planner.py)。OmniV2X的默认对象输入来自[官方builder](https://github.com/JuntongPeng/OmniV2X/blob/main/navsim/agents/omniv2x/core/infra_bbox_features.py)，官方[inference入口](https://github.com/JuntongPeng/OmniV2X/blob/main/navsim/agents/omniv2x/scripts/inference.py)允许外部infra标签目录；不能由此推断全部论文实验都用了GT或给其原任务定性违规。这里只判断我们的真实远端观测要求与其默认接口的距离。

OmniV2X公开checkpoint文档还写明history trajectory ego conditioning，和论文强调不使用speed/throttle/steering不是同一件事。不能把它描述成完全不使用本车历史运动的干净对照。[检查点规格](https://github.com/JuntongPeng/OmniV2X/blob/main/docs/CHECKPOINTS.md)。

## 4. 数据与导航：为什么建议V2Xverse纯V2V

本轮从官方展开目录核实一个Town03路段同时含`ego_vehicle_0`、`ego_vehicle_1`及独立的RSU目录。下载两车同文件编号0010的LiDAR与measurements，共4文件737,376字节。点云分别为22,595×4和22,291×4的float32，有限值检查通过。两车都有自己的位姿、速度和路线目标记录。这证明小样本资源存在，不证明所有路段的时钟同步、训练划分或覆盖已经合格。[官方数据入口](https://huggingface.co/datasets/gjliu/V2Xverse/tree/main/dataset/dataset_v2xverse)。

车辆目录也列出`rgb_front`等相机目录，可为后续真实多模态Agent提供候选来源；本轮没有读取图像，也没有将图像送入任何模型。正式使用前仍须核对图像时刻、标定和本车可见范围。仅把数值场景转成文字不能声称已经实现MLLM。

只选两辆车并显式关闭RSU读取。双方各自用单车传感器运行检测/跟踪，形成私有因果上下文。不能把全局`actors_data`裁成两份后冒充真实传感器P/F；GT仅用于离线评价/监督。

`x_command/y_command`由当前路线规划器节点写出；可从原生路线和同版本静态地图构造PDM所需中心线与路段集合。**一个局部目标点本身不等于完整的nuPlan地图API。** CARLA车道连接、道路多边形、限速和信号对应仍须实现适配。[采集源码](https://github.com/CollaborativePerception/V2Xverse/blob/main/simulation/leaderboard/team_code/base_agent.py)。

信号信息必须声明合法来源。若无法提供本车可见信号或所有方法共同拥有的公开信号条件，首批选择不依赖信号的预声明场景；不能读取全局expert hazard字段当本车感知。`should_brake`、`target_speed`、未来ego轨迹等不得成为Agent或PLAN的暗中提示。

V2V4Real官网在本次实际HTTP读取时仍把HDMap annotation与Camera Data列为`[next version]`；现有工程也没有已核实的预设导航。这个事实不否定V2V4Real用于真实感知/预测和无导航开环研究，但不足以支撑直接复用依赖地图的规划器。[官方页面](https://mobility-lab.seas.ucla.edu/v2v4real/)。

不推荐改用nuPlan或Waymo全局目标记录、再人为造一个peer来当主V2X数据集。可以用nuPlan最小样本验证PDM原版环境，但它不是我们的双车主实验。

## 5. 首版接入设计：复用什么、改哪里

### 5.1 保留的原实现

| 原文件/类 | 实际用途 |
|---|---|
| `proposal/batch_idm_policy.py` | 原IDM速度策略，不重写成自造神经轨迹头 |
| `proposal/pdm_generator.py` | 沿合法路线生成并展开候选 |
| `simulation/pdm_simulator.py`及车辆模型 | 仿真候选的可执行运动 |
| `scoring/pdm_scorer.py` | 原碰撞、TTC、道路/方向、进展和舒适性评分结构 |
| `utils/pdm_emergency_brake.py` | 原紧急制动逻辑，独立计入规划结果 |

保留官方许可和来源，适配修改单独列出。不能把PDM原nuPlan分数、延迟直接移植成ToolV2X结果。[评分源码](https://github.com/autonomousvision/tuplan_garage/blob/main/tuplan_garage/planning/simulation/planner/pdm_planner/scoring/pdm_scorer.py)。

### 5.2 需要新增的工程接口

1. `planning/pdm_driver.py`：接现有共同driver的prepare/plan/output/cost接口。初始化从本车合法状态执行；返回仍可投影为0.5秒间隔六点，但内部车辆状态和实际计算耗时保留。先前轨迹用于调用策略及反馈记录；PDM重新求解不必把它累加成输出基底。这个“从同一时刻重新求解”不同于上一轮失败的神经输出代数换基底。
2. `planning/pdm_observation_adapter.py`：只从已验证的本地、acquired和合法derived字段构造统一目标与预测占据，调用前不读provider对象。复用已有坐标/关联/身份结构，按一套固定规则选择或融合状态；GT不得决定实体关联和来源质量。
3. `planning/v2xverse_inputs.py`：双车传感器、定位、路线/地图、帧时刻白名单适配，离线监督reader分开。旧V2V4Real缓存入口保留。
4. 原PDM最小扩展：`PDMObservation.update`接外部路径；`PDMGenerator._update_leading_agents`的目标速度也要与该路径一致，不能只移动框却继续使用矛盾的恒速速度；地图初始化/route adapter采用CARLA来源。

以上为拟修改位置，文件尚未创建。`tools/vehicle.py`的P/F语义、receipt和执行器继续复用；若时间栅格或返回horizon要改变，另立版本，不偷偷修改v1契约。

### 5.3 三项必须在接入时明确的规格

**时间。** 原PDM默认8秒输出、4秒proposal，TTC额外查看约1秒；现有F只返回3秒。首版建议显式设置3秒输出、2秒proposal与原TTC查看窗口，所有条件一致，不能把3秒F悄悄外推成8秒“模型预测”。保留0.1秒内部步长，0.5秒F点间插值只在已返回范围内进行；曲线朝向/速度的导出另记。[原配置](https://github.com/autonomousvision/tuplan_garage/blob/main/tuplan_garage/planning/script/config/simulation/planner/pdm_closed_planner.yaml)。这是一项待验证的实验设置，不等于原PDM基准配置。

V2Xverse保存间隔可配置，采集代码的默认`save_skip_frames`与注释也不一致。本次样本没有验证绝对帧周期；不得沿用V2V4Real“编号差1=100ms”。若记录稀疏，缺失历史须显式mask或按已确认的因果重采样规格处理，不能用未来状态填补。MTR的11×100ms输入适用性属于首批门槛。

**多模式/多来源。** P/F原始多模式与分数完整保留，模式不能跨来源按索引强配或平均坐标。原PDM是单预测占据接口，首个源码接通测试可显式使用top-score模式，但这只是接入测试，**不能称完整多模态F方法验收**。主实验前须固定同一套多模式占据/评分方案并验证其增益与保守性；若需要新增大型学习融合网络才能成立，则不再属于本次最小PDM适配，需重新评估选型。这是当前选型留下的明确设计风险，不隐藏成“直接支持F”。

**同一物理时刻的重规划。** 原PDM有iteration、已碰撞对象列表与proposal状态。Tool调用两轮不是车辆实际前进两个tick；每次PLAN要从相同物理前缀重建/恢复这些状态，不能让第一次计算的内部副作用变成第二轮额外信息或把新障碍错误忽略。相同证据和确定性设置重复求解应一致，证据变化才可能产生修订。

## 6. 预测与感知资源没有凭空解决

- 官方V2Xverse提供单车感知权重，可分别处理两车LiDAR，避免拿协同融合后的特征构造Ego输入。官方模型清单本次核实到`no_collaboration/perception/net_epoch_bestval_at16.pth`约32.82MB，配置约4KB。[官方模型目录](https://huggingface.co/gjliu/v2xverse/tree/main/no_collaboration)。
- 现有冻结CMP/MTR仍是F首选预测器，但其V2V4Real权重在CARLA上是否有效尚未验证。不得把“同样是车辆xy历史”当成预测质量已经迁移；先比较真实目标的预测误差、覆盖与恒速参照，再决定是否需要限定适配。不能在F失效时继续训LLM掩盖问题。
- P依旧不调用MTR；它提供causal tracking-state motion proxy。Ego的本地预测也必须使用同一个已固定预测器和完整本地合法上下文。
- 完整P→receiver同MTR与provider F同信息控制继续成立：相同上下文/时标/模型应产生同预测，成本按执行地点和通信分别记录。

因此“PDM无需规划训练”不等于“整个系统不再需要任何感知/预测适配”。这是主要可行性风险之一。

## 7. 如何评价，避免再次只看loss或内部评分

主策略比较保持同一个PDM版本、检测/预测器、地图/路线、目标预算和代价规格。LLM相对小模型的比较在该共同基础上进行。

若LLM额外读取本车图像，必须将输入信息的增加与调用策略的贡献区分：同时保留同结构化输入的LLM/MLP比较，并让视觉对照获得同源视觉表征；不能把“只有LLM看到图像”的差异全部归因于LLM反馈推理。这里尚未指定或加载LLM/VLM权重。

PDM选轨迹使用**预测环境**；论文评价使用**独立离线真实环境/仿真结果**。两者必须分离。不能用加入F后PDM内部TTC分数更高，直接当成真实驾驶更好或Tool teacher reward。

推荐第一层为真实双车记录上的固定时刻任务：报告ADE/FDE、独立GT碰撞代理、道路合规、路线进展、平顺性及调用成本。这里是开环/短时反事实评价，不称闭环成功。成本lambda与失败惩罚在开发集确定，测试前冻结；不能按F收益调阈值。

推荐论文最终补一个有代表性的闭环子集，以验证规划器决策与实际驾驶结果的一致性；不要求这轮启动或迁移整套闭环实验。PDM原工作已经明确指出开环模仿和闭环驾驶指标可能不一致，所以不选择PDM后仍把单一ADE下降作为必然成功标准。[原研究](https://arxiv.org/abs/2306.07962)。

## 8. 下一批最小验收与停止条件

**先做接口接入和一个固定的小数据包，不训练LLM，不训练新的驾驶网络。**

1. 取得可复查的同版本路线/地图和时标，完成双车单车检测→因果跟踪→本地/peer预测的小链路；地图、GT、两车私有状态有分离入口。小样本按路线与时刻预先选择，不能按收益筛选。
2. 接原PDM，核对同证据重复、地图坐标、ego排除、F时间对齐及路径-速度一致；合成反例只证接口。
3. 冻结20个物理时刻，跨至少4个路线段，比较Ego/P/F/PF及同计算无新证据条件。PF不是全信息上界。记录所有失败、无效输出和每车原始字段来源。
4. 仅在基本规划有效、真实远端确有有用信息且独立指标出现可解释的收益/损害后，扩到按路线隔离的完整验证、再做真实oracle分支。

停止扩大范围的条件：地图/路线无法合法重建；时间规格不能支持MTR；真实F弱于基本参照且无增量；PDM适配变成另造复杂planner；或只有内部预测评分改善而独立评价无收益。出现这些情况就处理对应一项或转备选，不追加同配置长训练。

本轮只做研究，以上20帧尚未选择/运行，不设想已有正结果，也不因小样本一次失败判定整个方法不成立。

## 9. 已取得的资料与未取得资源

官方源码快照与manifest位于：`/root/autodl-tmp/toolv2x_backbone_research_2026_09_19/`。选型证据摘要见`docs/evidence/backbone_selection_2026_09_19/`。

本轮取得53个官方源码/说明/配置文件，共757,820字节，以及两个车辆的4个研究样本，共737,376字节，合计约1.50MB（另有少量目录与元数据）。一次旧评价入口查询404已保留，正确入口`codriving/tools/inference_e2e.py`随后取得。没有下载权重、全数据或CARLA。官方权重清单仅核实路径和字节数，没有验证权重实际加载：

- CoDriving单车/协作规划器分别约20.00MB，可在备选复现需要时直接下载。
- OmniV2X no-map/map检查点分别862,446,982和886,817,975字节，超过用户自行下载域名门槛，且本轮不选用，所以不要求用户下载。
- 主方案无需PDM-Closed神经权重。CARLA 0.9.10.1、地图或更大的路线包如需取得，应先列精确文件清单与用途；不能让用户先下完整nuPlan/Waymo作为双车数据。

## 10. 本轮完成与未完成

完成：候选论文/官方源码比对；PDM实际生成和评分链阅读；CoDriving入口/权重可用性核查；OmniV2X默认对象来源核对；V2Xverse双车小样本实读；主备方案和接入/评价/停止条件明确。

未完成：PDM原版或跨CARLA真实运行、传感器检测、预测迁移质量、P/F多模式适配、主实验数据迁移、LLM接入、任何新效果实验。生产代码与旧结果保持原状态；09-18中断质量脚本未恢复。
