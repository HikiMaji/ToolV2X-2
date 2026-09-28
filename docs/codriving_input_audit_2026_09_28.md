# CoDriving P adapter 探针审计：撤回 P 收益归因

> 后续用户已授权修复，见[修复实施与验证](codriving_native_fix_2026_09_28.md)。本文保留审计时结论；旧权重审计重放使用保存的v1源码快照。

2026-09-28。复核已有 route11 / route05_28 探针、上游源码、当前定位与冻结 adapter。零优化步骤，没有重新运行检测器、MTR、完整 planner 或闭环。实现、原权重和原实验输出不变。

**目前只证明可执行的 adapter 接口，不能证明有效的 P/F 协作链。之前将 route11 改善解释成 P 信号、将 route05_28 恶化解释成一般泛化失败，均不充分，现撤回这些归因。** 输入坐标、时间绑定确有错误；已保存 P adapter 在本次全部 14 个检查样本上完全忽略 P 内容。

## 1. 已训练 P 分支没有使用 P 内容

严格加载 `outputs/codriving_route11_p_train_checkpoint/adapter.pt`，在原 Torch 1.10.1 环境做冻结 CPU / CUDA 前向。只运行小型 encoder/head，不加载 base planner、标签或优化器。固定导航 target 与 F_valid，将原 P 清零或换成同 recording 下一窗口的 P。

| 原评价样本 | 数量 | 清零 P 后输出差 | 换帧 P 后输出差 | evidence body 全零 |
|---|---:|---:|---:|---:|
| route11，center78–80 | 3 | 0 | 0 | 3/3 |
| route05_28，center30–40 | 11 | 0 | 0 | 11/11 |

P 栅格本身非空。两层 Conv/ReLU 后的池化向量为全零；head 实际只依赖 target 和偏置。原 P 与清零 P 的完整修正张量 `torch.equal=True`。CUDA 重放修正范数与原完整运行日志最大差 `3.58e-7`，支持读取的是同一有效权重。

原日志数值复算成立：route11 P adapter ADE/FDE `0.108456/0.295758`，base `0.151332/0.383581`；route05_28 为 `0.727656/1.714175`，base `0.510769/1.179418`。前者不能归因于远端 P；后者反映额外 target/偏置修正分支未迁移成功。坐标错误是独立缺陷，不能在分支忽略 P 时把输出恶化归因于“坏 P 被吸收”。

限制：未重跑完整 planner 的 empty/shuffle ADE/FDE；本项证明冻结修正输出不依赖 P。没有逐一重放 F/PF 变体权重，不能将全零表征结论扩展到它们。人工设定非零 head 的单元测试不等于训练产物证据依赖验收。

## 2. 坐标错误使 receiver 本车成为远端障碍

临时 `build_route11_multi.py` / `build_cross05_28_multi.py` 的 `candidate()` 先对 detector box 使用 `[x+1.3,-y]`，再套 source 的 LiDAR 世界位姿，最后减 receiver 的 LiDAR 世界位姿。它混用车体与传感器原点，且在进入原生世界坐标前翻转 y。

上游 `v2xverse_basedataset.py` 的 detector 位姿为 `[lidar_pose_x,lidar_pose_y,...,theta-pi/2,...]`；`base_agent.py` 将传感器安装点变换成世界位置保存。`box2occ` 中加 1.3 是同车传感器到车体的局部转换，不能先加偏移再使用传感器世界原点。

审计直接提取执行上游未改动的 `x_to_world()`：原始 detector box → source 传感器世界变换 → receiver 当前车体原点/方向 → forward/left。使用同帧本车定位检查身份，未读取未来 actor 或 GT box。

| 检查 | route11 | route05_28 |
|---|---:|---:|
| 当前 P anchors | 11 | 11 |
| 还原后距 receiver 中心 <1m | 0/11 | **11/11** |
| 距 receiver 中心，平均 | 5.098m | **0.0784m** |
| 旧位置与正确位置之差，平均 | 2.233m | **10.745m** |

route05_28 frame30 旧 P 位置 `[-3.734,-4.975]`，正确还原为 `[-0.031,0.083]`。其 176 条历史记录（滑窗重复计数）全部距同帧 receiver 本车 <1m。此前“检测器没有检测到 receiver”的推测被推翻：错误转换导致本车排除失败，当前 P 不是第三方车辆证据。

