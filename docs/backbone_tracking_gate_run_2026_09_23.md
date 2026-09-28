# CARLA 0.9.15 安装与首批控制门槛执行记录

日期：2026-09-23。承接用户提供服务端包、要求开始既定验证。本批采用[冻结规格](backbone_decision_and_tracking_spec_2026_09_22.md)，不是规划/PF 方法实验。

## 结论与停止点

**CARLA 0.9.15 已安装、真实启动并加载固定 OpenDRIVE 试验场。最终运行停在 S2 初始化：`PREFLIGHT_FAIL / gear_not_one`。没有进入 PID 控制或完成任何跟踪格，不能评价起步、转弯、停车、恢复的跟踪能力。**

原定 `throttle=0.1、brake=1、manual_gear_shift=False` 持续 1 s 的预载没有建立一挡初态。20 个静置 tick 和 10 个预载 tick 的读回挡位全部为 0。按原规则停批，没有把初始化失败改记为通过，没有调 PID、放宽阈值或继续后七格。

执行了 20 个固定步的静止几何标定和 S2 的 30 个初始化步，共 50 个 0.1 s 步；这是实际服务端物理执行，不能说“完全没有运行物理”。汇总中的 `physical_trials_started=0` 专指尚无有效 PID 跟踪格；PID 控制次数为 0。

## 安装与环境

- 压缩包：`/root/autodl-tmp/carla-download/CARLA_0.9.15.tar.gz`，8,386,636,048 bytes。
- 完整 gzip 读取及校验通过，tar 路径/布局检查通过：36,163 个成员，常规文件解压总字节 20,205,989,874。不是仅检查文件存在或文件头。
- 安装：`/root/autodl-tmp/CARLA_0.9.15`，VERSION 为 0.9.15。保留下载包和原 0.9.10.1。
- 客户端：独立 `conda-envs/carla015`，Python 3.10.19、CARLA 0.9.15；成功运行时服务端与客户端版本读回均为 0.9.15。
- 当前 RTX 4090、驱动 595.71.05。未更换驱动、Python 客户端版本、渲染模式或车辆物理。

安装证据：[archive_check.json](evidence/backbone_tracking_gate_2026_09_23/archive_check.json)、[installation.json](evidence/backbone_tracking_gate_2026_09_23/installation.json)。

## 全部启动尝试与技术修正

| 尝试 | 结果 | 是否进入有效跟踪 |
|---|---|---|
| `outputs/backbone_tracking_gate_v1`，进程组 69837 | 60 s 内版本 RPC 未就绪；保留 `PREPARATION_OR_CONNECTION_FAIL` | 否 |
| 第一次只读启动诊断，进程组 70751 | 确认本批进程确实持有端口，旧客户端持续超时 | 否；未创建测试车辆 |
| 新客户端只读诊断，进程组 71793 | 监听后新建客户端约 8 s 时读到版本 0.9.15；随后 2 s 世界查询超时。启动器退出后子进程遗留，后续已核对并清理 | 否；未创建测试车辆 |
| `outputs/backbone_tracking_gate_v1_retry1` | 被端口保护拒绝，未创建新服务；遗留者确认是上行诊断的 71801 / PGID 71793 | 否 |
| `outputs/backbone_tracking_gate_v1_retry2`，进程组 73247 | 版本、地图、实际几何、八条参考预检通过；S2 初始化挡位失败后停止 | 否；已执行标定和初始化 |

实际创建了四个 CARLA 服务进程组，其中两个为只读启动诊断；另有一次入口被占用端口拦截。记录全部保留，不把诊断当作通过的驾驶格，也不隐去失败尝试。技术重试已结束，不继续循环启动。

只修正了 `scripts/probe_backbone_tracking.py` 中两处运行管理问题，并补充一个真实延迟 TCP 子进程的回归检查：

1. 先证明本批监听端口已存在，再创建 CARLA 客户端。原入口在服务监听之前就构造连接，并复用失败连接；现场新连接可响应，修正后实际世界也成功加载。未增加启动超时或更换协议。
2. 清理本批进程组不能只等 `runuser/bash` 启动器退出：它退出后 CARLA 子进程可能仍在。温和退出后对仍存在的本批组完成强制清理，保留所有其他进程。

