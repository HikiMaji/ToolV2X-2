# 时序条件联合核验开发结果

14个已使用开发父录制。此结果不是独立未见评估，也不提供风险保证。
主参数 W=10，s=0.9。门限只取cal，敏感性分别重新cal，不按eval挑选。
主假风险只统计target。F3辅助occluder、未实现任务、无target query和标签未知覆盖分别报告。

| 方法 | 真采纳 | 真拒绝 | 假采纳 | 假拒绝 | correct definite |
|---|---:|---:|---:|---:|---:|
| D | 0.3162 | 0.0370 | 0.0037 | 0.8478 | 0.5820 |
| B | 0.3416 | 0.0381 | 0.0037 | 0.7460 | 0.5438 |
| C | 0.3416 | 0.0381 | 0.0037 | 0.7460 | 0.5438 |
| T | 0.4019 | 0.0473 | 0.0037 | 0.7739 | 0.5879 |
| J | 0.4043 | 0.0489 | 0.0037 | 0.7843 | 0.5943 |
| Jind | 0.4019 | 0.0434 | 0.0037 | 0.7621 | 0.5820 |
| G | 0.3930 | 0.0473 | 0.0037 | 0.7802 | 0.5866 |
| MATE_policy | 0.6061 | 0.0039 | 0.0000 | 0.3372 | 0.4716 |

组件不可估状态及共同数值失败见metrics.json；不可估方法保留unknown，不删共同分母。
这里只报告观察差异和可估状态。保留决定待Task3按已批准标准裁决，不以NLL降低另加保留门槛。

```json
{
  "retention_status": "pending_Task3_approved_criteria",
  "method_status": {
    "D": {
      "status": "ok",
      "reason": null
    },
    "B": {
      "status": "ok",
      "reason": null
    },
    "C": {
      "status": "ok",
      "reason": null
    },
    "T": {
      "status": "ok",
      "reason": null
    },
    "J": {
      "status": "ok",
      "reason": null
    },
    "Jind": {
      "status": "ok",
      "reason": null
    },
    "G": {
      "status": "ok",
      "reason": null
    }
  },
  "method_estimable": {
    "D": true,
    "B": true,
    "C": true,
    "T": true,
    "J": true,
    "Jind": true,
    "G": true,
    "MATE_policy": true
  },
  "proxy_vs_direct": {
    "comparison_estimable": true,
    "correct_definite_difference": -0.03819768188523398,
    "true_accept_difference": 0.025382753317726714,
    "false_accept_difference": 0.0,
    "accepted_delay_median_difference": 0.0,
    "normal_window_nll_difference": 0.2789861964970708,
    "family_k_false_accept_difference": {
      "F0/1": 0.0,
      "clean/0": null,
      "F1/1": 0.0,
      "F1/2": 0.0,
      "F1/3": 0.0,
      "F2/1": null,
      "F2/2": 0.0,
      "F2/3": 0.0
    }
  },
  "temporal_vs_static": {
    "comparison_estimable": true,
    "correct_definite_difference": 0.04405784241144817,
    "true_accept_difference": 0.060222927577749,
    "false_accept_difference": 0.0,
    "accepted_delay_median_difference": 0.0,
    "normal_window_nll_difference": -1.1953680480438678,
    "family_k_false_accept_difference": {
      "F0/1": 0.0,
      "clean/0": null,
      "F1/1": 0.0,
      "F1/2": 0.0,
      "F1/3": 0.0,
      "F2/1": null,
      "F2/2": 0.0,
      "F2/3": 0.0
    }
  },
  "joint_vs_temporal": {
    "comparison_estimable": true,
    "correct_definite_difference": 0.0064362244728088935,
    "true_accept_difference": 0.0024557822789511574,
    "false_accept_difference": 0.0,
    "accepted_delay_median_difference": 0.0,
    "normal_window_nll_difference": 0.001233148688587704,
    "family_k_false_accept_difference": {
      "F0/1": 0.0,
      "clean/0": null,
      "F1/1": 0.0,
      "F1/2": 0.0,
      "F1/3": 0.0,
      "F2/1": null,
      "F2/2": 0.0,
      "F2/3": 0.0
    }
  },
  "joint_vs_group": {
    "comparison_estimable": true,
    "correct_definite_difference": 0.007686578840047309,
    "true_accept_difference": 0.011283352435573657,
    "false_accept_difference": 0.0,
    "accepted_delay_median_difference": 0.0,
    "normal_window_nll_difference": null,
    "family_k_false_accept_difference": {
      "F0/1": 0.0,
      "clean/0": null,
      "F1/1": 0.0,
      "F1/2": 0.0,
      "F1/3": 0.0,
      "F2/1": null,
      "F2/2": 0.0,
      "F2/3": 0.0
    }
  },
  "joint_vs_MATE_policy": {
    "comparison_estimable": true,
    "correct_definite_difference": 0.12268230319651363,
    "true_accept_difference": -0.20175995533101732,
    "false_accept_difference": 0.003703703703703704,
    "accepted_delay_median_difference": -0.09999999999999998,
    "normal_window_nll_difference": null,
    "family_k_false_accept_difference": {
      "F0/1": 0.0,
      "clean/0": null,
      "F1/1": 0.0,
      "F1/2": 0.0,
      "F1/3": 0.022222222222222223,
      "F2/1": null,
      "F2/2": 0.0,
      "F2/3": 0.0
    }
  }
}
```
