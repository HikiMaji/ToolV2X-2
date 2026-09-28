# Stage 2：CoDriving同网格P/F输入准备

2026-09-26。状态：**纯数据栅格适配和批次附加接口已实现；真实receipt→CARLA历史→MTR→训练消费链尚未接通。没有修改或训练planner主干，不宣称新增证据已被原权重使用。**

## 已核对的原版复现

直接读取 `toolv2x_backbone_research_2026_09_19/CoDriving/outputs/codriving_baseline_v1/baseline_results.json` 与复现报告：Single和CoDriving各3560样本，Town05/weather-0六条完整路线。Single ADE/FDE=0.631669/1.449718m；CoDriving=0.618416/1.411912m。原公开不完整路线被整条排除；这是已取得官方子集上的原版检查点评估，非完整测试集或新方法效果。两个方法采用各自官方planner权重，不可将差值全部解释为同权重只增加通信的效果。

## 真实网格与时间轴

- `planning_end2end.py`：原occupancy为[B,5,6,192,96]，输入卷积明确只接受6通道，输出[B,10,2]。
- 原6通道含动态occupancy、ego、导航目标、两张坐标网格、可行驶区域；不能占用这些通道来悄悄塞入F。
- `opencood/utils/occ_render.py:box2occ`的实际输出为192×96、0.25m/格，前36m、后12m、左12m、右12m。YAML的0.125是此前更高分辨率参数，collate/实际栅格路径最终为0.25；本次按实际张量核对。
- 新适配输入坐标明确为x向前、y向左、yaw逆时针，原点为当前ego actor。像素行向后、列向右；中心为x=36−(row+0.5)*0.25、y=12−(col+0.5)*0.25。
- 外部来源输入必须用显式3×3刚体变换投影；sensor/actor偏移由调用者提供，不能盲目再加1.3m。历史框需先统一到同一个来源参考系，不能给每个过去框重复套当前车姿。
- planner输出的10点来自输入尾帧之后连续10个保存帧。官方仿真20Hz，当前weather-0配置save_skip_frames=4，给出名义0.2s/点、2s时域；其他天气配置存在1，已读measurement无时间戳，不能只凭文件号断定所有录制均为0.2s。

**时间轴不硬编码成旧wire六点或统一3秒。** rasterize_pf要求future_times和time_binding，attach_pf_sidecar要求10个未来通道。示例0.2…2.0秒仅为明确标注的合成fixture；正式绑定要落实每条录制的采集来源/时标。时间不能确认时不把名义时域写成实测事实，不默认外推旧F。

## 实现的接口

`src/planning/codriving_pf_bev.py`：

- `rasterize_pf(p_records, f_records, ego_from_source, *, future_times, time_binding, decision_time)`：已准入P/F记录→统一BEV，纯NumPy，不读取provider、GT或模型。
- `attach_pf_sidecar(batch, rasters)`：新增toolv2x_pf_bev键，保留原occupancy/feature/target对象及数值；输出批次P=[B,5,192,96]、F/F_CV=[B,10,192,96]、F_valid=[B,10]及审计信息。

这里P的5是channel数，不能与原occupancy的5帧时间轴混淆；两者当前分开保存。

规范记录：source、track、box=[x,y,l,w,yaw]、velocity=[vx,vy]、velocity_valid、refs；P另有history条目(time≤0、box、valid)，F另有forecast_times、forecast[M,K,2]、forecast_scores、model_used。history time和forecast time相对于当前decision epoch；旧forecast origin不同或返回过期时，调用者必须先做合法时间对齐，不能直接转交本函数。

该模块要求有字段引用，但**不把refs字符串当作receipt验证**。生产调用者必须先走已有ledger的真实receipt准入、坐标/时标对齐和实体关联；本模块是其后的数值转换工具，不是可直接信任provider JSON的新服务。多记录只可在同一已声明参考系中共用一个变换。

### P通道

