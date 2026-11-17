# Task 2 独立审核

结论为 **Important，修复下列两项后再进入正式 evaluate**。未发现 Critical。Task 1 已批准的 b5aa3ca 真实 I/F 提取可以继续，本审核不要求停止、修改或重跑该冻结批次。

审核对象为 `b5aa3ca..341a659`，当前 HEAD 为 `341a659f098aa8eb419b2c0988c4405b4706c08d`。依据 Task 2 brief、最小 SDS 与修订设计第 4 至 7 节，核读完整差异、实际调用函数及实施报告。未重审 Task 1 几何，未重复已通过的 12 项测试。只运行了下文的新疑点临时夹具，没有读取真实 PCD、校准真实门限或运行效果评价。除本报告外未写仓库或真实批次文件，未改实现、提交代码或启动子 agent。

## Important

1. **侧录接入未核对接收车身份和查询状态，错误侧录能产生强本地采纳。** 问题位置为 `scripts/rq1_trusted_receiver/run.py:531-540`，相关入口为 `:503`、`:634-640`、`:663-671`。

   `evaluation_rows` 对 sidecar 只核对 job/id/frame/index/timestamp。它没有核对该记录的 parent、receiver_id、query_present、newborn，也没有把可选 local_path 关联回已完成的 Task 1 产物身份。上层检查 prepare.config 的 parents 和公共 job 描述，随后给实际选择的文件做 hash，但这些步骤不能发现同键、同时间的另一接收车侧录。sidecar 的 I/F 被采用，而判决使用的查询资格来自标签 rows，两者不一致时仍可通过。

   新定点反例使用一条合法主真 rows 和合法 D 模型。sidecar 保留相同 key/time，设置 `parent='WRONG_PARENT'`、`receiver_id=999`、`query_present=False`、`newborn=True`，同时给 `I=.9, I_eligible=True`。`evaluation_rows` 未报错；在 `tauP=.7` 下，公共 `decide` 返回 `accept/local_support`。这是资料接错时的工程反例，不表示当前真实侧录已经接错。

   最小修复是在阶段接入时按冻结 parent/receiver 核对侧录来源，并核对行级查询状态。若保留 local_path 覆盖，必须验证它确属同一 prepare 批次的相应产物。补一条错误 receiver/查询状态拒绝接入的检查即可，不需逐帧重新 hash PCD 或修改正在运行的提取输入。否则无法把强本地决定归因到预先固定的可信接收车及同一因果查询。

2. **D-only 特征提取仍会让 R 故障关闭 Count，未实现端到端的单分支失败。** 问题位置为 `scripts/rq1_trusted_receiver/run.py:508-511`、`:538-546`、`:695-699`；实际依赖为 `scripts/rq1_score_revision/heads.py:39-47,82-85` 和 `scripts/rq1_report_freeze/run.py:81-86`。

   `decide` 本身能分别处理 C 或 R 不可用。但新特征入口直接调用旧 `heads.window_features`，它在预测 D 后才填事件计数，并在分数数值失败时清空全部 features 和两个消息资格。随后 Count 的重算又要求 `finite=True` 且 D_head 存在。因此即使有效事件 U、时间及身份都正常，只有 p_D 无法计算时，LocalCount 的计数采纳与计数拒绝也一起失效。旧 features 的整体 finite 状态也会通过同一依赖影响 Count，不能据此声称 Count 与条件分数故障已分离。

   新定点反例固定一窗合法 `U=[1,1,0]`、三个有限 X、有效输出和身份。仅把 D 设置为不可估 `None`，`evaluation_rows` 抛 `TypeError: 'NoneType' object is not subscriptable`，整批停止。再只令 D 模型产生非有限预测，结果为 `R=None`、两消息资格 false、Count 输入报 `Count requires actual valid-event counts`，同时 `MissCount` 被记为 0，而本窗确有一次有效未报。反例使用临时模型，不声称冻结批次的真实 D 模型已经损坏。

   最小修复是保留既有有效事件的定义，但让计数摘要和共同资格不依赖 p_D 分数成功；D 不可估或数值失败只关闭 R，Count 模型或 Count 分数失败只关闭 C。缺失值不能写成实际未报数 0。补一个贯穿 `evaluation_rows` 到 Count/判决的定点检查，同时比较既有 features 和 D-only 路径；不需改旧生产算法或重跑已通过的手算门限测试。否则合法计数对照会受条件模型故障牵连，故障 Unknown 的变化也可能被误解释为方法差异。

## 已核对通过的主要定义

