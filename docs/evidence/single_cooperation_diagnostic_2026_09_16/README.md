# 冻结证据诊断复查包

本包来自真实数值模型，39个已有开发帧、3个固定检查点。主检查点为step500；不是新策略在线实验、独立测试集、训练或修复结果。

- `predictions.jsonl`：117个帧-检查点记录、3042组六点输出及标签、配对、原任务引用和内容摘要。原绝对路径仅为审计定位，复算不需要这些外部文件。
- `summary.json`：同次数输出/修订、逐录制组和预声明交互代理分组。
- `run.json`：完整DriverSpec/ExecutionSpec、模型身份、原始覆盖、固定阈值和成本范围。
- `audit.json`、`verification.json`、`additional_verification.json`：冻结、实际次数、独立指标复算、篡改坐标反例和原Ego成绩复现。
- `content_comparison.json`：后验解释性内容差异和观测来源注意力统计，不证明远端预测更准确。
- `runtime.log`、`tests.log`：真实运行进度、62项定向测试结果。
- `diagnostic.png` / `diagnostic.svg`：三幅诊断图。`make_figure.py` 从包内数据重画，需要matplotlib。

只用Python标准库复算，不加载模型、不读取外部标签或数据：

```bash
python docs/evidence/single_cooperation_diagnostic_2026_09_16/verify_review.py docs/evidence/single_cooperation_diagnostic_2026_09_16
```

完整真实模型重跑使用仓库入口，输出必须选择新目录：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src \
  /root/autodl-tmp/conda-envs/llava/bin/python -m evaluation.structured_evidence \
  --source outputs/structured_driver_expanded_2026_09_15_v1 \
  --output outputs/single_cooperation_diagnostic_replay_new --device cuda
```

`inspect_content.py` 需要原任务和数值模型检查点；它只执行观测融合子模块及已存预测比较，不更新权重。该解释性检查位于主对照完成之后，不能称为预声明主实验。

所有mask干预均标为诊断输入，不制造或修改receipt。所有共同prior来自无远端Ego输出；移除直接环境信息仍保留原Ego prior，因此不能将其称为移除了全部环境因果依赖。
