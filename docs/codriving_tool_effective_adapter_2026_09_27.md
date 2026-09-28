# ToolV2X 最小有效规划适配与真实输入探针

> **2026-09-28 审计更正：** 下文保留原探针历史，P 收益与有效协作链归因已撤回。已确认坐标/时刻错位、route05_28 本车误作 P、冻结 P adapter 在 14 个样本上对清零/换帧 P 完全不敏感。数值本身保留，不能继续解释为 P/F 收益或纯泛化结论。见[审计、证据与修复顺序](codriving_input_audit_2026_09_28.md)。

日期：2026-09-27。用户确认不因官方 CoDriving 的训练/推理 occupancy 差异而重建底座。本批保留官方 Single/CoDriving checkpoint 和推理流程，只增加最小 ToolV2X residual adapter，并跑 route11 少量真实 peer LiDAR 检测。

## 已完成

### 1. 最小 planner adapter

`src/planning/codriving_tool_adapter.py` 新增 `ToolEvidencePlanner`：

- 接收官方 `base_planner`，不修改 CoDriving 官方模型文件；
- 缺少 `toolv2x_pf_bev` 时返回原 planner 输出；
- P/F sidecar 进入单独小型卷积残差分支，F 的十个未来栅格没有伪装成原始五帧历史；
- 输入含 P 五通道、F 或 F-CV 十通道、F-valid 十通道以及导航 target；
- 最后一层零初始化，Ego/未购买证据在初始状态严格保持 base output；
- `forecast_variant='F'/'F_CV'` 使用同一 adapter，适用于配对预测价值比较；
- adapter 可单独训练，官方 base planner 可冻结，不引入新预测骨干或控制器。

这一步只是让证据拥有真实规划通路，不等于已有模型已经学会利用 P/F。只有训练并在 held-out 上取得指标后才可称为方法结果。

### 2. 契约与官方 checkpoint 探针

`tests/test_codriving_tool_adapter.py` 五项检查：缺 sidecar 的 exact base、零初始化 exact base、P/F 非零 adapter 前向改变、F/F-CV 形状和差异、输入错误拒绝。模型环境五项通过；资源独立环境因无 torch 全部按设计跳过。

使用官方 Single planner checkpoint `no_collaboration_planner.ckpt` 做实际前向探针：

- base 与零初始化 adapter 输出逐位相同；
- 手动打开 adapter 后，真实官方模型形状输入的 F 局部变化使十点输出 L2 变化 **12.2152**；
- 这是通路/敏感性验证，不是训练效果或论文结果。

### 3. route11 真实检测

使用官方 V2Xverse Single 感知 checkpoint，对 route11 的两个独立 ego vehicle 只读取各自 LiDAR 和 `lidar_pose_z`，没有读取对方点云、GT actor future 或 RSU：

- 单帧 frame80：vehicle0 三类检测数 `[4,3,2]`，vehicle1 `[3,0,2]`；
- 连续保存帧76–80：
  - vehicle0 `[3,1,1]`, `[4,2,2]`, `[5,1,2]`, `[5,2,2]`, `[4,3,2]`；
  - vehicle1 `[3,0,2]`, `[3,0,2]`, `[3,0,2]`, `[3,0,2]`, `[3,0,2]`。
- 由于官方运行库缺少 `libcuhash.so`，第一次探针启动失败；按已有官方复现记录设置动态库路径后成功。该环境修复不改变模型或输入。

原始检测产物：
`outputs/codriving_real_detection_probe_2026_09_27/`
`outputs/codriving_real_detection_history_probe_2026_09_27/`

后者包含五帧检测、版本信息和 `real_p_records.json`。其中 P 记录的历史由真实 detector 框在 route11 保存帧上形成；速度由最后两个因果历史状态差分，未使用未来。当前产物只用于输入验收，坐标/实体关联仍需独立人工和几何审计，不能称正式方法样本。

## 为什么这条路线比重新搭底座更可靠

- 官方 CoDriving 主干、感知 checkpoint、导航 target、waypoint loss 和评估口径均保留；
- ToolV2X 的新增代码只有证据残差接口，不替换成熟 planner；
- Ego 初始行为有 exact equivalence，能区分“adapter 改坏底座”和“证据带来改善”；
- F 与 F-CV 共用目标、时间轴、valid mask 和相同 adapter，能够排除“只是增加一次生成”的解释；
- 之后只需训练 adapter，不需要重新训练完整感知系统。

## 还不能声称的内容

