# 首批独立轨迹跟踪验收：实施与准备状态

日期：2026-09-22。依据：用户审阅[具体设计](backbone_decision_and_tracking_spec_2026_09_22.md)后要求“继续吧”。本批仅实施该设计的独立控制门槛；RP/F 接入、训练、PID 参数搜索均不在本批范围。

## 09-23 执行更新

用户已提供服务端包，安装并真实启动成功；固定地图、车辆几何和参考预检通过，S2 停在挂挡初始化失败，未执行有效 PID 跟踪。启动管理两处修正后定向25项通过；详见[实际运行记录](backbone_tracking_gate_run_2026_09_23.md)。下文保留09-22的准备快照，缺包已不再是当前阻塞。

## 09-22 准备时结果

代码、独立客户端环境和静态检查已准备；**真实物理跟踪尚未执行**。本机缺少 CARLA 0.9.15 Linux 服务端包，不能用已有 0.9.10.1 替代并继承版本兼容结论。静态参考通过不等于 PID 能跟踪。

新增代码在隔离工作树 `.worktrees/backbone-tracking-v1` 实施、审查后同步新增文件到主工作区；保留原有修改、旧 probe 和全部失败产物，不提交/推送。

## 实现了什么

- `src/planning/tracking_reference.py`：八格固定分段速度/曲率参考，0.1 s 采样，终点延拓到 T+0.4；后轴到 actor 位置及速率的刚体变换；完整车身与细分走廊；解析约束和半步积分核验。
- `scripts/probe_backbone_tracking.py`：默认只准备；显式 `--execute` 才启动自己的 CARLA 0.9.15 服务进程组。拒绝占用端口、旧版本、旧 Python、不合几何或初始化，使用冻结官方 PID。按观察→控制一次→tick→新状态顺序运行，终点不再控制；失败停批。
- `src/evaluation/tracking_gate.py`：只从落盘位置/时间/控制/初始化/碰撞记录复算，不改时钟；检查缺帧、漏终点、往返漂移、速度反馈点、车辆整体越界等。运行器只可写 `TRACKING_COMPLETE_PENDING_AUDIT`，最终 PASS 由独立批次复算产生。
- `vendor/carla_agents_0_9_15/`：官方 0.9.15 tag 的 PID 与 misc 两个源码文件，原样保存，附 LICENSE 和来源记录；没有把 CommonRoad 官方全局 actor wrapper 引入项目。
- `scripts/requirements_tracking_gate.txt`：本批的独立依赖。原模型和旧 CARLA 环境不改。

固定 PID 参数、前视、8 条参考、速度范围及数值判据与设计一致。没有追加停车锁存、调整油门、改变轨迹或用实跑结果搜索参数。

## 实施中明确的执行细节

