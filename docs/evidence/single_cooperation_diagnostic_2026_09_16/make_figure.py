"""Plot only saved diagnostic results; does not load models."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
rows=[json.loads(l) for l in (ROOT/'predictions.jsonl').read_text().splitlines()]
rows=[r for r in rows if r['checkpoint_step']==500]
summary=json.loads((ROOT/'summary.json').read_text())
content=json.loads((ROOT/'content_comparison.json').read_text())
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,3,figsize=(15,4.2),layout='constrained')
colors=['#2962a3','#008477','#d17b26']
for arm,color in zip(['P','F','PF'],colors):
 axes[0].plot(range(1,len(rows)+1),[r['pairs'][arm+'_shared_evidence']['trajectory_mean_delta_m']*1000 for r in rows],
              label=arm,color=color,lw=1.4)
axes[0].axvline(19.5,color='#888888',ls=':',lw=1)
axes[0].set(xlabel='Development frame (19 + 20)',ylabel='Mean waypoint displacement (mm)',
            title='Remote evidence response at step 500')
axes[0].legend(frameon=False)
steps=['0','500','3200']
for name,label,color in zip(['Ego_once','Ego_shared_prior','Ego_repeat'],
                           ['First output','Second output','Third output'],colors):
 axes[1].plot(steps,[summary[s]['all']['outputs'][name]['ADE3'] for s in steps],'-o',label=label,color=color)
axes[1].axhline(summary['500']['all']['outputs']['constant_motion']['ADE3'],color='#777777',ls='--',label='Constant motion')
axes[1].set(xlabel='Checkpoint step',ylabel='ADE3 (m)',title='Ego repetition with unchanged evidence')
axes[1].legend(frameon=False,fontsize=8)
att=content['summary']['P']['remote_attention']
means=[100*att[s]['mean'] for s in steps]
axes[2].plot(steps,means,'-o',color=colors[0])
axes[2].fill_between(steps,[100*att[s]['min'] for s in steps],[100*att[s]['max'] for s in steps],color=colors[0],alpha=.2)
for x,y in zip(steps,means):axes[2].annotate('%.1f%%'%y,(x,y),xytext=(0,7),textcoords='offset points',ha='center')
axes[2].set(xlabel='Checkpoint step',ylabel='Remote observation attention (%)',ylim=(0,60),
            title='P fusion: 87 paired observations')
fig.savefig(ROOT/'diagnostic.png',dpi=170)
fig.savefig(ROOT/'diagnostic.svg')
