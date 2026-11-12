# 时序条件联合核验最小实施规格

2026-11-12。用户已批准[完整方案](../时序条件联合核验_完整修订设计_2026-11-12.md)并要求连续推进。本文落实接口及首轮开发，不新增研究机制。原始产物只读，新代码位于`.worktrees/rq1-temporal-2026-11-12`，分支`experiment/rq1-temporal-2026-11-12`，base dacc5ff。

## 1. 固定范围与研究结束条件

首轮扩展为14个开发父录制，均属已使用材料，不称未见终测。现10父保留真实C批次的5fit/4cal/1eval角色。增加4个已有检测的父：

- fit：train/2021_08_23_22_31_01，4源，113帧。
- cal：test/2021_08_22_07_52_02，5源，167帧。
- eval：test/2021_08_24_07_45_41，4源，135帧。
- eval：validate/2021_08_20_21_48_35，5源，112帧。

合计6fit/5cal/3eval。检测均有缓存；前两test录制FOV可复用，两个扩5录制的FOV与必要离线回波处理读取PCD时生成。已知重叠train/2021_08_21_22_21_37与未使用的train/2021_08_22_06_43_37仍保护。其他9段多车缺检测、当前无GPU，保留为后续接入候选，不从47段资源范围删除。

新增攻击只对上述1个cal多车和2个eval多车录制，各生成F1/F2/F3、k=1/2/3、一个预声明seed=0，最多27任务，不按效果追加种子。每任务使用从头起80帧，前20正常，20..59为40帧攻击，后20停止；每个构造只一个假目标，F3额外一个假阻挡框。假目标物理上始终不存在，停止报告不是目标出生/消失标签。每任务冻结位置/轨迹后才运行核验。无法构造时保留失败原因及分母，不静默换成更容易攻击或剔除不利结果。F0复用既有29攻击任务，不重跑其前端。

只运行这套固定D/B/C/T/J/J-ind/G开发比较，主W=10、s=.9、rho候选0/.25/.5/.75/.9；开发敏感性按方案W5/20、s.5/.95仅重评分，不重新选主参数。结果必须回答代理状态是否优于直接D、时序是否优于C、联合是否优于T/G及多源假风险。若参数不可估或收益不足，记录具体结果并作保留/简化决定，不自动加模块或重选eval。

## 2. 资源与文件

当前exec cgroup内存上限2GiB、无可见GPU。核验numpy/scipy CPU，原生tracking用现有mate runtime；单线程BLAS，数据按父/job流式处理，不全量加载原始labelled和几何大对象。不得结束无关服务。

新文件限制为`scripts/rq1_temporal/{kernel.py,fit.py,data.py,run.py,test_temporal.py}`，可按实际职责将native适配单独置`native_adapter.py`。复用`scripts/rq1_real_cue/geometry.py`及必要稳定数值思路，旧static源码保持只读，不导入其固定39/5fit等管理约束。真实数据来源细节见[data_access.md](data_access.md)。

## 3. 公共紧凑行和序列

`Row`为JSON对象：key=[job_id,frame,id]，parent/job_id/kind/family/attack_k/attack_role/split，frame/index/timestamp/id/epoch，source_ids稳定排序，U[N]∈{-1,0,1}，X[N][5]或null，C[N]，C_missing[N]，groups（按来源索引分割全集），query_present/newborn/output_present/identity_ok/native_adopted/native_mean。离线字段query_truth/query_gt_id/output_truth/output_gt_id、label_conflict/gt_identity_conflict、Z[N]（-1为监督未知）。在线kernel函数显式只取得U/X/C/groups和在线资格元数据，不能读取truth、Z、split、kind、attack_k。

同job/track ID按index组序列；newborn无query行只输出unknown并结束旧epoch，不作为可观测窗口帧；第一个非空query开始窗口。索引不连续、dt不等于.1（容差1e-6）、来源集合变化时重启epoch。删除query仍评分但accept_eligible=False，下一时刻无query则自然结束。标签变化不触发在线重置。

`windows(rows,W=10)`按epoch生成当前及最多9个过去行。资格由原数据U有效且X finite的源定义：窗口有效来源union>=2；accept还要求fresh支持来源union>=2且当前query/output/identity相容；reject还要求至少一个有效U0。单源不清历史。无有效U仍保留时间槽，所有方法一致。

## 4. fit.py

`fit_logistic(X,y,w,signs)`复用稳定logloss和解析梯度，fit内加权标准化，std<=1e-6置1，L2=.01（截距除外），L-BFGS-B maxiter500/ftol1e-10/gtol1e-6。signs对原变量对应系数限制，scale正所以标准化后符号一致。缺所需类别/无样本抛明确不可估；不输出默认模型。预测统一clip1e-6。

所有拟合只使用fit/clean/query_truth1，且U合法、X有效。Z未知不补0。权重父等权、父内epoch等权、epoch内帧等权，最后在一行的有效来源内均分；每个拟合任务在其实际可用监督集合上重算并归一。转换样本按当前帧所属epoch权重，并在同GT ID、相邻扫描且两端Z/U有效的来源间分配。