另有两项问题：历史目标相对最终 receiver 位置排除，不能代替按历史同帧身份排除；全部 box yaw 被写死为 0。应保留原 corners/方向语义并验证，不能把恢复一个 yaw 字段当作朝向质量通过。

## 3. 时间早了四帧，坐标未同步

上游 `codriving/data_utils/datasets/pnp_dataset.py` 中 `route_frames` 是输入起始帧。五帧、skip=1 时：decision=start+4，十点 label=start+5 至 start+14。

临时推理脚本按 `start == sidecar.center` 配对，以 `np.eye(3)` 直接栅格化。保存间隔为 0.2s，故 P/F 早于规划 **0.8s**，且仍在旧 ego 时刻坐标中。不是未来泄漏，而是把旧证据误标为同步证据；F 未来通道的时间原点也错位。

应以 `(recording,receiver,decision_frame)` 绑定，用 `start=decision_frame-4` 找官方 batch；校验 source capture time 与坐标 epoch。不能将当前错位追认为延迟实验。

## 4. 其他已确认问题

1. route05_28 的 11/11 refs 仍写 route11 scene/context。该字段没进入本次卷积数值，但不满足正式 provenance/receipt 契约。
2. 14/14 metric rows 的 route/ego/frame_id 都为 null。Subset 没暴露原 `route_frames`，脚本捕获 AttributeError 后静默继续。后续须显式传样本键，不能按行号绑定。
3. MTR 临时脚本构造 `(1,11,7)`，只含预选单目标。真实模型运行成立，但不满足“完整合法 peer context 预测后再选目标”的 F 定义。
4. start70–77 的训练标签覆盖75–91，start78–80 的评价标签覆盖83–94，共用83–91这9个物理未来帧。相邻窗口诊断不是独立评价。
5. Ego 没有 adapter，P 有可训练 target/head，缺少同容量、同训练预算的 empty-P 对照。初始化等价不能排除训练后的导航修正解释。
6. route11 属于官方 Town05 test，在其上短训只可当开发探针。正式可比训练须回到官方 training towns 与独立 validation。

## 5. 后续最小修复顺序（本轮未实施）

1. 修共同数据入口：显式样本键、复用上游位姿变换、按同帧身份排除 source/receiver、自洽的方向/缺失状态、scene/context 校验。回归覆盖不同朝向、LiDAR 偏移、start/decision 差四帧、错 scene 拒绝。
2. 用已有 detection 检查正确 P：目标身份、时间和栅格先通过，不必重跑检测器/MTR。排除本车后无第三方目标的帧保留为空证据，不放宽过滤制造 P。
3. 针对观测到的全零 evidence 表征做最小修订，保留 CoDriving 主干；用正常/清零/打乱 P 检查训练产物的信息依赖。仅更换激活函数、梯度非零或 loss 降低都不能称有效。
4. 独立 recording 上比较 P 与同容量空证据训练对照；P 内容价值成立后接完整 peer context 的 F/F-CV。当前不扩大训练或更换底座。

官方未接 P/F 的复现、数据、权重和协议基础不因此自动失效。本轮重新读取官方 3560 样本结果文件，所查官方数据/坐标/栅格源码无 Git 修改；未重跑官方完整评价。

## 6. 复核材料

目录 `outputs/codriving_input_audit_2026_09_28/`：

- `audit_inputs.py`、`summary.json`、`geometry_and_binding_rows.json`：身份/坐标与指标复算。
- `audit_residual.py`、`residual_cuda_summary.json`、`residual_cuda_rows.json`：冻结干预和表征。
- `original_log_consistency.json`：14 个 CUDA 修正范数与旧日志比对。
- `source_snapshots/`、`source_manifest.json`：9 个原探针/实现/配置的副本和 hash。

```bash
python outputs/codriving_input_audit_2026_09_28/audit_inputs.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/miniconda3/envs/tcp_codriving/bin/python outputs/codriving_input_audit_2026_09_28/audit_residual.py cuda
```

两项均实际运行成功。没有实现修复，没有新训练，不把历史414项测试当作本轮新验证。
