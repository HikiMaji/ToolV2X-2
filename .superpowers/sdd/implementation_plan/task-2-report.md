# Task 2 实施报告

2026-11-12。当前状态为代码与有限fixture完成，等待独立规格/质量审核。没有启动正式prepare、真实14父拟合、真实攻击构造或研究评分。

## 文件与接口

新增`scripts/rq1_temporal/data.py`、`native_adapter.py`、`run.py`和`test_data.py`。Task1的kernel.py、fit.py和核心测试未改。

- data：固定14父6fit/5cal/3eval，旧39任务流式逐job gzip join，校验key/source_ids/U/帧/时间和全部EOF，补query_gt_id及native_mean，合法在线epoch及回波表连接。主监督只读clean fit PCD，每帧每源一次，对需要的GT用完整姿态OBB批量计数。GT/PCD缺失保留Z=-1。
- native_adapter：新增4/5源父复用冻结NPZ；两段FOV逐帧读旧native_corrected，只保留必要消息字段；另两段从PCD生成原生FOV。局部tracking后完整TrackEncoder/Decoder消息，中央统一消费局部轨迹转换BoxDetection。当前query与C先于中央更新；MATE原hook不替换，agents位置统一消息LiDAR pose。每job重置原生TrackBase的ID计数，保证续跑跳过已完成job不改变后续job的ID分配。
- 攻击：新3父、F1/F2/F3、k=1/2/3、seed=0共最多27任务。只在源局部输入追加世界坐标BoxDetection，固定尺寸和候选最多64个。不读取防御分数。冻结VALID/UNREALIZABLE及原因，F3提前5帧辅助框、停报20帧有界参考、GT相容与假角色歧义未知均有显式分支。F3保留原生前端实际公开遮挡帧及是否形成对应阻挡，不因不生效重选位置。
- run：prepare/fit/score/report CLI，已完成阶段拒绝覆盖；prepare逐job原子产物及complete.json，未完成阶段可续。原输入、既有脚本及旧批次只读。新manifest记录代码commit/适配源码哈希、旧特征/标签来源与划分；原生边界记录解释器/依赖版本及原生类源码哈希、检测NPZ/已有raw哈希、YAML和FOV来源。
- fit保持完整clean fit序列供OOF，含未知标签及无query历史。score保留新生、删除query、不可估方法和共同数值失败，不删共同分母。只存紧凑scores/NLL/资格/标签/状态及delta，不逐行存posterior或steps。五套预声明W/s重评分，不重拟主模型。
- report：同资格独立cal A/R门限，tie整体累计，正负分支分开且0分未知。总体及非空family/k层各5%经验预算，缺层记录not_calibrated；无相应错误类别关闭对应分支。主真clean父/epoch/时刻等权，主假family/k、父、target epoch、时刻分级等权。F3辅助occluder单列。输出六格、同政策MATE与原生MATE分别报告、每父/k/共同组等分层、NLL、state delta、参数支持、轨迹首次采纳/未采纳/曾假采纳/最长连续错误、开发父配对bootstrap、cases及PNG。

## 自审修正

1. 门限扫描采用排序后tie累计，避免候选门限乘全部行的平方时间；用小fixture与直接穷举门限比较。
2. 未知标签历史保留在OOF和轨迹起点，首次采纳延迟不从第一条已知标签重新计时。
3. 结构不可估只影响相关方法；numerical_failure同record全部方法unknown，MATE mean缺失不填0。
4. 停报后必须同epoch曾明确关联且在20帧参考范围内才标假，未见epoch不能继承假身份；GT可用性和角色歧义继续限制。
5. F3主风险只计算target，实际未形成公开阻挡另记，UNREALIZABLE保留任务分母。
6. 新FOV源逐帧消费，额外EOF检查在原子扫描缓存提交之前完成。

## 有限验证

最终命令及结果补在本报告末尾。fixture输出均在TemporaryDirectory内，没有写正式run_001。

新增四父只读检测元数据核对为4源113帧、5源167帧、4源135帧、5源112帧。没有读取真实PCD或运行真实原生帧。

Python3.10原生fixture使用合成NPZ，各4/5源5帧，实际走局部tracker、wire解码、fresh匹配、central与MATE及新生N维数组。既有quaternion触发numpy转换弃用提示，未修改外部依赖。

## 真实未覆盖范围

没有证明旧39份真实gzip join最终全部匹配、真实PCD/GT回波覆盖、真实新增父FOV/原生轨迹可用性、任何新攻击可构造或有效、参数可估或方法增量。完整真实批次和最终资源峰值仍待独立审核后由主会话执行。fixture和元数据检查不能替代这些实证。未安装框架、torch或新检测，不改旧代码、数据或核心算法。

## 运行入口

