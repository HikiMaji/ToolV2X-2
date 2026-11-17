# Task 2 实施报告

BASE为b5aa3ca。已实现并通过定点工程验收，尚未运行真实效果、训练或修改旧方法。代码只改新runner和新增test_policy.py，Task1几何与prepare实现未改变。

## 接口与执行

`calibrate(cal_rows, required_layers, mode)`返回四门限、各分支状态、完整主真/主假及逐family/k覆盖、原始I/F风险、实际本地风险和分开的剩余真假预算。mode为Local、LocalCount或LocalCond。只接受cal角色，主假行含非声明层直接停止。unknown标签与攻击回放真实背景不进入候选池。本地门限三方案相同，两个消息方案分别校准tauR与tauC。

内存中关闭门限为正无穷。calibration JSON持久化为字符串`Infinity`，公共decide可直接读取这种JSON；不会经finite_json被改成null。F/R严格大于，I/C大于等于，I必须有严格正重叠。raw I/F分别先校准2%，不以冲突减少原始错误质量。按完整主类权重计算实际本地错误后分别扣除总5%，各假层单独使用其完整假分母。剩余预算负值返回infeasible_local_risk，不截成0。

`decide(public_row, policy, mode)`只接收PUBLIC_FIELDS白名单，没有标签、父录制、family/k或受控身份参数。返回decision/reason/local_state。公共输入故障、冲突、无因果查询直接未知。合法强本地支持不要求第二个消息源，也不受远端沉默、Count或R数值失败推翻。强支持但无可输出框或身份不对应分别返回local_support_no_output、local_support_identity_unavailable，均不可进入消息拒绝。普通本地未知才进入消息分支；C/R不可用只关闭对应分支。

CLI使用同一新输出目录已有的prepare侧录。

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m scripts.rq1_trusted_receiver.run --stage evaluate --config METHOD_INPUTS.json --out NEW_OUT
```

config沿用Task1的parents/jobs，并增加batch中的model_sources、regimes、required_k和criteria。jobs必须只纳入COMPLETE；split可由parent推导。fit跳过rows/features/local，不读取SHAPE_ONLY样本。cal/eval每job需rows_path与features_path，可选local_path，默认NEW_OUT/jobs/job_id/local.jsonl.gz。features_path=null时仅从明确公共字段投影调用旧heads.window_features，D-only模型和rho=0、W=10，随后附回离线评价元数据。已有特征直接复用。C统一由对应regime旧models.Count和旧count_inputs/base_score重算，不采用旧三态门限或决定。

可选batch_path指向冻结batch.json，将全部计划任务和不可构造结果绑定到总报告；可选domains格式为`{域名: [parent,...]}`。不提供domains则保留by_parent，不猜原3/额外6/追加3分组。prepare.config中的parents和public jobs必须一致，评价允许补充模型、标签/特征路径和域映射。接入时一次确认各主键、时间、特征标签身份、来源顺序与公共输入一致，不逐帧重新hash静态文件。

产物为evaluate.binding.json、calibration/REGIME.json、predictions/REGIME/cal或eval.jsonl.gz、report/REGIME/cal或eval.json、evaluate.report.json、evaluate.complete.json。完整六格、独立父数、注入实体/真GT实体与epoch覆盖、普通local_unknown组、所有local_state分层、首窗、各family/k、by_parent、可选by_domain、每方案轨迹曾采纳/首次采用、相对LocalCount配对时效和决定转移均保留。输入/模型/代码在evaluate阶段边界绑定一次。旧输出不改写。

## 定点验证

新增12项测试，native环境运行`python -m unittest scripts.rq1_trusted_receiver.test_policy`，最终12项通过，0.287秒。CLI help与git diff空白检查通过。未重复已有旧20项或Task1 17项及3项定点检查。

手算主表共100条主真与100条主假。原始F严格超限质量2%，两条都与强I冲突，实际本地误拒为0。tauF=.7、tauP=.9，消息tauR=4严格超限5%，tauC=2使整体假采纳5%。另一手算表实际本地真误拒2%、假误采1%，剩余分别为3%和4%，tauR=3、tauC=2，最终两类风险各5%。这些检查使用完整类分母，不在本地未知子集重归一。

覆盖缺声明层、逐层完整分母、raw I不借冲突减风险、无正质量采纳区关闭、未知标签与攻击背景不进入候选、单可信支持、分数单分支失败、输入故障、严格边界、不可输出强支持不落到消息拒绝、拒绝离线字段、D-only重算无标签消费、主键缺失停止、fit不读文件、source-family校准/target-family评价隔离、故障Unknown仍完整保留分母、绑定与相同输入复用。

## 未完成与边界

本报告为工程实现证据。真实数据I/F、经验门限、实际方法效用和独立审核由主会话后续完成。代码中的5%是校准工作预算，没有总体概率保证；父/实体支持不足仍按报告输出。原始局部形体及射线检查不认领多源创新。本任务未增加旧Count/Cond整体采用变化参考，按主会话要求可由后续分析单列，不作为新增门限来源。

没有需要用户裁决的新增问题。

## 独立审核后的两项修复

独立审核对341a659复现两项Important。本次先以实际evaluation_rows夹具复现了错误侧录未拒绝、D=None的TypeError和条件特征失败吞掉计数，再限定修复新runner及其测试。未改变Task1执行快照、method_inputs、旧方法或真实效果资料。

侧录接入现在由evaluate传入冻结parent.receiver_id，核查sidecar的parent、receiver_id、query_present、newborn和已有job/frame/id/index/timestamp。无input_fault时还检查receiver_timestamp有效且与查询时间差不超过Task1已有1e-8界。已标input_fault的时间故障保留未知，不因此中止整批。local_path不再允许另指任意文件，只接受本prepare的规范job产物路径。evaluate阶段绑定补入prepare.config、prepare.complete及原online_path，原查询几何仍由Task1固定公开来源产生，不从标签提取或重建。

Count事件摘要改为从同一公共W10窗口独立计算，合法事件仍遵循旧predict_row的U/X定义。X缺失或不是有限5维时，该来源该步为未知；没有把不可用当未报。计数生成Count_inputs五输入、n_minus、context及共同消息资格，不依赖D成功。D正常时与原freeze.count_inputs逐项核对，C继续用同一冻结Count模型和heads.base_score，仅跳过原count_inputs对D_head存在的非必要依赖，不重训也不改门限规程。D不可估或坏模型不传给旧预测器；有效D运行时的数值失败仍由旧head捕获，只令R不可用。旧features整体失败也不再清除合法Count计数。R不可用时不会把其缺失值写成0；合法未报数量仍由公共事件给出。

新增3项审核回归，覆盖同键同时间下parent/receiver/query状态/接收时间错配拒绝、异批local_path拒绝、D正常/None/空模型/数值失败及旧feature失败的真实evaluation_rows接入，以及正常D下13次窗口含W10截断、历史中断、X缺失与旧计数逐项相同。D故障夹具保留Count_inputs=[2,1,1,3,2]、MissCount=1、两个消息资格，冻结Count分数仍可让LocalCount和LocalCond采纳，计数反证分支仍可拒绝。

本次只运行新增3项与受影响的原2项evaluation入口测试，共5项，最终全部通过，0.280秒。未重跑已通过的校准手算、公共decide测试、Task1或旧方法测试。git diff空白检查通过。此次未执行真实校准或效果评价，待两项定点复审。
