# 扩样训练启动规格与脚本

冻结 160 train / 40 development、800 个计划任务、5 轮最多 3200 步。此目录是启动快照，不代表训练完成。运行状态、实时日志、权重和最终结果位于本机 `outputs/structured_driver_expanded_2026_09_15_v1/`。

脚本运行位置与本机资源有关，不能直接从此证据目录启动。它们复用现有数值驾驶器及真实 P/F 服务；监督标签仅在采集后准备阶段读取。完整执行边界见[说明](../../structured_driver_expanded_training_2026_09_15.md)。
