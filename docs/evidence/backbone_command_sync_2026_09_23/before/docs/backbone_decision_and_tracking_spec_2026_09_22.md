# 共同底座定案建议与首批轨迹跟踪规格

日期：2026-09-22。状态：**具体设计，供用户审阅；尚未实施、安装或实跑，未证明可靠性。**

本轮只完成三个问题：选定规划—控制组合、落实真实 F 来源、规定第一批独立跟踪验收。依据包括 AGENTS.md、STATUS.md、9-19.md、9-22.md、设计重置记录、现有源码/失败产物以及上游官方源码。保留已有工作区和全部历史结果；本文不授权继续调 PID、训练或运行闭环。

## 1. 首选组合及实施边界

**首选：CommonRoad Reactive Planner v2024.1 核心 + CARLA 0.9.15 官方 VehiclePIDController + 明确参考点和时间索引的薄适配。车辆固定为 `vehicle.lincoln.mkz_2017`（0.9.15 的准确蓝图名，不能沿用旧版 `vehicle.lincoln.mkz2017`）。[官方蓝图库](https://carla.readthedocs.io/en/0.9.15/bp_library/)** PDM 保留为有条件备选，本轮不同时维护两条新实现。

这项选择不保证换框架后自然通过。它减少了一项额外待证关系：PDM 内部 LQR/自行车模型对候选的预计执行，与外部 CARLA PID 实际执行是否足够一致。RP 输出运动学参考后，仍须通过独立跟踪误差门槛，才能以参考近似执行进行碰撞检查。预测输入方便只是选择理由之一。

### 1.1 两条路线的实际差异

| 核对项 | 首选 RP 核心 + 官方 PID | 保留 PDM + 同一官方 PID |
|---|---|---|
| 输出及执行关系 | 输出带时标的位置、速度、朝向等运动学状态；交给独立控制器跟踪 | 生成参考 → 内部 LQR/模型模拟 → 原评分 → 返回所选参考；不能把模拟结果再冒充参考 |
| 额外待证假设 | 运动学可行参考在指定车辆/控制器下具有足够小的实际误差 | 除左项外，还要证明内部模拟对候选排序足够准确，或建立一致的执行模型 |
| 自车状态 | 后轴位置、航向、速度、加速度、等效单轨转角；实际几何/运动约束 | 类似状态需求；另有 nuPlan 车辆模型与 LQR 参数假设 |
| P/F 消费 | P 改当前对象及共同基准预测；F 改动态障碍的未来占用，同一候选族/碰撞检查选轨迹 | P/F 需同时适配 leading agent、future occupancy、TTC、heading、stopped 判定，不能只替换 polygon |
| 时域设计 | 本方案固定 4 s、0.1 s、40 个未来状态，碰撞查询不越过 4 s | 如启用备选，设计为 proposal/output 均 4 s；原 TTC 额外约 1 s 要 5 s 预测。原 4/8 s 不沿用 |
| 主要迁移 | 合法 Scene/静态地图 → Scenario/CollisionChecker；实际车辆参数；同 t 重入；参考到 PID | 上述地图/控制适配之外，未来状态查询、参考速度导出、内部执行模型关系还需关闭 |
| 当前证据 | 官方有 RP/CARLA 接口与依赖组合；本项目未安装/实跑 | 本地接通过，已有失败；接通不抵销控制与模型适配债务 |

PDM 的上述职责见原始 `abstract_pdm_closed_planner.py`、`pdm_simulator.py`、`batch_lqr.py` 与[本地设计评审](common_backbone_design_2026_09_22.md)。RP 的状态/接口见[官方状态定义](https://github.com/CommonRoad/commonroad-reactive-planner/blob/v2024.1/commonroad_rp/state.py)及[官方 CARLA 适配](https://github.com/CommonRoad/commonroad-carla-interface/blob/v1.0.0/crcarla/controller/reactive_planner.py)。这里比较适配责任，不比较不同论文的成绩。

**退出条件：**固定控制器未通过第 3 节，先判本组合的执行假设失败，不进入 RP 场景调参，也不直接换回 PDM。若相同控制器失败，换规划器没有排除共同问题。控制通过后，RP 若必须重写主要采样/代价算法、借助全局 actor 或瞬移才能覆盖已批准任务，也退出该路线。只有失败明确属于 RP 的候选/场景适配，且 PDM 能在上述有限边界内解决时，才重新评审 PDM。两条路线都不满足时，应报告暂未找到合适底座。

### 1.2 版本、控制器和执行顺序

选择 Python 3.10、CARLA **server/client/PythonAPI agents 均 0.9.15**、RP **v2024.1**。CommonRoad CARLA 接口 v1.0.0 的官方依赖包含 CARLA 0.9.15 与 RP 2024.1，作为组合依据；不安装/直接运行整套包装器。本机当前只有 0.9.10.1，升级资源与安装验证尚未完成。模型 worker 可继续隔离在原环境。[官方依赖声明](https://github.com/CommonRoad/commonroad-carla-interface/blob/v1.0.0/pyproject.toml)

0.9.10.1 的 PID 本身可提交物理控制，但本地 API 缺少所核对的本车物理轮角读取方法；因此不能据此宣布满足 RP/PDM 初态。0.9.15 有 `get_wheel_steer_angle`，单位为度；接口存在不等于等效单轨状态已验证。[CARLA 0.9.15 API](https://carla.readthedocs.io/en/0.9.15/python_api/#carla.Vehicle.get_wheel_steer_angle)

以下为第一版固定设计值，**不作参数搜索**：

| 项目 | 固定值/语义 |
|---|---|
| 物理/控制周期 | 同步模式，dt=0.1 s；物理子步最大 0.01 s，最多 10 次 |
| RP | `time_steps_computation=40`，`planning_horizon=4.0`，`replanning_frequency=1`；返回含 t 的 41 个状态 |
| 横向目标 | 转成 actor origin 后的 `p_ref(t+0.4 s)` |
| 纵向目标 | 同一参考的 actor-origin 速率 `v_ref(t+0.1 s) × 3.6` km/h |
| 横向 PID | Kp=1.95，Ki=0.05，Kd=0.2，dt=0.1 |
| 纵向 PID | Kp=1.0，Ki=0.05，Kd=0.0，dt=0.1 |
| 显式限幅 | throttle≤0.75，brake≤0.3，归一化 abs(steer)≤0.8；offset=0 |
| 控制器内置限速 | 每 tick 归一化 steer 变化≤0.1 |
| 控制输出 | `VehicleControl(throttle, brake, steer)`；正常控制不使用 handbrake、set_transform 或 set_target_velocity |

PID 增益采用 CommonRoad `ControlParams` 的预设，限幅采用 CARLA 构造器默认值并显式传入。CR 包装器没有传递其部分 max 配置字段，不能只填写这些字段就宣称生效。[CR 参数](https://github.com/CommonRoad/commonroad-carla-interface/blob/develop/crcarla/helper/config.py)、[CR PID 包装](https://github.com/CommonRoad/commonroad-carla-interface/blob/develop/crcarla/controller/vehicle_controller.py)、[CARLA PID 源码](https://github.com/carla-simulator/carla/blob/0.9.15/PythonAPI/carla/agents/navigation/controller.py)

**项目适配选择：**横向空间前视与纵向速度目标分开取样；不沿用 CR develop 包装器把 t+0.4 的速度也交给纵向环的做法。下一 tick 速度避免额外 0.4 s 的速度时间前移，但不是无延迟跟踪的保证。若上游参考以车身中心或后轴为基准，先做刚体点变换；速度取变换后位置对时间的导数模长，不能只移动位置而默认曲线上的标量速度完全不变。

循环固定为：在 t 读取自车快照 → 信息内环的所有 PLAN 使用该快照且不更新控制器 → 选最终参考 → **仅调用一次 PID、apply_control 一次** → `world.tick()` → 记录 t+0.1 的实测状态。第一批没有 PLAN，直接按绝对时间消费预存参考。停车/恢复期间不重建 PID、不清积分、不添加临时停车锁存；检验这套固定组合本身是否合格。

该 PID 有位置/方向反馈和速度反馈，但横向实际控制的是“车头指向前视点”的夹角，纵向控制的是速度差；它不直接闭环目标航向或沿程定时误差。因此 `e_long(t)`、停车位置和保持必须独立验收，不能用走到了同一条路径代替准时跟踪。

原生 Ackermann 不选作完整跟踪器：其转向没有路径误差反馈，`acceleration` 被取绝对值作为速度环的加速度限幅，`jerk` 没有进入执行控制律。不能把 RP/PDM 的有符号加速度直接接上就声称语义一致。[CARLA Ackermann 实现](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Vehicle/AckermannController.cpp)

### 1.3 自车状态和参考点契约

- 统一内部坐标为右手系、米、秒、弧度。CARLA 到内部坐标按同一固定原点映射 `(x,y,yaw) → (x,-y,-yaw)`；速度、角速度和转角也做对应变换。地图与对象用同一个变换。
- RP 状态用后轴中点。控制器反馈用 actor origin。碰撞车身用 `bounding_box` 的实际中心/朝向。不能把三者都叫 center；从实际蓝图轮轴/box 标定各刚体偏移，并保存原始单位及往返转换检查。
- 本车 pose、velocity、acceleration、wheel angles 允许读取自身 actor，作为**仿真精确定位/里程计假设**披露。其他车辆仍由合法感知或购买的证据进入。不得把此假设写成已完成真实车载定位。
- `get_velocity()` 的线速度参考点不能由 API 名称推定：CARLA 服务端继续调用 Unreal actor 的 `GetVelocity()`，物理控制里的 `center_of_mass` 又来自 COMNudge，不能直接当已知真实质心坐标。当前设计明确把“原生线速度可在规定误差内视作 actor-origin 速度”作为待验假设；第 3 节用姿态位置序列独立核验。通过后才按刚体关系转换后轴速度供 RP，并给误差留界；未通过则状态适配失败，不宣布控制/规划接口完成。RP 纵向加速度保留正负号，由相邻物理 tick 的后轴纵向速度作因果差分，禁止 `sqrt(ax²+ay²)` 代替。[CARLA actor 速度实现](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Actor/CarlaActor.cpp)、[车辆物理字段实现](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Vehicle/CarlaWheeledVehicle.cpp)
- RP 初始转角用前轮物理角和实际轴距/轮距构造等效曲率，不直接把左前轮角当自行车角。一个明确的低速无侧滑映射是：内部前轮角 δ_i、轮心侧向坐标 y_i、轴距 L，`kappa_i=tan(delta_i)/(L+y_i*tan(delta_i))`，取两前轮均值，再 `delta_eq=atan(L*kappa)`。直行时为零；左右符号、几何和稳态转弯 yaw-rate/后轴速度的一致性待核验。该映射是模型假设，不是已证 CARLA 动力学事实。
- 固定时刻多次 PLAN 不推进 planner iteration、路线进度、控制历史或实车；动态碰撞表必须只由当次合法 Scene 构建，不从官方 wrapper 的历史 world scenario 继承对象。

### 1.4 要改哪些模块

| 工作块 | 复用与有限改动 | 第一批是否需要 |
|---|---|---|
| 运行/状态 | 新的隔离 0.9.15 启动配置；本车状态/几何单位转换；复用已有同步采集经验 | 是 |
| 控制 | 新薄适配直接调用官方 PID；明确参考点及两个时间索引。旧 `pdm_control.py` 和失败 probe 保留 | 是 |
| 跟踪验收 | 独立解析参考、固定试验场、原始状态/控制日志和离线指标；不得 import planner/detector/MTR | 是 |
| RP 接入 | 一个合法 `Scene → Scenario/CollisionChecker → RP` 适配；配置实际车辆参数和固定约束，导出参考与失败原因 | 否，控制通过后另实施 |
| 静态地图 | 复用 `carla_map_inputs.py` 的来源/坐标经验，新增同版本车道多边形与路线到 CommonRoad 的映射 | 否 |
| F 历史/协议 | 第 2 节的 20→10 Hz 窗口、坐标与版本化时域；涉及 `vehicle.py`、`task_spec.py`、`evidence.py` 等消费者 | 否 |
| 方法循环 | 将 `episode`/worker 的 PLAN 边界绑定新后端，保持预算与同 t 语义；旧训练 driver 不作为低层驾驶器 | 否 |

不迁入 `CommonRoadPlannerController` 整体：其读取全局 actor 的场景构造及 Transform 选项不符合本项目边界。[官方整栈包装](https://github.com/CommonRoad/commonroad-carla-interface/blob/v1.0.0/crcarla/controller/commonroad_planner.py)

## 2. 真实 F 的来源、已有能力和缺口

### 2.1 固定使用的预测器

**CMP no-cooperation MotionTransformer，ToolV2X 因果历史适配后的 `full_seed20 / epoch09` 冻结模型。**

- 权重：`outputs/mtr_stability_v1/full_seed20/best_model.pth`，本轮核对文件存在，699,865,450 bytes。
- 选择绑定：[frozen_model.json](../outputs/mtr_stability_v1/frozen_model.json)；配置：`vendor/cmp_mtr/configs/v2v4real_multiego_no_coop.yaml`；intention points 文件也已存在。
- 历史严格加载记录：`outputs/t9_real_smoke_2026_09_13_v1/models.json`；已有真实预测与同信息重算记录：`outputs/mtr_full_seed20_connection_v1/`。本轮未重载模型或执行前向。
- `cmp_adapter.py` 的模块默认权重仍指向 CMP 原始 checkpoint，**新运行必须显式传入上述冻结路径**，不能依赖默认值。

这些事实支持“有真实模型、权重和既有输出”，不支持“已能在 CARLA 提供可靠 F”。[当前适配器](../src/prediction/cmp_adapter.py)、[既有稳定性结果](mtr_stability_results.md)

### 2.2 输入、上下文与原生输出

| 项目 | 已核实契约 |
|---|---|
| 历史 | 每个 source 的当前目标集合；每目标 t−1.0 到 t 的 11 个状态，间隔 0.1 s |
| 状态 | `states[N,11,7] = x,y,z,l,w,h,yaw`，另有 valid、scores；当前状态必须有效 |
| valid | 可用的因果 tracker state；不等于 detector_hit，不用未来补缺 |
| 完整上下文 | provider 在 t 的全部当前 tracks 先入模，随后才按请求/ROI/容量选返回目标 |
| 外部资源 | 活跃实现只编码对象历史；不需要地图多段线、BEV、未来真值或邻车的已知驾驶计划 |
| 原生输出 | raw pred_trajs 为每目标 6×50×5 的 GMM 参数；适配器恢复坐标后导出 6×50×2 均值 xy，0.1–5.0 s，另有模式分数；local_gmm 保留其他参数 |
| 短历史 | 至少 2 个 valid 状态才实际调用 MTR；否则 `model_used=false`，现有实现返回静止锚点 fallback，必须原样标明来源 |
| 能力边界 | 非 ego-plan-conditioned。current/change 改请求检索/排序，不等于模型预测了对新 ego 计划的反应 |

依据：[窗口校验](../src/probe/kinematic_tools.py)、[模型适配](../src/prediction/cmp_adapter.py)、[真实工具调用](../src/tools/vehicle.py)、`vendor/cmp_mtr/mtr/models_v2v4real/context_encoder/mtr_encoder.py`。原生 CUDA 算子一致性与最初 checkpoint 的完整训练溯源尚未全部确认；不能抹去原记录的这些限制。

### 2.3 规划时域由真实 F 约束，显式升级旧协议

现有 wire 只返回 0.5、1.0、…、3.0 s 的六点，**当前接口不能直接供应首选的 4 s 规划**。本方案决定新建明确的协议版本：F 发送原生 0.1 s 网格上的 `6×50×2` 六模态均值 xy 与模式分数（不传 GMM 尺度/相关参数）、当前锚点、origin time、dt、valid-until、model_used/source binding；PLAN 内部为 4 s/0.1 s，request 的轨迹摘要改为 0.5–4.0 s 的八点。旧六点记录仍按旧版本解释，不自动补点或重标时域。

选 4 s 是本轮工程设计：为 0–4 m/s 的初期运行留出停车/等待决策窗口，并给原生 5 s F 留出最多 1 s 的物理龄期；不是已证明足够覆盖所有论文任务。对每个返回检查 `age + 4.0 ≤ 5.0`；超期 F 不消费其过期部分，标明失效并走所有臂共用的基准预测/失败策略。RP 不另读 4 s 以外的动态占用；后续若发现后端实际需要更远查询，必须重新设计时域，不能静默外推。同步暂停的墙钟耗时另计成本，不当作物理时间流逝。

成本变化不能隐瞒：单目标 xy 从 72 个数增加到 600 个数，数量约 8.33 倍；float32 数值体由 288 增至 2400 bytes，**这不是最终 wire 字节数**。最终按真实序列化 bytes、远端/本地计算与延迟计费，旧预算阈值不得直接宣称等价。首版规划只消费最高分模式，六模式和分数保留并计费；不称完整利用不确定性。这个选择有通信代价，若研究预算容纳不了，应在方法实验前重新冻结传输规格，而非截断后仍声称 5 s。

**新版接口必须一起完成以下适配，不能全局替换一个 TIMES 常量：**

- 三个时间轴分开：request=4 s 八点，仅用于检索；F payload=5 s/50 点；RP occupancy=当前 anchor 加 4 s/40 点。F 排序取原均值数组 indices `[4,9,14,19,24,29,34,39]`；P 检索 proxy 用同样八个时刻。传输仍保留 F 全 50 点。
- P 路径的共同因果基准预测单独生成 40×0.1 s 动态占用；不能把八点检索 proxy 或未购 F 当作该占用。
- `origin_time/valid_until` 使用仿真 tick/time。首版仅允许非负、0.1 s 整数倍的 age，记 k=age/0.1；未来占用取原 F 的 `[k:k+40]`。非栅格 age 拒绝消费。k>0 时当前状态来自当时合法状态源，F 的当前预测位置只作预测锚点一致性诊断，不伪装成新观测。所有 origin-frame 坐标先用保存的 origin pose 变为稳定 world frame，再进入当前规划坐标，禁止只切索引不变换坐标。
- forecast 的字段身份必须包含 schema/time-grid/horizon revision；receipt、field reference、ledger、cache、dedup 都隔离版本。现有 field_key 没有时域身份，仅改 response.version 会造成旧六点/新50点冲突。
- 旧 `ExecutionSpec` 的 response 8192 bytes、episode 24576 bytes、max_targets=4 不作为新版默认。新版启用前必须冻结预算 profile，并证明最终 header 加至少一个完整目标可编码；容量不够应真实返回 budget_empty，不分拆或隐式截断 atomic target。本轮不启动 F 调用，新的方法预算数值尚未确定，不能将此项包装为已具备可调用的新版 F。
- 实施范围包括 `task_spec.py` 的校验/排序/字段身份、`vehicle.py` 的 encoder/decoder、`evidence.py`、`planning/inputs.py` 的 forecast 形状，以及复用方法循环时的 `method_episode.py`、`method_controls.py`、plan validation 和 bundle candidate。`query_value.py` 的六点 feature identity、旧 structured-driver 张量及旧 3 s evaluation/labels 必须隔离；新 RP 路径不调用它们，不能默默改旧实验解释。
- 完整 P + same-MTR 对照比较完整 50 点均值、scores、model_used、track order 和 fallback，不只比较旧 wire 的六点。已有 independent_array_check 可作模板。

这是明确的协议迁移工作，尚未实施；预测器本身无需更换或训练。

P 和 F 进入同一个动态障碍接口：P 改当前状态/历史并使用共同基准预测；F 改同实体未来占用；两者都能改变同一个规划器的可行候选与选择。F 的当前锚点价值与未来增量分开审计。完整 P + 相同 MTR 是同信息对照，ROI P 子集不是；实际通信/计算成本分别报告。[既有数组一致性记录](../outputs/mtr_full_seed20_connection_v1/independent_array_check.json)

### 2.4 已有资源够做什么，还缺什么

| 状态 | 具体结论 |
|---|---|
| 已经能提供 | V2V4Real 因果窗口上的真实冻结 MTR 预测、六模式原生数组、旧 3 s wire；完整 P 同模型重算曾有数组一致证据 |
| 资源已具备但还需适配 | 已有 CARLA 双车各 30 帧、20 Hz 的 world tracks。保存 21 帧连续历史，按当前 t 的 `t−20,t−18,…,t` 取 11 点；每个历史 box 投影到同一个 t 时刻坐标。当前脚本尚无这个 MTR history adapter |
| 尚未提供 | CARLA tracks → 冻结 MTR → 新 5 s F wire 的真实产物；0.9.15 下检测/跟踪输入分布的复核 |
| 尚未知质量 | CARLA 上 3/5 s 误差、冲突时序、top-1 分支可靠性、短历史/遮挡质量及下游价值。现有 1.45 s 记录连完整 5 s 标签都不具备 |

20 Hz 方案适用于已有数据；后续若传感器/跟踪统一为 10 Hz，则连续取 11 帧，并明确记录 rate profile，不能把帧数当时间。模型特征始终是同一 11×0.1 s 契约。GT future 只可用于后续离线质量评价；本车/peer 的当前物理真值不能替代检测历史。若冻结模型在目标域无有效预测增量，应暂停依赖 F 的方法实验，而不是现在默认追加训练。

## 3. 首批验证：仅检验预先给定参考的真实跟踪

本节所有数值是**试验前设计的验收值，尚无实跑结果**。通过只证明下面低速、平坦、给定轨迹域的控制能力；不证明规划质量、真实感知质量、P/F 收益或论文结论。

### 3.1 固定车辆、试验场和初始化

- CARLA 0.9.15，`vehicle.lincoln.mkz_2017`，原默认质量、动力、轮胎、摩擦、转向曲线和自动变速箱；全程 physics enabled。禁止 autopilot、Traffic Manager、位置/速度强制赋值。
- 同步 dt=0.1 s、子步 0.01 s×10；天气 ClearNoon，干燥无风，其他车辆/行人数量 0。控制只读当前本车状态及预存参考；仅设置碰撞记录，不运行 LiDAR/检测/tracker/PDM/RP/MTR/LLM。
- 试验场设计为生成式 OpenDRIVE 平坦柏油单路：长 600 m、宽 120 m，路面覆盖 x∈[0,600]、y∈[−60,60]，z=0，无 junction、坡度和路侧障碍。参考后轴起点固定 `(50,0)`、航向 0，以下解析坐标相对此点给出。所有参考的完整车身扫掠距真实路面边界至少 5 m。fixture 目前尚未生成/加载，加载或碰撞网格不符即停在环境预检，不能换一块碰巧通过的路面。
- 用参考后轴路径及其两侧 1.75 m 的边界定义虚拟 3.5 m 走廊，端部沿初末切线延长 10 m，避免车身端部被人工封口截断。整车检查按 world_actor_transform 与 bounding_box_local_transform 的复合变换得到实际车身多边形，再与整段走廊边界比较，不只看后轴或四角；边与边相交也要检查。
- 旧 0.9.10.1 记录约为：宽 2.128324 m、轴距 2.87113 m、后轴到车身前端 3.84849 m、到后端 1.05320 m、到 actor origin 1.39360 m。新版本必须重新读取实际几何；任何长度与旧值差异 >0.01 m 时暂停核对蓝图/单位/版本，不静默继承旧参数。这里只使用旧值作可行性估算。

每格使用新 actor，初始化固定为：按后轴固定起点反算 actor 的 x/y，spawn 高度 1.0 m → brake=1、throttle=0 稳定 2.0 s → 自动挡下 throttle=0.10、brake=1、steer=0 固定预载 1.0 s。预载后必须 gear=1、速度≤0.05 m/s、预载期间后轴位移≤0.02 m；否则预检失败，不延长等待或增加油门。**这是进入 Drive 挡的固定准备条件，不是停车验收的一部分。**

随后第一个观测定义 t=0；不按实际起步时刻重新计时，不把参考原点移到漂移后的实际位置。顺序固定为：完成稳定/预载 → 取得 t=0 快照并核验后轴 x/y、yaw、前轮角、gear、速度及最后一次 control → 创建一次 PID，使其 past_steering 来自最终初始化状态 → 发出 t=0 命令。t≥0 的所有正常控制来自同一 PID。初始后轴位置误差须≤0.02 m、航向误差≤0.005 rad、前轮物理角各≤0.01 rad。预载数值是本稿提出的唯一初值，尚未验证，不能从历史记录推断它一定成功。

### 3.2 参考轨迹的生成与独立可行性检查

所谓“已知可执行参考”，在实跑前严格表述为**独立于规划器、满足声明运动学/几何约束的解析参考候选**；本车动力学是否能跟踪正是本批待检验的假设。

定义 `q(u)=10u³−15u⁴+6u⁵`，u∈[0,1]。每个加/减速段：

`v(t)=v0+(v1−v0)q((t−t0)/Tv)`，`Tv=2V 秒`，V∈{2,4} m/s。

因此 `max|a|=0.9375 m/s²`；V=2/4 时 `max|j|` 分别约 0.7217/0.3608 m/s³；端点的 a、j 均为零。弧长由 v 积分，区间外维持端点速度。直线曲率为零。

左右转弯用 σ=+1/−1，转弯入口后弧长 s_c∈[0,24] m：

```text
0 ≤ s_c < 8:   kappa = σ × 0.05 × q(s_c/8)
8 ≤ s_c < 16:  kappa = σ × 0.05
16 ≤ s_c ≤24:  kappa = σ × 0.05 × [1−q((s_c−16)/8)]
```

转弯段恒速 V；按 `dx/ds=cos(yaw)`、`dy/ds=sin(yaw)`、`dyaw/ds=kappa` 构造后轴路径。转弯总航向变化为 ±0.8 rad；最大曲率 0.05 m⁻¹，半径 20 m。旧轴距下等效转角约 0.1426 rad；V=4 时最大横向加速度 0.8 m/s²、曲率变化引起的横向 jerk 0.75 m/s³。首批包含平缓转弯，不等于已验证城市 90° 路口等全部机动。

生成器用固定 0.001 m 弧长步长 RK4 积分路径，在精确的 0.1 s 时刻采样；另用半步复算验证位置差≤0.0001 m、航向差≤0.00001 rad。速度积分可直接使用 q 的原函数。每行保存 t、后轴 x/y、yaw、v、a、jerk、curvature、curvature_rate；再由实际几何生成 actor-origin 位置及其导数速率供控制。actor-origin 的曲线速度可由刚体导数 `p_dot_actor=p_dot_rear+omega×r` 求得。

CARLA 启动主批前，独立检查：上述连续性和数值上界、时间点完整性、终态速度为零、无倒行、完整参考车身离走廊边界≥0.30 m。旧几何在最紧曲率处估算仅约 0.34 m 余量，必须用新实测几何和完整路径核算；若不满足，应判 fixture/reference 设计未通过，不先跑再放宽条件。

### 3.3 恰好 8 格的参考与运行预算

表中 A=按上述 smoothstep 加速，D=同式减速，C=恒速直线，H=静止，K=24 m 的完整曲率段；所有未标速度的 A/D 均在 0 与该行 V 之间变化。

| 顺序/案例 | V | 精确时间段（秒） | 终止时间/弧长 |
|---|---:|---|---|
| 1 S2 | 2 | H 0–1；A 1–5；C 5–9；D 9–13；H 13–15 | 15 s / 16 m |
| 2 L2 | 2 | H 0–1；A 1–5；C 5–7；K左 7–19；C 19–21；D 21–25；H 25–27 | 27 s / 40 m |
| 3 R2 | 2 | 与 L2 相同，K 取右转 | 27 s / 40 m |
| 4 SR2 | 2 | H 0–1；A 1–5；C 5–9；D 9–13；H 13–16；A 16–20；C 20–24；D 24–28；H 28–30 | 30 s / 32 m |
| 5 S4 | 4 | H 0–1；A 1–9；C 9–11；D 11–19；H 19–21 | 21 s / 40 m |
| 6 L4 | 4 | H 0–1；A 1–9；C 9–10；K左 10–16；C 16–17；D 17–25；H 25–27 | 27 s / 64 m |
| 7 R4 | 4 | 与 L4 相同，K 取右转 | 27 s / 64 m |
| 8 SR4 | 4 | H 0–1；A 1–9；C 9–11；D 11–19；H 19–22；A 22–30；C 30–32；D 32–40；H 40–42 | 42 s / 80 m |

每格一次有效运行，固定上述顺序；总有效仿真时间上限 216 s、2160 次控制，再加每格固定 3 s 初始化。无随机交通；记录统一 seed=0。第一批是有限工程门槛，不以八格一次运行估计统计可靠率。任一格失败即停批；不是跳过失败跑完再选好看的案例。

每格 N=T/0.1：状态记录 i=0…N（含终点）；控制只在 i=0…N−1 调用，apply 后 tick 并记录 i+1。t=T 只评价、不再发命令。参考明确定义到 T+0.4，T 之后均为静止终态，供最后几个控制 tick 前视；不追加“再等它停下”的运行时间。

### 3.4 时间对齐、指标和 PASS 条件

在 t_i=i×0.1 s 观测自车，以**同一时刻**参考的切向 T_ref、法向 N_ref 计算：

`e_long=(p_rear_actual−p_rear_ref)·T_ref`；`e_lat=(p_rear_actual−p_rear_ref)·N_ref`；`e_yaw=wrap(yaw_actual−yaw_ref)`。

禁止时间平移、最近轨迹点匹配、DTW、按起步重置时间、去掉换挡/起停样本或终点对齐。前视只是控制算法输入，不改变评价时钟。评价用后轴位置序列的中心差分 `(p[i+1]−p[i−1])/0.2` 得到同 t 速度，再投影车头方向；端点用二阶单边差分。它只用于离线评价，不送回在线控制或 PLAN。速度误差比较此后轴有符号速度与同 t 的 v_ref；控制器仍按 actor-origin 参考速率工作。

| 验证项 | 每格必须满足 |
|---|---|
| 数据/执行 | 无碰撞、NaN/Inf、缺 tick、非法命令、倒挡；前向速度≥−0.02 m/s；最大速度≤4.25 m/s |
| 沿程定时误差 | max abs(e_long)≤0.75 m；RMSE≤0.40 m |
| 横向与航向 | max abs(e_lat)≤0.30 m；RMSE≤0.15 m；max abs(e_yaw)≤0.10 rad |
| 移动段速度（v_ref>0） | RMSE(e_v)≤0.35 m/s；max abs(e_v)≤0.75 m/s |
| 整车几何 | 每 tick 完整车身离虚拟走廊边界≥0.15 m |
| 速度参考点假设 | 转弯移动段原生水平速度向量与 actor 位置中心差分的差≤0.10 m/s，速率差≤0.05 m/s；否则状态/控制适配 FAIL |
| 动态响应 | max abs(a_long)≤2.0 m/s²；max abs(a_lat)≤1.2 m/s²；P99(abs(j_long))≤5.0 m/s³ |
| 每次起步/恢复 | 加速段中点 v_actual≥V/2−0.40 m/s；段末≥V−0.30 m/s，且全局位置/速度门槛仍成立 |
| 每次停车 | 到参考速度首次为零后允许固定 1.0 s 收敛；此后到恢复前/终止的每 tick 速度≤0.10 m/s，累计后轴路程≤0.10 m，保持末端 abs(e_long)≤0.50 m |
| 恢复时机 | SR2 的 t<16、SR4 的 t<22 属于保持窗口，仍须满足停车门槛；预览不能作为提前移动的免责理由 |
| 转弯 | K 段结束时累计实际航向变化与 ±0.8 rad 相差≤0.08 rad，且全过程航向/位置/走廊门槛成立 |

动态响应指标从相邻 tick 的上述离线后轴世界速度差除以 0.1 s，再投影到当前车体轴；jerk 为相邻有符号 a_long 的差除以 0.1 s。首个差分不足样本只标记不可计算，不用零填充；不平滑、不删峰。P99 固定采用排序后的 nearest-rank 定义，同时报告原始最大值。碰撞/执行保护记录与普通跟踪指标分开保留。

每个 2 s 末端保持，严格窗口为最后 1 s；SR 的中间 3 s 保持，严格窗口为后 2 s。收敛期仍计入全局时标/横向误差和动态指标。停车的“累计路程”是逐帧位移模长求和，不能用首末净位移掩盖往返波动。

### 3.5 最小顺序、失败含义及停止规则

| 顺序 | 做什么 | 失败意味着什么 |
|---|---|---|
| A 静态预检 | 核对 server/client/agents 版本、几何、参考点变换、参考时域/解析约束、走廊扫掠、日志字段及单位 | 环境或规格尚未闭合；不能开始主批，也不能判 planner 无效 |
| B 固定初始化 | 仅执行规定的落地/挂挡预载，核验 gear、速度、位移及地面稳定 | 所选运行初态无法按固定步骤建立；停止，不临时寻找新的油门/等待时间 |
| C S2、L2、R2、SR2 | 固定参数，检验 2 m/s 起停、弯道、恢复 | 该控制消费方式/控制器在低速基本域不达要求；与 F、感知、候选切换无关 |
| D S4、L4、R4、SR4 | 原配置检验 4 m/s 上界 | 不能将 2 m/s 通过外推为 4 m/s；本批整体 FAIL，不能暗中把论文速度域改窄 |
| E 原始数据独立复算 | 从参考文件和帧日志复算全部误差、窗口与判定，与运行汇总比对 | 日志或检查器结论不可信；在结论不一致时不得宣布通过 |

碰撞、离开真实路面/虚拟走廊、abs(e_lat)>0.75 m、速度>4.5 m/s、倒车、非法数值或控制异常，立即停止该格并终止整批。可以施加 brake=1 作为**中止后的保护动作**，不得计作正常跟踪通过。一般阈值超限允许完成该格的固定时间以保留诊断，但该格 FAIL 后不进入下一格。

只允许“第一个有效控制 tick 之前”的 server 崩溃、fixture/日志初始化失败原配置重试：每格最多一次、整批最多两次；不增加有效试验数。有任何有效控制 tick 后的错误必须保留为失败，不能换标签后重跑。

改变任一 PID 值、前视、初始化、参考、车辆物理或阈值，都形成新设计版本，经审阅后重新从第一格开始，不能覆盖旧失败。本批通过后也只交付控制门槛结果，后续理想输入规划、真实感知和 F 质量均为独立工作，不自动启动。

### 3.6 交付产物和当前未知项

将来实施时只用一个新目录 `outputs/backbone_tracking_gate_v1/`：保存运行清单、实际蓝图/物理参数、OpenDRIVE、8 条 reference、每 tick 的当前 actor/后轴状态、gear、两种控制目标、完整 VehicleControl、碰撞/异常、初始 PID 状态、逐项指标和独立复算结果。文件/版本/配置以可读来源标识，不覆盖旧 probe。

当前未知明确保留：0.9.15 本地可启动性及资源尚未验证；同名蓝图实际几何、轮角及原生速度参考点未实测；固定预载能否挂入 1 挡未知；上游 PID 预设能否达到严格时标/停车门槛未知；RP 参数/地图接入及 F 的 CARLA 域质量均未验收。**本轮确定的是可实施且可被否定的组合和试验规格，不是已经合格的共同底座。**
