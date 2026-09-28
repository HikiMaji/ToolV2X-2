# CoDriving 原生 P/F 接线修复

2026-09-28，用户授权修正上一轮审计发现。本轮保持 CoDriving 官方主干、checkpoint、旧 v1 wire 和现有 receipt/ledger 实现。修复新增输入接线与 residual adapter；未运行真实数据训练、检测器、MTR、完整 planner 或闭环。

## 实际修改

| 文件 | 改动 |
|---|---|
| `src/planning/codriving_native_inputs.py` | 版本化 NativeInputSpec、sensor/world/actor 变换、同帧 source 排除、显式 start/decision 样本绑定、嵌套 Subset 解析、完整上下文 F 后选择、batch 接入、recording 隔离检查 |
| `src/planning/codriving_causal_context.py` | 从既有跟踪输出构造完整因果源上下文、原生历史和 MTR 时间轴转换、目标记录及来源校验 |
| `src/planning/codriving_tool_adapter.py` | v2 LeakyReLU 和相对空证据修正；严格拒绝旧架构权重 |
| `scripts/prepare_codriving_native_probe.py` | 替代 `/tmp` 中复制改名的探针；从已有检测准备新输入，写明确样本身份和完整规格 |
| `tests/test_codriving_native_inputs.py` | 坐标、安装偏移、真实本车误关联、时间/Subset、规格拒绝 |
| `tests/test_codriving_causal_context.py` | 因果多目标、跟踪维护状态/检测命中区分、缺失掩码、角度插值、完整上下文、来源一致性 |
| `tests/test_codriving_probe_pipeline.py` | P 无预测、F 完整输入、回调不能裁剪、自洽样本、batch/recording 隔离 |
| `tests/test_prepare_codriving_native_probe.py` | 只读指定同帧定位，拒绝跨场景/车辆来源 |
| `tests/test_codriving_tool_adapter.py` | 真实优化过的合成内容依赖回归、null/shuffle、冻结 base、CPU/CUDA 和架构版本 |
| `scripts/check_review.py` | 注册全部新增轻量回归 |

另更新状态和报告。旧审计 `audit_residual.py` 改用其保存的 v1 源码快照，使其在当前模块升级后仍能重放旧权重；没有修改原检测、结果或 checkpoint。

## 数据与模型契约

- detector 的原始中心/方向先按 source sensor 世界位姿转换，最后进入 receiver actor forward/left 坐标；不提前翻转 y 或重复加 1.3m。history 统一到 decision 时刻固定 source frame。
- source 本体只用同帧定位排除，radius 保持 1.4m；receiver 排除半径保持 3m。两者保存在 `NativeInputSpec`，不调整阈值制造 P。它们是几何身份代理，不冒充真实 actor ID。
- 完整 provider context 包括合法观测到的 receiver 和 ROI 外目标；receiver 只从返回目标排除。F 的 callback 先接收完整 MTR window，再选返回 targets；校验 callback 未修改 window，输出 IDs/states 对齐原完整窗口。P 不调用 predictor。
- 新 builder 复用现有 `FixedRateTracker`/AB3DMOT，没有新增关联器。`valid` 表示因果跟踪状态，可包含 detector miss 后的短期维持；单独保存 `detector_hit`。尚未出现的历史槽保持 invalid/zero。
- 0.2s 原生 history 到 MTR 的11个0.1s槽，仅在相邻有效历史状态间插值，yaw 沿最短圆弧；不跨缺失状态、不外推。插值标为派生准备，不声称新 detector hit。
- `decision=start+4`（五帧、skip1）。规范样本保存 input/decision/label 全部帧号与完整规格，拒绝内部矛盾。`resolve_planner_sample` 解开 Subset 索引，不再默默写 null。十点未来为相对 decision 的0.2…2.0s。
- 0.2s 是 weather-0 的采集配置推导的录制内相对时标；原检测 `timestamp_seconds=null` 没被改称传感器真时间。其他 weather 须显式提供规格。
- context hash 只是内容一致性检查，不是认证或合法购买证明。`raster_for_sample`/`attach_context_batch` 明确用于离线准备；完整 paid receipt 链仍使用已有 ledger 接口，本轮未声称它已在 CoDriving 上实跑。

## adapter v2

```text
residual = h(P/F content, navigation) - h(empty content, same navigation)
output = frozen CoDriving output + residual
```

空参考清零全部5个 P 通道及所选 F 内容，保持相同 F_valid。body/head 使用非零负斜率激活，避免旧检查点实测到的整支 ReLU 截断。缺省无 sidecar、零初始化、以及任意训练后空内容都返回原 planner。base 保持冻结/eval。

架构 marker 为2；旧 `adapter.pt` 缺 marker，或值/类型/形状不符时，在 adapter 和整个 wrapper、strict=True/False 下均拒绝。旧权重不自动迁移，也没有生成新数据集权重。

