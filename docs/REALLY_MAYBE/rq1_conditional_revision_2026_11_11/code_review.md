# 条件联合核验修订独立代码审核

2026-11-11。审核锁定`d3c29ae80ab0e55c661812e0ff41691dfcd6a7a4`，工作树干净。已按root当前规则、经验教训、方案和已审SDS核读三个新增文件，沿用ponytail-review的定点代码审查方式。没有修改实现，没有运行正式研究表或旧实验。

## 结论

代码审核通过，没有发现本批运行阻塞。可以直接运行已授权的固定主表与八个压力配置，不需追加审批、模型或大测试。

本次实现交付条件真侧组混合、固定四族假混合、七种评分及两类风险政策。以下结论针对实现符合规格，不预判Jc会超过控制或达到保留标准。

## 数学与输入隔离

- `scripts/rq1_conditional_revision.py:43-95`的Bayes权重、C分布、真侧组混合及四族概率与SDS一致。全隐藏组事件积分为1，C仍在原context中。partial先在全部注册peer上选恒报成员，成员隐藏时约束积分掉，没有转为只从可见peer选攻击者。
- 第139至177行将单源强度、真侧delta及假侧gamma分开。Jc的raw总分与这些分量一致；JcF固定Q_F后只去掉真侧联合修正，Gc不额外加gamma或系数。无C方法虽与其他方法共同接收公开context，其计算不使用C的值；相同事件改变C时I0/J0结果不变。
- I0/J0/Ic/Jc/Gc/JcF/Ec分子和分母与计划对应。有限score出口只舍入一次，raw及解释分量不舍入。单侧零概率保留无限证据，不填epsilon。anchor按身份验证，不因数组顺序变化改变提出者。
- `scripts/run_rq1_conditional_revision.py:51-92`中生成参数只计算实际C权重、真概率和额外实际假概率。评分只调用冻结reference_params与公开context。改变实际theta/a或攻击参数不会改变同一C/U的参考评分。

## 权重、门限与输出

- basecontext先按N及N内等权，再乘实际P(C)。mask前所有组均枚举C。34个base、128个带C context、460个模式及eligible原始质量11/18由必要测试核对，未知资格没有稀释风险分母。
- core第199至231行分别保存真实、各Fk、先混合质量后归一的Q_F及可选actual_F。context极值先逐context取max/min再汇总，单context最大风险只取有资格context。事件条件层明确null及原因，各族保留自身分母；无peer系统代价仍为未知。
- 第234至266行分支搜索遵守严格正负号、包含端点及enabled。前六法按Q_F约束，Ec按context最坏族约束。Ec最坏拒假主收益为0但Q_F拒假次级收益为正时仍能保留可行门限，未错误提前关闭。平局遵守收益、Ec次级收益、错误和保守门限顺序。
- runner第115至125行的压力图和超预算标记使用实际生成分布。theta/a压力用实际C加权Q_F，独立r及partial用actual_F。参考四族最坏风险仅作另列诊断，没有替代实际风险。主图所有方法使用共同Q_F混合坐标，Ec明确标robust calibration，保守目标另列。
- runner固定三种转移、全部预定例表及八个压力。共同政策使用Ic的主5%门限，只替换评分。各自校准结果及1%/10%预算均保留，没有按模式另选门限或按结果筛例。
- 非空输出拒绝覆盖。JSON禁止NaN，无穷值及未定义率明确编码。来源commit、参数、计时和方法保留或撤下条件均有输出位置。默认结果目录解析到root项目证据目录。

## 独立执行的必要检查

仅执行本批12项新测试，退出码0，全部通过，unittest计时1.441秒。没有重跑旧14项、全仓库测试或正式runner。

```bash
cd /root/autodl-tmp/ToolV2X/.worktrees/rq1-conditional-revision-2026-11-11
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m unittest discover -s tests -p test_rq1_conditional_revision.py -v
```

检查覆盖条件概率与边际、缺失、C边际化、参考冻结、有限计数和权重、必要评分恒等、partial隐藏成员、context极值及模式分母、Ec次级收益、零资格和实际压力口径、小型产物及严格JSON。测试通过不等于研究主表已运行，也不说明各单族或压力满足主混合预算。

后续按冻结计划执行一次固定批次，再按实际结果作机制保留或撤下。受控C和手设参数没有因此成为合法车端输入或数据估计，不能扩写为实车性能或发表保证。