1. P_current_occupancy：当前目标矩形并集。
2. P_history_occupancy：所有valid过去框并集，不包含time=0；无有效历史则为空。
3. P_vx、4. P_vy：旋转到ego系的绝对运动速度分量，m/s；不减ego速度、平移不作用于速度。
5. P_valid_mask：当前像素上有合法速度支持。不是自由空间、可见域或逐帧detector hit；无效速度与真实零速度可以区分。

重叠像素的速度由有效目标中心距离最近者决定；相同距离按source/track排序打破平局，避免输入顺序改变输出。history_valid表达因果tracking-state有效性，不能宣称每帧检测命中。历史联合通道不保留先后顺序，这是首版明确的表示限制，必要时再扩为分时历史通道。

### F与F-CV

- top-1依据分数最大值选取；平局选原mode索引较小者，不做模式平均。
- F-CV严格来自同一F返回目标集合的当前锚点和合法当前速度，不从F未来点反推速度、不替换为更大的目标集合。
- F与F-CV共用尺寸、当前yaw保持代理、网格、时刻和栅格函数。当前wire未来xy没有明确未来姿态，因此首版两臂都保持anchor朝向，避免给F额外姿态而CV没有；这不等于完整车辆未来姿态预测。
- 允许在当前anchor(t=0)和已返回预测之间线性插值；不越过最后预测时刻外推。若任一目标在某个请求时刻没有覆盖，该整个未来通道标invalid且两臂均置零，避免把缺失目标当作安全空场景。消费者必须读F_valid；空返回另有evidence_presence标记。
- model_used=false如实保留：静止fallback不能被称作MTR预测结果。
- 缺合法当前速度不能构造公平F-CV，显式报错；需要先从已购因果历史估计或把该样本列为不可配对，不能免费读取对方真值。
- 二值occupancy/validity是0/1；速度保持m/s。原occupancy图为0…255范围且抗锯齿。新增sidecar不直接替换原输入；后续输入适配必须明确尺度，不默认旧卷积权重可直接使用新分布。

## 已完成验证

11项定向检查：空间范围/方向/尺寸、刚体旋转与速度、历史因果边界、top-1与同信息CV相等、转弯F与CV不同、缺未来覆盖、无速度拒绝、重叠确定性、空/回退语义和原batch不变。经历缺接口RED→GREEN；额外确认batch接口拒绝非10点时间轴。

直接提取并执行原官方CPU函数turn_traffic_into_map，以四组已知几何检查新网格。两个轴对齐框阈值化IoU=1，旋转框0.9412，边界裁剪框0.9703，最大质心误差0.039像素。原版有matplotlib边缘/抗锯齿、新模块是二值像素中心判定，因此不声称逐像素等价。这验证同范围/分辨率/方向，不是模型效果实验。

合成示意图和npz见 `docs/evidence/codriving_pf_bev_2026_09_26/`，明确标为contract fixture，不是真实MTR预测。当前没有运行原planner前向的等价性检查；代码保持原输入对象、原forward只读取原键，但“已运行模型等价”需后续实际验证。

## 未完成的必要连接

1. 为公开录制落实物理时间绑定，不能用合成fixture替代。
2. 真实peer本地检测/跟踪→合法P记录；完整私有上下文MTR→合法F，接入已有receipt ledger。当前规范记录不自动从旧6点wire改造为新时域。
3. 同目标F-CV需要确定可用的因果速度来源；F-anchor收益与未来增量分开评价。
4. 下阶段才选择小型输入投影/输入层扩展与共同训练方案。原planner第一层固定6通道，当前sidecar不会被原权重消费；不应把“张量已生成”写成“planner已利用P/F”。
5. 使用独立训练/验证数据，当前Town05公开测试子集不能拿来适配后仍称独立测试。

本轮没有更改planner主干、原官方配置/权重/复现结果，没有训练、闭环或协作收益结论；也没有增设object transformer或额外预测骨干。

最终资源独立回归389项通过（195.971s）；该运行启动于最后增加10点batch约束之前，最终约束另以主目录定向11项验证通过（0.034s）。git diff --check通过。源码检查原forward仅读occupancy、feature_warpped_list、target，不读取新增sidecar；未做真实模型效果评估。