`fit_models(rows)`输出：
- D：X5+C+C_missing，C缺失用0并保留flag，C系数<=0。
- h_B：X5预测Z；h_C：X5+C预测Z，C<=0，仅C有效监督拟合。
- emission：X5+Z预测U，Z系数>=0。
- transition：X5+C+Z_prev预测Z，C<=0、Z_prev>=0，C必须有效。
- pi：全部可用fit Z的加权比例；T_base：两行加权转移频率，任一前状态无样本则该基础转移不可估。频率0/1可clip但保留原计数和边界标记。
- 支持量、训练父、范围/裁剪和优化器状态。

`predict_row(row,models)`输出D[N]、hB/hC[N]、emit[N,2]、trans[N,2,2]和u[N]有效mask。h_C缺C退h_B，X缺失则h退pi、转移退T_base且u=-1；C缺失且X有效时emission仍可用、转移退T_base。不得用离线Z参与预测。

`fit_rho_oof(fit_rows)`按fit父逐一留出，所有参数及标准化在折内重新拟合，对每个rho重新按完整窗口前向。目标为held clean真实当前query窗口NLL，按父/epoch/帧归一；过去窗口只使用在线字段，不用held Z滤波。未知标签不作监督目标但不因标签在窗口删除。保存每rho目标及共同有效组数量，平局容差1e-8选小rho，零信息或无增量取0并说明。主拟合后用全部fit重估模型，rho不看cal/eval。

## 5. kernel.py 正常与假侧

状态枚举`states=list(product([0,1],repeat=N))`，source0为最高位，b.reshape([2]*N)轴i对应source i。逐轴应用行旧/列新的2x2转移，复杂度O(N*2^N)。N<=7真实路径；测试可变N及排列等价，不写死3。

`normal_window(predictions,groups,rho,mode)`：左端b=product Bern(hC)，首帧直接发射；第二帧起传播。给定每个状态，用各组独立/comono混合发射，空组概率1。以状态加权得到L_T和每源边际p_i；先保留logL及边际，再更新b。使用log计算发射及归一，避免概率乘积下溢。当前u全未知则L=1、后验等于预测状态。

T取rho0；J用已拟rho。B/C每帧p=(1-h)*emit0+h*emit1，正常侧跨源跨时独立；D直接用其预测。它们同样累计窗口内的正常log概率。

`false_window(U,s=.9)`：r=[.1,.2,.4,.2]，前三族每源二状态独立，第四族共享一状态。左端按r初始化，首帧直接发射；之后T_r=sI+(1-s)ones⊗[1-r,r]传播。log权重初始-log4；本帧先算族完整模式概率及混合边际q_i，得到全来源L_F，再更新族权重及状态。当前混合0/1使共同族概率0时其权重=-inf，本窗口不复活；跳过0/0归一。全未知时权重不变。不同几何组不拆假侧。

`score_window(window,models,rho,W,s)`返回D/B/C/T/J/Jind/G总分、当前和窗口e/Delta_T/Delta_F摘要、机会/支持union、accept_eligible/reject_eligible及finite标记。Jind使用J同一预测边际与状态更新，计分去Delta_T；G同一e按当前组有效U成员平均、空组0，再减同一Delta_F。所有分数由窗口从头重算，不缓存窗前后验或再次加S_previous。

## 6. data.py和原生适配

### 旧39任务

复用已存real_cue/features，每job一条feature迭代器；顺序扫描旧static labelled，按job逐条对应key/U/source_ids/time，补query_gt_id及全部必要离线标签。解码到EOF检查gzip及覆盖，原目录不写。顺序不符才用小sqlite按key连接。保存新的紧凑分job文件，禁止全部几何dict装内存。

### 回波代理与新FOV

按clean parent/frame/source读取一次ASCII PCD。用完整roll/yaw/pitch转到native世界；GT中心OBB按rotation及hwl转局部，容差1e-6米；为Z只需any point，计数可保存审计。使用空间预筛（cKDTree球范围或逐框AABB）后做精确OBB，不能先套检测ROI。只生成fit所需Z，评估阶段不要求额外PCD；新增FOV缺失父按同一PCD pass生成，与GT计数逻辑独立。

十父GT复用offline_gt.json，新增父从YAML沿recording_inputs._gt_frame语义合并，GT冲突记不可用。Z用query_gt_id连接，不能替换为output_gt_id。无GT/无PCD/冲突保留Z=-1。

### 新4/5车正常缓存和攻击

从冻结det NPZ boxes/scores/lidar_pose恢复原生BoxDetection，按任意N维护local trackers，再生成完整原生TrackEncoder消息、fresh计数和FOV。复用BasicBoxTracker3D/MeasurementBasedMultiTracker与原MATE hook；当前query在fused.update前生成。新生数组按len(source_ids)，不能直接沿用旧[-1]*3。现存FOV直接取native_corrected；缺FOV用原生FOVEstimator，公开计算不读GT。

