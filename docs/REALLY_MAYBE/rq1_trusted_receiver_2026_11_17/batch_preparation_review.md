# 固定清单与校准准备包装独立审核

2026-11-17。采用ponytail-review的具体风险审查方式，只审查prepare_calibration.py、batch.json及实际调用的_legacy_scans、_public、_worker和native replay/label函数。未执行新攻击或方法效果。

**结论：未发现阻断这16项固定准备任务的问题，可以按该清单运行。** 本结论只覆盖准备包装、角色、身份与输入语义，不代表新方法有效或假侧覆盖充分。

1. 清单有23父，角色为6 fit、5 cal、12 eval。87任务唯一，包含23 clean、20 cal fake、44 eval fake。与先前核实来源逐项比较，既有任务的父、角色、族、k、状态及online/rows/features路径没有变更。F0整体、fit攻击、k3及F3未进入本轮主比较，既有不可构造任务保留。
2. 20个cal任务的job ID均等于原data.job_id定义。16个缺失任务确实不在旧任务集中，另外4项沿用旧任务。全部受控来源为sorted source IDs的前k项，normal_probe为source_ids[k]，固定receiver为父清单最大ID，不在受控集合内。没有按目标、标签或分数选择receiver或父角色。
3. 四个新增cal父由原clean sender、expected_frames前80及对应原LEGACY_GT进入_legacy_scans。函数核对帧、索引、时间、来源顺序和GT帧对应。spec显式绑定旧h1检测目录，绕过native.recording_spec的默认路径。没有偷挪fit或eval进入cal。
4. 构造参数保持seed0、最多64个候选、80扫描、20至60注入区间和原F1/F2构造规则。旧_worker直接使用原construct_attack、replay_online和attach_labels，包装未改算法或标签标准。当前两个旧源文件没有未提交差异。Count及p_D模型来源与核实清单相同，没有训练调用。
5. _public仅向回放传递消息、帧和时间，剥离GT及echo。回放中的attack配置用于离线实验注入，不写入公开事件或供核验器识别攻击来源。query由上一中央状态预测，标签只在online落盘后通过attach_labels附加。后续本地侧录仍须读取online_path，不能读取带标签rows替代公开查询。
6. 4个进程只写各自job目录。原replay_online在每job重置TrackBase.ID_counter，因此进程复用不会使轨迹ID依赖任务调度。原_worker按job锁和独立完成文件恢复，不修改旧产物。UNREALIZABLE按原终止语义写出，不换seed或替代场景。

本次必要核对是固定清单和接口的静态语义及元数据一致性，没有运行感知、PCD解析、攻击构造或全库盘点。16次尝试完成后应按实际可标注假查询、父和实体报告覆盖。不能用prepare.complete或函数返回门限代替校准支持判断。
