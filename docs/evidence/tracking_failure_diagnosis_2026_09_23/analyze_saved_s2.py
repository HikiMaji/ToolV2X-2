"""Saved-data causal/interface audit only; no CARLA, planner or model imports."""
from pathlib import Path
from collections import deque
import json,math
import numpy as np
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
run=ROOT/'outputs/backbone_tracking_gate_v2_2026_09_23'
rows=list(map(json.loads,(run/'S2/frames.jsonl').open()))
fields=['throttle','brake','steer'];errors=deque(maxlen=10);replay=[];mismatches=[]
for i,r in enumerate(rows[:-1]):
    speed=float(np.linalg.norm(r['actor_velocity']))
    err=r['target']['speed_kmh']-3.6*speed;errors.append(err)
    integral=.05*sum(errors)*.1 if len(errors)>1 else 0.
    u=float(np.clip(err+integral,-1.,1.))
    expected=[min(u,.75) if u>=0 else 0.,min(-u,.3) if u<0 else 0.]
    actual=[r['control']['throttle'],r['control']['brake']]
    replay.append(dict(i=i,t=r['t'],error_kmh=err,integral_contribution=integral,
        expected=expected,actual=actual,max_abs_difference=max(abs(a-b) for a,b in zip(expected,actual))))
    echo=rows[i+1]['last_control'];difference=max(abs(echo[k]-r['control'][k]) for k in fields)
    if difference>0:
        matches=[j for j in range(max(0,i-3),i+1) if max(abs(echo[k]-rows[j]['control'][k]) for k in fields)<1e-9]
        mismatches.append(dict(observed_index=i+1,t=rows[i+1]['t'],expected_command_index=i,
            matching_command_indices=matches,max_abs_difference=difference,
            issued=r['control'],readback=echo))
assert len(replay)==150 and max(x['max_abs_difference'] for x in replay)<1e-6
cruise=rows[50:90];signed=[r['control']['throttle']-r['control']['brake'] for r in cruise]
first=rows[0];delta=np.asarray(first['target']['actor_local_xy'])-first['actor_xy']
angle=math.atan2(delta[1],delta[0])-first['yaw']
ref=json.loads((run/'references/S2.json').read_text())['rows']
summary=dict(scope='offline diagnostic; neither new physical execution nor effect estimate for proposed fixes',
 source_run=str(run.relative_to(ROOT)),samples=len(rows),controls=len(replay),
 pid_formula_max_abs_error=max(x['max_abs_difference'] for x in replay),
 command_echo_mismatch_counts={str(tol):sum(m['max_abs_difference']>tol for m in mismatches) for tol in [0.,1e-7,1e-6,1e-5]},
 command_echo_mismatches=mismatches,
 initial_target_distance_m=float(np.linalg.norm(delta)),initial_direction_error_deg=math.degrees(angle),
 initial_hold_max_steer=max(abs(r['control']['steer']) for r in rows if r['t']<1),
 cruise=dict(interval='5.0 <= t < 9.0',samples=len(cruise),sign_switches=sum(a*b<0 for a,b in zip(signed,signed[1:])),
  throttle_cap_count=sum(r['control']['throttle']>=.75-1e-6 for r in cruise),brake_cap_count=sum(r['control']['brake']>=.3-1e-6 for r in cruise),
  speed_min_mps=min(np.linalg.norm(r['actor_velocity']) for r in cruise),speed_max_mps=max(np.linalg.norm(r['actor_velocity']) for r in cruise),
  added_longitudinal_error_m=rows[90]['rear_xy'][0]-rows[50]['rear_xy'][0]-8.,
  max_integral_contribution=max(abs(r['integral_contribution']) for r in replay[50:90])),
 final_reference_x_m=ref[150]['x'],final_actual_x_m=rows[150]['rear_xy'][0],
 native_vertical_speed_abs_max_mps=max(abs(r['actor_velocity'][2]) for r in rows),
 gears=sorted(set(r['gear'] for r in rows)),
 max_dt_error_s=max(abs(b['timestamp']-a['timestamp']-.1) for a,b in zip(rows,rows[1:])))
(OUT/'diagnosis.json').write_text(json.dumps(summary,indent=2)+'\n')
(OUT/'pid_reconstruction.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in replay))
print(json.dumps({k:v for k,v in summary.items() if k!='command_echo_mismatches'},indent=2))