- adapter 尚未训练，不能称 P/F 已改善 ADE/FDE；
- route11 五帧仍不是完整 tracking→receipt→MTR F 样本；
- 当前 `real_p_records.json` 的坐标/实体关联是受控探针，正式样本需通过跨车坐标变换、self/ego target 排除和 track continuity 检查；
- 手动打开 adapter 的输出变化不是效果实验。

## 下一步硬验收

1. 修正 route11 peer detector 框到 receiver ego 坐标的正式变换，并排除 receiver 自身目标；
2. 用同一五帧因果历史生成合法 P 与 F-CV，确认 P raster 和 F-CV raster 可视化/统计；
3. 接入真实 peer-context MTR 得到同目标 F-MTR；要求 F-MTR 与 F-CV 至少在轨迹内容上可区分；
4. 只训练 adapter，固定 official Single base，先做短训和 held-out；若 P/F 不优于 Ego，则停止调参并回到数据质量诊断；
5. 通过后再接 ToolV2X 的 current/change/STOP 策略。

本批未启动训练，未修改官方 CoDriving 源码或检查点。

## 真实 F-MTR 配对探针

在同一路线扩展到保存帧60–80（21个0.2秒保存帧）后，两个 receiver 的 source ego 与 receiver ego 检测均先排除；每个 receiver 保留一个连续第三方可见目标，21/21 帧有因果 detector 状态。为适配冻结 CMP MTR 的11×0.1秒历史，使用过去2秒的保存状态做显式0.1秒插值，另存 provenance；这不是把0.2秒文件号直接伪称0.1秒。

冻结 `CMP MotionTransformer` 对两个真实窗口执行 top-1 F：`model_used=true`。与同目标、同锚点、同时间轴的 F-CV raster 对比：

| receiver | F-MTR occupancy | F-CV occupancy | 差异像素和 |
|---:|---:|---:|---:|
| 0 | 1451 | 882 | 1857 |
| 1 | 0 | 0 | 0 |

receiver1 的目标在未来时域离开当前 BEV 范围，这个失败/无效样本被保留，不能挑掉。receiver0 证明真实 detector history→MTR F 与 CV 具有可区分的内容，但不证明 F-MTR 更准确。

MTR 使用旧 Torch 环境时遇到 `mmap`、meta/assign 和 `argsort(stable=...)` 兼容差异；本次只用临时运行时 shim，原 vendor 源码已恢复未修改。原始探针与输出在 `outputs/codriving_real_detection_long_probe_2026_09_27/`。

这一步已经满足“不是合成 F”的输入通路验收，但仍未把该 sidecar 接入官方真实 planner batch，也未训练 adapter。下一步才是 route11 单样本官方 planner wrapper 和 adapter 短训；短训只验证梯度/过拟合门，不作为论文结果。

## 官方真实 planner batch 接入

使用官方 route11 数据、Single 感知 checkpoint、Single planner checkpoint，在官方 inference 数据路径上选取 route11 frame80 的一个样本。为避免加载缺失路线，使用临时 route11-only dataset index；运行结束后已恢复原 index。

真实 batch 包含：官方五帧 occupancy、导航 target、官方感知 feature_warpped_list、真实未来 waypoint 标签，以及由 route11 detector/MTR 探针生成的 `toolv2x_pf_bev` sidecar。wrapper 前向成功，输出 `[1,10,2]`；冻结 base 的零初始化 adapter 与原 planner 输出 L2 delta 为 **0.0**。该 batch 的单样本 ADE/FDE 为 **0.876213/2.867154 m**，只表示接线样本，不能与六路线统计或方法收益比较。

运行日志和形状见：
`outputs/codriving_real_planner_batch_probe_2026_09_27/tool_one_planner.txt`
`.../input_shapes.json`
`.../metrics_per_sample.jsonl`

这一步确认 sidecar 已进入**官方真实 planner forward**，不再只是独立 adapter 合成测试。仍未训练 adapter，因此 P/F 对 ADE/FDE 的增益尚未测量。


## 训练边界

`ToolEvidencePlanner(freeze_base=True)` 现在默认冻结官方 base 参数，并在 `train()` 时强制 base 保持 eval，避免 BatchNorm 统计被短训污染；新增梯度与训练模式回归。adapter 允许 NumPy sidecar自动转到 target device。

## adapter 短训门

在同一个真实 route11 planner batch 上仅训练 adapter 20 步，base planner 参数冻结且保持 eval。L1 从 **0.484042** 降到 **0.312683**，`base_frozen=true`。这证明真实 batch、sidecar、监督和 adapter 梯度可以连通；它是单样本过拟合门，不能当作 held-out 或论文效果。

