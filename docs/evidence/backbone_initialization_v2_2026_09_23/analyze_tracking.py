"""Offline explanation of the frozen S2 run; no planner/simulator calls."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
run=ROOT/'outputs/backbone_tracking_gate_v2_2026_09_23'
rows=list(map(json.loads,(run/'S2/frames.jsonl').open()))
ref=json.loads((run/'references/S2.json').read_text())['rows'][:len(rows)]
t=np.array([r['t'] for r in rows]);xy=np.array([r['rear_xy'] for r in rows]);yaw=np.array([r['yaw'] for r in rows])
velocity=np.gradient(xy,.1,axis=0,edge_order=2)
speed=(velocity*np.column_stack([np.cos(yaw),np.sin(yaw)])).sum(1)
controls=[r['control'] for r in rows[:-1]]
audit=json.loads((run/'S2/independent_case_audit.json').read_text())
original=json.loads((run/'S2/audit.json').read_text())
for key in ['max_abs_e_long_m','rmse_e_long_m','max_abs_a_long_mps2','p99_abs_j_long_mps3']:
 assert audit['metrics'][key]==original['metrics'][key]
initial_target_distance=float(np.linalg.norm(np.asarray(rows[0]['target']['actor_local_xy'])-rows[0]['actor_xy']))
result=dict(status='FAIL',effective_cases=1,effective_controls=len(controls),record_count=len(rows),
 initial_target_distance_m=initial_target_distance,
 maximum_initial_hold_abs_steer=max(abs(r['control']['steer']) for r in rows if r['t']<1),
 final_x_reference_m=ref[-1]['x'],final_x_actual_m=rows[-1]['rear_xy'][0],
 independent_failures=audit['failures'],
 physical_failures_excluding_float_boundary_flags=[v for v in audit['failures'] if v not in ['illegal_control','steer_slew']],
 metrics={k:v for k,v in audit['metrics'].items() if k!='recorder'},
 initialization_status=json.loads((run/'S2/initialization_check.json').read_text())['status'],
 explanation='Near-coincident waypoint direction causes stationary steering saturation. Longitudinal root cause not isolated. No criteria changed.')
(OUT/'tracking_analysis.json').write_text(json.dumps(result,indent=2)+'\n')
fig,ax=plt.subplots(4,1,figsize=(9,10),sharex=True)
ax[0].plot(t,[r['x'] for r in ref],label='Reference rear axle');ax[0].plot(t,xy[:,0],label='Actual rear axle');ax[0].set_ylabel('x (m)');ax[0].legend()
ax[1].plot(t,[r['v'] for r in ref],label='Reference');ax[1].plot(t,speed,label='Actual position derivative');ax[1].set_ylabel('Speed (m/s)');ax[1].legend()
ax[2].plot(t[:-1],[c['throttle'] for c in controls],label='Throttle');ax[2].plot(t[:-1],[c['brake'] for c in controls],label='Brake');ax[2].set_ylabel('Command');ax[2].legend()
ax[3].plot(t[:-1],[c['steer'] for c in controls],label='Steering command');ax[3].set_ylabel('Steer');ax[3].set_xlabel('Frozen reference time (s)');ax[3].legend()
for a in ax:a.axvspan(0,1,color='grey',alpha=.15);a.grid(alpha=.25)
fig.suptitle('Initialization v2: S2 tracking FAIL (no retuning, no time alignment)')
fig.tight_layout();fig.savefig(OUT/'s2_tracking.png',dpi=150);plt.close(fig)
print(json.dumps({k:v for k,v in result.items() if k!='metrics'},indent=2))
