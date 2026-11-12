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
