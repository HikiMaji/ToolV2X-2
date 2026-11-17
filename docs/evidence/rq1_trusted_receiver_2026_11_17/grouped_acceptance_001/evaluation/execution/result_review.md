# 分组采纳约束开发结果独立复核

2026-11-17。标准库独立复核PASS。三个配置的最终裁决均为 not_retained，旧 run_002 结论保留。

审计按主键逐行比对原运行和新运行，核对全部原始字段、分数及资格不变，只提高 tauC；独立复现新旧决定及原因，确认只允许采纳转未知，全部拒绝保留。没有修改源文件、搜索门限、重做校准或运行几何与模型。

核对 331876 条跨配置 cal/eval 记录、995628 组方法新旧决定、15266296 个保留输入字段。时间点和派生配置不是独立样本。数值容差 1e-10，最大差 4.36e-14，错误 0。

## 评价结论

| 配置 | Cond旧FA | 新FA | Cond旧TA | 新TA | Cond自身TA损失 | Count自身TA损失 | 新Cond相对新Count CD增益 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| mixed | 3.2197% | 1.8229% | 64.4742% | 62.5121% | 1.9621个百分点 | 2.2660个百分点 | 3.3801个百分点 |
| F1_only | 3.0303% | 0.3788% | 64.3749% | 61.3191% | 3.0558个百分点 | 3.4163个百分点 | 4.8325个百分点 |
| F2_only | 4.2424% | 3.6869% | 65.0369% | 64.7909% | 0.2459个百分点 | 0.2877个百分点 | 1.7777个百分点 |

所有表格和裁决按完整主真假、原层/父/query epoch/时刻权重独立重计。Local 只作描述基线，没有将其相对增益失败算作候选失败。

mixed 的失败检查为 false_accept_F1/2, own_TA_loss_LocalCount, FA_LocalCount_F1/2, FA_LocalCond_F1/2。Cond超限层 F1/2 为 6.5341%。

F1_only 的失败检查为 own_TA_loss_LocalCount, own_TA_loss_LocalCond。Cond各声明层假采纳未超5%，仍因自身采用代价失败。

F2_only 的失败检查为 false_accept_F1/2, FA_LocalCount_F1/2, FA_LocalCond_F1/2。Cond超限层 F1/2 为 7.3737%。

## 校准筛选与范围

| 配置 | Count cal TA损失 | Cond cal TA损失 | Count/Cond最差cal父组FA |
| --- | ---: | ---: | ---: |
| mixed | 1.4591个百分点 | 1.3210个百分点 | 4.5455% / 4.5455% |
| F1_only | 1.9765个百分点 | 1.7729个百分点 | 4.5455% / 4.5455% |
| F2_only | 0.1060个百分点 | 0.1006个百分点 | 4.5455% / 4.5455% |

三个配置 cal 两方法均满足完整总体、攻击层及已观察父组5%约束、自身真采纳损失不超过2个百分点、正质量远端真采纳。此次仅用已保存 cal 判决核对 screen.json，没有重新搜索门限。所有 eval 中两方法也保留正质量远端真采纳；失败不能归因于把远端采纳全部关闭。

本次是 cal 改动后，在已看过 eval 上进行的开发验证。总体误采下降不代表各攻击层风险通过，cal 通过不保证跨父采用代价达标。新增未知不得称为成功拒绝。此次结果不支持替换完整方法，也不否定已有条件反证的有限增益；不增加多车依赖或新父总体风险保证。

可复现命令

```bash
python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/grouped_acceptance_001/evaluation/execution/independent_verify.py --evaluation /root/autodl-tmp/ToolV2X/docs/evidence/rq1_trusted_receiver_2026_11_17/grouped_acceptance_001/evaluation
```

审计复用 run_002/execution/independent_verify.py 中已独立编写的标准库统计与判决函数。没有导入项目方法实现。复核范围不包括原始标签、上游分数重算、PCD几何、门限最优性或盲测保证。
