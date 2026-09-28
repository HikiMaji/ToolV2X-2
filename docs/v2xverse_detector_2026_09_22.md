# V2Xverse 原生检测器小批验证（2026-09-22）

结论：原预训练检测网络已在官方双车连续点云上真实运行，具备继续接因果跟踪的工程条件；尚未成为ToolV2X生产P服务，不是检测精度或协作收益验收。

## 使用了什么

- 官方来源：https://github.com/CollaborativePerception/V2Xverse 。模型来自作者仓库 https://huggingface.co/gjliu/v2xverse 的 no_collaboration/perception（32,817,341字节）。未借用V2V4Real检测权重。
- center_point_codriving原网络、原SpVoxelPreprocessor、原预测框解码和VoxelPostprocessor/NMS。194项state_dict严格匹配，未修改上游Python源码。每次record_len=[1]，只有该车当前点云，不混入邻车。
- 原config阈值0.2、NMS阈值0、点云范围[-36,-12,-22,36,12,14]保持不变。
- 显式输入薄层复现原数据入口的(x,y)->(y,-x)、z+=lidar_pose_z，以及原shuffle、mask_ego_points_v2。没有实例化会读取标签/专家信息的完整dataset。
- 原生环境tcp_codriving（PyTorch1.10.1+cu113）；设置进程LD_LIBRARY_PATH解决已有libcuhash依赖，不重装训练环境。复用CMP已有Python3.7 box_overlaps二进制满足原模块导入，其路径已记录；本次旋转NMS仍用官方Python/Shapely路径，不替换为简化NMS。

## 真实数据与结果

来自官方routes_town03_21_w0_05_01_06_57_16，ego_vehicle_0/1各0010—0014帧。20个小文件共3,670,949字节。先验证现有2帧，再运行连续10条样本；合计12次真实模型前向，0次训练。

| 车辆 | 0010 | 0011 | 0012 | 0013 | 0014 |
|---|---:|---:|---:|---:|---:|
| 0原始车辆框数 | 2 | 2 | 2 | 2 | 2 |
| 1原始车辆框数 | 3 | 4 | 4 | 4 | 2 |

这些数包含疑似本车框，不是外部有效目标数。两车在约(-1.3,0)位置持续输出车身大小框，置信度约0.22—0.25；该位置与本车安装几何一致，须由合法本车排除逻辑处理。保留原输出，没有事后调高阈值。远处车辆检测随帧变化，不能据框数判断稳定跟踪已实现。

离线几何核对使用双方当前measurement中的位置和原官方坐标变换，最近框中心偏差平均0.0713m、最大0.2020m。这些双方位置信息未送入检测网络；该核对仅针对已知对方车辆的中心，并采用最近中心匹配，没有GT全目标集/尺寸/身份评估，不能称AP、召回率或身份关联通过。

连续10次纯模型前向累计约0.192s（包含首帧冷启动）；不含文件读取、体素化和后处理，不作为端到端时延。现有录制没有绑定capture timestamp，记录timestamp_seconds=None，不按文件号伪造速度或时标。

## 修改与验证

新增`scripts/probe_v2xverse_detector.py`和`tests/test_v2xverse_detector_probe.py`，注册到轻量检查；三项新测试RED→GREEN，含既有读取测试共6项通过，git diff --check通过。未重跑整套轻量测试；此前356项通过属于上一批。未修改生产planner/provider/wire，也未训练、运行MTR或新P/F方法实验。

## 下一步

1. 按合法本车几何排除本车检测，并把原始框与过滤理由分别记录；不凭本批结果调参。
2. 对明确时标的连续采集接原有因果跟踪，处理位置/速度/实体身份；旧样本时标未知不阻塞新受控采集。
3. 让本车检测跟踪进入同一PDM，再把邻车相同检测服务包装为P，做坐标关联和遮挡小场景验收。F/MTR与LLM调度后置。

上一轮CARLA采集使用yaw=0、z=2m、32线配置，与此原生数据入口不同。**不得直接将那批点云送入本脚本**；需要按原传感器配置重新采集或经过明确标定转换后另立输入规格。

## 复跑

```bash
cd /root/autodl-tmp/ToolV2X
DETECTOR_ROOT=/root/autodl-tmp/toolv2x_backbone_research_2026_09_19/detector
LD_LIBRARY_PATH=/root/miniconda3/envs/tcp_codriving/lib/python3.7/site-packages/spconv:/root/miniconda3/envs/tcp_codriving/lib \
/root/miniconda3/envs/tcp_codriving/bin/python scripts/probe_v2xverse_detector.py \
  --source-root "$DETECTOR_ROOT/V2Xverse" --model-dir "$DETECTOR_ROOT" \
  --sample-root "$DETECTOR_ROOT/sequence" \
  --overlap-extension-dir /root/autodl-tmp/CMP/opencood/utils \
  --output /tmp/new_v2xverse_detector_probe
```

输出目录必须不存在。外部代码和权重不入Git。原始输出在outputs/v2xverse_detector_sequence_2026_09_22，精简证据在docs/evidence/v2xverse_detector_2026_09_22。未推送GitHub。
