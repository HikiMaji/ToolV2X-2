# 真实观测条件接入最小实现规格

2026-11-11。对应[已独立通过的计划](../真实观测条件接入_实施计划_2026-11-11.md)。本批用户已授权连续实现和有限比较，无需再次询问开始。

## 文件与运行

隔离工作树`/root/autodl-tmp/ToolV2X/.worktrees/rq1-real-cue-2026-11-11`，分支`experiment/rq1-real-cue-2026-11-11`，base d3c29ae。仅新增`scripts/rq1_real_cue/geometry.py、model.py、run.py、test_real_cue.py`，保留旧实现。使用现有Python/numpy/scipy，不依赖AVstack重放、GPU或新检测。

CLI `run.py --stage extract|fit|report|all --out PATH`。默认root `docs/evidence/rq1_real_cue_2026_11_11/run_001`。各阶段产物存在时拒绝覆盖，允许在输入产物完整且前阶段成功后继续下一阶段；不热改已冻结批次。代码审过后只运行一次all。旧manifest/configs/events/labelled是唯一数据入口。

提取只用公开events和sender消息。离线label join在特征产物完成后执行，按key严格一一对应，不向geometry传标签。输入路径/大小/来源哈希在阶段边界确认一次，不逐帧重hash或重扫registry。记录本工作树commit。每job一次进度输出即可。

## geometry.py

`obb_from_corners(corners)`返回中心、正交轴、半边长。中心取八角均值；边取c1-c0、c3-c0、c4-c0，长度为extent，归一化为局部轴。检查finite、edge>1e-6、正交和八角局部边界误差<=1e-4米/轴点积<=1e-5。不直接用bottom xyz当中心。无效框计数并排除；不能凭标签修复。

`segment_box_interval(origin,directions,centers,axes,half)`采用slab区间法，方向为endpoint-origin，参数t∈[0,1]。平行轴abs(d)<=1e-12时显式处理内/外，防止0乘inf的NaN。返回首交t及相交mask，射线并非单位向量。几何容差1e-8，首交并列按ID升序。

`frame_cues(query_geometries,source_poses)`只接收本帧所有非空预测query几何和公开source pose。每query固定probe center=xyz+[0,0,.75]，half=(.5,.5,.5)，世界轴不转，9端点为中心+8角。先求probe首交，再判断其他OBB是否在该t之前相交。排除同ID、预测bottom XY距离<=3m的框、包含source原点的框。源在probe内、非finite query位置或source无效时该源C_missing=1，C=0作模型填充值，主ID=None。

每个射线保留最近有效遮挡框ID；C=非空首交数量/9。主ID取出现次数最多者，并列小ID。无已知遮挡时C=0、missing=0、主ID=None，不能解释成无遮挡保证。无效其他OBB只从已知集合排除并统计，不把其GT补回来。

`groups_from_cues(source_ids,cue)`按主ID对C>0且非missing的来源分组，其余来源各自单组，按稳定ID规范排序。组在有效事件mask之前定义，之后只取可用维度，不重建共同关系。

效率：每帧预计算全部OBB，按source将Q×9条射线对B个框做numpy广播或有限chunk；不要为每条射线重复构造Shapely/OBB。缓存每frame输入一次。样例约40框，广播内存有界；超出时按query分块64，不改变结果。

## run.py的提取与划分

`extract(manifest_path,out)`读取旧manifest的39job及configs。按sender的index/frame/timestamp流与events按frame分组对齐。没有query的初始frame合法；同帧所有非空query_geometry都进入阻挡集合，包括output_present=False的记录。newborn的query=None只保存不可评分状态，不能拿其output_geometry补query。

几何运算不读取U、truth、output_present、identity_ok或current output。这些字段仅在几何结果产生后用于原样保存事件或离线评价。来源次序依据source_ids并核对sender ID集合和时间。输入几何/时间错配属于错误，不静默使用上一帧。

产物`features/{job}.jsonl.gz`保留key/job/frame/index/time/source_ids，原U及X前5列、C/C_missing/主阻挡ID/9射线ID、公开分组、query_present、newborn、native_adopted和当前输出状态诊断字段。无query所有score将未知。原X为null的未知事件不制造新特征值供拟合；C仍可独立提取，但模型只消费U为0/1且基础X有效的维度。

几何完成后另读旧labelled，按key加入parent、kind、query_truth、query_label_reason及output_truth作诊断。新split覆盖旧split字段：保留旧eval父；其余含attack任务父均cal；其余父fit。应恰好5fit/4cal/1eval，打印名单；若不符停止而不按结果另选。无需读取新的GT文件或重建标签。

输出manifest.json、features各job、labelled_features.jsonl.gz、extraction_summary.json。summary只统计实际本批输入/输出、未知/排除和时间对齐，不做资产盘点。绝不以当前标签筛阻挡几何。

## model.py的可识别参数

`query_weights(rows)`按父等权、父内job等权、job内query等权归一。单车拟合在该query权重内再均分有效来源。primary定义为clean/query_truth=1或attack/query_truth=0，拟合p只取前者的fit记录。m=1正常记录可拟合边际，不用于明确三态。

`fit_margin(rows,use_cue)`特征为旧X[:5]，C版本再加[C,C_missing]。L2=.01，截距不正则；每次拟合仅用该次训练父的加权均值/标准差，std<=1e-6的尺度1。scipy L-BFGS-B解析梯度、maxiter500、ftol1e-10、gtol1e-6。C列系数<=0，其他自由；这是预设的观测概率单调假设，不是数据已证明。优化失败保存错误，不强行输出默认模型。

