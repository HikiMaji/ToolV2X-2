# Task 2 评分修订实现报告

2026-11-13。审核基线为4a64954。交付限于新增heads.py、run.py、test_heads.py和test_run.py。prepare.py、旧rq1_temporal模块及旧研究产物没有修改。本报告不覆盖历史task-2-report.md。

## 已落实

- 正常侧特征只调用predict_row、normal_window及windows。D、T和J边际分别生成六维表征。G逐时刻在有效来源组内平均，w/d/m保留窗口长度、有效来源数、不同支持来源数。未调用Q_F定方向。
- 四个基础头均按冻结的7系数、正负约束、常量列固定0、分级类权重、L2与优化器设置拟合。原尺度来源贡献与全局项分开。J/Q固定I为offset，只有一个无中心RMS增量参数。
- 支持门槛先于任何OOF或头拟合。全部不足时可直接形成未检验报告。部分支持时只拟合通过方案，未通过方案保留。每头记录每父监督行、可用行及normal状态。组件不可估或整父特征缺失关闭相应头，D等独立对照仍可保留。
- 每个外层父的normal及rho都只从其余父估计，保存normal缓存、训练父和折特征。cal/eval复用冻结六父normal模型。normal折可用最多8个单线程worker并行。
- 三方案分别拟合scaler、头、增量和cal门限。source-only监督先筛源族。评分文件也只处理该方案的源族cal、目标族eval及各自clean；目标族及F0不会进入source-only的scaler或校准。
- 原calibrate及six_cells_many通过局部列名映射复用，没有改旧METHODS或默认参数。输出六格、完整F0/F1/F2及F3覆盖格、初窗、父分层、逐源贡献、错误转移、配对epoch时效和冻结逐项判据。
- c区间先做原cell父覆盖预检查。不支持则明确跳过。可执行分支固定原cell并保留重复父的draw_cluster_id，重新拟合I的scaler、基础头、RMS及联合增量，保留每次失败及原因。
- 阶段和子产物原子发布，可恢复且不覆盖完成文件。pipeline.json固定配置和本次代码来源。历史error/partial不会被当作当前失败状态。

## 验证

执行命令

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest \
  scripts.rq1_score_revision.test_heads \
  scripts.rq1_score_revision.test_run \
  scripts.rq1_score_revision.test_prepare \
  scripts.rq1_temporal.test_temporal \
  scripts.rq1_temporal.test_data
```

共57项，55通过，2项按既有条件跳过。新增Task2共16项均通过。两项跳过分别为显式启用的容量fixture和要求Python3.10的原生fixture。本次使用Python3.8。

新增检查覆盖来源置换、组平均、标签不进入特征、常量列、无中心offset、Delta可估门槛、父折排除、源族scaler隔离、优化失败、normal折缺失、手算分级六格、重复父、bootstrap执行及无效重复、解析跳过、配对时效、共同数值失败、全部或部分支持不足、空cal及三方案完整临时fixture。

CLI --help、compileall和git diff --check通过。按AGENTS尝试运行scripts/check_review.py，但该工作树不存在此文件，命令退出2。没有为此增建脚本或扩大环境。

## 证据边界与交接

本任务只运行临时fixture与相关回归，没有启动真实features、fit、score或report。端到端fixture使用确定性normal模型替身以检查外折训练父传递，头拟合、评分、校准、六格、区间及报告路径使用实际实现。没有把fixture通过解释为真实normal估计、真实收益或统计保留成立。

真实阶段须由主会话在独立代码审核通过后启动。c区间是否可用由实际I训练原cell的父覆盖决定，不能删单父k=3层。没有运行1000次真实bootstrap，没有跑完整外部资源模型测试，也没有形成方法有效性的结论。

## d6abf17审核后的两项工程收尾

fix基线为d6abf17。只修改run.py和test_run.py。

1. cal/eval特征改为按独立job并行。master对两个split各调用一次iter_rows，按job分组为list，再交给最多workers个进程。worker只接收本job的行，不扫描其他job。每个job独立调用原_feature_rows，窗口顺序、来源元数据、normal模型与参数不变。已完成job不重写，残留partial按原原子文件边界恢复。外折pool先结束，再启动cal/eval pool，因此并发不叠加超出8。
2. 每个阶段入口一次绑定实际导入的7个小文件，分别为新run、heads、prepare和旧temporal的fit、kernel、run、data。复用这一批hash核对实际导入fit/kernel是否仍匹配冻结来源。任一依赖变化或缺失均拒绝恢复，保留原pipeline及完成标记。不逐行、逐worker或全数据重复hash。

只运行以下4项定点fixture，均通过，耗时4.95秒。没有重跑57项全套。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest \
  scripts.rq1_score_revision.test_run.PipelineContracts.test_parallel_cal_eval_features_match_serial_and_resume_per_job \
  scripts.rq1_score_revision.test_run.PipelineContracts.test_dependency_change_or_missing_source_refuses_stage_resume \
  scripts.rq1_score_revision.test_run.PipelineContracts.test_imported_normal_code_must_match_frozen_hash_before_binding \
  scripts.rq1_score_revision.test_run.PipelineContracts.test_fold_isolation_and_three_regime_end_to_end_fixture
```

新增三项分别核对真实2进程与串行的逐条特征一致、每job窗口重新起算和partial恢复，依赖变化/缺失时拒绝已完成阶段恢复，以及normal代码偏离冻结hash时不发布pipeline。第四项为受影响的三方案临时端到端fixture。未修改冻结config/protocol、prepare、heads或旧模块，也没有启动真实features/fit/score。
