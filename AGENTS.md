# ToolV2X repository guidance

## 当前方案与每次任务必读规则

当前唯一方法主文档为[研究点一当前方案](docs/研究点一_当前方案.md)。按用户2026-11-06最新要求重建，只保留当前方案正文与导航。后续直接修改正文，不在首尾叠加整版修订历史；历史过程记入STATUS或专题记录。`docs/OQEA_current.md`已经转为历史修订档案，`docs/OQEA.md`、`docs/OQEA-v1.md`及`docs/observation_conditioned_verification_scope_2026_10_05.md`也只作历史参考。

1. 每次开始本项目相关任务，包括研究讨论、调研、设计、编码、实验、结果解释，以及新对话或上下文压缩后继续，都先完整阅读[研究推进经验教训](docs/research_lessons_2026_10_08.md)和当前主方案[研究点一_当前方案.md](docs/研究点一_当前方案.md)，再查看 `docs/user_requirements.md` 的最新要求和 `docs/STATUS.md` 的最新状态。不能只依赖记忆、对话摘要或旧计划。本任务内连续工具调用且文件未变化时，不要求机械重复读取；每个新任务仍须复习经验教训。
2. 开始推进前，核对本次工作是否符合方案的研究问题、威胁模型、信息权限、证据语义和评价边界。当前预算获取第二贡献暂缓，不自行恢复旧 P/F、LLM 或完整驾驶系统目标。
3. 用户后续明确修正，或在授权范围内采纳评审意见时，先同步修改这份主方案对应正文，并在状态或专题记录中注明日期、改动和依据，再开展依赖这些改动的工作。候选想法、待验证假设、已确认要求、实现状态和实验结论必须分开。未经确认的范围扩展不能写成已批准方案。
4. 不另建互相冲突的当前方案。补充文档从主方案链接；旧方案与旧实验记录保留为历史。方法修订不回写旧实验结果，也不把设计写成已完成实现。
5. 当前用户指令优先于方案。若新指令已明确改变范围，按新指令更新方案；只有影响执行且无法从已有授权判断的歧义才需要澄清，普通实施选择不因此反复暂停。

每个研究阶段开始以及上下文压缩后，还要核对当前用户目标与经验教训。当前研究点一以目标真实性为核验对象，当前设计与实现边界见研究点一_当前方案.md，不再要求从旧OQEA历史修订中寻找当前方法。固定A原型属于历史版本。旧二值准入、固定A和历史实验授权不能作为新算法实施授权。具体目标以研究点一_当前方案.md、STATUS.md及用户最新指令为准。阶段内文件未变化时沿用已读内容，不逐条工具重复阅读；阶段结束检查交付物是否实际回答研究问题，不用新增文档数量代替完成。目标变更以用户后续指令为准。

## 每次运行的研究优先核对

启动新的训练或实验批次前，再核对经验教训中的三点：本批研究假设、论文证据价值、有限结束条件。不要把工程检查、框架完整度或测试数量当作方法进展；必要检查通过后，直接推进已授权的核心工作。若同类适配问题重复出现，回到设计判断，不无限补丁或扩训。此核对不增加新的审批流程，不要求在每条工具命令前重复读文档。

## 历史驾驶工作入口

以下入口和后续驾驶检查规则用于维护对应历史模块，不代表当前必须恢复或完成这些研究目标。

Start with `README.md`, `docs/github_review.md`, and `docs/driver_readiness_stage_a_2026_09_15.md`.
`docs/structured_driver_implementation_2026_09_15.md` records the preceding numeric-driver implementation; readiness configuration remains prepared, not executed.
`docs/evidence_adaptation.md` records the retained GoT evidence path.
`docs/framework_design.md` describes the approved target architecture; it is not a completion report.
Older documents and `src/probe`/`src/oracle` retain historical experiments. Some probe validation utilities are still imported by the current tools, so inspect callers before removing them.

## Checks and resources

