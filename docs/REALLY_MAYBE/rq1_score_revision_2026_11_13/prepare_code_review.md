# Task 1 准备代码独立审核

日期为2026-11-13。审核对象为提交`bae0a6719d639ae4b405869bf0c85c9568a8d07e`，相对`3638f32`新增的`prepare.py`和`test_prepare.py`。已核读完整task diff、任务简报与实施报告、SDS、冻结规程及配置，并追查直接调用的`rq1_temporal/data.py`、`native_adapter.py`接口。使用ponytail-review的实际数据流审查要求，按项目要求用中文报告。

本次只审准备层。没有运行26个研究任务，没有修改实现、旧输入或冻结文件，没有重新执行实施者已在Python3.8与原生Python3.10环境通过的8项fixture。报告所列测试通过来自实施者的task-1-report，不冒充本次独立重跑结果。本次只为一个新增恢复疑点执行了临时目录最小检查。

## 审核结论

**规格符合性通过。** 未发现需要在启动计划内prepare前修复的规格偏离。原26次尝试、seed与构造策略保留，旧输入引用与新输出分开，在线回放不接收GT或echo，支持门槛按单次物理注入实体合并碎片。

**代码质量通过，附1项非阻断恢复诊断问题。** 原子文件与完成标记的先后次序、worker隔离及失败保留可满足本批有界运行。下述问题不改变样本、标签、支持门槛或完成与否，但会让同一任务的诊断元数据随中断位置不同而变化。

上述结论只对应准备代码。尚未证明首个三车或四车任务的前20扫描与旧clean实际回放相同；该核对由主会话在首个成功任务后完成。也没有证据表明26次尝试一定可构造、支持门槛已经满足或新方法有效。

## 规格核对

| 检查项 | 代码证据与结论 |
| --- | --- |
| 26任务及种子 | `prepare.py:28-42`验证26个不同job、fit划分、F1/F2、seed=0及冻结来源顺序与角色。`259-295`直接复制计划元数据，保留70旧任务来源并检查新旧96个ID无碰撞。实际构造调用原`construct_attack`，其`RandomState(0)`、前80扫描、最多64候选和首个合法候选策略未变。 |
| 冻结来源 | `173-183`在首次建立manifest时核对绑定来源及当前导入的冻结kernel、fit、native_adapter。此次独立确认本工作树冻结protocol/config均匹配`freeze_sha256.json`；本task diff没有修改旧概率代码或冻结文件。 |
| 旧输入只读 | `277-284`把旧rows/status作为绝对路径引用。三车缓存只写新out，四车扫描直接引用旧缓存。`357-365`在锁文件写入前拒绝旧run及其父子目录。未发现向旧rows、旧status、检测缓存或GT写入的路径。 |
| 三车检测与GT | `23-25,206-222`使用既有检测根目录并保留parent中的`train/`层，和原`replay_online`逐帧逐source的npz读取方式一致。sender前80包与GT按frame连接，消息用公共字段白名单重建，echo为空。`223-242`检查扫描/来源/检测文件及前20扫描已有clean行的元数据对应。该元数据检查不是实际replay等价证明。 |
| 四车复用 | `199-204`直接引用旧父目录的scans及provenance spec；worker在`311`取前80扫描。没有重做检测、FOV或回波监督。 |
| 离线与在线权限 | 原`construct_attack`可离线读取GT决定冻结攻击；`_public`在`158-161`去掉scan层GT/echo，并重新限定消息字段。`327`只把这些公共扫描及已冻结攻击送入原`replay_online`，随后`337`才调用原`attach_labels`。没有新增用真值构造在线特征的分支。 |
| worker与恢复 | 每job独立原生子进程，线程环境为1，调度最多8个worker。父缓存在调度前建立。attack、online、rows、coverage和complete使用既有原子写入；`.partial`不会被视作已发布文件。rows与coverage均成功后才发布COMPLETE；UNREALIZABLE作为不补seed的终态保留。异常保留error，已完成job不重跑。 |
| 物理实体支持 | `79-130`只统计冻结新job内合法预查询、非newborn、truth=0、role=target的不同frame。ID和epoch只记录碎片数，不作为实体数。一个job的target只贡献一个实体，同帧多片不增加扫描数。至少10扫描的实体才贡献6实体/3父门槛；k存在性使用所有非空明确假query，短轨迹保留。mixed与两个source-only方案分别给出支持状态。 |
| 下游行接口 | `45-76`按job及原帧序完整返回行，保留原Z，不按truth、family、epoch长度或攻击角色预筛。仅按请求split选择job，并跳过有明确UNREALIZABLE状态的无行任务。因此目标族和短轨迹不会在prepare接口提前漏掉，后续源族隔离仍须由Task2落实。 |

## 非阻断问题

1. **完整行文件恢复时丢失构造诊断计数。** 位置为`prepare.py:331-349`。

   当rows和entity_coverage都已原子发布，但进程在complete发布前中断，恢复会跳过`attach_labels`。此时新建的diagnostics只含`public_occlusion_frames`空集合，最终`actual_construction`缺少本来应有的`target_query_rows`。正常首次生成会由原`attach_labels`累加该字段。

   本次以临时fixture设置一条明确假target query及对应coverage，再调用worker恢复。得到`rows=1`、`counts.query_truth_0=1`、`entity_coverage.target.active.query_definite_false_count=1`，但`actual_construction`仅有`public_occlusion_frames=0`。由此确认问题是恢复诊断缺失，没有把残片冒充完成，也没有损坏行或覆盖统计。F1/F2不使用F3的公开遮挡诊断，本批支持统计直接从行计算，所以该缺口不阻断计划内prepare。

   最小修改是在已经执行的rows遍历中重计`target_query_rows`等角色计数，并统一写入diagnostics，无需重跑原生回放或重新生成标签。主会话决定本批保留该非阻断缺口并在执行ledger记录，不为此重跑整套测试。原始rows、entity_coverage及主分母不受影响；最终归档以rows及由其重计的support为权威计数，不读取缺失的`actual_construction.target_query_rows`来判断支持，也不把缺失字段当作真实零计数。

