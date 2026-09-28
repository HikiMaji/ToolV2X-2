# PDM 项目适配最终独立复审及 batch2 配置核对（2026-09-22）

## 范围与方法

本次先在 batch1 按预声明执行期间只读复审冻结的 `src/planning/pdm_core.py`、`src/planning/pdm_control.py`、对应测试、runtime 与 `predeclared.json`；batch1 实际 FAIL 后，再只读比较 `batch1_sources/`、`batch2_sources/` 与 `batch2_change.json`。没有启动额外 CARLA、修改运行源码或训练；本文件是本次唯一修改。

batch1 冻结时的实时源码与 `batch1_sources/` 一致；batch2 当前源码与 `batch2_sources/` 一致。两个 snapshot 文件集合相同，递归差异只在 runner 的 probe 版本和 `lateral_offsets=[]` 两处。静态 AST/JSON 解析和限定文件 `git diff --check` 已通过。`planner_green.log` 记录 core/control 合并 33 项在 PDM 环境通过，包括 pristine upstream v1 对照；`control_green.log` 另记录 15 项控制定向测试通过。这些是冻结前已有日志，本次没有在实时三臂期间重跑。

## 结论

没有发现实际 P1/P2 源码问题。冻结实现满足本批声明：v2 控制轨迹来自经过原 PDM scorer 评分、项目 hard mask 后选中的 2 秒动力学模拟；非有限候选结果整体 fail closed，负向运动、负向位置和初态漂移不能入选；v1 保持独立旧路径和旧输出契约。停止保持与释放只依赖当前实测自车速度、适配器自身历史状态以及由本帧合法 PlanningScene 生成的 v2 rollout，没有读取未来自车 GT、peer actor 真值或评价字段。

batch2 是有明确几何根因的配置层纠正：移除无法装入已声明单车道的固定 ±1 m 横向参考，只保留中心线上的五个纵向候选。它是共同 single-route lane-keeping 操作域的收缩，不是 lane-change、obstacle-bypass 或几何自适应能力改进；core/control 源码未改。

本结论是代码、配置差异与合成契约 PASS。batch1 的三臂结果保持 FAIL；本审查不预判 batch2 结果，也不构成驾驶质量、实时性、舒适性或 P/F 方法收益结论。

## Batch1 FAIL 与 batch2 配置纠正

- `batch2_change.json` 声明的车道宽为 3.500029 m、本车宽为 2.128324 m，轴向对齐时可容纳的最大中心偏移为 `(3.500029-2.128324)/2 = 0.6858525 m`。固定 ±1 m 参考超过该上限约 0.3141475 m，其完整车身最终不能留在声明的单车道内。2 秒短 horizon 可能在过渡尚未完全越界时暂时接纳该候选，因此 batch1 的候选切换、转向波动和 no-feasible brake 有具体配置根因。
- `batch1_sources/` 与 `batch2_sources/` 的递归 diff 只有 runner 两行：`toolv2x_pdm_project_probe_v1` 改为 `v2`，以及 execution spec 从仅指定 core v2 改为 core v2 加 `lateral_offsets=[]`。前者是证据版本标识；后者是唯一规划行为变化。core、control、worker 和两份测试逐文件相同。
- core 始终构造 `[centerline] + lateral_offsets`。batch1 默认三条 path（中心、-1 m、+1 m）与五个 `speed_limit_fractions` 形成 15 个候选；batch2 只有中心线一条 path，仍与相同五个纵向策略形成 5 个候选。检测、跟踪、控制器、车辆物理、地图路线、传感器、运行时长和验收门槛均未改变。
- 该修改不把 batch2 当作同配置重复样本，也不回溯重分类 batch1。它只回答中心线车道保持、前车停车和前车释放；不能支持换道、绕障、多车道选择或一般几何自适应横向 proposal。以后 Ego/P/F 各臂必须共用这一 maneuver domain，才可比较远端信息作用。
- batch1 还违反了加速度等门槛；移除横向参考是否同时解决这些实际失败，必须由 batch2 逐帧结果和独立复算决定，不能仅凭几何诊断预先归因或宣称通过。batch2 是预声明允许的最后一批。

## 先前 finding 关闭状态

以下先前问题均已在冻结源码中修复，不再作为未解决 finding：

1. `unconfirmed_track_brake` 已由 `unconfirmed_track_holds` 计数，验收和 `predeclared.json` 均要求为 0。
2. runner 会把完整协议、批次号和修改原因归档到 `batch.json`；批次限制为 1/2，第二批原因使用 `strip()` 后必须非空。
3. worker 与 client 初始化位于外层 `try` 内，部分启动失败会进入 worker/log 清理。
4. 协议的 runs/dt 一致性已改为显式 `if` 和 `ValueError`，不再依赖会被 `python -O` 移除的 `assert`。
5. summary 写出与 CARLA teardown 已用嵌套 `try/finally` 分离；sensor/actor 单项清理失败不会阻断后续 actor 清理，world settings 仍会尝试恢复。
6. `PDMControlAdapter` 已精确要求 `rollout.source == 'selected_scored_simulation'`，测试 fixture 同步正式标识，并新增拒绝 raw generator 来源的测试。