审核通过后，主会话在本工作树以单线程环境依次运行以下阶段。默认输出为新证据目录run_001，各阶段完成后拒绝重复覆盖。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.rq1_temporal.run prepare
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.rq1_temporal.run fit
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.rq1_temporal.run score
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.rq1_temporal.run report
```

prepare内部仅原生适配使用已存在的Python3.10 CPU runtime，主CLI与核心保持Python3.8兼容。

## 最终验证记录

- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest scripts.rq1_temporal.test_temporal scripts.rq1_temporal.test_data -v`，26项，25项通过，原生fixture按解释器条件跳过1项，26.905秒。
- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m unittest scripts.rq1_temporal.test_data.NativeFixtureTests -v`，1项通过，82.794秒。
- `python -m py_compile scripts/rq1_temporal/*.py`、`git diff --check`及CLI `--help`通过。
- 小fixture fit/score/report覆盖120条合成行，主参数和四套敏感性均生成评分，六格PNG、metrics、predictions、case诊断完成，覆盖复跑拒绝覆盖检查。临时目录自动清理。
- 最终方法裁决自审另确认joint相对G的明确判断收益也须通过J的两类开发风险预算。

代码提交待本报告同批提交。独立审核未执行，正式研究批次未执行。

## 独立审核集中修复 round 1

2026-11-12。根据独立审核`data_code_review.md`的五项阻塞/结果缺口集中修复。审核原文已复制到本工作树`docs/REALLY_MAYBE/rq1_temporal_2026_11_12/data_code_review.md`。未改kernel.py、fit.py、几何或原生跟踪/消息算法，没有正式prepare或新攻击运行。

1. report改为SQLite保存磁盘payload和217字节的固定数值记录。仅一个variant的一个split加载到NumPy数组。cal门限、六格和权重使用数值列。主predictions和案例候选逐行读取磁盘，案例候选最多48条。每variant/split的epoch明细直接写`report/epochs/*.jsonl.gz`，metrics只保留轨迹汇总。敏感性不重复保留主结果全量Python对象。SQLite是标准库，不增加框架。
2. cal同时累计正确类别的分级加权质量，在总体及非空family/k错误预算内最大化正确质量。平手保持更严格的A或R，关闭分支是零正确质量下的最保守候选。未知标签、辅助框和无资格行不提供门限放宽理由。ties整体、共同主类分母和0分未知保留。
3. 增加family/k联合六格，各类保留父/epoch/时刻数量，同时标记该层在cal是否有主假标签。原family、k、每父等边际分层保留。
4. 删除自动retain_increment及新加的NLL强制门槛。method_decisions现在只给同政策观察差异、方法可估状态和`pending_Task3_approved_criteria`，包括family/k假采纳差异、真采纳差异及已采纳延迟中位数差异。Task3仍须按批准标准结合未采纳轨迹和分层风险裁决。
5. 离线标签阶段即使某帧没有任何中央事件，也对冻结target/occluder写紧凑实体覆盖行。逐实体、逐帧分别保存pre/active/stopped阶段的query/output出现、明确假、GT相容、角色冲突、标签未知及无query，另保留对应候选数量。主六格不插入不存在的query。每任务complete保存覆盖汇总，report按family/k报告尝试、UNREALIZABLE、成功注入、无target query及标签未知覆盖。旧F0未有该实体覆盖表，显式记录not_available_for_all_tasks和legacy_injection_unverified，不把缺测填零。

正常首次标签写入与实体覆盖同次离线遍历。只有中断后的纯标签边界恢复会重读既有online产物，不重跑tracking。score增加每job/variant完成日志，保留既有每job汇总；核心OOF未改。

### 新定点证据

只运行本轮指定定点检查，没有重跑原生fixture或26项全套。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest \
  scripts.rq1_temporal.test_data.DataTests.test_conservative_correct_quality_tie \
  scripts.rq1_temporal.test_data.DataTests.test_calibration_matches_bruteforce \
  scripts.rq1_temporal.test_data.DataTests.test_calibration_ties_and_common_denominator \
  scripts.rq1_temporal.test_data.DataTests.test_family_k_joint_and_pending_decision \
  scripts.rq1_temporal.test_data.LabelFixtureTests.test_entity_coverage_includes_absence_ambiguity_and_newborn \
  scripts.rq1_temporal.test_data.DataTests.test_report_scalar_cache_stream -v
```

6项通过，2.542秒。三行审查反例现在为A=3、R=-2，eval假分数0.5保持未知。穷举对照已改为同一正确质量最大和保守平手目标。联合分层核对了cal缺层、父/epoch/时刻分母。覆盖fixture核对了无query帧、仅output新生、GT相容及角色歧义，并核对尝试2、UNREALIZABLE 1、实际注入1的汇总。

### 一次15万行report容量验证

```bash
RQ1_REPORT_LOAD_ROWS=150000 \
RQ1_REPORT_LOAD_EVIDENCE=/root/autodl-tmp/ToolV2X/.worktrees/rq1-temporal-2026-11-12/docs/REALLY_MAYBE/rq1_temporal_2026_11_12/report_load_peak.json \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m unittest scripts.rq1_temporal.test_data.DataTests.test_report_load_peak -v
```

1项通过，165.940秒。只执行了一次15万行容量验证。输入为合成评分记录，cal和eval各75,000行，有三个eval父。完整main report覆盖SQLite接入、cal、全部split统计、epoch明细、bootstrap、流式predictions/cases及PNG。固定标量记录每行217字节。进程基线RSS 57,408 KiB，`RUSAGE_SELF.ru_maxrss`为243,908 KiB，基线到进程总峰值的保守增量上界为182.129 MiB，低于300 MiB。原始证据在`report_load_peak.json`。此值包含导入和PNG，不把它解释为模型本身的内存峰值，也没有据此声称真实prepare/native资源峰值已测。

大容量路径之后，身份分组键由保留整行stride的结构视图改为三个整数的紧凑数组，并补了方法分数可用量和覆盖候选数量。217字节布局及阶段结构保持；最终6个定点检查覆盖这些小改动，没有追加第二次15万行运行。

### 运行时间边界

当前CPU配额为0.5核。既有120行五variant评分fixture约16.19秒，若仅作线性外推，15万行评分约5.6小时。这不是实际批次耗时保证。4/5源前向状态数、窗口长度和缺失情况会改变速度，另有PCD/FOV、tracking和OOF拟合。主会话应根据首个真实job/variant速度更新耗时判断。此次完整15万行report约123.586秒，其余42秒用于合成输入和临时目录清理。没有开多进程或线程加速，没有把启动后台任务当完成。
