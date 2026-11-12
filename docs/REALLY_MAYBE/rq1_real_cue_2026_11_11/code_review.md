# 真实观测条件接入独立代码审核

2026-11-11。初审锁定`8a2592c9eb8637dc4b4ed31ccd138d176904c969`。已复习当前方案、经验教训、要求和状态，按已审SDS核读四个新增文件及调用关系，沿用ponytail-review。没有启动真实39job、旧回归或全仓库检查。

## 初审结论

核心实现没有发现研究语义或信息权限阻塞。剩余一项有限交付修复，补齐SDS要求的PNG/SVG图后锁定最终提交，不扩展算法或新增验证框架。

## 一次修复清单

`scripts/rq1_real_cue/run.py:332-357、379`目前手写SVG并只保护、交付six_cells.svg，没有PNG。SDS要求PNG/SVG，环境已有matplotlib，无需以避免新增依赖为由省略PNG。

最小修正是用已装matplotlib依据同一cal/eval六格指标绘图，输出PNG和SVG，并将PNG加入防覆盖列表和既有微型产物检查。仅定点运行受改动影响的产物检查即可，无需再次跑14项或真实批次。该项是图产物不齐，不是概率或评分方法失败。

## 核心核查结果

- `geometry.py:10-55`按原角点相邻边恢复OBB中心和局部轴，slab使用有限线段t。平行轴显式判断，未进行0乘无穷计算。probe首交、前方阻挡、自身/近重复/source内部排除及固定ID并列一致。
- 第58至145行先处理完整预查询集合，query自身probe不使用其extent/yaw。源无效或在probe内标缺失，其他无效OBB排除并留计数。公开源分组发生在事件mask之前。chunk改变不改变结果。
- `run.py:83-119`只向geometry传入非空query的ID/xyz/corners及公开pose。deleted query保留，newborn不使用output_geometry补query。U、标签、当前输出及identity不改变几何计算。稳定source ID在public_groups和模型维度间通过source_ids.index显式映射，没有把ID当数组下标。
- 第122至219行按sender与events核对index/frame/time，空初始frame合法。全部公开特征文件完成后才解析旧labelled，一对一key及元数据核查后附标签。没有新GT入口，未匹配GT或删除假query的未知标签没有补0。新5/4/1划分覆盖旧split，原eval不动。
- `model.py:48-120`的正常拟合、query/source权重、折内标准化、C非正系数及优化器设置符合SDS。缺少两类U监督时失败，未用正则或默认概率冒充可估。五父留一生成p_C，最终B/C只读全部fit重估。相同固定clip进入OOF、rho和最终概率指标。
- 第123至200行按固定分组边际化未知维度，rho用正常折外概率估计且只一个共享值。无信息及微小增益分别回退，端点与有界最优比较，留一父重新归一权重只作稳定性描述。cal/eval标签没有进入边际或rho拟合。
- 第203至234行B/C/J/G共享Q_F；000合法，m=0假概率为1，共同Bernoulli族全0/.8及全1/.2正确，单源边际.225。C/J共享p_C，G为组内平均e再加同一gamma。score不读当前输出/identity/标签/k资格门控，m<2保持未知。数值失败共同处理，没有按方法另删分母。
- 第237至281行按两类分别父、job、query等权校准全局正负分支，风险分母保留无支持评分的资格记录，分数为None不作明确决定。缺少校准类时not_estimable并关闭，未恢复k覆盖未知规则。有限分数同值合并累积，门限包含端点，零分未知。
- `run.py:240-319、377-429`分别保存资格与全部query六格、原始计数和权重、未知标签及newborn代价。attack真实背景按父另列，不混主真分母。概率NLL/Brier按query/source权重，联合NLL含同边际相同项并另列共同组。MATE仅旁列采用/未采用，删除query的kernel采纳没有写成恢复系统输出。
- 参数保留规则直接依据预定概率与任务指标；案例按key固定选取而非按有利方向。没有增加分类头、使用评价集重选参数或恢复长时序状态。

## 独立执行的必要检查

只执行本批14项测试，全部通过，退出码0，unittest计时1.114秒。完整微型39任务流程只在临时fixture中生成小输入，未调用实际缓存的39job。

```bash
cd /root/autodl-tmp/ToolV2X/.worktrees/rq1-real-cue-2026-11-11
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 /root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python -m unittest discover -s scripts/rq1_real_cue -p test_real_cue.py -v
```

覆盖底面/中心、旋转和平行射线、排除与前后关系、标量/向量及chunk一致、标签不影响C、删除query/newborn、PMF及未知边际化、权重和OOF、rho、source维度排列、零类监督、门限预算及临时流程产物。测试通过不说明实际C有效或实际数据满足保留标准。

正式结果仍受历史预测框污染、已标假选择及已看过开发材料限制。固定批次完成后按计划决定保留或撤下具体收益，不通过重拟合同一eval或扩大检查代替方法决定。

## 图产物补丁有限复审与关闭

最终版本锁定`817aa470b33e0facf7423383be45b7a22133ce4d`，工作树干净。仅核读`8a2592c..817aa47`差异，没有重复14项或运行实际批次。

补丁用现有matplotlib依据原cal/eval资格六格画同一张图，交付six_cells.png与six_cells.svg，并将PNG纳入report启动前防覆盖。修改只涉及绘图、产物保护及对应fixture，未改几何、模型、标签、评分、校准或统计口径。fixture新增PNG签名和PNG单独存在时的拒绝覆盖检查，并兼容matplotlib的SVG文件头。主会话报告相关定点fixture先失败后通过，耗时2.497秒；本审核仅核读差异和断言，不认领独立重跑。

唯一交付修复已关闭，最终代码审核通过，无剩余阻塞。主会话可以按已授权计划直接执行一次all，不需新审批或扩大验证。