两个缺陷都先有失败复现再修正。原日志中的 SIG11 出现在终止清理附近，不作为已证实的自发启动崩溃；网上相似驱动故障报告也不能当作本机根因。最终正常加载已证明本次不需要更换驱动来跨过启动门槛。

## 固定预检结果

| 检查 | 结果 |
|---|---|
| 服务端 / 客户端 | 0.9.15 / 0.9.15 |
| 车辆 | `vehicle.lincoln.mkz_2017`，默认物理参数已完整落盘 |
| 世界 | 固定生成式 OpenDRIVE；同步 0.1 s，子步 0.01 s × 10，设置读回通过 |
| 实际几何 | 宽 2.128324270 m，轴距 2.871127930 m，后轴到 actor 1.393598746 m；原几何门槛通过 |
| 八条参考的静态检查 | 8/8 通过；转弯参考最小完整车身走廊余量约 0.337158 m |
| S2 预载最大偏移 | 0.000000324 m，低于 0.02 m |
| S2 初始后轴误差 | 约 0.000094 m，低于 0.02 m |
| S2 初始挡位 | **0；要求为 1，失败** |
| 有效跟踪格 / PID 控制 | 0 / 0 |

实测几何通过和静态参考通过，不等于所有路面位置的物理碰撞网格已验收，更不等于车辆能够跟踪这些参考。没有有效帧序列，未调用整批跟踪审计器生成误导性的跟踪 PASS；本次只独立核对落盘几何、参考检查、初始化及汇总。

## 挡位问题能说明什么

已确认：冻结预载在本次真实环境中没有满足一挡初态。这里读回的 `gear=0` 不是单纯沿用请求中的默认字段。CARLA 0.9.15 原生 `ProcessControl` 会把运动组件的 `GetCurrentGear()` 写回 Control.Gear；自动挡路径并不因为请求写了 `gear=1` 就执行指定挂挡。[官方 DefaultMovementComponent.cpp](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Vehicle/MovementComponents/DefaultMovementComponent.cpp)

未确认：自动变速箱在该油门/刹车组合下未挂挡的完整 PhysX 内部原因；解除刹车后会不会挂入一挡；固定 PID 的实际跟踪品质。本次不从零次 PID 控制推出控制器不适配，也不通过改初始化让这次失败追认为通过。

下一步应先修订初始化协议。可审阅的候选是：静止制动状态下通过原生 `manual_gear_shift=True, gear=1` 明确选挡，再切回自动挡并读回验证；不是只给自动挡命令增加 `gear=1`。切回后能否维持一挡、能否满足固定时长与静止约束仍需单独验证。具体时长及验收协议需在新版本设计中先冻结，当前没有实施或测试此候选；PID、轨迹和门槛不应随之调参。

## 验证、文件与清理

- 最终定向检查：25 项通过，28.414 s；包括监听时序、遗留子进程清理、几何/参考/评分契约。
- 项目要求的资源独立复核：378 项通过，221.550 s。它不等于完整模型集成或驾驶效果通过。
- 与首轮运行存档逐字比较，参考生成、评分器、原生 PID/misc、冻结设计文档均未改变。仅启动管理与上述回归测试改变。
- 最终核对：无 CARLA 服务进程，2015–2017 端口均可绑定，GPU 13 MiB。没有训练、P/F 或 RP 实跑；未提交/推送；原工作区修改和历史失败产物保留。

主要入口：

- [最后运行汇总](../outputs/backbone_tracking_gate_v1_retry2/summary.json)
- [S2 初态门槛原始结果](../outputs/backbone_tracking_gate_v1_retry2/S2/initialization_check.json)
- [S2 全部初始化记录](../outputs/backbone_tracking_gate_v1_retry2/S2/initialization.json)
- [最终验证与清理快照](evidence/backbone_tracking_gate_2026_09_23/verification.json)
- [最终定向测试日志](evidence/backbone_tracking_gate_2026_09_23/targeted_tests_final.log)
- [资源独立复核日志](evidence/backbone_tracking_gate_2026_09_23/review_suite.log)
