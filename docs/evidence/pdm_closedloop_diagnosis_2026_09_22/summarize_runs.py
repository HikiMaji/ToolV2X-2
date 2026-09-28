"""Recompute finite-run metrics from full raw rows and plot the control chain."""
import csv,json
from pathlib import Path
from collections import Counter
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
report={};table=[];fig,axes=plt.subplots(4,2,figsize=(12,10),sharex=True)
for version,color in [('v3','tab:orange'),('v4','tab:blue')]:
    base=ROOT/('outputs/pdm_closedloop_2026_09_22_'+version)
    summary=json.loads((base/'summary.json').read_text());spec=summary['spec'];report[version]={}
    for column,case in enumerate(['empty','lead']):
        all_rows=[json.loads(s) for s in (base/case/'frames.jsonl').read_text().splitlines()]
        rows=[r for r in all_rows if r['phase']=='driving'];n=len(rows);assert n==160
        times=np.array([r['timestamp'] for r in rows]);assert np.allclose(np.diff(times),.05,atol=1e-7,rtol=0)
        assert all(b['frame']==a['frame']+1 for a,b in zip(all_rows,all_rows[1:]))
        assert len(list((base/case/'lidar').glob('*.npy')))==len(all_rows)
        assert all(r['plan']['timestamp_us']==round(r['timestamp']*1e6) for r in rows)
        v=np.array([r['evaluation_only']['speed_mps'] for r in rows]);target=np.array([r['target']['speed_kmh']/3.6 for r in rows])
        a=np.array([r['tracked']['scene']['acceleration_mps2'] for r in rows]);idx=[r['plan']['selected_index'] for r in rows]
        throttle=np.array([r['applied_control']['throttle'] for r in rows]);brake=np.array([r['applied_control']['brake'] for r in rows])
        last=rows[-1]['evaluation_only'];saved=next(o for o in summary['outcomes'] if o['case']==case)
        lateral=max(r['evaluation_only']['lateral_error_m'] for r in rows)
        invalid=sum(r['control_status']=='invalid_plan' for r in rows)
        passed=not saved['collision_events'] and invalid==0 and lateral<=spec['criteria']['max_lateral_error_m'] and last['progress_m']>spec['criteria']['min_'+case+'_progress_m']
        clearance=min(r['evaluation_only']['bumper_clearance_m'] for r in rows) if case=='lead' else None
        if case=='lead':passed=passed and clearance>0 and last['speed_mps']<spec['criteria']['max_final_lead_speed_mps']
        assert passed==saved['acceptance_pass'] and last==saved['final_metrics']
        time=times-times[0];after_launch=time>=2.
        tail=rows[-40:];stops=[]
        for i in range(1,n):
            if v[i]<.01 and v[i-1]>=.01 and np.any(v[i+1:]>0.2):stops.append(rows[i]['index'])
        metrics=dict(acceptance_recomputed=passed,driving_steps=n,detections=len(all_rows),progress_m=last['progress_m'],
            final_speed_mps=float(v[-1]),min_clearance_m=clearance,max_lateral_error_m=lateral,
            collision_event_count=len(saved['collision_events']),invalid_plans=invalid,
            status_counts=dict(Counter(r['control_status'] for r in rows)),
            max_abs_acceleration=float(max(abs(a))),max_abs_acceleration_after_2s=float(max(abs(a[after_launch]))),
            min_acceleration=float(min(a)),max_brake=float(max(brake)),brake_saturated_steps=int(sum(brake>.2999)),
            speed_target_rmse=float(np.sqrt(np.mean((v-target)**2))),stop_then_restart_indices=stops,
            last40_speed_range=[float(min(v[-40:])),float(max(v[-40:]))],
            last40_target_range=[float(min(target[-40:])),float(max(target[-40:]))],
            last10_speeds=v[-10:].tolist(),candidate_switches=sum(x!=y for x,y in zip(idx,idx[1:])),
            zero_score_frames=sum(max(r['plan']['proposal_scores'])==0 for r in rows),
            detector_misses=sum(not t['detector_hit'] for r in rows for t in r['tracked']['tracks']),
            track_id_sets=[list(k) for k in set(tuple(t['id'] for t in r['tracked']['tracks']) for r in rows)],
            secondary_acceleration_pass=bool(max(abs(a))<4),secondary_lead_tail_pass=bool(max(v[-40:])<.5) if case=='lead' else None,
            mean_loop_seconds=float(np.mean([r['loop_seconds'] for r in rows])))
        report[version][case]=metrics
        for i,r in enumerate(rows):
            table.append(dict(version=version,case=case,index=r['index'],time=float(time[i]),speed=float(v[i]),target=float(target[i]),
                acceleration=float(a[i]),throttle=float(throttle[i]),brake=float(brake[i]),steer=r['applied_control']['steer'],selected_index=idx[i],
                top_score=max(r['plan']['proposal_scores']),steering_angle=r['tracked']['scene']['steering_angle_rad']))
        axes[0,column].plot(time,v,color=color,label=version+' speed');axes[0,column].plot(time,target,color=color,ls='--',alpha=.65,label=version+' target')
        axes[1,column].plot(time,a,color=color,label=version)
        axes[2,column].plot(time,throttle-brake,color=color,label=version)
        axes[3,column].step(time,idx,color=color,where='post',label=version)
for i,label in enumerate(['Speed (m/s)','Acceleration (m/s2)','Throttle - brake','Selected candidate']):
    for j in range(2):axes[i,j].set_ylabel(label);axes[i,j].grid(alpha=.2)
for j,case in enumerate(['Empty road','Stationary lead']):
    axes[0,j].set_title(case);axes[0,j].legend(fontsize=8);axes[-1,j].set_xlabel('Recorded driving time (s)')
fig.suptitle('One finite run per version/case; v4 changes longitudinal Kp only')
fig.tight_layout();fig.savefig(OUT/'v3_v4_control.png',dpi=160)
with (OUT/'v3_v4_timeseries.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
(OUT/'v3_v4_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