跨输出目录的全局批次注册仍由操作过程控制；当前设计只承诺单次 runner 校验和输出内协议归档，符合本批预声明边界。

## PDM core v2

### 实际被评分的 2 秒输出

- v2 固定 `dt=0.1`、`proposal_steps=20`、`output_steps=30`。前 2 秒用于 proposal simulation/scoring，3 秒 observation horizon 保留原 TTC 所需前视；其他 v2 时域组合直接拒绝。batch2 只通过 execution spec 覆盖 `lateral_offsets=[]`，没有改变这些时域或数值核心。
- `PDMSimulator` 生成 21 个状态的候选轨迹，并在 v2 注入当前车辆实际 wheelbase。`PDMScorer` 对这些 `simulated` 候选计算分数，选择也在同一数组上进行。
- 最终 `rollout` 直接取 `simulated[selected]`，包含 0.0–2.0 秒的 0.1 秒密集位置、heading、速度和纵向加速度。0.5/1.0/1.5/2.0 秒稀疏 `waypoints` 也从同一数组索引取得，没有再回到未模拟的 generator path。
- 测试逐元素比较 rollout、稀疏 waypoint 与 `simulated_proposals[selected_index]`，同时检查正式 source 标识。

### hard mask、负速与非有限值

- hard admission 要求原 scorer 的三项 multiplicative metric——no collision、drivable area、driving direction——逐项严格等于 1。任一项不满足都会记录原因并排除该候选。
- v2 在候选判定前检查全部 `scores` 和 `simulated` 为有限值；任一 NaN/Inf 会抛 `ValueError`，不会进入 JSON RPC 或通过 `argmax` 选择。`_candidate_feasibility` 仍保留逐候选 `nonfinite` 原因逻辑，但正常 core 路径采用更严格的整批 fail closed。
- 任一时刻 signed `VELOCITY_X < 0` 会标记 `reverse_motion`；局部 `X < -1e-5` 会标记 `reverse_position`；第 0 状态与当前 `ego_state_to_state_array(ego)` 不一致会标记 `unanchored_initial_state`。速度只有在这些检查通过后才以 `hypot(vx, vy)` 作为非负控制速度输出。
- 选择使用 `np.where(feasible, scores, -inf)`，只在 hard-feasible 候选中取最高分；没有可行候选时 `selected_index=None`、无 rollout，并显式返回 brake fallback。EmergencyBrake 也接收同一 masked scores，不会重新选回被 hard mask 排除的候选。

### v1 兼容

- 默认 execution spec 仍是 `toolv2x_pdm_core_v1`。v1 在进入 v2 非有限检查与 hard admission 前走原有 emergency/generator trajectory 分支，结果版本和字段保持 v1；不会出现 `plan_status`、`candidate_feasible`、`rollout` 等 v2 字段。
- 实际 wheelbase 注入只在 v2 启用，避免改变 v1 上游数值。已有 pristine upstream 测试对 waypoints、heading、scores 和 simulated proposals 做严格数值对照并通过。

## PDMControlAdapter

- 适配器只接受 `selected_feasible` 的正式 scored-simulation rollout，或把 `no_feasible_candidate` / `emergency_brake` 显式转成制动 hold。未知状态、错误 source、错误时域/形状、非有限数值、负速度、非原点锚定、负向位置和无前向路径均失败关闭。
- 进入停止锁存同时要求当前实测速度不高于 0.2 m/s、当前 2 秒 rollout 最大速度不高于 0.2 m/s、rear-axle 路径总长不高于 0.3 m。路径距离不混入随 heading 旋转的 rear-to-actor offset。
- 锁存后，仅当本帧合法 rollout 最大速度达到 0.4 m/s或路径总长达到 0.6 m 才释放；否则持续 `hold_stopped`。这些量来自当前 PlanningScene 的模拟输出和当前自车状态，不来自未来执行结果或评价 GT。
- 跟踪模式以密集模拟轨迹上 0.5 秒的显式速度作为 PID 目标速度，以 actor-origin 动力学轨迹上的 0.5 m 空间前视点作为转向目标。runtime 再应用已声明的低速油门上限；三种实验臂共用同一逻辑。

## 输入权限、时标与证据边界

- core 的 `validate_scene` 使用精确字段白名单，不接受 World/Actor/label handle。runtime 的 scene 仍只来自同帧本车 LiDAR、当前本车状态、因果 tracker 和静态路线；peer actor 真值只用于场景生成、预声明释放动作及控制后的 evaluation。
- scene timestamp 绑定当前扫描；tracker 要求 frame 连续与 50 ms 间隔；PDM 内部固定 0.1 秒模拟时标。同步推理期间仿真暂停，因此这不是实时 20 Hz 证明。
- worker 的异常经 JSON error 返回并使 case 失败；runtime 的 invalid plan、无可行候选和未成熟 track hold 均有独立计数/验收语义。输出失败不会改记 PASS，清理修复如上。
- 33 项测试主要是合成几何和接口契约。batch1 失败证据必须保留；最终 CARLA 工程验收仍须依据 batch2 的 `batch.json`、逐帧文件、summary、独立复算和运行后资源复核。即使 batch2 通过，也不得把本审查写成换道/绕障能力、方法收益或完整 P/F 闭环结论。
