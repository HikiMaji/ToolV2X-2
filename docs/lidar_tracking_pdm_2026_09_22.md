# 本车排除、因果跟踪与PDM真实输入接通（2026-09-22）

## 本轮结论

已用原V2Xverse预训练检测器、既有AB3DMOT和原PDM，在新采集的双车连续原生LiDAR上接通局部输入链。30个ego固定时刻中26个规划相对移除障碍物的诊断对照发生变化；最后一帧3秒前进距离4.56m，对照10.64m。这证明真实检测/跟踪输入影响同一规划器，**不证明协作收益、碰撞避免或闭环安全**。未运行P/F远端查询、MTR、LLM或训练。

## 数据与输入权限

Town03受控短同车道场景，两辆Lincoln相距15m，前车制动，后车以4m/s初速滑行。共30帧/车，真实步长50ms（第一帧到末帧1.45秒）。控制用于数据采集，不由PDM输出控制，因此不是规划器闭环。

LiDAR采用官方wrapper参数：64线、85m、20Hz旋转、500000点/秒、10/-30度上下视场、原衰减/dropoff；安装x=1.3m,z=1.85m,yaw=-90度。与上一轮简化传感器配置分开。每个传感器frame/timestamp与world snapshot匹配后才保存。

各车记录独立点云、当前自车位姿/速度/加速度、轮轴/车身几何。检测只读该车点云及lidar_pose_z；各跟踪器只消费各自检测及当前本车标定。没有全局actor列表/对方GT姿态/未来轨迹进入跟踪或PDM。批处理归档同时包含两车，但没有跨车融合/ID关联。

新采集已建立时标；旧官方录制仍不据文件号推测时间。首次服务端启动未就绪导致load_world超时，保留失败日志与空目录；确认服务端版本可查询后，在新目录采集成功。结束后销毁本次actor、恢复world设置并停止自启服务端。

## 本车排除与跟踪

- 本车排除：使用当前本车位姿和真实bounding_box几何，BEV IoU>=0.5时判为本车；阈值在运行前固定于版本化execution_spec，没有按效果改阈值。保存原始世界框、IoU、删除原因和保留框。
- 60条样本共移除60个本车框，保留60个对方车辆检测；各车连续30帧保持一个本地track ID。两车ID空间独立，不能将相同数字ID当作跨车统一身份。
- 复用原AB3DMOT Hungarian/GIoU3D、min_hits=3、max_age=2；这些是既有工程参数，不宣称V2Xverse最优。固定采样经真实时间验证后，把Kalman每步位移除以0.05得到m/s；不连续frame/时标拒绝，不静默补帧。
- 新适配明确KITTI camera yaw=-world yaw，底部y=-中心z+h/2；实际上游Box3D角点测试验证，不只做自反转换。旧V2V4Real转换函数和已有实验未修改。
- 输出区分detector_hit、time_since_update、hits。实际本批无丢帧；测试覆盖因果预测维持状态，不能把history有效等同于逐帧detector hit。
- 首帧速度为Kalman零初始化，外层审计标为unknown；PDM当前接收到的仍是0速度，**没有未知速度专用处理或不确定性建模**。该简化明确保留，不冒充观测速度。

## PDM与限制

本车当前rear-axle RH坐标、车道多边形、真实检测轨迹进入原PDM；轨迹使用causal tracking-state motion proxy，未调用MTR。当前只适配车辆类和受控单车道片段；对信号/路口没有部署覆盖，也不能由单车道ID推出无信号。PDM输入中的signal_constraints仍为空，使用范围仅为这次无交通参与者额外投放的短片段接口验收。

首轮60次PDM调用为30帧有障碍/空障碍配对；空障碍臂仅是删除输入的敏感性诊断，绝不是论文中的Ego baseline。所有帧平均六点位置变化约1.99m，并非误差下降。冻结前缀因果测试和独立回放用于代码验证，不是方法统计证据。

原生产method_episode/ledger/P/F服务尚未绑定到这条新感知链。局部轨迹的parent_refs只表示本地检测帧依赖，不是远端receipt或完整field admission证明。

## 文件与检查

- src/tracking/lidar_tracks.py：几何本车排除、KITTI转换、固定实测时标AB3DMOT适配与PDM对象转换。
- scripts/capture_native_lidar_probe.py：受控连续原生点云采集。
- scripts/probe_lidar_tracking.py：独立本车跟踪及场景导出，完整execution_spec随记录保存。
- scripts/probe_pdm_tracks.py：原PDM固定时刻敏感性复跑。
- tests/test_lidar_tracks.py：本车/相邻车分离、坐标角点、m/s、前缀因果性、时间拒绝和预测维持。

跟踪定向7项通过；PDM、地图及输入相关17项通过。完整轻量回归见最终记录。未提交或推送GitHub。

原始采集：outputs/native_lidar_tracking_2026_09_22_v2；检测：outputs/native_lidar_detections_2026_09_22；跟踪/场景/规划：outputs/local_tracks_pdm_2026_09_22；精简证据：docs/evidence/lidar_tracking_pdm_2026_09_22。

下一步应做本车规划到原生低层控制的短路线验收，并把当前本车链作为共同基线；随后才能接邻车P、跨车关联和真实收益对照。不能拿本批空障碍诊断代替Ego/P实验。

独立审查发现晚出现目标在确认前漏记检测依赖，已用失败测试复现并修复；原60行结果逐项完全不变。可执行PDM脚本又复跑60次调用，六点输出逐项一致；累计120次PDM调用，统计样本仍为30帧，不把复跑当新样本。

最终轻量回归362项通过（239.130秒），主目录跟踪7项通过，PDM/地图/检测读取17项通过，git diff --check通过。检查计数有覆盖重叠，不相加为独立测试总数。

### 保留的启动异常

采集通过set_target_velocity设置4m/s初速度后立即记录，首帧本车加速度约80m/s²，第二/三帧约-12.66/-9.40m/s²；原PDM首帧触发emergency_brake，3秒终点x=-0.165m。该异常与初始化输入瞬态并存，未进一步判定全部内部成因；原始输入/输出完整保留。跟踪初期还有速度估计波动。不能把当前曲线称作稳定控制行为。下一轮闭环前先规范受控采集启动预热和速度成熟策略，不通过修改原PDM输出、剔除坏帧或读取未来轨迹掩盖问题。
