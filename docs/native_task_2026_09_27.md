# CoDriving Stage 2：原生时间协议与付费运动锚点

2026-09-27。本批扩展现有 service / receipt / ledger，新增 `toolv2x_task_v3`。只做协议、数值转换与回归；**没有运行真实检测、MTR或CoDriving planner，没有训练，也没有完成真实Town05整链**。

## 已实现

- v3 request 保留 current/change、ExecutionSpec、acquired_field_manifest，新增 frame_binding。显式声明版本、当前物理时刻、x-forward/y-left、ego actor原点和时间来源。provider构造时须独立持有相同binding；请求不匹配时先于私有读取拒绝。
- request.times/tau 采用相同长度的原生未来时间轴，例如0.2…2.0秒十点，不强行转成旧六点。历史可保留实际长度和递增非正时刻，终点必须为0，不强行填成0.1秒。
- P/F共同的anchor新增motion：velocity、valid、support_times、source。速度由完整因果tracking context末两个valid状态差分计算，source明确为causal_tracking_state_motion_proxy。未知速度以valid=false表示；不是逐帧detector hit，也不读取GT或未来预测估计速度。
- P返回原生历史，不调用预测器；F先以完整合法window调用预测器，之后再排序、裁剪及装包。预测器输出额外包含forecast_times；协议可在已有覆盖范围内连同当前anchor插值，不外推。此操作不是历史重采样。
- F单独购买即可通过其已计费motion anchor构造F-CV，不再强制购买完整P。两个分支共用目标、尺寸、当前yaw、时域与栅格。未观察到合法速度的目标仍明确拒绝成对转换，不悄悄补真值。
- 同episode固定协议/frame_binding/未来请求时间轴，ledger首次接收后也固定request_times。防止改时间轴后将不同内容误判为已购字段。旧v2/control合法组合保留。
- 复用原manifest验证、provider receipt registry、最终UTF-8字节预算和最多两次调用限制。P后F或F后P可以只引用已真实返回的相同anchor，不免费读取历史。P历史到达后，receiver复核它与motion anchor一致。
- v1 query/decode_response/history_window/make_evidence的AST与HEAD逐项相同；默认v2保留。

## 文件/API

- `src/tools/native_time.py`：原生时轴/绑定检查、motion计算和预测时间采样。
- `src/tools/task_spec.py`：v3分支，原生window/prediction形状，真实时间间隔下的计划检查与current/change评分。
- `src/tools/vehicle.py`：VehicleTools增加可选task_frame_binding；原query_task/decode_task_response支持v3，返回版本toolv2x_task_response_v3。
- `src/planning/evidence.py`：new_ledger增加可选task_version/frame_binding；原apply_response接收原生字段并保留receipt、上下文证书、motion交叉检查和时间绑定。
- `src/planning/codriving_ledger_bev.py`：legacy仍需已购历史；v3可直接用已购motion anchor形成F-only规范记录。
- `tests/test_native_task.py`：11项新增契约测试；`scripts/check_review.py`纳入该组。

未增加RSU、预测骨干、策略网络或训练任务，未改CoDriving主干、官方权重和基线报告。

## 过程与审查

新增测试在未支持v3时失败，随后实现通过。独立审查发现“不同请求时间轴使用同一字段身份”问题，新增失败测试后修复为episode/ledger冻结时间轴；复核17项相关测试通过。测试中的第二个service仍名为peer，因此该测试严格证明重建service不能绕过ledger，不冒称已经用不同provider fixture执行过跨provider测试；ledger检查本身不依赖provider。

完整资源独立回归首次发现旧v2/control组合被版本冻结误拦截；修复为仅涉及v3时冻结协议，保留首轮失败日志。一次直接按测试模块运行包含两个需要torch/transformers的模型测试，在轻量环境因依赖缺失报错；其余68项通过，不将该命令称全部通过。正式最终以check_review的资源独立列表为准。

## 实施决定与边界

- 时间轴首版固定在episode内，不支持同一时刻针对同字段换采样协议；未来要支持必须将相应时间规格纳入字段语义身份。代价是当前不能在第二次请求更换时域，但十点共同planner无需此功能。
- frame_binding是可信provider/receiver持有的定位与时间元数据契约，不自动认证传感器标定/采集时钟。
- 原生P→本地MTR还没有重采样适配。本批v3 ledger只允许observations_only，显式拒绝local_mtr，避免旧固定0.1秒预测器静默消费0.2秒历史。既有v2等信息对照仍保留；不能声称原生CoDriving等信息对照已执行。
- 原生F predictor回调也尚未绑定真实CARLA→MTR适配。合成forecast只用于接口验证，不是模型效果。
- 尚未把v3挂到旧GoT/数值episode驱动器；本批打通的是service/receipt/ledger/BEV层。旧驾驶接口并不因能调用同名函数就自动支持新时间轴。
- CoDriving sidecar依旧未进入原planner forward。

下一步：在既定Town05-11录制上运行一小段各车独立因果检测/跟踪，明确坐标和history有效性；接入原生P，再完成MTR的显式历史适配并生成真实F/F-CV样本。之后才改planner输入层及开展共同训练。

## 最终验证

资源独立回归 **406项全部通过，195.949秒**，日志 `docs/evidence/native_task_2026_09_27/review_fixed.log`；相关105项定向回归先前通过。v1四个接口的AST不变记录在 `v1_source_check.json`。`git diff --check`通过。代码已同步主目录，未提交或推送GitHub。
