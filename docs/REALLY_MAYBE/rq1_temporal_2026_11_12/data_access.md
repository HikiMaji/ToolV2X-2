# 时序实施的数据接口核查

2026-11-12。只读核查既有inventory、有限缓存目录、配置及源码。未重新盘点47段，未扫描原始点云，未训练、检测、回放或改代码。下列文件存在性和接口是核查事实，扩展安排仍是实施建议。

## 1. 可直接扩展的多车开发材料

既有盘点入口为`docs/evidence/dataset_inventory_2026_11_04/inventory.json`。旧21段中以下4段均已有冻结检测，抽样NPZ均保存相同checkpoint SHA256 `84e37c565a9af221b925eaaa89dd12e276f062df3974b348e34b0e0215ae9921`。

| 父录制 | 来源数 | 帧数 | 检测文件数 | 当前可复用FOV |
| --- | --- | --- | --- | --- |
| test/2021_08_22_07_52_02 | 5 | 167 | 835 | 每帧已有 |
| test/2021_08_24_07_45_41 | 4 | 135 | 540 | 每帧已有 |
| train/2021_08_23_22_31_01 | 4 | 113 | 452 | 已查native文件未保存，需补算 |
| validate/2021_08_20_21_48_35 | 5 | 112 | 560 | 已查native文件未保存，需补算 |

前两段检测目录为`docs/evidence/mate_continuous_occurrence_2026_10_08/detections/{scene}/{frame:06d}_{source_id}.npz`。后两段为`docs/evidence/oqea_expanded_test_2026_10_16/detections/{scene}/`，同一文件名。NPZ字段为`boxes,scores,lidar_pose,raw_pcd_sha256,checkpoint_sha256`。没有读取原始PCD重新hash。

前两段FOV来自`docs/evidence/mate_coverage_correction_2026_10_08/native_corrected/{scene}.jsonl`中的`fov_boundaries[str(source_id)]`。文件也有`raw_pcd`路径、`timestamp`和`source_positions`，但消息的传感器位置应从NPZ的lidar_pose转换，不能把车体source_positions当LiDAR位置。

5车段来源为`[3477,3486,3495,3504,3513]`，frame为71至403、步2、时间0至16.6秒。4车段来源为`[121,130,139,148]`，frame为70至338、步2、时间0至13.4秒。按已有native逐行核实，各段来源集合稳定。两段都是已经参与旧研究的开发材料，不能称独立未见保留集。

建议先把这两段加入新开发manifest，在CPU上直接从冻结检测生成sender和中性前端事件。旧native的`local_tracks`只保存track_json投影，缺完整协方差P，不应伪装成TrackDecoder完整消息。应复用冻结检测重跑局部跟踪，不重跑检测。后两段可在首次回波监督读取PCD时同时生成FOV，减少重复读取。

## 2. 任意N的真实代码边界

`scripts/oqea_joint/expanded_native.py:execute`和`docs/evidence/mate_continuous_occurrence_2026_10_08/run_native.py:main`按来源字典遍历，局部tracker、中央MeasurementBasedMultiTracker、FOV和MATE均没有固定三车维度。历史4/5车产物存在，证明这些原生组件已有多车运行记录。

当前39任务的管理包装却确实写死三车。相关实现位于`.worktrees/oqea-h1-2026-10-30/scripts/oqea_joint/`。

- `recording_inputs.build_manifest`检查`sources==3`、`len(ids)==3`，并绑定旧批次角色/保护范围。
- `recording_replay.validate_receiver_config`和`send_job`检查3源；统计预算使用`3*len(frames)`。
- `.worktrees/rq1-static-2026-11-10/scripts/rq1_static_trial/extract.py:attach_outputs`的新生分支写死`U=[-1]*3,X=[None]*3,G=[None]*3`。主要预查询和fresh关联循环按来源遍历。
- `rq1_real_cue.run.extract_frame`及geometry函数按source_ids工作；但extract和parent_splits绑定39任务及5/4/1父划分，不能原封不动用于新批。

