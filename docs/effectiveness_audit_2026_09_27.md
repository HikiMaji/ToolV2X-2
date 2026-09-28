# ToolV2X 有效性审计与论文主线收敛

日期：2026-09-27

本轮目的不是继续堆协议，而是判断 P/F 是否有机会真实改善规划，以及当前 CoDriving 底座能否给出可发表的因果比较。没有训练、没有真实新方法运行；只读官方源码、已有检查点，执行一次单样本敏感性诊断，并查阅官方 CoDriving/V2Xverse、Where2comm、How2comm 的方法定位。

## 一、当前底座的事实

### 1. CoDriving planner 已经使用导航

官方 `planning_end2end.py` 的 `WaypointPlanner_e2e` 接收 `occupancy`、`feature_warpped_list` 和 `target`。`target` 经 `target_encoder` 后与 BEV 特征拼接再预测十个 waypoint；数据集还把 `occupancy_local_command` 作为原 occupancy 通道之一。因此当前问题不是缺少导航输入，不能靠“加导航”解释后续收益。

证据：

- `toolv2x_backbone_research_2026_09_19/V2Xverse_official/codriving/models/planning_end2end.py:101-165`
- `.../codriving/data_utils/datasets/pnp_dataset.py:287-327, 413-442`

### 2. 当前训练/推理动态输入存在语义差异

训练数据集的 `occupancy_map` 在 `pnp_dataset.py:273-287` 由 `actors_data` 生成；这是一份录制的 actor 状态热图。训练循环在 `train_end2end.py:330-374` 没有把它替换为检测器预测 occupancy。

推理循环则在 `inference_e2e.py:224-259` 对感知网络做预测，调用 `box2occ`，随后在 `:270-288` 将 warp 后的预测 occupancy 写入 `pred_batch_data['occupancy'][:,:,0]`。

所以已有官方规划 checkpoint 不能简单解释为“在与部署完全相同的感知输入上训练”。已取得的 Single/CoDriving ADE/FDE 仍可作为官方复现参考，但在 ToolV2X 新方法比较中必须先固定这个输入口径。否则 P/F 的增益可能只是改变了训练/推理错配，而不是协作证据带来的收益。

### 3. 不能直接以 CoDriving 作为 ToolV2X 主基线

官方 CoDriving 的 planner 读取已经融合的 `fused_feature`，推理时它来自 `output_dict['ego']['fused_feature']`；Single 和 CoDriving 使用不同的感知/规划检查点。CoDriving 已经拥有协同特征，ToolV2X 再给同一 planner 添加 P/F 时，远端信息很可能重复或被融合特征遮蔽。

因此建议：

- **主比较**：Single/Ego-only 感知与 planner + P、+F-CV、+F-MTR、+PF、ToolV2X policy。
- **CoDriving**：保留为完整协同系统参考/上界，不把它当成同权重的“只加通信”对照。
- 所有 ToolV2X 条件共用同一个 Ego-only planner、同一预测/训练/测试分割、同一导航输入和同一输入尺度。

## 二、敏感性诊断

加载现有 Single planner checkpoint，在 CPU 上构造一个形状正确的输入，固定 feature 和 target，只对 occupancy 单个通道一个局部区域做极端 255 值扰动。输出变化的 L2 范数如下：

| 通道 | 输出变化 L2 | 解释 |
|---|---:|---|
| dynamic occupancy | 0.1165 | 有响应，但较弱；不是效果证据 |
| ego mask | 5.6017 | 结构通道响应明显 |
| command map | 0.5038 | 有响应 |
| coordinate channels | 1.2834 / 2.5192 | 有响应 |
| drivable area | 18.0062 | 结构性影响很大 |

这个 probe 不是论文实验：输入是合成的、扰动过大、feature 不是实际样本，不能推出真实 ADE/FDE。它只说明将 P/F 二值栅格静默替换已有通道风险很高；P/F 应有显式、可训练的输入分支。

## 三、真正能产生作用的最小方法

### 1. 先修正共同底座的输入一致性

第一步不是加 P/F，而是建立一个 **Ego-only realistic-input planner**：

- 感知模型冻结；
- 训练和验证都使用与推理相同的 detector-produced occupancy；
- 保留原来的 `feature_warpped_list`、导航 target、十点 waypoint supervision；
- 只更改 occupancy 产生路径，不改 planner 的任务定义；
- 先验证 Ego-only ADE/FDE 与输入统计，再冻结该 planner 作为所有 ToolV2X 条件的共同底座。

这个步骤解决“planner 训练时看 GT occupancy，推理时看 detector occupancy”的混杂。若没有它，之后 P/F 好坏都难归因。

