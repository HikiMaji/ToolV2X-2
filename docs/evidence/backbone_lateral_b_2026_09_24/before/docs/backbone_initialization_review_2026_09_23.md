# 共同底座当前停止点复核与初始化修订建议

日期：2026-09-23。状态：审阅稿；仅复算已保存记录并查阅源码，未实施修订、未启动服务/模型/训练。本文接续最新实际进度，不重新选型，不覆盖已冻结规格和历史失败。

## 1. 先校正当前进度

上一段对话建议的“确定组合、F来源和独立跟踪规格”已在其他对话落实，见 [具体规格](backbone_decision_and_tracking_spec_2026_09_22.md)。目前的工作顺序如下：

| 项目 | 已有决定/事实 | 当前边界 |
|---|---|---|
| 首选组合 | RP v2024.1核心 + CARLA 0.9.15原VehiclePIDController | 控制门槛未过；RP未接入，不算可用底座 |
| 平台 | CARLA 0.9.15已安装并实际加载固定试验场 | 无需重新下载或重做版本选型 |
| F来源 | 已选CMP no-cooperation MTR，冻结full_seed20/epoch09 | CARLA历史适配、5s新wire与跨域质量未完成；不能声称CARLA的F已可用 |
| 第一批控制验证 | 给定8条解析轨迹，PID/参考/阈值已固定 | 还未进入任何有效PID跟踪格 |
| 当前实际停止点 | S2初始化要求gear=1，30个初始化tick读回全为0 | 初始化假设失败，尚不能判定PID跟踪失败 |

原候选PDM失败产物继续保留。当前不恢复PDM调参，也不扩展到第三种规划器。

## 2. 本轮独立核对了什么

读取 `outputs/backbone_tracking_gate_v1_retry2/S2/initialization.json` 全部30行，核对20行settle和10行preload、逐帧连续；按保存的刚体偏移重新计算后轴位置：

- 30/30读回gear=0；有效PID跟踪格为0。
- 预载期间最大后轴位移为0.000000323707354m，与原门槛文件在1e-12m内一致。
- 末状态三维速度约0.0000010496m/s；原失败列表只有gear_not_one。
- 运行器在创建PID之前检查挡位并退出，与原summary一致。没有“PID已经试过但失败”的证据。

本轮是对既有文件的复算，不是重新运行物理；独立结果见 [existing_initialization_recheck.json](evidence/backbone_initialization_review_2026_09_23/existing_initialization_recheck.json)。

## 3. 原因边界与源码依据

CARLA 0.9.15 `DefaultMovementComponent::ProcessControl` 在reverse不发生变化的正常前进分支中，先按manual_gear_shift设置自动换挡；只有manual_gear_shift=true时才调用 `SetTargetGear(Control.Gear, true)`。随后从运动组件读取实际挡位写回Control.Gear。

因此，原“自动挡+0.1油门+全制动”没有显式指定进入一挡，它依赖自动箱自行建立初态；本次记录证明该假设未满足。在自动挡命令里仅填gear=1不构成修复。

[CARLA 0.9.15官方实现](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Vehicle/MovementComponents/DefaultMovementComponent.cpp)

**仍未知**：PhysX自动箱为什么在该组合下保持空挡的全部内部原因、显式挂挡后切回自动能否稳定保持一挡、原PID的实际跟踪性能。源码支持采用原生选挡接口的方向，不证明新方案已经成功。

## 4. 建议的最小修订：只替换初始化协议

建议新建 `toolv2x_backbone_initialization_v2`，跟踪运行清单随之使用 `toolv2x_backbone_tracking_gate_v2`；旧v1保持原解释。时长仍为每actor30个0.1s tick，分三段：

| 阶段 | tick数 | 每段开始时提交一次的控制 | 必须记录/检查 |
|---|---:|---|---|
| settle | 20 | throttle=0, brake=1, steer=0, reverse=false, hand_brake=false, manual_gear_shift=false | 保留原落地稳定过程，允许尚未挂挡 |
| engage_drive | 1 | throttle=0, brake=1, steer=0, reverse=false, hand_brake=false, manual_gear_shift=true, gear=1 | 完成一个tick后，读回manual=true、gear=1；否则立即失败 |
| verify_automatic | 9 | throttle=0, brake=1, steer=0, reverse=false, hand_brake=false, manual_gear_shift=false | 9个tick每次读回manual=false、gear=1；否则立即失败 |

一个tick对应源码显式立即选挡命令后的首次物理观测；九个tick用于原1s准备预算中剩余的自动挡交接检查。它们是待验证的固定协议，不是依据成功样本选出的等待时长。不增加油门、不延长等待、不循环搜参数；取消原0.1油门预载是改为直接选挡的组成部分，不声称仅改变了一个数值变量。