合成回归分别对 P、F、F-CV 做20次小更新；固定同样导航和有效性，以内容区分两行，比较正常/null/shuffle，而不只手工改 head 后观察输出。该测试验证通路和防捷径约束，**不证明真实协作有效**。也不能排除模型将“有信息”作为场景标签的更复杂捷径，正式效果仍需要独立 recording 的内容对照。

## 已有检测的真实离线复核

每条路线复用 source1 的21个保存检测帧和原 AB3DMOT，准备11个 decision；无 learned model 调用。

| recording | decision | 完全无第三方返回 | 当前 P occupancy 空 |
|---|---|---:|---:|
| route11 | 70–80，对应官方start66–76 | 0/11 | 0/11 |
| route05_28 | 30–40，对应官方start26–36 | 6/11 | 11/11 |

两组每个 decision 均排除了一个 receiver 本体目标，source 排除累计分别17/21帧和21/21帧。route05_28 frame30–33的第三方在 BEV 外；frame34仍有一次 detector miss 后维护的同轨迹状态，35–40无返回。因此“栅格为空”和“无第三方目标”不是同一个计数，全部保留。

22个新样本的绑定、完整 context IDs、因果 parent refs、输出栅格逐位重放验证通过。原来 route05_28 中落在本车附近的错误 P 不再被当成第三方证据。

注意：新样本的实际 decision 已纠正，不能直接将其与旧错位 ADE/FDE 配对比较；本轮没有生成新的规划误差。完整 peer-context F 接线只通过注入 fixture 的契约测试，尚未重新执行真实 MTR。

## 验证和后续

验证结果见本页末尾最终记录及 `outputs/codriving_native_fix_verification_2026_09_28/`。轻量测试覆盖旧 v1 回归；模型环境另跑 adapter 的 CPU/CUDA 检查。Numba 在 AB3DMOT 中提示旧版本 object-mode fallback，本次实际跟踪和导出成功，没有调整上游依赖。

本轮停止于修复和真实输入准备。下一项是用正确输入、冻结底座及 v2 adapter 做有界的内容价值检查：正常/清零/打乱证据、同容量控制、按 recording 隔离。正式训练使用上游 training towns；已用作开发的 Town05 route11 不再冒充未见 test。`validate_recording_split` 已提供拒绝同录制分组的接口；正式训练入口尚未在本轮新建，不能声称未来所有调用方已经强制采用它。

原 CoDriving 官方复现与旧失败产物继续保留；不重建原始数据、不更换底座、不开始长训练。

## 可复用入口

离线重新准备（使用新目录，拒绝覆盖）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/root/autodl-tmp/conda-envs/dmstrack/bin/python scripts/prepare_codriving_native_probe.py \
  --route-root /root/autodl-tmp/v2xverse/dataset/dataset_v2xverse/weather-0/data/routes_town05_28_w0_05_01_11_18_29 \
  --detections outputs/crossroute_town05_28_detection_2026_09_28/detections.json \
  --decisions 30 31 32 33 34 35 36 37 38 39 40 \
  --output outputs/codriving_native_route28_new_run
```

官方离线 batch 接口：

```python
# indices 是该 batch 在传入 dataset/Subset 中的实际索引，不是 DataLoader 行号猜测。
# contexts 按显式 decision key 检索；函数再次核对场景、车辆和完整时间规格。
from planning.codriving_native_inputs import attach_context_batch
prepared = attach_context_batch(
    official_batch, dataset, indices, contexts,
    tool='P', target_ids=selected_ids_per_sample,
)
output = wrapped_planner(prepared)
metric_identity = prepared['toolv2x_sample_keys']
```

F/PF 额外传 `predictor`（绑定同一冻结 CMP 的 callable）和稳定 `predictor_version`，不传裁剪后的窗口；该 API 会准备完整 window 并在返回后装包。首个正式模型重跑前仍须检查当前 Torch 环境与 CMP loader 的兼容，不能把历史临时 shim 当正式实现完成。

新版尚无真实数据训练权重。旧 P adapter 必须留在原 v1 源码重放路径；禁止简单增加 version 字段以绕过检查。

## 最终验证记录

- 完整资源独立回归：447项，437通过、10项因无Torch跳过，0失败，209.105秒。包含旧v1/黄金回归；最终两处审查修复后重新运行。
- Torch模型环境：10/10通过，6.787秒，含CPU/CUDA和每分支20次合成优化。
- 独立复核：样本自洽与完整context防裁剪，8/8通过。
- 两路线共22个保存检测decision的身份/因果引用/栅格重放通过。
- `git diff --check`与Python语法检查通过。

机器可读记录与完整轻量日志见 [证据目录](evidence/codriving_native_fix_2026_09_28/README.md)。本轮无提交或推送。
