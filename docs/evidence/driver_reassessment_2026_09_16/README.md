# 09-16 驾驶器重评的归档汇总

这是对既有扩样训练结果的重新汇总，没有新增模型前向、参数更新或远端调用。完整解释见[重评报告](../../driver_reassessment_2026_09_16.md)。

- `stage_metrics.json`：原 `summary.json` 的全部8个检查点，按 condition/output_kind 提取平均前缀L2；同生成次数的差值是聚合均值之差，不能证明逐帧输出相同。
- `admission_summary.json`：实际保留的796个任务，各任务最后一个阶段的入模审计汇总。597个协作任务都有远端primary字段；不是重新前向验证，也不证明网络有效利用了这些字段。
- `sources.json`：两篇论文的公开版本和两份官方规划代码的来源记录；全文/代码仅保存在本机研究目录，不在此重复发布。
- `verification.json`：从原始归档再次核对指标、入模汇总、源码快照和报告数值的记录；不代表新增模型测试或方法收益。

原运行位置：`outputs/structured_driver_expanded_2026_09_15_v1/`。先读 `status.json`、`summary.json`、`eligible_tasks.jsonl`；最终入模记录为 `collection/inputs/g{g}_{arm}/structured_audit.json` 的最后一项。按 `labels.jsonl` 的 role 字段分成train/validation。`summary.json` 的 validation_history 中，groups 的 condition/output_kind 确定报告各行，读取 metrics.got_prefix_L2_avg。

原800个采集任务中798成功；开发g5557的F/PF失败，按整帧四条件规则排除后保留199帧/796任务。开发物理帧数为39；Ego阶段有重复训练上下文，不能把156条Ego阶段行当成156个独立帧。PF的额外refinement是原离线训练验证中的第四次生成，不属于最多三次驾驶生成的在线预算，本报告主表未将该项作为在线方法结果。

后续16帧冻结权重诊断及候选驾驶器改动只是建议，尚未执行。所有解释以报告中的结论边界为准。