## 已有测试证据与剩余边界

实施报告记录8项fixture在两个环境通过，覆盖实体碎片、短轨迹k覆盖、frame连接、来源顺序、公开字段、旧Z、原子残片、错误保留、online复用、coverage补齐及UNREALIZABLE终态。此次核读测试与实际实现，未发现这些测试结论与代码矛盾。上面的双文件已发布恢复点未被已有fixture覆盖，本次用最小检查补证，没有重复整套测试。

本审核不检查Task2头拟合、源族校准隔离、最终统计与方法保留判据。真实输入的回放一致性、构造成功率、有效假query和父覆盖仍需后续批次产物确认。通过代码审查不能换算成论文效果、可识别性或样本量充分性结论。

## 追加定点复审 4a64954

2026-11-13。真实prepare在两个任务遇到缺失FOV的原生Polygon接入错误后退出。主会话确认批次已停止、Task2已暂停。本次只核读`bae0a67..4a64954`完整修复diff、追加实施报告及直接相关接口，不运行研究任务，不重跑已有整套fixture，也不改其他源码。

**修复规格符合性通过，修复代码质量通过。** 本轮未发现新的阻断问题。此前的恢复计数问题已在新代码中修正；旧24个终态任务不因这项诊断修正重写。结论限定为以下技术变动及恢复安排，不预先声称两个任务恢复成功或真实回放已等价。

1. `prepare.py:158-165`只在新建的公共消息dict内把`fov_boundary=None`替换为`[]`。父scan、缓存、构造器接收的原始扫描和有效FOV均不变，GT/echo仍被剔除。修复发生在调用原构造器之后，不改变seed、候选顺序、位置、几何、标签或26次尝试清单。
2. 实际依赖`message_conditions.polygon`对None直接返回None，对空数组因维度或点数不足也返回None。`static.source_features`对两者均给出无覆盖、margin=0、eligible=False；原`replay_online`因此仍写未知事件，不把缺FOV补成有效未报。旧`static.extract_job`在这种情况下使用包含判断恒False的替代对象。实施者的原生空Polygon内存检查确认空Polygon不覆盖测试点，与该旧语义一致。新增fixture也固定原scan不被修改。这里确认的是缺FOV表示兼容性，不是整段实际回放等价。
3. `prepare.py:344-353`在原有rows遍历中另建role_counts，再赋值覆盖diagnostics的同名计数。它没有对attach_labels已经累加的计数再次相加。完整rows/coverage恢复时也从持久化rows得到相同`target_query_rows`，空计数显式为0。支持统计、标签及样本分母不变。新增定点fixture覆盖此恢复点。

本次沿用实施者记录的两个新增定点fixture与原生emptyFOV检查通过证据，没有重复执行。代码追查与这些结论一致。修复diff不修改冻结native_adapter或manifest的config/code hashguard。

### 未完成run的技术恢复边界

本次只读核查实际新run，未发现`prepare.complete.json`，manifest.config与冻结config完全相同。两未完成job为`88d0c4cf9eb9c85e`和`9ea31a51fd2ff89e`。两者都有完整attack及错误记录，均只有`online.jsonl.gz.partial`，没有完整online、rows或entity_coverage。错误均为`TypeError: iteration over a 0-d array`。

在这一实际状态下，主会话提出的恢复安排可接受，不需要放宽自动hashguard。

- 先保留`manifest.before_fov_fix`完整快照及其旧prepare_code。当前旧hash为`de3878491762e5148615aa808508e2c01f41f7da815e9e7458f1fdc2645aed70`，4a64954对应当前prepare文件hash为`549d0e40b182530a66a82af1630cefaecc2d10651faf57a9928775f4d0e5ebcf`。
- 在单独执行记录中保存24个旧终态job与2个恢复job的代码来源，显式更新未完成run manifest中的当前prepare_code。config、jobs、来源路径、父绑定及旧任务状态保持原样；manifest替换应原子发布。这里是一次有记录的未完成批次接入修复，不能据此把自动hash校验改为忽略不同版本。
- 两恢复job直接复用已有attack，从头重做尚未原子发布的online，再附标签并完成。旧partial可按原atomic_rows实现重新写入，不能提升为成功online。保留原error作为历史失败证据。其余24个终态job不重跑、不重写，旧输入及原26任务规则不变。
- 两恢复job的attack是在旧prepare下生成，online和labels才由4a64954执行。记录须注明这一阶段差别，例如保存`attack_reused_from_before_fov_fix`，不能把两job全部产物概括为新代码生成。最终报告也应保留批次包含两个prepare版本的事实。

完成上述来源记录后，可仅恢复两失败job。这里审核的是已陈述恢复方案及当前文件边界，尚未验证主会话实际完成manifest迁移或研究任务恢复。此前要求的真实clean前缀核对继续保留。
