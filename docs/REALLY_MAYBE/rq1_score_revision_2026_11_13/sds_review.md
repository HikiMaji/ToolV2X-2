# 评分修订SDS独立审核

2026-11-13。审核对象为本目录SDS.md和implementation_plan.md，对照已审核冻结的frozen_protocol.md、frozen_config.json及原scripts/rq1_temporal源码。审核工作树基于eb0617f。本次只作静态接口审核及有限缓存样本核查，没有构造攻击、拟合模型或运行评分，没有修改其他文件。

## 结论

**通过。未发现阻塞实施的规格冲突。** 可以按计划编写新增接口，完成相应代码审核后执行用户已授权的有界批次。此结论只表示这些接口可以忠实实现冻结规程，不表示代码已通过、数据支持已满足或方法有效。无需重新讨论MCS、参数或再次请求设计批准。

## 已核对的关键条件

1. **数据准备有可行的缓存入口。** SDS第11至13行明确五个legacy fit父从旧clean配置取得sender，按frame连接既有offline GT，检测路径包含完整parent的train层；第六个四车父复用已有scan与provenance spec。只读抽查确认五个clean配置的sender前80包均可读，包含frame/index/timestamp及各源pose、FOV，且各父首包首源的指定检测缓存存在。四车provenance含原检测目录、source_ids及frames。原native_adapter.recording_spec第32至47行不适合直接解析这五个legacy父，SDS已明确通过新适配解决，不要求重读PCD或重新感知。本抽查不等于已逐项验证全部检测文件。
2. **构造与在线信息权限没有被扩展。** 原construct_attack只读离线GT和扫描消息并固定RandomState(0)，replay_online只需公共扫描及检测路径，attach_labels才接收GT/echo。SDS保留这三个边界，并规定clean监督直接复用旧行和Z，不把新攻击中的正常背景重复加入训练。新攻击echo为空不会破坏头训练，因为新的Z监督只来自旧clean行。
3. **支持不足会实际停止对应拟合。** SDS第24至26行按每个注入job的单target合并ID/epoch碎片，累计不同明确假query扫描。六实体、三父和k覆盖分别检查，短轨迹保留。mixed两族分别过门槛，source-only分别判断；全部不足时直接报告未能检验，不执行无效OOF或强行拟合。部分满足时只继续该部分，未满足方案不能从比较表消失。
4. **父折外包含rho。** SDS第30行要求外层留一父后，在剩余五父调用fit_models和fit_rho_oof。原fit_rho_oof确实在其输入父集合内再次留一父，并为每个rho重算完整窗口后验；失败返回rho=None，不会自动成为0。该调用方式排除了外层held父，符合冻结规程。cal/eval复用原六父normal模型，不会把这两部分重新纳入normal拟合。
5. **新评分可以独立于旧Q_F实现。** kernel.normal_window已返回观测前p、边际loglik与delta，并在计算本帧似然后才更新后验。新增头可以直接复用predict_row、normal_window和windows得到D/T/J表征，不需要更改原概率核或从旧真假分数反推。I/J/G/Q共享J边际，G逐帧按有效组平均，J/Q固定I为offset且不中心化、不加截距，均与冻结规格一致。
6. **source-only的训练与校准均隔离目标族。** SDS第34至36行要求先筛选对应监督，再估scaler、权重、头和增量，并使用该方案的源族cal选门限。目标族仅进入该方案的eval，F0按上位规程排除。cal缺假类不能开放未校准采纳分支。已有calibrate确实在缺错误类时保持对应门限为空，且逐非空family/k约束风险。
7. **不可估及区间不足不会被当作通过。** normal组件、头、scaler、增量和数值失败分别保留状态及原因。c的父覆盖预检查、原cell固定、重复父multiplicity和epoch级配对时效均已有明确接口约定。单父k=3导致区间支持不足属于冻结规程的既定限制，不是通过删层或更换重采样修复的实现问题。
8. **新旧产物隔离明确。** 原70任务通过引用保留，新增26任务只写new_output_root，新包不改旧五个模块或旧run_001。Task1审核后可以运行prepare，Task2仅新增独立文件，不热改已运行prepare。残片不算完成，成功边界原子发布。

## 留给代码审核的定点检查

以下是已经被SDS约束的实现细节，不是新增设计条件或审批步骤。

- 旧run.calibrate依赖ReportRows及旧METHODS列，不能仅传入新方法名就认为可直接运行。按SDS作局部表格或方法别名适配，不修改旧模块全局METHODS或默认参数。
- 新头的w/d/m按冻结定义分别是窗口扫描数、窗口有效来源数、窗口不同支持来源数。旧run.prediction中的m是有效来源数，不能因字段同名直接复用。常量列必须固定系数0，不能仅沿用旧fit_logistic将scale设1的做法。
- 明确假实体门槛只计attack_role=target的合法明确假query，同一时刻多个碎片不能重复累计。fold训练父清单、源族筛选、权重和scaler来源应能从新产物复核。

上述定点检查可纳入计划已有fixture与独立代码审核，无需另开研究设计阶段。本轮审核不对未实现代码或全部缓存完整性作提前保证。
