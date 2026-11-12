# 最终主结果独立核对脚本

`recount_main.py`仅使用Python标准库，不导入冻结run、kernel或fit。当前只交付脚本，未读取尚未完成的正式结果。唯一手算样例已通过，5行原始采纳率0.6，按族/k、父、epoch、时刻逐级平均后的采纳率0.625。

最终`report.complete.json`、`report/predictions.jsonl.gz`和`report/metrics.json`齐备后，由主会话触发一次执行。

```bash
/root/miniconda3/bin/python /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/recount_main.py --run-out /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/run_001 --output /root/autodl-tmp/ToolV2X/docs/evidence/rq1_temporal_2026_11_12/execution_2026_11_13/recount_main.json
```

输出文件必须新建，脚本拒绝向原report目录写入。返回码0表示本次核对一致且cal实际风险未超5%，返回码1表示存在差异或超预算；明细最多列前40项，同时保留差异总数。正式文件缺失会直接失败，不等待后台、不产生占位结果。

核对范围

- 按最终主参数W10/s0.9的冻结门限，重新从分数和共同资格推导决定，逐行对照已保存决定。
- 独立筛选主真和主假。未知决定留在分母，真假标签未知不进入主六格。用层内epoch均值、父均值及层均值逐级聚合，核对cal/eval八方法六格的原始计数、比例、分母和正确明确率。
- 核对每family/k主假六格，输出cal总体及各非空层的实际错误风险和缺cal层。不重新搜索或修改门限。
- 独立核对J-T与J-G的正确明确率、真采纳、假采纳、每family/k假采纳及已采纳者延迟中位数差异。轨迹首次采纳及未采纳数量也从预测重建。
- 保留共同数值失败计数和原因、各方法状态/有限评分覆盖、全局不可估说明，确认失败或不可估记录没有贡献明确决定，也没有因缺分数离开共同分母。

脚本不复核其他四套敏感性、重拟合、原生回放、最优门限、bootstrap区间或轨迹最长错误。数值容差为1e-10。PASS只说明主结果与独立重计一致，不能替代Task3依据完整设计第11节作保留决定。cal的5%只是开发点估计；eval风险、父录制数量及缺失层仍须进入评审。已采纳者延迟必须与未采纳数量一起解释。