概率统一clip到[1e-6,1-1e-6]，从运行前固定。拟合目标使用稳定logistic logloss；OOF依赖拟合、正式评分及NLL/Brier使用同一裁剪模型，保存clip数量及范围，不能看结果改floor。所有方法共享相同p_C。

`crossfit_cue_margin(fit_rows)`五个fit父逐一留出，每折独立拟合标准化和C模型，输出该留出父正常query的p_C。不是拿全fit标准化再留出。最终B/C边际在全部五fit父重估，cal/eval不参与。

`fit_rho(oof_rows)`只估一个跨ID共享rho∈[0,.95]。对每正常query的共同组取已观测U，计算固定p下的P_ind/P_comono，单组无贡献。目标为query_weights加权的组联合负logloss。无至少两有效源的组或所有P_ind=P_comono时rho=0，标structurally_unidentified。其他情况用一维有界优化并比较rho=0/.95；若最优相对0的NLL改善<=1e-8，取0并标negligible_gain，不把它称严格不可识别。保存目标差、非平凡query/组/parent数量及rho。留一父重算rho仅用于描述稳定性，重新归一剩余父权重，不选择最好rho。

`normal_logprob(p,u,groups,rho)`对各组部分事件计算计划中的独立/共单调混合。rho=.95以下与p裁剪保证有限；单组/空组按边际/1处理。对应参数是残余统计依赖，可能吸收p模型误差，不是真实遮挡率。

`false_logprob(u)`为三个独立r加共同Bernoulli(r=.2)四族等权，明确m=0时概率1、全0时第四族.8、全1时.2、混合时0。单源边际.225。全部源都未报合法，不补anchor或重新选择候选。

`score_query(row,models)`返回B/C/J/G、每源p及e、组delta、假gamma、m/k、eligible。有效维度由既有U∈{0,1}和基础X有效决定；新缺失C用缺失flag，不擅自丢source。分组只对原固定组边际化。B用base p及真独立，C用cue p及真独立，J用同一cue p和rho，G=按组平均cue单源e再加同一gamma。无额外头。

eligible为query_present且m>=2；不读取当前output_present、identity_ok、k或标签。有限score仅最终round(raw,12)，保留raw用于分析；只有m=0的raw总分为0。任何不支持/数值失败共同置unknown并记录，不按方法删除分母。

## 校准与评价

`calibrate(rows,method)`仅cal primary eligible，两类各自按query_weights归一；alpha=.05。采用需score>0，拒绝需score<0，门限包含端点且有enabled。正负分支分别最大真采纳/假拒绝，约束相反类错误<=.05；同收益先小错误，再严格门限，无收益分支关闭。唯一分数+关闭分支即可，不加任何k覆盖门控。加权累积排序实现，不逐门限重新扫描全部rows。

`evaluate`输出加权和原始计数的真假三态，eligible分母与系统query分母分别列，另外保存newborn数量和query_truth未知行的三态分布。未知标签不等于算法unknown。全体query/predictions保留，不能只保存survivor。报告m/k、C>0、共同有效组、output_present分层，每层各类自己的分母归一，零分母null。

正常cal/eval指标：单源NLL/Brier按相同query/source权重；C/B差；J/C组联合NLL按同query权重（包含无共同组的相同项，另列共同组）。rho估计与五留父值，C系数、裁剪及特征范围摘要。范围核查只在此阶段一次，不按帧反复检查。

MATE复用native_adopted旁列采用率/假采用率及计数，不填拒绝率或把未采用等同三态unknown。主要结论是相同候选与资格下四法比较，原生旁列信息边界明确。

本批状态称预查询核验决定。被中央删除的query即使kernel采纳，也不代表已恢复中央前端输出；报告“全部query”分母不冒称完整系统实际采用。attack/query_truth=1的真实背景预测保留并另列按父诊断，不混入主clean真分母、不当新增独立正常样本。

输出models.json、predictions.jsonl.gz、metrics.json、cases.json、summary.md，至少一张cal/eval六格图PNG/SVG。cases按预先固定规则：eval中C>0且有共同有效组的key字典序前12条，保留真假未知标签；另列C到J决定不同的key前12条，不按有利方向筛。输出集合/查询标签与旧实验不同，不直接和旧总体百分比比提升。

## 必要检查

使用简单可手算的OBB验证bottom/中心恢复、旋转、平行射线、probe后方、自身框、近重复排除、首交并列；改变当前U/GT/output字段不能改变C，删除输出的预测框仍参与阻挡。小fixture检查帧join、newborn与未知label分开、父split隔离与折内标准化、C负系数约束、缺失flag、rho=0与边际恒等、正常/假PMF全模式归一含000、未知维度边际化、m<2unknown而k不门控、加权门限预算。

性能以向量化几何小fixture检查结果与标量参考一致即可，不创建性能基准框架。审核和必要测试通过后直接运行固定批次；结果不佳不修改probe/rho上界/划分/风险预算或追加调参。

规格自检：数据接入、真实参数化、四法、固定划分和决策标准均有函数及产物；原始输入与标签信息权限分开；四文件职责完整。当前只验证成熟预查询真实性，不声称完成出生/长时序/一般串谋。