攻击生成在所有防御计分前执行。固定控制源为source_ids排序前k（角色偏差如实记录，本轮不以轮换制造样本数）。F1在受控来源FOV内从真实轨迹中心偏移候选中按seed顺序选不存在轨迹；F2沿某正常来源到真实GT阻挡框的方向，在阻挡框后以固定世界偏移生成跟随该框的假轨迹；F3在F1式目标与选定正常来源之间加入一个持续假框，提前5帧注入，使其可能进入预测遮挡集合。使用普通车辆尺寸[4.5,1.8,1.6]的声明攻击实例，主在线目标probe不读该尺寸，但历史阻挡尺寸的影响必须承认。

候选数量上限64，位置偏移距离取6/10/14米及八方向的确定列表，seed只决定排列；有效性仅看预定义FOV、与GT/其他注入目标无3米相容及连续轨迹约束，不读任何防御分数。F2/F3要求选定正常来源在攻击40帧至少80%达到既有九射线阻挡比例>=1/3，未满足就记UNREALIZABLE，不强制报告成功攻击。F3阻挡采用普通车辆尺寸，若未形成遮挡必须保留失败。具体有效/无效数量进入manifest。

注入在来源的对象/局部跟踪输入或独立完整fake track生成层完成，不改检测器，不改诚实来源报告；必须保留fresh计数连续性。新攻击的中央查询标签优先GT真匹配；与冻结注入轨迹相容且无GT相容者才标假，停止后可按已知注入轨迹与预测连续性保留假标签，模糊情况未知。在线函数不得读攻击spec。保留原MATE输出和更新均值。F3的被核验假目标标attack_role=target，辅助假阻挡框标occluder；两者全部保留，但主假风险针对预声明的target，occluder单列，避免增加辅助框后稀释目标攻击风险。F0/F1/F2假目标均为target。

## 7. run.py与统计

CLI阶段`prepare`（新manifest、旧复用、标签/前端/攻击）、`fit`、`score`、`report`，均--out新目录、存在则拒绝覆盖；支持完成阶段后继续，不热改正在运行代码。每job一次进度，文件原子完成标记，失败保留error.json，来源哈希在阶段边界一次；不逐帧重算PCD哈希。

数据缓存落新artifact目录`docs/evidence/rq1_temporal_2026_11_12/run_001`。按job加载紧凑行和构造epoch；拟合仅保留数值数组，评分逐epoch输出gz，最后统计可读小型预测字段；无需把大geometry装内存。保存code commit、input/source provenance、parent split、参数、未实现攻击及标签缺失。

cal各方法独立选择A/R但共用相同资格。门限正负分支分开累计扫描，包含ties，允许关闭。风险分母是共同主真/主假query总体（包括资格不满足的unknown，不隐藏系统代价），同时另报可判资格分母。各非空family/k层使用同一经验5%预算；样本少只称开发点估计、保留轨迹/父分母，不能给零错误“保证”。缺某层报告not_calibrated，不复活旧k覆盖整组unknown政策。总体真假缺一类才关闭相关政策并标not_estimable。

主真实为clean/query_truth1，主虚假attack/query_truth0且attack_role=target；攻击真背景单列。新生用output_truth给系统层单列，不能拿其标签训练query模型。MATE原生仅采用/未采用；共同政策版本可用mean-.5作为单调分数，门限按相同cal程序选取并明示不是原生输出。

报告D/B/C/T/J/Jind/G真假六格、原始/父等权比例、correct_definite、k/组条件/每父分层，正常概率NLL、rho目标、state delta/参数支持。轨迹指标按epoch报告首次采纳、曾假采纳、最长连续错误；未采纳轨迹单列，不能只在幸存采用者算延迟。3个开发eval父的配对bootstrap仅描述稳定性，不作一般风险认证。至少summary.md/metrics.json/predictions.gz/cases.json及六格PNG。案例预定按key最早的共同组及J/T不同决定各12条，保留不利方向。

## 8. 必要测试与完成

核心：N2/3的序列枚举总质量1，联合前向对手工枚举路径；未知等于求和；rho0退独立；先计分后更新；共同假族混合事件归零不复活；源排列不变；窗口移出旧事件后结果一致；一源重复始终不能采纳但新源到来可用历史；缺C/X、空U、ID重启。

数据：小OBB点数与手算一致含旋转/完整pose；GT标签改动不改变公开C；新生N4/5数组；fresh/coast/缺包语义；fit/cal父不交叉与已知overlap；元数据join一致。先用有限fixture全流程，不能把fixture当实测。

代码独立审核通过后运行固定开发批次。结果由独立审核者从冻结小预测重计核心六格和门限，不重跑全部前端。明确D/C/T/J各自保留或简化的决定，真实恢复与假风险一起报告。
