"""Export saved, frozen results for reporting; no fitting or decision changes."""
import csv
import json
from pathlib import Path
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

RUN=Path("/root/autodl-tmp/ToolV2X/docs/evidence/rq1_independent_supplement_2026_11_16/run_001")
reports={n:json.loads((RUN/"report"/(n+".json")).read_text()) for n in ("mixed","F1_only","F2_only")}
folder=RUN/"figures"
folder.mkdir(exist_ok=True)
columns=["regime","split","method","true_n","false_n","true_accept","true_unknown","true_reject","false_accept","false_unknown","false_reject","correct_definite"]
with (RUN/"metrics_for_report.csv").open("w",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=columns,lineterminator="\n");writer.writeheader()
    for regime,report in reports.items():
        for split,measurement in report["metrics"].items():
            for method,value in measurement["system_query"].items():
                row=dict(regime=regime,split=split,method=method,true_n=value["true"]["n"],false_n=value["false"]["n"],correct_definite=value["correct_definite"])
                for truth in ("true","false"):
                    for decision in ("accept","unknown","reject"):
                        row[truth+"_"+decision]=value[truth]["weighted"][decision]
                writer.writerow(row)
fontpath=subprocess.check_output(["fc-match","-f","%{file}","Noto Sans CJK SC"],text=True).strip()
font=FontProperties(fname=fontpath)
plt.rcParams.update({"axes.spines.top":False,"axes.spines.right":False,"axes.axisbelow":True,"savefig.dpi":180})
fig,ax=plt.subplots(figsize=(10.7,5.4))
names={"Count":"原计数基线","MissCount":"追加未报次数","BaseTail":"扩展原拒绝区","Cond":"追加条件反证"}
colors={"Count":"#758494","MissCount":"#BBC3CE","BaseTail":"#DEA66C","Cond":"#148C8B"}
x=np.arange(3);width=.19
for j,m in enumerate(names):
    values=[100*r["metrics"]["eval"]["system_query"][m]["correct_definite"] for r in reports.values()]
    bars=ax.bar(x+(j-1.5)*width,values,width,label=names[m],color=colors[m])
    ax.bar_label(bars,labels=[f"{v:.2f}" for v in values],padding=3,fontsize=9)
ax.set_xticks(x)
ax.set_xticklabels(["混合方案","基线假族 F1 / 评价 F2","基线假族 F2 / 评价 F1"],fontproperties=font,fontsize=11)
ax.set_ylabel("正确明确判断比例（%）",fontproperties=font,fontsize=12)
ax.set_title("独立条件核验：三个开发方案及同预算对照",fontproperties=font,fontsize=15,pad=16)
ax.set_ylim(0,86);ax.grid(axis="y",alpha=.18)
ax.legend(prop=font,ncol=4,loc="upper left",frameon=False)
fig.text(.08,.035,"CD 为真采纳率与假拒绝率的均值；同校准预算上限，实际误拒率不同。\n已查看的开发录制，非独立终测；本图不含新的联合机制。",fontproperties=font,fontsize=9,color="#444444")
fig.subplots_adjust(left=.08,right=.985,top=.86,bottom=.2)
fig.savefig(folder/"condition_comparison.png")
fig.savefig(folder/"condition_comparison.svg")
svg=folder/"condition_comparison.svg"
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines())+"\n")
plt.close(fig)
print("Exported metrics_for_report.csv and PNG/SVG comparison.")
