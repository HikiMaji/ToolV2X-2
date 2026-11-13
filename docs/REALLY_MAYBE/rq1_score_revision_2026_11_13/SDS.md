# 评分修订实施接口

2026-11-13。用户已授权执行。[冻结规程](frozen_protocol.md)、[机器清单](frozen_config.json)及其hash是方法权限，本文件只落实接口，不改变参数或保留判据。

## 数据来源与输出

原批次为`/root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/run_001`，只读。新输出使用机器清单的new_output_root；原方法代码`kernel.py,fit.py,data.py,native_adapter.py,run.py`不改。新增包`scripts/rq1_score_revision/`，核心Python3.8/numpy/scipy，原生子进程使用既有Python3.10 runtime。所有Numba/BLAS/OMP线程设1，原生最多8个独立job并行。

新manifest保留70个旧任务的来源引用，另列26个新fit攻击。旧任务行路径直接引用旧jobs，不重跑或覆盖prepare/fit。新任务保存attack、online、rows、entity_coverage及complete/error。所有成功标记原子发布，存在完成标记的任务不重复；不把残片当完成。

五个旧三车fit父的原生scans从旧clean sender的前80包与已存在offline_gt按frame连接，echo设空；新攻击不需要回波监督。消息去掉私有GT再进入replay_online。检测位于`docs/evidence/oqea_h1_retrain_2026_10_30_envfix1/run_001/detections/{parent}/%06d_{source}.npz`。原始clean sender路径由旧manifest的config获取。第六个四车fit父直接复用旧parents目录的scans及provenance spec。source_ids、frame/index/timestamp须与冻结清单吻合。

仅调用现有construct_attack、replay_online、attach_labels与coverage_summary，保持几何/尺寸/阶段/标签规则。为了读取旧三车检测，只做缓存路径适配，不新推理、不改攻击选择。训练clean行始终复用旧完整行及Z，不从新攻击回放重复添加正常背景。

## 文件与接口

1. `prepare.py`负责来源绑定、原生prepare worker和支持统计。公开`read_config(path=None)`、`iter_rows(out, split=None)`、`support_summary(rows, config)`。`iter_rows`按job连续且帧升序给出元数据及原fields，旧行只读、新行读取新out。CLI `python -m scripts.rq1_score_revision.prepare --out ... --workers 8`；原生worker由该模块的私有子命令运行。
2. `heads.py`负责正常侧窗口特征、7系数头、固定offset增量与逐源贡献。只消费冻结在线字段计算特征，再附上标签作离线监督；不调用Q_F来决定新分数。输出每记录D/T/I/G六维特征、Delta_T、来源表征、窗口长度与共同资格，以及各方法可估状态。
3. `run.py`负责fold、fit、score、report命令。复用现有calibrate/weights/decide等无副作用函数及口径，必要紧凑适配表格列名；不修改旧模块全局METHODS影响默认参数。新增完整报告须包含六格、family/k、覆盖、初窗、配对时效、c区间状态和冻结判据逐项裁决。
4. `test_prepare.py,test_heads.py,test_run.py`只覆盖新增研究契约；不重复原概率核已通过检查。

## 支持门槛和缺失

支持统计按新注入job内单target计实体数，跨ID/epoch合并其明确假query扫描数。6条/族的计数要求每条>=10不同扫描，父数>=3也按这些计数实体；k1及k>=2存在性按全部非空明确假query样本，短轨迹仍进入训练。每个source-only及mixed分别判门槛。缺支持不拟合对应头，不改family或门槛。

全部方案若支持不足，输出覆盖和未能检验报告，不做无效OOF/训练；若仅部分可估，仅对可估方案继续，其他方案在报告中保留不可估状态。旧MATE可列参考，但不能将缺模型行删除后冒充已比较。

## 特征、拟合与评估执行顺序

每外层留一fit父：调用旧fit_models拟合其余五父clean，rho用其余五父内的旧fit_rho_oof估计。保存折模型和训练父列表后，转换该父clean及新攻击行。无需在cal/eval重新估normal参数，直接复用旧models。fold可独立并行，缓存完成后复用。normal参数不可估时沿用组件状态，不能捏造rho=0。

窗口仍由旧kernel.windows建立。每时刻用当前条件先预测p，计算正常loglik和边际，再用当前U更新；J状态会包含其他来源过去信息。D直接p、T独立过滤p、I/J/G/Q共享J边际。G按每时刻每个有有效事件的组取表征均值后累积，w/d/m不变。缺C/X等规则沿用正常模型。特征构造不以truth、family或attack_k分支。

头拟合按source-only规则筛选监督，再做scaler和权重；不同方案不得共享学得的头scaler。基础头按冻结logistic设置，常量列固定0。J/Q以冻结I为offset，仅一个无中心RMS增量参数，禁止增加截距。显示源贡献使用原尺度参数，中心化常数只进入整体截距。scaler/参数不可估保留None及理由。

每个方案重新用对应cal选择A/R；target族不参与校准，只有split=eval时读作该方案评价。cal缺整类假标签时不能无约束采纳。实际数据的共同数字异常保留unknown和分母，模型不可估按方法记录。

coefficient bootstrap按冻结原cell的父覆盖解析预检查执行，满足才做1000次。原父重复抽取要保留draw_cluster_id；不支持时输出明确原因，不编造区间。风险率差与新错例转移分开。时效在主真epoch上按父/epoch等权，标签未知不作正确采用；配对集合和起点按冻结规程。

## 必要验收

- prepare：三车缓存路径与四车scan复用、公开/离线字段分开、假实体碎裂不重复计数、失败与残片不算完成。
- heads：未报直接项非正、来源置换、来源加全局贡献等于总分、无中心offset、常量列固定0、group平均及共同未知资格。
- pipeline：父折外与source-only隔离、两类权重各.5、空层/不支持保留、风险与正确明确率手工可复算、epoch级配对时效不随轨迹长度偏置。

生产实现完成审核后才启动对应研究阶段。prepare先完成代码审核即可先运行，Task2仅新增heads/run文件，不能热改已运行的prepare或旧概率核。最终核心统计另行独立重计；重计是结果口径核对，不承担方法有效性结论。
