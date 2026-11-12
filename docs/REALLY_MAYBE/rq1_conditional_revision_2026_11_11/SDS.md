# 条件联合核验修订的最小实现规格

2026-11-11。执行已独立复审的[修订计划](../条件联合核验_修订实施计划_2026-11-11.md)。用户已授权持续实施，不新增确认步骤。本规格只落实函数、统计和有限产物，不扩研究范围。

## 工作树和文件

工作树`/root/autodl-tmp/ToolV2X/.worktrees/rq1-conditional-revision-2026-11-11`，分支`experiment/rq1-conditional-revision-2026-11-11`，基于7ab0f4a。保留旧代码，新增三个文件：

- `scripts/rq1_conditional_revision.py`：模型、七评分、三态、风险与政策搜索。
- `scripts/run_rq1_conditional_revision.py`：34basecontext的固定生成、460行主表、8压力、分层和图。
- `tests/test_rq1_conditional_revision.py`：必要数学及信息隔离行为测试。

复用现有`rq1_common_factor.decide`等稳定小函数可以，但不修改旧core，不引入新依赖。Python/numpy/matplotlib即可。输出root `docs/evidence/rq1_conditional_revision_2026_11_11/run_001`，非空目录拒绝覆盖。结果记录脚本所在工作树commit和参数一次，不逐行hash。

## 模型和评分接口

context含稳定ID、anchor、注册peer分组、clear/blocked概率、observed IDs和按规范组次序排列的C。anchor属于注册源但不在peer组；所有peer恰好进入一组。事件字典只含可用0/1，必须包含anchor=1。缺事件直接边际化，不重新分组或删除条件读数。

`cue_distribution(groups,theta,accuracy)`枚举mask前全部组的C及其联合概率。P(C=1)=theta*a+(1-theta)*(1-a)。组间独立。`visibility_weight(c,theta,a)`用Bayes公式求w；无C模式明确用theta，不能读取实际C。零概率C不产生模型输出；本批所有C在theta∈(0,1)、a∈[.5,1]下均有正概率。

`true_logprob(events,groups,p_clear,p_blocked,theta,a,cues,use_cue,joint)`：忽略已给定的anchor事件，按每组已观测peer计算两种Bernoulli乘积的log混合；joint=False时按同一w得到每源边际再乘积。空组概率1。参数与输入验证在构造/入口必要位置一次，源码接口不含truth或实际攻击身份。

`false_probabilities(events,registered_peers)`返回固定F1/F2/F3/F4四个条件概率。前三个为已观测peer的Bernoulli(.1/.2/.4)乘积，第四个为全部已观测peer为1的指标，空peer为1。Q_F为四者平均，B_F按边际.425相乘，M_F取四者最大。评分分母不读取实际压力配置。

`score_methods(context,events,reference_params)`返回I0/J0/Ic/Jc/Gc/JcF/Ec七种score、raw_score、supported，以及可解释的单车e_i、真侧各组delta、假侧gamma。I0/Ic为两侧边际乘积log比；J0/Jc为真组联合对Q_F；JcF为真边际乘积对Q_F；Ec为真组联合对M_F；Gc为sum_g mean_{observed i∈g}(e_i)，不额外加入gamma，也不拟合系数。e的rbar=.425。源码中I0/J0应完全不消费C值。

最终有限score只round(raw,12)一次，统一-0.0到0。概率/贡献不舍入。实际模型单侧零概率允许无穷，双侧0标unsupported，不能产生NaN或偷偷加epsilon；本批Q/B/M均正，故普通主评分有限。总分的解释分量按raw核对，不把round后的差异当语义错误。无peer直接0和unknown。

## 精确表、权重和实际/参考隔离

`build_base_contexts()`按计划固定N2/3/4、去重分组、质量及mask，总34个，分N为4/12/18。N等权，N内basecontext等权。anchor0固定是本批子场景；算法不以数组首项识别它。

`build_rows(base,reference_params,generation_params,attack_override=None)`先对mask前全部组枚举C，再枚举已观测peer报告模式。每行context权重为base权重乘实际P(C)。真概率用实际theta/a的组联合；四个F概率用固定参考族；攻击压力可额外保存独立r或partial族的实际F概率。score只读reference_params和公开context/C，不能读generation_params或attack_override。主128带C context、460行，分N为8/36/84及12/84/364。

每context真概率与各假族模式概率各和1；全体wT及各wFk各和1。无C方法仍在同一460行上评价，分数不依赖C；其概率关系应等于对C边际化后的同一过程。eligible后只按原权重统一归一，不重新给N或context等权。主eligible分母均为11/18。

保存行字段至少包括base_id/context_id、N/groups/quality/observed/C、base_weight/cue_prob/context_weight、events/eligible/pattern、probT、probFk[4]、wT/wFk、scores及解释分量。C分类为all_clear/all_blocked/mixed；不保存不可用Z真值作为评分输入。

## 指标和政策

