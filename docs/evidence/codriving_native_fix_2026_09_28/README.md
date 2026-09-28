# 09-28 输入和 adapter 修复证据

- route11_summary.json / route28_summary.json：基于保存检测的真实跟踪与 P 准备；不是规划效果。
- replay_verification.json：22 个样本身份、因果历史和保存栅格的重放，含实现 hash。
- verification.json：最终测试结果（完整轻量及模型环境单元测试）。

完整本地输入、逐样本与栅格在 outputs/codriving_native_fix_route11_2026_09_28 和 route28 目录；测试日志在 outputs/codriving_native_fix_verification_2026_09_28。大数据和检查点不复制进此目录。

没有真实数据训练、新检测/MTR/完整planner/闭环结果。合成优化只验证 adapter 对输入的依赖及空证据恒等性质，不作为论文收益。
