# 本轮独立审查与处置

审查对象为 v1 源码和逐帧产物；审查者 closedloop_review。

确认 rear axle 轨迹与 CARLA actor 原点不一致：lead 第116行/frame40312首次被适配器强制制动，实速0.5145m/s，PDM仍要求前进。53/160步来自适配层 hold，因此 v1 停车不能归为 PDM停车。

v3用未来heading旋转 rear-to-actor offset后选择actor原点目标；该偏移来自当前actor transform，不使用bounding-box center。短前进路径仍有效。定向回归验证短路径、旋转、单位和停止；v3真实320步均pdm_pid，无hold。

修复期间v2发现上游generator仅写STATE_SE2，EgoState速度字段为未填充零值。放弃读取该字段，v3按actor轨迹前两个采样点位移/时间计算目标速度。这是控制桥接规则，不修改原PDM候选或宣称原PDM已给出该速度。

审查者没有独立复审v3；最终版本由主agent运行针对性测试与真实复测。v3 lead预声明验收失败，未通过修改阈值重分类。
