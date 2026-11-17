# 可信接收车本轮数据范围核对

2026-11-17。仅核对冻结清单、现有元数据、少量必要路径及实际读取接口。没有生成攻击、读取PCD内容、重训模型或计算新方法效果。

结论是保留原6 fit、5 cal、3 eval和后续6加3个eval父。固定每父max(sorted source_ids)为receiver。主假范围仅F1/F2及k1/k2，F0全族不纳入本轮主校准、主评价。已有k3仅可作预先声明的范围外压力资料，不进入新门限和主裁决。

## 五个校准父

| 父录制 | receiver | 同步扫描 | 检测缓存 | 首80全源检测路径和ego代表PCD路径 |
| --- | ---: | ---: | --- | --- |
| train/2021_08_18_22_16_12 | 1331 | 267 | legacy h1 | 已存在 |
| train/2021_08_20_20_39_00 | 1252 | 110 | legacy h1 | 已存在 |
| train/2021_08_21_22_21_37 | 3005 | 134 | legacy h1 | 已存在 |
| train/2021_08_22_22_30_58 | 1259 | 96 | legacy h1 | 已存在 |
| test/2021_08_22_07_52_02 | 3513 | 167 | native test | 已存在 |

扫描范围来自旧clean配置或native provenance。检测路径按明确帧号核对，没有重做全库盘点。PCD只核对首帧、第80帧、末帧路径，不能由此声称已经解析和验证每帧PCD内容。

现成test/2021_08_22_07_52_02的F1/k1 13df4899473dbad7、F1/k2 343d46fc7b709925和F2/k1 4c23cf38a32e4c03为COMPLETE。F2/k2 9e76a1233ee15da2为UNREALIZABLE，保持原结果，不重试。四个train cal没有F1/F2既有任务，需按清单各补4个，共16次固定尝试。不可构造不换seed或场景。

## 最小兼容处理

`native.recording_spec`对train默认找expanded检测目录，不能用于这些legacy父。四train cal应复用原clean配置的sender_path与expected_frames前80项，配合prepare.LEGACY_GT中对应父的原GT，调用prepare._legacy_scans形成scans。它没有fit角色限制，保留原消息、帧、时间和FOV。spec.detections明确指向h1缓存，离线GT只供原攻击构造与标签。

prepare._worker可以复用，它只检查origin为score_revision、manifest父绑定和构造角色，不硬编码split为fit。包装器应提供独立输出目录、parents scan_path/spec、controlled_sources及normal_probe_source。不能调用旧read_config/完整prepare入口，因为它们硬编码26个fit攻击。

## 公开查询、特征与模型来源

原5个legacy fit clean、4个legacy cal clean及原train eval的公开查询在rq1_static_trial_2026_11_10/run_001/events/{job_id}.jsonl.gz。第6fit及其他native任务在temporal相应job/online.jsonl.gz。代表行均含query_geometry，没有标签字段。temporal legacy rows含标签并省略query_geometry，不可交给本地侧录代替公开输入。

legacy的公开C、C_missing等条件在rq1_real_cue_2026_11_11/run_001/features/{job_id}.jsonl.gz。fit窗口特征由score_revision/features.complete.json的folds映射到父聚合文件，须按job_id取对应clean；不按clean job文件名猜路径。其余cal/eval特征已有完整路径。

5cal及六个额外eval的Count预测在report_freeze/run_001/predictions/{regime}/{split}.jsonl.gz。追加三eval在joint_supplement/run_002/predictions/additional/{regime}/eval.jsonl.gz。原3eval尚无当前Count现成预测，需用已有features和report_freeze/run_001/models/{regime}.json的冻结Count模型计算，不重训。p_D沿用temporal/run_001/models.json。

完整绝对路径、父角色、固定receiver、全部141个旧任务的完成状态、公开查询、rows、features及Count来源已记录在[batch_scope_sources.json](batch_scope_sources.json)。23父中6 fit、5 cal、12 eval。141历史任务有107 COMPLETE、34 UNREALIZABLE。保留清单不等于这些任务全部进入新主比较。

## 边界

历史F0有10个任务控制了该父最大source ID，其中8个属于cal、2个属于原eval。它们与固定可信receiver前提冲突。当前采用全F0族排除主比较，避免只按冲突逐个筛选。事实保留在JSON，不改旧结果。

16次新增构造能否产生每层足够独立父与实体尚未知。构造成功、查询有明确假标签、校准分母有效和风险估计充分是不同条件。一次固定尝试后照实报告覆盖。缺层按SDS关闭采纳，不把无样本当零风险，不无限扩任务。现有资料都属于已经看过的开发资产，不能称新盲测。
