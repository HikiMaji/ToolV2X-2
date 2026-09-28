import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
fig,axes=plt.subplots(3,3,figsize=(15,9),sharex='col')
for batch,color in [(1,'tab:orange'),(2,'tab:blue')]:
    for j,case in enumerate(['empty','lead','lead_release']):
        rows=[json.loads(s) for s in (ROOT/('outputs/pdm_project_adapter_2026_09_22_v%d'%batch)/case/'frames.jsonl').read_text().splitlines()]
        rows=[r for r in rows if r['phase']=='driving'];t=np.array([r['timestamp'] for r in rows]);t-=t[0]
        v=[r['evaluation_only']['speed_mps'] for r in rows];a=[r['tracked']['scene']['acceleration_mps2'] for r in rows]
        steer=[r['applied_control']['steer'] for r in rows]
        axes[0,j].plot(t,v,color=color,label='batch %d'%batch);axes[1,j].plot(t,a,color=color);axes[2,j].plot(t,steer,color=color)
        mask=[i for i,r in enumerate(rows) if r['control_status']=='hold_infeasible']
        axes[0,j].scatter(t[mask],np.array(v)[mask],color=color,s=10,marker='x')
for j,case in enumerate(['Empty road','Stationary lead','Lead departs after 15 s']):
    axes[0,j].set_title(case);axes[0,j].legend();axes[0,j].axhline(.1,color='gray',ls=':',lw=1)
    axes[1,j].axhline(-4,color='gray',ls=':',lw=1);axes[1,j].axhline(4,color='gray',ls=':',lw=1)
    for i,label in enumerate(['Speed (m/s)','Longitudinal acceleration (m/s2)','Applied steering']):
        axes[i,j].set_ylabel(label);axes[i,j].grid(alpha=.2)
    axes[2,j].set_xlabel('Recorded driving time (s)')
    if j==2:
        for ax in axes[:,j]:ax.axvline(15,color='black',ls='--',lw=.8)
fig.suptitle('Both project-adapter batches FAILED; x marks no-feasible braking')
fig.tight_layout();fig.savefig(OUT/'failed_batches.png',dpi=150)
