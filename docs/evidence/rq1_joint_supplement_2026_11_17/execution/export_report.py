"""Read frozen outputs and export descriptive tables/figures; no new decisions."""
import csv
import json
from pathlib import Path
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

RUN=Path("/root/autodl-tmp/ToolV2X/docs/evidence/rq1_joint_supplement_2026_11_17/run_002")
reports={(d,r):json.loads((RUN/"report"/d/(r+".json")).read_text())
         for d in ("existing","additional") for r in ("mixed","F1_only","F2_only")}
folder=RUN/"figures";folder.mkdir(exist_ok=True)
columns=["domain","regime","split","method","true_n","false_n","true_accept","true_unknown","true_reject","false_accept","false_unknown","false_reject","correct_definite"]
with (RUN/"metrics_for_report.csv").open("w",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=columns,lineterminator="\n");writer.writeheader()
    for (domain,regime),report in reports.items():
        for split,measurement in report["metrics"].items():
            for method,value in measurement["system_query"].items():
                row=dict(domain=domain,regime=regime,split=split,method=method,true_n=value["true"]["n"],false_n=value["false"]["n"],correct_definite=value["correct_definite"])
                for truth in ("true","false"):
                    for decision in ("accept","unknown","reject"):row[truth+"_"+decision]=value[truth]["weighted"][decision]
                writer.writerow(row)
font=FontProperties(fname=subprocess.check_output(["fc-match","-f","%{file}","Noto Sans CJK SC"],text=True).strip())
plt.rcParams.update({"axes.spines.top":False,"axes.spines.right":False,"axes.axisbelow":True,"savefig.dpi":180})
fig,axes=plt.subplots(1,2,figsize=(12.6,5))
x=np.arange(3);width=.32;labels=["混合","基线 F1 / 评价 F2","基线 F2 / 评价 F1"]
for j,(domain,label,color) in enumerate([("existing","原六段","#738797"),("additional","追加三段","#D78964")]):
    values=[100*(reports[domain,r]["metrics"]["eval"]["system_query"]["Joint"]["correct_definite"]-reports[domain,r]["metrics"]["eval"]["system_query"]["Cond"]["correct_definite"]) for r in ("mixed","F1_only","F2_only")]
    bars=axes[0].bar(x+(j-.5)*width,values,width,label=label,color=color)
    axes[0].bar_label(bars,labels=[f"{v:+.3f}" for v in values],padding=4,fontsize=9)
axes[0].axhline(1,color="#A74646",ls="--",lw=1,label="预定最低增量")
axes[0].axhline(0,color="#555555",lw=.8);axes[0].set_ylim(-.48,1.28)
axes[0].set_ylabel("Joint 相对 Cond 的 CD 变化（百分点）",fontproperties=font)
axes[0].set_title("联合增量未达到保留条件",fontproperties=font,fontsize=13)
for j,(domain,label,color) in enumerate([("existing","原六段 Cond","#738797"),("additional","追加三段 Cond","#D78964")]):
    values=[100*reports[domain,r]["metrics"]["eval"]["system_query"]["Cond"]["false"]["weighted"]["accept"] for r in ("mixed","F1_only","F2_only")]
    bars=axes[1].bar(x+(j-.5)*width,values,width,label=label,color=color)
    axes[1].bar_label(bars,labels=[f"{v:.2f}" for v in values],padding=4,fontsize=9)
axes[1].axhline(5,color="#A74646",ls="--",lw=1,label="5% 工作预算")
axes[1].set_ylim(0,28);axes[1].set_ylabel("假采纳率（%）",fontproperties=font)
axes[1].set_title("追加资料暴露基础采纳风险",fontproperties=font,fontsize=13)
for ax in axes:
    ax.set_xticks(x);ax.set_xticklabels(labels,fontproperties=font,fontsize=9)
    ax.grid(axis="y",alpha=.18);ax.legend(prop=font,fontsize=9,frameon=False,loc="upper left")
fig.text(.065,.035,"两域分开评价，参数与门限不重拟合。追加资料仅6个假实体，假层覆盖不足；高误采集中于一个实体。\n这些是开发资料上的观察，不能解释为部署风险估计，也不否定全部联合建模方向。",fontproperties=font,fontsize=9,color="#444444")
fig.subplots_adjust(left=.065,right=.985,top=.88,bottom=.22,wspace=.25)
fig.savefig(folder/"joint_result_and_adoption_risk.png");fig.savefig(folder/"joint_result_and_adoption_risk.svg")
svg=folder/"joint_result_and_adoption_risk.svg";svg.write_text("\n".join(s.rstrip() for s in svg.read_text().splitlines())+"\n")
print("Exported frozen-result CSV and PNG/SVG.")