1. 新包需要独立 Python 3.10；已安装 `/root/autodl-tmp/conda-envs/carla015`：Python 3.10.19、carla 0.9.15、numpy 1.24.2、shapely 2.0.7，来自官方 Anaconda/PyPI。基础环境未升级。
2. A 阶段实际几何读取需要车辆实例。运行时先用单次、固定 2 s、brake=1 的静止标定 actor 读取几何，再销毁；没有 PID 或参数搜索。主批仍恰为 216 s 有效控制及 8×3 s 固定初始化，这额外 2 s 只属于几何准备。
3. 全部正常控制来自原官方 PID。为了防止误替换其他世界，入口自行启动并核验 PID/启动时间/端口/进程组，只终止本批创建的进程组，不接受裸端口连接已有服务。
4. 在初始化后/t0前开始官方服务端 recorder；它在 PostTick 写记录后才广播世界快照。末个 tick 后停止 recorder，并在世界暂停时最多 2 s 轮询完整原文：必须有连续 1…N 帧、正确时间、ego/sensor 身份、每帧 ego 位置和文件尾。客户端碰撞回调只负责尽早中止，不能靠固定等待 0.2 s 推断“无碰撞”。每帧参考时钟与 recorder 自身从0开始的帧时间分开绑定。[官方时序](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Game/CarlaEngine.cpp)、[记录查询格式](https://github.com/carla-simulator/carla/blob/0.9.15/Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Recorder/CarlaRecorderQuery.cpp)
5. 预载位置检查包含预载前一帧和10个预载 tick，使用相对起点的最大偏移≤0.02 m，同时保存净位移和累计路程。不能往返后以净位移为零通过。创建 PID 之前核对有限值、垂直稳定及原设计初态条件。
6. 默认物理参数完整保存；世界步长、子步、天气和蓝图读回保存。生成式地图会写新包的 Nav/OpenDrive 目录，启动器仅准备这些准确路径及 Saved 的写权限，不递归更改旧 CARLA 目录。
7. 正常结束或异常都销毁本批 actor/sensor、终止专属 server；清理 RPC 用短超时，失败原因与汇总保留，不用还原新世界设置的额外 RPC 覆盖原始异常。

这些是运行/证据采集细节的落实，没有改变驾驶验收阈值。服务端 recorder 时序有官方源码依据，但本机实际服务尚未启动，所以其运行兼容性也未宣称通过。

## 验证证据与边界

- 主工作区（含保留的原有修改）规定的轻量复核：378项通过，239.474 s；日志 `docs/evidence/backbone_tracking_gate_2026_09_22/main_review_suite.log`。此前隔离工作树349项通过，日志 `review_suite.log`。
- 新模块定向测试及最终静态准备结果见同目录的 `verification.json` 与准备产物；包括不允许时间平移、漏终点、预载往返、侧向运动误判停车、记录器不完整、错误版本与占用端口等反例。
- CARLA 0.9.15 客户端原生 Map 已离线解析生成的 OpenDRIVE：指定内点位于120 m宽路面、外点不在路面，z=0；**不是服务端碰撞网格验收**。未给本地试验场定义地理投影，解析器会提示使用默认 georeference；本批不使用 GNSS/地理坐标。
- 定向模块的最终联合检查为24项，结果见 `targeted_tests.log`；它们是解析/合成/接口检查，不是物理驾驶。
- 另一次在仅为控制准备的 carla015 隔离环境中做完整 discovery，实际为134项、62 errors、2 failures，退出码1：旧模块缺少 SciPy/PyTorch/Transformers；两个 failure 均为公开 validate-only CLI 子测试，因缺 scipy.spatial.cKDTree 返回1。可恢复的原始输出及工具截断边界保存在 `full_discovery_attempt.log`，不能声称完整模型集成通过，也未为此扩大旧模型依赖。
- 一次扩大到模型集成的测试尝试在输出若干 `E` 后被人工中断，未保存日志、未得到各错误 traceback，不能归类为已有问题，也不能计为完整集成通过。中断时位于 `tests.test_query_value.QueryValueTests.test_synthetic_regression_learns_and_checkpoint_is_written_before_updates` 的临时JSON写出；这是中断位置，非该测试已证失败。后续改用项目明确的资源独立复核与本批定向测试。未启动真实模型训练。

## 服务端包缺口与准确路径

官方 CARLA 0.9.15 Linux 包：

- [官方下载](https://downloads.carlasim.com/Linux/CARLA_0.9.15.tar.gz)，[官方发布页面](https://github.com/carla-simulator/carla/releases/tag/0.9.15)。
- 本轮带浏览器 User-Agent 的 HEAD 返回 200；Content-Length 为 **8,386,636,048 bytes**（约8.39 GB）。普通HEAD曾403。
- 建议压缩包路径：`/root/autodl-tmp/carla-download/CARLA_0.9.15.tar.gz`。
- 独立解压目录：`/root/autodl-tmp/CARLA_0.9.15`；保留已有0.9.10.1。生成式试验场无需 AdditionalMaps。

[AGENTS.md](../AGENTS.md)保留大文件由用户提供、直接小文件下载少于100 MB的约定，因此本批没有自动下载此包。用户提供路径后，先检查尺寸、完整读取压缩包、解压布局和磁盘，再启动本批；不重复准备或修改控制方案。

## 已准备的运行入口

本轮已执行的静态准备命令（不连接服务端；该输出目录现已存在，勿重复运行或覆盖）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/root/autodl-tmp/conda-envs/carla015/bin/python \
/root/autodl-tmp/ToolV2X/scripts/probe_backbone_tracking.py \
--output /root/autodl-tmp/ToolV2X/outputs/backbone_tracking_preparation_2026_09_22
```

服务包到位并检查后，由入口启动自己的服务，尝试固定首批：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/root/autodl-tmp/conda-envs/carla015/bin/python \
/root/autodl-tmp/ToolV2X/scripts/probe_backbone_tracking.py \
--execute --carla-root /root/autodl-tmp/CARLA_0.9.15 --port 2015 \
--output /root/autodl-tmp/ToolV2X/outputs/backbone_tracking_gate_v1
```

落盘数据复算（运行器不会自己宣布完整PASS）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
/root/autodl-tmp/conda-envs/carla015/bin/python \
/root/autodl-tmp/ToolV2X/src/evaluation/tracking_gate.py \
--batch /root/autodl-tmp/ToolV2X/outputs/backbone_tracking_gate_v1
```

首批任一项失败就停在该层；通过后也只报告给定参考的控制结果，不自动开始 RP、感知、F 或论文方法实验。
