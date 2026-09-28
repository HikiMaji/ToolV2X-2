# 控制命令时序修复A：实施与S2实测

日期：2026-09-23。用户要求“开始修复”。本批按[诊断顺序](tracking_failure_diagnosis_2026_09_23.md)只完成第一层：命令同步确认→单次tick→下一帧回显绑定。PID、参考目标、前视、初始化20/1/9及物理验收阈值不变。没有RP/PDM、感知、MTR、P/F或训练调用，未提交/推送。

## 结果

**时序修复在本次S2的150次控制上通过；驾驶跟踪仍FAIL。** 同一场景完整15s、150次控制、151个状态记录，无碰撞、无中途补帧、未运行其余七格。

| 项目 | 修复前v2 | 同步确认后v3 |
|---|---:|---:|
| 控制回显错位（字段按float32比较） | 8/150 | **0/150** |
| 服务端确认、本车/帧号、下一帧回显独立审计 | 当时没有此完整契约 | **150/150通过** |
| 最大沿程定时位置误差 | 2.1003m | 2.0565m |
| 沿程误差RMSE | 1.2875m | 1.2457m |
| 最大移动段速度误差 | 0.9174m/s | 0.9774m/s |
| 最大纵向加速度绝对值 | 6.1871m/s² | 7.2294m/s² |
| 纵向jerk绝对值P99 | 65.6869m/s³ | 64.8695m/s³ |
| 初始静止段最大转向指令绝对值 | 0.800000012 | 0.800000012 |
| 终点位置（参考16m） | 13.9025m | 13.9505m |
| 原跟踪门槛 | FAIL | FAIL |

旧诊断用1e-6容差计7处错位；本表按命令/回显实际float32字段逐项相等计8处，两种统计都来自同一旧记录。新记录两种口径均为0，未改写旧结果。

位置误差略变不构成稳定收益，部分动态指标反而变差。该次干预支持：原提交方式确有可消除的时序问题；**它不是整体跟踪失败的唯一原因**。只有一次修复前/后工程诊断，不作统计效果结论。

## 修改内容

- `scripts/probe_backbone_tracking.py`：新submit_control统一几何准备、初始化、正常控制及中止命令的同步提交；`apply_batch_sync(..., False)`返回后检查响应数量、error和actor_id，并确认提交期间物理frame未推进。保存请求、响应结果、source_frame和expected_next_frame。调用者仅推进一次tick。拒绝/异常先落盘，失败不继续下一步。新增s2-only限制本批只跑原S2。
- `src/evaluation/tracking_gate.py`：新增control_echo_matches和audit_control_delivery，按float32数值表达比较throttle/brake/steer，模式字段一致，手动挡校验gear；自动挡gear由仿真决定，不将请求默认gear=0误当实车空挡。独立复算请求、内嵌确认、journal、本车身份、时间和下一帧读回。
- `tests/test_tracking_runtime_contract.py`：确认前不tick、拒绝/错误actor/错误响应数量必须记录失败；原初始化测试改用同一同步通道。
- `tests/test_tracking_gate.py`：读回错位、缺确认、命令不一致、缺journal、额外tick、错误actor、非有限时间等反例；旧v1/v2输出继续原路径审计。

新运行清单为toolv2x_backbone_tracking_gate_v3，命令提交协议为toolv2x_control_submission_v1。日志为本地CARLA执行记录，不是ToolV2X远端P/F receipt。

同步批量接口在服务端按命令列表执行并返回各自结果；False表示不附带tick cue。没有使用True后又额外world.tick，也没有set_transform/set_target_velocity。依据：[CARLA 0.9.15批量命令实现](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Server/CarlaServer.cpp)。

## 保持冻结的部分

对照修改前与实际运行归档，官方PID/misc、tracking_reference.py、原设计文件逐字一致；control_reference和audit_trial函数AST一致。未修静止目标方向、未补纵向位置反馈、未调整Kp/积分/前视、未改变驾驶阈值。

已知illegal_control/steer_slew的float32边界误报仍保留原结果；本批用于传输等价性的float32比较没有放宽物理评分。即使将这两个标签另记，仍有7项真实跟踪失败。

## 测试与审查

- 新接口失败测试先RED，随后GREEN；完整定向36项通过（28.117s）。
- 独立审查运行29项runtime/gate测试，发现一个P2：若可选清单丢失，现代数据会跳过命令审计。已复现失败，再修为发现v3/ACK/journal等现代证据时必须执行审计并拒绝不一致清单；最终36项覆盖该修复。
- 资源独立回归378项通过（222.602s），使用最终同步到主目录的版本。不是完整模型集成测试。
- 独立case-dir重读本次原始文件，命令150/150通过；物理失败列表与运行器一致。
- 非阻塞审查项保留：手工将journal行损坏为JSON null时，当前会抛异常而非返回结构化FAIL；不会得到PASS，正常运行器不生成这种行。未为此扩展本批修复。
- git diff --check通过。没有第二次独立复审；修复由失败→通过测试确认。

代码在 `.worktrees/backbone-command-sync` 实施，主目录四文件复制前做精确原内容比较，未覆盖并发变化；其他既有改动全部保留。

## 运行与证据

本次只启动一个专属CARLA 0.9.15服务。几何标定20 tick、初始化30 tick、实际控制150 tick，共20s仿真推进；同步等待墙钟另计，不宣称实时10Hz。初始化仍PASS，全部驾驶状态gear=1。

S2 journal共153条成功确认（3条初始化阶段命令+150条驾驶命令），另有1条几何标定命令；没有拒绝、没有重复tick。150个recorder物理推进帧完整，无碰撞。

- 原始产物：`outputs/backbone_command_sync_s2_2026_09_23/`。
- 精简证据、源码前后快照、差异、审查与日志：`docs/evidence/backbone_command_sync_2026_09_23/`。
- 对照数值：[comparison.json](evidence/backbone_command_sync_2026_09_23/comparison.json)。

服务、actor、sensor已清理，2015–2017端口释放，末次GPU13MiB/0%。本轮没有启动其他场景或继续长训练。

## 下一层修复边界

继续沿既定顺序修复B：为横向选择有空间间隔的参考方向，明确静止/重复点和末端语义，保留纵向时间律。它必须作为新的参考适配版本单独验证，不能与纵向增益或位置外环同时改后混合归因。

纵向位置/速度/停车距离跟踪属于C，仍未完成。共同底座未通过，不能进入RP或P/F方法实验。本轮成果是一个已测通的执行时序基础，不是驾驶质量已经修好。