因此是有限包装适配工作，不是底层必须重建，也不能直接宣称现有39任务入口已支持任意N。新入口保留排序、唯一来源、时间、标签对应等必要检查，使用新manifest和新产物目录，不重写旧冻结批次。

可复用基础函数为`run_native.ref_from_pose`、`make_detections`、`config_model`、`track_json`，`rq1_static_trial.extract.fresh_tracks`、`predict_queries`、`associate_fresh`、`source_features`，及`rq1_real_cue.geometry.frame_cues`。native运行解释器为`/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python`，当前链接到carla015环境。源码使用numpy、scipy、numpy-quaternion、shapely和已有AVstack/avtrust目录。CPU原生依赖与GPU检测依赖应分别检查。

旧`expanded_native.py --kind old_clean/new_clean --pilot`属于旧固定批次，已有输出会拒绝覆盖，不是新批启动命令。旧`recording_inputs.py --stage manifest/detect/gt/attacks --spec ... --out ...`也有三源与registry绑定。新批须先完成上述小适配，再提供可复制命令，不能靠直接重用旧CLI制造已就绪假象。

## 3. 其余9段四至七车资源

以下直接来自既有inventory，未再扫描原始目录。已查的三个检测根只覆盖旧16、扩5及旧10父，未见这些录制的冻结检测。缺当前缓存不等于禁止使用。

| 父录制 | 来源数 | 帧数 |
| --- | --- | --- |
| train/2021_08_18_19_11_02 | 4 | 122 |
| train/2021_08_21_09_09_41 | 4 | 174 |
| train/2021_08_22_06_43_37 | 4 | 181 |
| train/2021_08_22_07_24_12 | 4 | 190 |
| train/2021_09_09_13_20_58 | 4 | 391 |
| train/2021_09_09_22_21_11 | 6 | 154 |
| train/2021_09_09_23_21_21 | 5 | 451 |
| train/2021_09_10_12_07_11 | 5 | 383 |
| validate/2021_09_09_19_27_35 | 7 | 459 |

原始根为`/root/autodl-tmp/ToolV2X_resources/oqea_raw_extension_2026_10_29/OPV2V`。可按冻结前端补检测、FOV和消息，无需训练新感知模型。本次未判断其全部是否具备未见资格，应先沿使用记录冻结开发/保留划分。已知`train/2021_08_21_22_21_37`与`train/2021_08_22_06_43_37`有保护重叠，旧spec的`protected_overlap`明确登记，不能跨fit/保留泄漏。

当前exec环境没有可见GPU，新增检测不能按GPU已就绪安排。先完成既有4/5车缓存的CPU开发；6/7车和其他新录制仍在主数据范围，后续接入须列明实际可用检测资源及运行预算，不把当前资源限制改写成长期只用十父。

## 4. 回波监督的最小新增读取

已有计数脚本是`docs/evidence/oqea_controlled_observation_2026_10_15/quality_audit.py`，输出过`offline_target_returns.jsonl`。它只处理固定合成目标900、固定三源、yaw位姿和轴对齐框，不能原样用于一般OPV2V目标。其计数思想可复用，通用OBB适配必须新增。

原始ASCII PCD读取可复用`run_native.load_points(path)`，返回有限float32的N乘3数组。`run_native.rot`或`recording_inputs.rotation`提供完整roll/yaw/pitch变换。不要在通用录制中沿用quality_audit的仅yaw变换。

当前十父GT可直接复用`oqea_h1_retrain_2026_10_30_envfix1/run_001/offline_gt/offline_gt.json`。结构为`recordings[].recording,frames[]`，每帧有`frame,index,timestamp,available,status,boxes`，框有`gt_id,xyz,hwl,rotation,where_is_t='center'`。GT合并与冲突处理接口为`recording_inputs._gt_frame`；它读取每源yaml的`vehicles`，使用`location + rotation(angle) @ center`，已有完整姿态和一致性检查。旧21段可按新manifest调用同一语义；不能直接采用旧offline_gt中任取首源而忽略冲突的行为。

