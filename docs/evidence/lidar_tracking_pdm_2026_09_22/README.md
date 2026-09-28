# 局部真实输入链证据

详见 ../../lidar_tracking_pdm_2026_09_22.md。

capture_manifest.json记录原生传感器和时间；summary.json是本车排除/跟踪统计；plan_summary.json是30帧固定时刻的有/无障碍敏感性诊断。

sample_tracks.json/sample_plans.json保留首、中、末样本，包含首帧初始化未知速度与反向规划终点。pdm_response.png展示规划输出，非车辆执行轨迹。

tracking_tests_final.log/main_tracking_tests.log：7项跟踪测试。pdm_regression.log：17项PDM及输入测试。full_review_tests.log：362项轻量回归。late_parent_red.log与review.txt记录审查发现及修复。

未训练、未P/F查询、未MTR、未LLM、未闭环控制。空障碍对照不是论文Ego基线。