- `run.py:394-408` 只允许 cal，候选池先经既有 primary 筛选，未知标签和攻击回放真实背景不参与边界或目标函数。逐 family/k 的权重在该层完整主假集合计算，本地未知不被移出分母。
- `:416-436` 先分别校准 raw F 的主真 2% 与 raw I 的总体、逐层主假 2%，未借 I/F 冲突减小原始风险。F 严格大于，I 大于等于且资格要求严格正重叠。关闭值为正无穷，持久化为字符串 Infinity 后可由公共接口读取。
- `:437-476` 用实际互斥本地决定分别计算真误拒和假误采，再分配剩余总 5%。负剩余预算返回 infeasible；tauR 只看正常 cal 且先于 tauC；tauC 检查总体及每个声明假层的本地误采加消息误采。无正质量可行采纳区关闭。
- `:409,427,463,477-480` 缺声明假层会关闭本地与消息采纳并标不可估，仍可保留正常侧已校准拒绝。分支关闭不被写成总体风险保证。
- `:294-296,342-360` 的公共决定白名单无标签、父、family/k 或受控身份。故障、无因果查询、冲突直接未知。强本地支持不依赖第二报告源，且无输出或身份不对应时保留专门的未知状态，不落入消息拒绝。普通本地未知才进入消息分支。该函数级性质不能替代 Important 2 的入口检查。
- `:653-654` 跳过 fit 的 rows/features/local；`:687-690` 按配置分别筛选 cal 与 eval 家族。已只读核对冻结 batch.json 和实际三个 Count 模型，mixed/F1_only/F2_only 的 fit_false 分别为 F1+F2、F1、F2，train_parents 均为原六 fit 父，未见目标族实际进入单族拟合。冻结配置的校准为源族、评价为目标族。此处没有把“允许配置任意值”推断为当前已发生族泄漏。
- `:691-699` 三 regime 都重算冻结 Count 连续分数，不继承旧决定或旧三态门限。正常成功路径下，既有 features 与 D-only 路径均使用旧 count_inputs/base_score 语义。失败路径的一致性仍受 Important 2 阻塞。
- `:563-597` 保留完整六格、父、实体与 epoch 覆盖、窗口、本地未知及全部 local_state 分层、逐 family/k、可选域分组、轨迹曾采纳与首次采用、相对 LocalCount 的配对时效和决定转移。`:607-618` 保留风险、真实采纳损失及增量门槛，未把结果归因于 Joint。

## 审核边界与能否运行

本报告确认的是代码与规格的对应关系，不是实际门限可估、方法收益或论文贡献结论。当前默认资料和三个 Count 模型的角色匹配已作一次只读核对；未执行真实特征重算或统计重计。评价报告的 total_evaluate_seconds 只覆盖 evaluate 阶段，后续汇报总运行成本时还须结合本地侧录提取耗时，不能把它写成完整方法耗时。

**Task 2 暂不批准正式效果 evaluate，先修复 Important 1 和 2 并做相应定点复审。冻结 b5aa3ca 的 I/F 提取可继续。**

## d5f81ba 定点复审

**Important 1 和 2 均为 ADDRESSED。Task 2 Approved，允许在已绑定清单及完整侧录准备完成后执行 evaluate。** 本节覆盖上文暂不批准的旧结论，未发现剩余 Critical 或 Important。

本次仅核对 `341a659..d5f81ba` 修复差异、实际调用者和实施报告末节，不重审几何及四门限算法，没有重跑已报告的 5 项回归或其他测试。`git diff 341a659 d5f81ba --check` 通过。未修改实现、配置或 run_001/run_002 物理侧录，未执行真实效果评价。

- **Important 1 已解决。** `run.py:549-552` 将 local_path 限定为当前 prepare 的规范 job 产物。`:579-592` 校对冻结 receiver_id、该接收车存在于来源列表、parent、query_present、newborn、job/id/frame/index/timestamp；非故障记录还核对 receiver_timestamp 与查询时间。已标 input_fault 的时间故障仍保留未知，不会因这项检查整批退出。`:741-742` 的真实 evaluate 调用由冻结 parent 配置传入 receiver_id，接口调用者已同步更新。`:722-726` 的阶段绑定补入 prepare.config、prepare.complete 及原 online_path。上述改动已覆盖原反例的接错接收车和矛盾查询状态，不依赖再次修改物理侧录。
- **Important 2 已解决。** `run.py:498-527` 在公共窗口上直接形成有效 U/X 计数、共同资格和 Count_inputs。有效 X 的有限五维条件与旧 `predict_row` 一致，缺失 X 将该事件保留未知，不补未报。窗口仍由既有 `kernel.windows(..., 10)` 处理来源顺序、epoch、时间中断及 W10 截断。`:530-540` 将 D 缺失、不可估或非法模型排除在预测器之外；有效 D 的数值失败继续由旧 head 捕获。`:595-609` 保留公共计数，R 单独判断可读性，缺失计数不再补 0。`:761` 的实际 C 重算使用独立 Count_inputs，不再依赖 D_head 存在或条件特征的整体 finite 状态。D 正常可读时，`:605-607` 仍核对公共计数与原 freeze.count_inputs 完全一致，防止成功路径改变冻结 Count 分数语义。
- 已核对 3 项新增回归及 2 项受影响入口测试的代码与报告中的 5 项通过记录。覆盖错误侧录身份及查询状态、异路径拒绝、D 正常/None/空模型/数值失败、旧 feature 失败，以及 13 次窗口的 W10 截断、历史中断和 X 缺失。端到端夹具直接经过 evaluation_rows，D 失败后保留 `[2,1,1,3,2]`、一次未报及两消息资格，随后实际使用冻结形式 Count 评分和公共 decide 验证采纳与计数拒绝。因此本次通过不只依赖 decide 的函数级边界测试。

本次修复没有改 Task 1 几何、原 Count 参数、门限选择、primary/权重或效果门槛。允许 evaluate 是工程审核结论，不表示真实校准覆盖充分、方法有效或论文贡献已经成立。原有不可估层、独立父及实体支持限制仍须按冻结规程报告。
