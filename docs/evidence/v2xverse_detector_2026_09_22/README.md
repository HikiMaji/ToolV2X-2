# 原生检测器证据

参见 ../../v2xverse_detector_2026_09_22.md。

- summary.json：10次连续帧模型运行和参数/环境记录。
- detections.json：每车每帧输入路径、点数、原始三类检测框及分数。
- detections.png：首末帧车辆框叠加原点云，无GT；橙色为接近本车位置的框。
- peer_center_sanity.json：离线双方位置一致性核对，未给检测器使用，不是AP/跟踪。
- official_config.yaml、source.json、sample_manifest.json：原配置及资源来源。
- inference.log、tests.log、tests_red.log：实际执行和定向测试记录。