- Resource-independent review: `python scripts/check_review.py` after installing `requirements-review.txt`.
- Full local integration: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s tests -p 'test_*.py'` in the model environment described in the README.
- The full suite requires external checkpoint/tokenizer files. A lightweight PASS does not mean the full model was run.
- Model weights, full datasets and repeated run snapshots are intentionally external. Do not treat archived absolute paths as portable input manifests.
- The user supplies large downloads from GitHub, GitHubusercontent, GitHubassets and Hugging Face. On 2026-09-14 the user explicitly authorized direct downloads smaller than 100 MB; enforce that limit when size is unknown. Use official sources, not mirror workarounds. Access to the explicitly assigned project repository is authorized separately.
- Preserve old evidence files. New runs use new output directories and describe their own code/configuration.

## Code Review Rules

1. Trace actual time-t input access. Flag future observations or labels entering online planning, peer evidence available before a query, missing history silently filled from the future, and confusion between physical dataset splits and recording-level research holdout. Offline labels may read future poses; follow the caller rather than flagging every future read.
2. Check P/F semantics and fair comparisons: common coordinates and timestamps, full source context before ROI filtering, P local recomputation versus F at equal information, retention of remote-only targets and separate modes/sources, and actual request/response bytes. Distinguish prompt rounding/truncation from wire compression.
3. Check the real driving/supervision path: in `q8_q9` mode Q9 must use the generated Q8 parent; explicit `direct` mode uses the `Trajectory` task and must not contain or execute Q8. Missing parents must never silently switch the mode. Invalid answers remain failures, only target answer tokens receive loss, and point/prompt tokens stay masked. Parsed trajectories, finite forward loss and historical checker PASS do not establish task quality, successful training, CUDA parity or sequential-query benefit.

4. The opt-in numeric driver uses `toolv2x_interaction_v2` and a full `StructuredDriverSpec`. Check that P histories and F modes enter the shared numeric model, that actual prior plans carry field dependencies, and that exact-repeat versus same-evidence refinement preserves the intended input. Numeric outputs are not Q9 text; bill all driving attempts separately from language generation.
5. Numeric training must use independent offline labels, recording-level train/validation isolation, and the same structured collator/network as inference. No target may fill a missing prior. Checkpoint initialization is explicitly untrained; synthetic gradient/resume tests are not dataset training or method evidence.


## 结论归档规则（2026-10-30用户明确要求）

每次研究讨论、审查或实验完成后，将本批已核实且成立条件清楚的结论维护到docs/REALLY，将待验证原因、候选方案和参数假设维护到docs/REALLY_MAYBE。先读两目录README和相关条目，避免重复宣称未做过既有实验。REALLY不表示永久无误，每条写明证据、适用范围与不能推出什么；数学假设成立不等于实测假设成立。外部AI原文保留原位，错误建议明确标记，不因存入MAYBE而默认合理。不要批量把历史方案未经核查搬入REALLY。研究点一_当前方案.md是唯一当前主方案，OQEA_current.md仅为历史档案，两目录为证据与候选索引。用户当前授权覆盖此次整理与后续持续记录，不需每次再次询问。


## 重要方法与实现的分阶段审核（2026-10-30用户要求）

必要时严格按docs/REALLY/研究实施流程.md执行：计划初稿，grill-me与用户讨论，讨论完成后独立子agent审核及修订复审，计划确定后写SDS，独立子agent审核SDS并复审，SDS确定后在新顶层会话用Superpowers按SDS实施。实现主会话负责调度及关键审查，分别开编码agent与独立审核agent，检查通过才运行计划内研究实验。子agent按任务难度选gpt-6-sol high或medium，关键研究/统计审核优先high。不能跳过讨论提前宣称计划通过，不把子agent冒称新顶层会话。grill-me不存在时查找后报告缺失并请求来源，不能伪称执行。普通只读检查与明确授权的归档不机械扩成该流程，但实质性方法改动不应假借小修补绕过。下载维持当前分段续传，未获指令不改整包。


## 2026-10-30后续子agent型号更新

用户最新明确将子agent改为`gpt-6.1-sol`。此要求覆盖后续任务，替代上文历史`gpt-6-sol`型号。研究设计与独立审核用high，常规有界任务用medium。既有历史报告中的型号按实际保留，不追改。


## 2026-10-30当前主会话继续实施

用户最新明确“这也要交接吗，你就是主对话啊”。据此本批不再要求用户另开顶层会话，直接由当前主会话调度gpt-6.1-sol编码和独立审核，按已审SDS连续推进。此修正覆盖之前新会话实施要求，其余计划、独立审核、规格和实验边界保留。


## 2026-10-30 校验必须与科研风险相称

用户要求删除无必要及重复校验。数据分组隔离、标签与特征对应、信息权限、必要数值合法性和最终核心统计需要保留。原始输入、模型和代码来源在接入/阶段边界确认一次；不要逐帧重新解析全registry、反复hash同一静态PCD/代码、持续全目录扫描或重复验收已经通过且未变的内容。消息攻击模型不等于本地实验文件持续遭篡改。先判断检查能否防止具体科研错误，再决定是否保留。普通工程精简不机械扩成新一轮研究计划，不以删除语义检查换取速度。正在运行的冻结批次不热改，已完成产物不因此重跑。


## 2026-11-12 数据范围澄清

用户指出项目已有更多数据，要求纠正长期只用10父录制/39任务的限制。该范围以及5/4/1划分仅属于特定冻结开发批次，不是方法限制或用户永久禁令。不得将“不反复扩数据或重训练、不重复盘点”解释为禁止使用已有其他录制。后续根据研究覆盖使用现有资产，缓存优先，必要的消息/标签适配或冻结前端补算可纳入具体实验；它们与新采集、训练感知模型分开。既有盘点可直接复用，不能据此再开展全量重复盘点。冻结批次保留原输入和结果，新数据安排另记清单与划分。