统一到已有native右手世界坐标后可计算：

```text
world = (points @ R_pose.T + lidar_pose[:3]) @ FLIP
local = (world - gt_box.xyz) @ gt_box.rotation
half_extent_xyz = gt_box.hwl[[2,1,0]] / 2
count = sum(all(abs(local) <= half_extent_xyz + tolerance))
Z = int(count > 0)
```

固定数值容差并记录。原始框内回波是监督代理，不先套检测ROI裁剪，也不称真实遮挡标签。PCD或GT不可用记缺失，不能补零。

推荐按`(parent,frame,source_id)`读每份clean点云一次，在该帧上批量计数所有需要的gt_id，输出小表`parent,frame,index,timestamp,source_id,gt_id,gt_available,pcd_available,count,Z`。只处理clean及实际监督需要的帧，不按攻击job再次读取。当前query的GT身份从旧labelled中的`query_gt_id`连接，不能用output_gt_id替换预查询身份。连续转移须同GT身份、相邻合法扫描和父内隔离，不能跨缺帧拼接。

## 5. 39份C特征的安全复用

`docs/evidence/rq1_real_cue_2026_11_11/run_001/features`有39份gzip，合计10,116,270字节，文件job集合与静态manifest完全相符。`manifest.json`、`extraction_summary.json`和`labelled_features.jsonl.gz`均不存在。这是未完成批次，不应冒充完成manifest。

已有特征字段包括`key,job_id,id,frame,index,timestamp,source_ids,U,X,C,C_missing,main_blocker_ids,groups,newborn,query_present,native_adopted,output_present,identity_ok`。`X`已经只保留前5列。`ray_ids/public_groups`可只留审计副本，核心拟合不必全量装入内存。

恢复源为`docs/evidence/rq1_static_trial_2026_11_10/run_001/labelled.jsonl.gz`，来自同一job/key。旧realcue.run.extract结尾把39份特征整体装dict再join；不要重跑该extract，也不要只为了join再次hash全部sender/events/labelled。

最小流式方案是逐行扫描旧labelled，按job_id维护对应feature gzip迭代器，每个label只消费该job的下一条feature，检查`key,source_ids,U,frame,index,timestamp`相同，最终每个迭代器EOF并核对job计数。若实施时发现顺序不一致，再用小型sqlite键连接，不默认把全部大对象装dict。gzip完整解码本身能暴露截断，最终EOF和计数是必要完成条件。

只附加`parent,kind,query_truth,query_gt_id,query_label_reason,output_truth,output_gt_id,label_conflict,gt_identity_conflict`及新冻结split。旧realcue白名单没有保留query_gt_id，不能照搬。标签和GT身份只在离线处理使用。新manifest注明复用39个已存特征、补成的阶段和边界验证，不追补伪装原run已经完成。

## 6. 必须真正补算的内容

1. 新时序状态监督。现有39份C特征没有GT框内点数，需按clean录制生成一次回波小表。
2. 新4/5车sender、当前预查询事件、C与标签。检测和前两段FOV已有，不需要新GPU推理；包装必须去掉三车维度并使用新目录。
3. 扩5中两段的FOV。可与其回波读取合并；仅有旧native候选日志不足以恢复完整FOV和当前预查询。
4. 其余9段多车录制的冻结检测/FOV/消息。按实际资源接入，不能因当前没有cache将其排除。
5. F1/F2/F3的多受控消息及标签。旧29个attack job只覆盖旧攻击设定，不能充当已经存在的k>=2或条件污染检验；不必重复检测clean背景。

直接复用静态labelled和39份C能先开发状态前向及窗口评分；多车及新攻击是随后必要实证，不因旧批次恢复方便而消失。以上接口事实不支持方法有效性、状态代理有增量或论文贡献的结论。
