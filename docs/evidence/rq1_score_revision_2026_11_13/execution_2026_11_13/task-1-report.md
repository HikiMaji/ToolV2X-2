# Task 1 实施报告

日期 2026-11-13。基于3638f32，工作树为`.worktrees/rq1-score-revision-2026-11-13`。本报告只说明新增准备代码及有限验证，不表示26次真实攻击已经构造，也不表示数据支持或方法收益成立。

## 交付

仅新增`scripts/rq1_score_revision/prepare.py`与`test_prepare.py`。未修改冻结配置、协议、标签规则、原`rq1_temporal`代码或旧run数据。未启动真实攻击、clean回放、拟合或评分。

公开接口为`read_config(path=None)`、`iter_rows(out, split=None)`和`support_summary(rows, config)`。CLI为`python -m scripts.rq1_score_revision.prepare --out ... --workers 8`。worker通过私有`--_worker JOB_ID`在既有原生runtime中按job独立启动，Numba/BLAS/OMP线程为1，并行数限制为1至8。

新manifest保留70旧任务的原rows/status绝对路径引用，旧任务origin改为reference并保留source_origin。新26任务保留全部冻结元数据及source_clean_job_id，origin为score_revision。每条新任务仅在自己的jobs目录写attack、online、rows、entity_coverage与complete/error。旧UNREALIZABLE仍保留来源引用，iter_rows跳过其无rows情况。旧clean完整行和Z直接复用，iter_rows不筛掉攻击背景或短轨迹。

五三车父从旧clean配置取得sender前80包，与现有offline GT按frame连接，检测路径保留parent中的train层。消息字段用公共字段白名单去除私有GT，echo为空。父级scan缓存在调度前一次性建立，避免26worker重复写父缓存。四车父直接引用旧scans及provenance spec，worker只取前80扫描。父输入检查冻结source顺序、frame/index/timestamp、指定检测文件存在，以及前20扫描已有clean行的元数据对应。

worker直接调用原construct_attack、replay_online、attach_labels、coverage_summary。没有新推理，没有改变构造器随机数或几何策略。完整attack和online可恢复，rows与coverage可独立补齐。失败保留error及partial，不发布complete。UNREALIZABLE作为固定尝试结果完成记录，不替换seed或父。根目录和job锁避免重复写，成功文件及最终标记沿用原atomic写法。输出在写锁文件前排除旧源run及其父子目录。

## 支持统计接口

`support.json`包含`entities[job_id]`、`families[F1/F2]`、`regimes[mixed/F1_only/F2_only]`以及`any_regime_supported`。每个family有`counted_entities`、`counted_parents`、`attack_k_support`、`data_support_met`和`reasons`。每个regime有`fit_false`、`data_support_met`与`unsupported_families`。

计数单位是冻结job中的单个target，合法预查询、非newborn、query_truth为0且attack_role为target时才累计不同frame。跨ID和epoch合并，同帧多个碎片只计一次。至少10不同扫描的实体贡献六实体与三父门槛，k1及k>=2存在性使用所有非空明确假query，包括短轨迹。缺支持不改变阈值。prepare只发布支持结果，是否运行后续头由Task2负责。

## 验证证据

1. 首次新增测试在实现文件不存在时失败，随后完成实现。新增旧输入写入保护fixture曾触发缺少提前隔离检查，补齐后通过。
2. `python -m unittest scripts.rq1_score_revision.test_prepare -v`通过8项。
3. `/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m unittest scripts.rq1_score_revision.test_prepare -v`通过同8项。
4. fixture覆盖实体碎裂及重复帧计数、计数父与短轨迹k覆盖区分、GT按frame连接、来源顺序/扫描错误拒绝、私有字段排除、旧Z保留、残片不完成、错误保留、online恢复、缺coverage补齐、UNREALIZABLE终态，以及已完成任务不重跑。
5. 一次临时目录实际输入接入检查通过6父。五三车各80扫描，第六父引用旧113扫描缓存，worker取前80。不产生新研究目录、不构造攻击。冻结source manifest/model/protocol/native/kernel/fit的hash绑定通过。临时缓存随TemporaryDirectory清理。
6. 原生runtime成功导入native_adapter.imports、quaternion、TrackEncoder/TrackDecoder/TrackBase、Polygon和extract_frame。CLI help正常。

按任务指令仅执行上述必要fixture与原生导入检查，未启动完整项目测试或26真实任务。完整项目套件涉及无关外部模型与历史任务，本报告不据此声称全库通过。

## 审核关注点及剩余边界

独立审核须追查五三车检测路径、公开/离线字段边界、原子恢复和支持门槛。真实三车/四车首次成功任务的前20扫描与旧clean行为核对由主会话另行完成，本次只验证输入元数据对应，没有做真实replay等价性检验。当前八项测试和导入成功不保证26次攻击可构造，也不保证六实体/三父支持足够。标签和研究效果仍须真实批次及后续独立统计证据。

## 追加修复 空FOV接入与恢复诊断

日期仍为2026-11-13。主会话报告真实批次已退出，16 COMPLETE、8 UNREALIZABLE、2错误；本轮以bae0a67为修复基线，仅修改本任务拥有的prepare/test文件，不操作Task2草稿，不重跑研究任务。

失败任务88d0c4cf9eb9c85e的error.json已实际核读。原生replay_online第291行把缺失FOV的None转为零维数组后传给Polygon，触发`TypeError: iteration over a 0-d array`。旧static.extract_job第118至120行对无效FOV采用包含判断恒False的对象，message_conditions.polygon对于None和[]都返回None，source_features保持eligible=False。

最小修改只在_public新建的公共消息dict中把None boundary改为[]。原始父scan与构造输入不修改，已有有效polygon也不变化。冻结native及所有构造规则不修改。manifest的配置和代码hash保护不放宽，本实现不迁移既有manifest，不重写24个终态job。快照、执行版本记录及未完成manifest的显式迁移由主会话审核后处理。

同轮修复非阻断诊断问题。在worker已有rows遍历中重计target_query_rows和其他明确假角色计数，覆盖attach_labels中已有计数，避免首次生成时双重累计，也使rows/coverage均已发布但complete未发布的恢复点得到相同诊断。支持门槛和标签不变化。

新增两个定点fixture先失败后通过，分别固定公共None转空但原scan不变，以及复用完整online/rows/coverage后重计target_query_rows。只运行这两个新增fixture，没有重复完整套件。命令为`python -m unittest scripts.rq1_score_revision.test_prepare.PrepareContracts.test_public_null_fov_becomes_empty_without_changing_raw_scan scripts.rq1_score_revision.test_prepare.PrepareContracts.test_complete_marker_recovery_recounts_target_queries_from_rows -v`。

原生Python3.10纯内存检查确认`Polygon(np.asarray([]))`是empty，三个测试点check_point全部False，message_conditions.polygon在原始None和公共[]输入均返回None，两种source_features结果逐项完全相同且eligible=False，原始None仍保留。未调用真实construct_attack或replay_online。

这一修复验证的是空FOV表示兼容性及恢复诊断，不预先保证两个真实错误任务恢复成功或数据支持足够。