### 2. P/F 不能只放进 prompt，也不能冒充历史帧

新 planner 保留原始分支，新增一个残差 `ToolEvidenceEncoder`：

- P 输入：当前 occupancy、causal history occupancy、vx、vy、valid；
- F 输入：十个未来 occupancy、F-valid；
- F-CV 与 F-MTR 使用完全相同的目标、尺寸、当前 yaw、时间轴和有效性；
- 未来分支用小型 2D/3D 卷积编码十个未来时刻；
- 在原时序 BEV 编码后的 latent 处做残差融合，而不是把未来图伪装成过去五帧；
- adapter 的初始残差为零，Ego 条件在训练初始时严格退化为原 planner；
- 所有条件共享 adapter、decoder、loss 和训练预算，输入缺失用显式 valid mask，不用全零隐式表示“未购买”。

这不是论文创新本身，是让 P/F 有机会进入实际规划计算的工程底座。论文创新仍是：在最多两次远端调用和真实返回反馈下，决定买 P、F 还是 STOP，并让第一轮结果改变第二轮 `current/change` 请求或终止。

### 3. 先做“能否起作用”的最小训练，再做策略

顺序固定为：

1. Ego-only realistic-input planner；
2. 同一底座 + P；
3. 同一底座 + F-CV；
4. 同一底座 + F-MTR；
5. 同一底座 + PF fixed；
6. same-evidence extra-generation；
7. strong one-shot conditional delegation；
8. rule-based acquisition；
9. 最后才是 ToolV2X feedback policy（最多两次调用，真实返回后修订或 STOP）。

如果 `F-MTR` 不优于 `F-CV`，不能说 MTR 预测本身有价值；如果 `P/F` 都不优于 Ego，先查输入质量、时间/坐标、目标关联和底座输入一致性，不能用继续调 loss 代替诊断。

## 四、论文主实验的可归因口径

必须同时报告：

- ADE/FDE：十点真实未来 waypoint；
- communication：request/response UTF-8 bytes、远端调用次数、预测器调用次数；
- acquisition：P/F/STOP、第一次和第二次请求、第二次是否由真实返回改变；
- valid coverage：P/F 实际有效目标比例、F-valid 时刻；
- 分场景：遮挡/远距/交互目标/无协作需求；
- 误差和收益都保留，不能只挑改善样本。

核心表格至少包括：

`Ego`、`P`、`F-CV`、`F-MTR`、`PF-fixed`、`one-shot`、`rule`、`ToolV2X-feedback`、`CoDriving reference`。

其中 `CoDriving reference` 不是同输入严格对照；论文中必须标为独立完整系统参考。真正证明 ToolV2X 的是共同 Ego-only 底座下、等预算的固定调用/单轮/规则/反馈比较。

## 五、与领域工作的关系

[V2Xverse/CoDriving 官方仓库](https://github.com/CollaborativePerception/V2Xverse)明确将协同感知特征和 occupancy 输入共同用于 waypoint planner，并提供训练、离线 waypoint 评测和闭环评测。因此它适合作为底座和完整协同参考，但它的协同输入已经是融合后的感知结果，不等于 ToolV2X 的 P/F 工具调用。

[Where2comm](https://arxiv.org/abs/2209.12836)和[How2comm](https://openreview.net/pdf?id=Dbaxm9ujq6)主要证明通信选择、稀疏化和时延补偿可以改善协同感知任务；它们不是 ToolV2X 的 planning-feedback 对照。ToolV2X 若只展示“新增通道让预测误差降低”，创新会退化成普通输入融合；必须展示请求决策、返回后修订、预算成本以及与固定/单轮/同证据对照的差异。

## 六、当前结论

项目仍有论文路线，但路线已经收敛：

- **先修正输入一致性，再训练 P/F adapter；**
- **Single/Ego-only 是主共同底座，CoDriving 是参考上界；**
- **P/F 作用必须进入 planner 的显式未来证据分支；**
- **ToolV2X 的创新是预算化、反馈驱动的远端能力获取，不是 BEV encoder；**
- **在真实 peer detector/tracker/MTR 样本未产生前，不启动长训练，不声称协作收益。**

下一步实现前需要确认这一版收敛设计。第一批代码应只做：

1. detector-produced occupancy 的训练/验证输入适配和一致性回归；
2. `ToolEvidenceEncoder` 的零残差接口及 P/F/F-CV 形状测试；
3. 不启动长训练，先用一个真实 route11 小窗口验证 Ego/P/F 输入统计和 planner 前向。
