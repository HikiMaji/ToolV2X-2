"""Synthetic geometry illustration, not real MTR or planning evidence."""
from pathlib import Path
import sys,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'src'))
from planning.codriving_pf_bev import rasterize_pf
r=dict(source='fixture-peer',track='1',box=[10.,0.,4.,2.,0.],velocity=[3.,0.],velocity_valid=True,
       history=[dict(time=-.4,box=[8.8,0.,4.,2.,0.],valid=True),dict(time=-.2,box=[9.4,0.,4.,2.,0.],valid=True)],refs=['synthetic-contract-only'])
f=dict(r,forecast_times=[.5,1.,1.5,2.],forecast=[[[11.,.5],[12.,1.5],[13.,3.],[14.,5.]]],forecast_scores=[1.],model_used=True)
out=rasterize_pf([r],[f],np.eye(3),future_times=np.arange(1,11)*.2,time_binding='synthetic 0.2s illustration, not authenticated dataset clock',decision_time=0.)
np.savez_compressed(Path(__file__).parent/'synthetic_channels.npz',P=out['P'],F=out['F'],F_CV=out['F_CV'],F_valid=out['F_valid'])
fig,axs=plt.subplots(1,4,figsize=(10,7))
for ax,a,title in zip(axs,[out['P'][0],out['P'][1],out['F'][-1],out['F_CV'][-1]],['P current','P history','Synthetic F at 2s','Matched F-CV at 2s']):
 ax.imshow(a,extent=[-12,12,-12,36],origin='upper',vmin=0,vmax=1,cmap='gray_r');ax.plot(0,0,'r+');ax.set_title(title);ax.set_xlabel('right (m)');ax.set_ylabel('forward (m)')
fig.suptitle('Contract fixture only: shared 192x96 grid, 0.25m cells')
fig.tight_layout();fig.savefig(Path(__file__).parent/'synthetic_grid.png',dpi=140);plt.close(fig)