`evaluate_policy(rows,method,policy,eligible_only)`返回真实三态、每Fk三态、Q_F三态及各自质量分母；另外分别算

- `context_worst_false_adopt`：逐context汇总各Fk的采纳概率质量，取最大后加总，除共同分母。
- `context_worst_false_reject`：对应逐context最小拒绝质量之和，除共同分母。
- `max_context_false_adopt`：所有有资格context/Fk中的最大条件假采纳。

后两种保守界和各极端不能拼成同一组三态概率，因为达到极端的Fk可不同。主正确明确率是(T_adopt+Q_F_reject)/2，Ec另报(T_adopt+context_worst_F_reject)/2。零分母率用null和zero_denominator，系统anchor-only未知仍保留；unsupported也计eligible分母。

逐context极值只在每个所选context保留全部U模式时计算，包括总体及N/分组/质量/peer_count/C类型等外生分层。按全报/全未报/混合筛选属于事件条件分层，各Fk的条件分母不同：这些层保留各族自己分母的三态，所有context极值指标置null并说明 `event_conditioned_stratum`，不能套共同分母。Q_F条件三态必须先将四族质量按.25混合，再除混合分母，不能平均四个已归一化的条件率。某族该模式质量0时其率为null。fit_policy只在完整总体上运行，不对模式分层另选门限。

`fit_policy(rows,method,epsilon,robust=False)`选择正采纳和负拒绝两分支门限。候选为唯一正/负分数及关闭分支；score0永远unknown。前六法按Q_F假采纳和真误拒预算，Ec按context最坏假采纳和真误拒。采用分支最大T采纳，同收益小假风险再严格门限；拒绝分支最大Q_F拒绝，Ec最大context最坏拒绝再最大Q_F拒绝，同收益小真误拒再严格门限。无收益分支关闭，显式enabled。概率可行性和收益平局容差1e-12，不改变分数比较端点。

Ec的“无收益”指主收益和次级Q_F拒假收益均无增加。若最坏族拒假始终为0，但有可行门限提高Q_F拒假，应按既定平局规则保留，不能提前因主收益0跳过所有门限。

主epsilon=.01/.05/.10，全部方法分别校准。固定主5%门限后生成八压力，不重新拟合。对于仅一项新实际F的压力，保存其实际三态，原参考族的评分仍不变。压力theta/a变化时真假P(C)一起变化，base权重保持，不能假定P(C)固定。

压力图和超预算标记使用实际生成分布：a/theta压力用实际C权重下四族等权Q_F；独立r/partial压力用新增actual_F的质量与分母。固定参考四族仅作另列诊断，不能替代实际压力风险。Ec仍显示同一实际分布的风险，并可另列参考族context最坏指标，避免混淆图中口径。

partial实际F：在全部注册peer上均匀选择j，给定anchor报告使j恒报，其余独立r=.2。若j被mask隐藏，其约束应被边际化；不能改成在observed中选择j。N2对应全协调并单列解释。

## 产物与图

输出config.json、main_rows.jsonl、main_frontier.json、main_strata.json、stress_summary.json、transitions.json、examples.json、summary.md；两张图main_frontier及stress_risk各PNG/SVG。JSON禁止裸NaN/Infinity，无穷编码字符串，unsupported/未定义率显式null。保存运行耗时和来源commit。

分层为N、groups类型、quality、peer_count、C类型、全报/全未报/混合/无peer。每法主5%报告系统和eligible六格、每Fk风险、context最坏及max_context风险。转移只需Ic到Jc、JcF到Jc、J0到Jc，各格保存真假混合质量和分母。共同政策对照固定采用Ic的主5%政策，再分别作用于Ic和Jc，不追加调参；Ec不参加这个政策归因。

固定例表取N4、全peer共享与split、两质量、全部可见，所有C/U模式。包括共同未报、共同报告、混合，不能事后选图删掉不利模式。summary分开报告主预算是否满足、Jc是否超过Ic/Gc/JcF/J0、单族及压力风险和unknown，末尾只给条件结论，不自动声称迁移准入。

## 必要测试和结束条件

测试固定概率归一、单车边际一致、缺失边际化、噪声Bayes权重、同生成过程的C边际化、a=.5、a=1的Jc=JcF、N2 Ic=Jc、无信息unknown、ID排列不变、评分不读实际压力参数、四族与混合边际、partial隐藏成员边际化、风险按context先max/min再汇总、零分母和门限关闭。数值容差1e-12；最终评分恒等使用规范化后的精确比较。

这些是防止具体研究错误的有限检查，不扩全仓库测试。代码由独立审核者通过后，主会话一次运行固定批次。结果后执行计划中的方法决定，不改参考权重/参数寻找正结果。当前无车端C校准，不把受控成功变成实车性能。

规格自检：七评分和八压力均有对应函数；真/假概率、context权重和资格分母一致；三文件及输出覆盖计划，无新增训练模块。