位移以settle第20个tick的后轴位置为基准，覆盖engage_drive和全部verify_automatic，最大偏移仍须≤0.02m；同时保存累计路程，不能往返抵消。两个新阶段各tick速度模长须≤0.05m/s；末态位置、航向、前轮角、垂直稳定、有限值沿用原初态门槛。首次几何标定的2s静置不变。

初始化期间保存phase、frame、snapshot timestamp、本次生效的requested_control、readback_control及原始本车状态。写入的新命令和实际读回必须分开，不能把请求gear=1记录成实测gear=1。失败在对应tick即时落盘，允许不足30行的真实失败记录；不足的后续记录不得补齐，也不得被审计为PASS。

完成全部初始化后才定义t=0并创建一次PID。之后继续原观测→PID一次→apply_control一次→tick顺序；不重置起步时钟、不清积分、不覆盖正常PID输出。正常停车/恢复仍交由原冻结控制验收；本修订不增加停车锁存。

## 5. 为什么只选这条修订

- **推荐：显式选挡再交回自动挡。** 使用已核对的原生物理控制分支；正常阶段仍为已选自动挡PID。变化局限于明确建立测试初态。
- **不选：解除刹车/加大油门/延长预载，等待自动挂挡。** 会加入新的未受控起步和时间选择，不直接解决显式一挡初态要求。
- **不选：取消一挡门槛或全程锁定手动一挡。** 前者改变初态定义，后者改变正常执行器，超出当前修订。

如显式挂挡或交回自动仍失败，则保留新失败并停止，不现场换用其余方案，也不从初始化失败推出RP/PDM算法不适用。

## 6. 建议实施范围和必须验证的接口

只需改现有入口/检查器及相关测试，不新增框架：

| 文件 | 建议改动 | 验证要求 |
|---|---|---|
| scripts/probe_backbone_tracking.py | v2三段初始化、记录请求/读回、立即失败落盘；增加显式initialization-only模式以复用同一初始化路径 | 20/1/9顺序、零油门、反向/手刹关闭、自动交回；失败不创建PID、不运行后续格 |
| src/evaluation/tracking_gate.py | 添加纯数据初始化复算；按记录版本区分v1与v2；初始化单项结果与整批跟踪结果分开 | v2错误gear/mode、漂移、缺tick或时间错误必须拒绝，即使保存文件声称passed=true；v1历史phase不重解释 |
| tests/test_tracking_runtime_contract.py | 合成控制接口记录与阶段调度检查 | 证明执行顺序和停止边界，不作为真实挂挡证据 |
| tests/test_tracking_gate.py | v2真实记录格式fixture和反例，保留v1回归 | 假passed、仅请求挂挡成功、切回自动变空挡、往返漂移、提前终止均不能PASS |

旧完整审计器目前硬编码20+10 phase，且挡位主要依赖运行器检查。v2不能仅改运行器而继续沿用旧审计结论；必须从raw记录独立检查实际挡位与模式。这里只补新协议所需验证，不展开新的安全或防攻击研究。

PID vendor、增益、前视、参考生成器、8格顺序、轨迹评价阈值、车辆物理、地图和正常控制保持原冻结版本。旧P/F协议、MTR、RP、LLM均不属于此次修改范围。旧失败不覆盖，新实现与新运行均另存版本。

## 7. 有限验证和通过后能做什么

1. 先完成上述离线单元/回归，确认模式与审计一致。
2. 新目录仅运行一次初始化验证：沿用原环境/几何预检，新S2 actor执行2s稳定+0.1s手动挂挡+0.9s自动交回；不创建PID，不跑跟踪参考，不采集LiDAR，不调用模型。首次几何标定另有2s，合计最多5s仿真物理时间；服务启动墙钟时间另计，不保证几秒完成。
3. 单项结果命名INITIALIZATION_PASS或INITIALIZATION_FAIL，不能写TRACKING_PASS。通过只说明所选初态可按固定协议建立，不证明起步、停车或恢复。
4. 初始化通过后，后续正式跟踪批次仍从S2开始，每格新actor重复相同初始化；原8格2160次控制上限与任一格失败停批规则保持。不得在一份初始化验证中自动升级到RP、F或论文实验。

该验证范围不再比较多种初始化，也不调PID。若通过初始化但后续S2跟踪失败，才有证据讨论控制器/参考消费；两类失败必须分别记录。

## 8. 本轮交付与下一阶段边界

本轮只新增本审阅稿和既有记录复算JSON，并更新STATUS入口；实现、测试、vendor以及旧冻结设计未修改，无新增物理/模型运行。具体组合与F来源已有定案，不再重复写第二份选型。

按用户此前要求，改变初始化需形成可审阅的新版本。原[冻结规格3.5节](backbone_decision_and_tracking_spec_2026_09_22.md)明确：“改变任一 PID 值、前视、初始化、参考、车辆物理或阈值，都形成新设计版本，经审阅后重新从第一格开始”。本稿给出具体修订供审阅，尚不代表获准改实现或启动验证。