产物：`outputs/codriving_adapter_short_train_probe_2026_09_27/adapter_short_train.json`。最终资源独立回归为 **414 项通过，8 项因无 torch 跳过**。

## 多窗口短训诊断

进一步使用 route11 frame70–80 的 11 个真实官方 planner batch：前8个窗口各训练 adapter 8步，后3个窗口（78–80）只评估。base planner 始终冻结并保持 eval。

held-out 三个相邻时间窗口的结果：

| 条件 | ADE | FDE |
|---|---:|---:|
| frozen Ego base | 0.1513 m | 0.3836 m |
| ToolEvidencePlanner | **0.1164 m** | **0.3218 m** |

相对下降约23.1% ADE、16.1% FDE。这是第一次在真实官方 planner batch 上观察到 adapter 的正向 held-out 信号，但只能叫**同路线相邻窗口诊断**：训练/评估来自同一 route11，P/F 坐标关联仍是受控探针，尚未做 P-only、F-CV、F-MTR、PF 的独立消融，也没有跨 route split。因此不能写成论文主结果或泛化结论。

产物：`outputs/codriving_multi_adapter_probe_2026_09_27/metrics_per_sample.jsonl`。下一步先在完全相同窗口和训练预算下跑 Ego/P/F-CV/F-MTR/PF 对照，再做按 route/recording 隔离的 held-out；不能只保留这次改善结果。

## 同预算 P/F 消融诊断

在完全相同的 route11 frame70–77训练、frame78–80评估、每窗口8步adapter更新和冻结Single base下，跑了 Ego、P-only、F-CV、F-MTR、PF：

| 条件 | ADE | FDE |
|---|---:|---:|
| Ego | 0.1513 | 0.3836 |
| P-only | **0.1085** | **0.2958** |
| F-CV | 0.1174 | 0.3140 |
| F-MTR | 0.1151 | 0.3171 |
| PF | 0.1164 | 0.3218 |

这组结果不是论文主结果：所有窗口来自同一条 route11，训练/评估是相邻时间段，坐标关联仍是受控探针。它有两个明确结论：

1. P 当前/历史分支已经能在真实 planner batch 上产生较强的短训信号；
2. F-MTR 只在 ADE 上略优于 F-CV，PF 没有超过 P-only，说明当前 F 表示或 P/F 融合不是天然有效，不能预设协同信息单调叠加。

所有变体产物分别保存在 `outputs/codriving_ablation_{Ego,P,F_CV,F_MTR,PF}_2026_09_27/`，没有删除变差结果。下一步应先做跨 route/recording 独立验证，并检查 F 的时间/坐标和 adapter 融合，而不是继续扩大训练。

## 跨路线验证状态

本轮检查了 V2Xverse 本地数据：当前只有 route11 解压目录；route12、27、28、29、31、6 只有 208MB–2.4GB 的压缩包。没有在未确认额外解压空间的情况下展开这些大归档，因此尚未声称跨 route 泛化。

另外用 route11 的另一辆 ego 做了真实 P/MTR 输入探针。其目标在较晚窗口逐渐离开当前 36m×24m BEV，frame77–80 的 F-MTR/F-CV occupancy 均为零；该 coverage failure 被保留，不能为了得到正结果而丢弃。正式跨 recording 验证需要先取得并解压至少一条完整独立 route。

## 跨 recording 结果：route05_28

用户补充的数据根目录包含完整 route05_28 recording。本轮使用 route11 frame70–77 训练得到的 P-only adapter，完全冻结、不在新路线更新，直接评估 route05_28 frame30–40 的11个官方 Single planner batch。

| recording | 条件 | ADE | FDE |
|---|---|---:|---:|
| route05_28 | frozen Ego base | 0.5108 | 1.1794 |
| route05_28 | route11-trained P adapter | 0.7277 | 1.7142 |

adapter 在跨 recording 上恶化约42.5% ADE、45.3% FDE。这是重要失败结果：route11 的正向短训信号不能直接当作论文收益，当前 P 坐标/检测域/训练样本覆盖仍未泛化。完整逐样本结果在 `outputs/crossroute_town05_28_adapter_eval_2026_09_28/metrics_per_sample.jsonl`。

当前结论应改为：**通路有效，但现有 adapter 只在单 recording 诊断中有效，跨 recording 失败。** 下一步不应长训；先检查 route11→route05 的坐标绑定、目标关联、检测分布和 P 历史质量，再决定是否需要 recording-level 训练隔离或数据归一化。
