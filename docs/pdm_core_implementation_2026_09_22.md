# 研究点一：PDM 核心部分接入（2026-09-22）

## 本次实际实现

- `vendor/pdm_core/`：保留原 PDM 数值链，共 26 个源文件/配置。仅三处上游文件适配未来时刻对象查询，原候选生成、IDM、模拟、评分、紧急制动均复用。
- `src/planning/pdm_core.py`：新增 PDMExecutionSpec、validate_scene、actor_at、ForecastObservation、PDMCore.plan、scene_from_ledger。显式 rear-axle RH 场景输入；不接受 World 对象，不读取标签，不调用检测/MTR。
- `scene_from_ledger` 复用已有 receipt 校验、ledger 和实体关联。P 使用 causal tracking-state motion proxy；F 使用已购得或合法派生预测的 top-1。当前确定性工程规则优先真实模型/full context/远端，随后稳定排序；这不是学习融合，也没有证据证明该优先级更优。
- 场景构造引用、购得字段、派生字段分开记录；输出保留进入/被排除的对象。**尚未完成 method_episode driver 绑定及完整下游 admission 闭合**，不能把 scene_construction_refs 当成最终消费证明。
- `src/planning/v2xverse_inputs.py`：双车原始传感器白名单读取与显式标定变换。拒绝 RSU 和无效变换；没有时间戳就保留未绑定，未把文件序号硬解释成 100ms。
- `tests/test_pdm_core.py`、`tests/test_v2xverse_inputs.py` 和 `scripts/check_review.py`：增加契约/回归检查。旧 v1 query/decode/wire 未修改。

## 执行配置与范围

首版 dt=0.1s、输出 3s、候选 2s，兼容现有 F 报文；完整 ExecutionSpec 随结果保存，不在 3s 后外推。仅前向、无信号控制片段和车辆对象；扩大场景需显式扩展契约。P 路径没有新增 MTR 调用。

PDM 内部候选评分是候选集合相关数值，不当作 teacher reward。F 的位置、朝向、速度使用同一离散时刻；已用失败测试发现并修正“转向后停止恢复初始朝向”的问题。

## 验证结果

- 改动前轻量回归：349 项通过。
- 改动后轻量回归：353 项通过，200.070s；包含旧协议/黄金回归。
- 专用 PDM 核心：8 项通过，包括独立 pristine 上游进程恒速等价性、同一场景重复调用、P/F 改变同一规划器、receipt 约束、未来状态一致性。
- 原始读取：3 项通过（也在 353 项中，不能重复计数）。
- 独立代码审查未发现限定范围内明确 P1/P2 问题，并独立复跑核心 8 项、读取 3 项。
- 环境存在 matplotlib/Pyparsing 弃用告警，测试无失败。合成 fake predictor 仅用于契约，**不是 MTR 或协作效果证据**。

日志、环境版本、上游差异与真实输入检查见 `docs/evidence/pdm_core_2026_09_22/`。

## 真实资源检查与未完成内容

已实际读取双车 0010 帧 LiDAR，点数分别 22595 和 22291；只完成输入检查，未运行真实检测、MTR 或规划效果实验。

本地只找到 CARLA 客户端，未找到服务端/Town03 地图。实际采集日志记录 cop3_split_routes/routes_town03_21.xml；该公开地址 404，同名 splitted_routes 文件不能替代。代码配置推算保存间隔可能 0.2s，仍不等于实际 capture-time 绑定。rear axle 标定/车辆几何仍待补齐。

CARLA 官方脚本资源：
https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.10.1.tar.gz

HEAD 确认 3,956,990,664 字节，约 3.96GB；超过用户允许直接下载的 100MB，未下载。无需因此先下载整个训练数据集。

下一步依赖：
1. 独立可推进：把 core 接入 method_episode 的 PLAN 生命周期，闭合最终入模 provenance、最多两次调用/三次 PLAN 与成本统计；保留旧 driver。
2. 补齐 CARLA/Town03、实际路线、时标与标定，建立真实 map/route 适配器及因果检测跟踪链。
3. 原规划器短路线控制验收，再固定少量 Ego/P/F/PF 配对验收。

**本次未完成完整方法框架部署或真实闭环验收；未训练 LLM，未运行新模型效果实验，未进入研究点二。**

交付：已将本批新增文件及测试注册同步到主工作目录，保留此前全部用户改动；未提交或推送。主目录复跑核心与读取共11项通过（含独立原始上游对照），git diff --check通过。
