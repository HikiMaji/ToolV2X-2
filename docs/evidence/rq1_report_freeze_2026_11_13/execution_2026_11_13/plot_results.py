"""Export fixed comparison tables and PPT figures from completed audited metrics."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

base=Path(__file__).resolve().parent.parent
report=base/'run_001/report_corrected'
metrics=json.loads((report/'metrics.json').read_text())
review=json.loads((base/'execution_2026_11_13/recount.json').read_text())
assert review['status']=='pass' and review['n_audit_errors']==0, 'independent audit required'
# Figures only display saved audited values.
font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
if not font.exists(): font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')
font_manager.fontManager.addfont(str(font))
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),'axes.unicode_minus':False,'font.size':11,'svg.fonttype':'path'})
figures=report/'figures';figures.mkdir(exist_ok=True)
methods=['MATE_policy','Count','CountQ','D_old','D_zero','I_zero','J_zero','G_zero','Q_zero']
regimes=['mixed','F1_only','F2_only']
titles={'mixed':'混合训练与评价','F1_only':'F1训练，F2评价','F2_only':'F2训练，F1评价'}
with (report/'ppt_metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.writer(f);writer.writerow(['方案','方法','真采纳%','真未知%','真拒绝%','假采纳%','假未知%','假拒绝%','CD%','真时刻数','假时刻数'])
    for regime in regimes:
        cells=metrics['regimes'][regime]['metrics']['eval']['system_query']
        for method in methods:
            c=cells[method];values=[c[t]['weighted'][d] for t in ('true','false') for d in ('accept','unknown','reject')]+[c['correct_definite']]
            writer.writerow([regime,method]+['NA' if v is None else round(v*100,5) for v in values]+[c['true']['n'],c['false']['n']])

for regime in regimes:
    cells=metrics['regimes'][regime]['metrics']['eval']['system_query']
    fig,axes=plt.subplots(1,2,figsize=(13,6.5),sharey=True)
    positions=np.arange(len(methods))
    colors={'good':'#218660','unknown':'#d8dce2','bad':'#c84646'}
    for ax,truth,title,order in [(axes[0],'true','真实目标',[('accept','good','采纳'),('unknown','unknown','未知'),('reject','bad','拒绝')]),(axes[1],'false','虚假目标',[('reject','good','拒绝'),('unknown','unknown','未知'),('accept','bad','采纳')])]:
        left=np.zeros(len(methods))
        for action,color,label in order:
            values=np.asarray([0 if cells[m][truth]['weighted'][action] is None else cells[m][truth]['weighted'][action]*100 for m in methods])
            ax.barh(positions,values,left=left,height=.7,color=colors[color],label=label)
            for index,value in enumerate(values):
                if value>=6: ax.text(left[index]+value/2,index,f'{value:.1f}',ha='center',va='center',fontsize=9,color='white' if color!='unknown' else '#222222')
            left+=values
        for i,m in enumerate(methods):
            if cells[m][truth]['n']==0: ax.text(50,i,'无该类样本',ha='center',va='center')
        ax.set_title(title);ax.set_xlim(0,100);ax.set_xlabel('分级加权比例（%）');ax.set_yticks(positions);ax.set_yticklabels(methods)
        ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
        ax.legend(loc='lower center',bbox_to_anchor=(.5,1.02),ncol=3,frameon=False)
    axes[0].invert_yaxis()
    c=cells['D_zero'];fig.suptitle(titles[regime]+'：完整三态结果',fontsize=16,y=.98)
    fig.text(.5,.015,f"扩大开发评价，非未见终测 | 真目标 {c['true']['n']} 个时刻，假目标 {c['false']['n']} 个时刻 | Unknown保留在分母",ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.04,1,.91))
    for ext in ('png','svg'): fig.savefig(figures/(regime+'_six_cells.'+ext),dpi=220,bbox_inches='tight')
    plt.close(fig)

config=json.loads((base/'run_001/binding.json').read_text())['config']
parents=config['additional_eval_parents'];columns=[('F1',1),('F1',2),('F2',1),('F2',2)]
matrix=np.zeros((len(parents),len(columns)),int)
for record in metrics['construction_coverage']['entities'].values():
    i=parents.index(record['parent']);j=columns.index((record['family'],record['attack_k']))
    matrix[i,j]=2 if record['definite_false_query'] else 1 if record['constructed'] else 0
from matplotlib.colors import ListedColormap
fig,ax=plt.subplots(figsize=(9,5.5));ax.imshow(matrix,cmap=ListedColormap(['#e1e4e9','#eec064','#71b792']),vmin=0,vmax=2,aspect='auto')
ax.set_xticks(range(4));ax.set_xticklabels([f'{f} / k={k}' for f,k in columns]);ax.set_yticks(range(len(parents)));ax.set_yticklabels([p.split('/')[1] for p in parents])
labels={0:'不可构造',1:'构造完成\n无明确假query',2:'有明确假query'}
for i in range(len(parents)):
    for j in range(4):ax.text(j,i,labels[int(matrix[i,j])],ha='center',va='center',fontsize=10)
ax.set_title('24次冻结攻击尝试的实际覆盖',pad=15);ax.tick_params(length=0)
fig.text(.5,.02,'每格是一个注入目标构造任务；不可构造和无query均不计为防御成功。',ha='center',fontsize=10)
fig.tight_layout(rect=(0,.05,1,1))
for ext in ('png','svg'):fig.savefig(figures/('construction_coverage.'+ext),dpi=220,bbox_inches='tight')
plt.close(fig)
print('PPT figures and CSV exported to',report)

focus=['Count','D_old','D_zero','J_zero','MATE_policy']
fig,axes=plt.subplots(1,3,figsize=(13,4.8),sharey=True)
for ax,regime in zip(axes,regimes):
    cells=metrics['regimes'][regime]['metrics']['eval']['family_k']
    rates=[max(v['metrics'][m]['false']['weighted']['accept']*100 for v in cells.values() if v['n_primary_false']) for m in focus]
    bars=ax.bar(range(len(focus)),rates,color=['#9ca4af','#3675a8','#d98930','#8867a8','#498576'])
    ax.axhline(5,color='#be3333',linestyle='--',linewidth=1.3)
    ax.bar_label(bars,labels=[f'{x:.1f}' for x in rates],padding=3,fontsize=10)
    ax.set_xticks(range(len(focus)));ax.set_xticklabels(focus,rotation=30,ha='right')
    ax.set_ylim(0,56);ax.set_title(titles[regime]);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False)
axes[0].set_ylabel('最坏已测family/k层假采纳（%）')
fig.suptitle('新增评价的分层假采纳风险',fontsize=16)
fig.text(.5,.015,'虚线为冻结的5%开发门槛；均为有限样本点估计，不代表部署风险保证。',ha='center',fontsize=10)
fig.tight_layout(rect=(0,.06,1,.93))
for ext in ('png','svg'):fig.savefig(figures/('risk_by_regime.'+ext),dpi=220,bbox_inches='tight')
plt.close(fig)
