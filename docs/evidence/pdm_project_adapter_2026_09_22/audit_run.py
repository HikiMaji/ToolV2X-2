"""Independent raw-row acceptance and deterministic control-target replay."""
import json,sys,math
from pathlib import Path
from collections import Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'src'))
from planning.pdm_control import PDMControlAdapter
base=Path(sys.argv[1]);summary=json.loads((base/'summary.json').read_text());spec=summary['spec'];criteria=spec['criteria'];results={}
for case,expected_steps in spec['steps_by_case'].items():
    rows=[json.loads(s) for s in (base/case/'frames.jsonl').read_text().splitlines()];driven=[r for r in rows if r['phase']=='driving']
    assert len(driven)==expected_steps
    assert len(list((base/case/'lidar').glob('*.npy')))==len(rows)
    assert all(b['frame']==a['frame']+1 and abs(b['timestamp']-a['timestamp']-.05)<1e-7 for a,b in zip(rows,rows[1:]))
    adapter=PDMControlAdapter(**spec['control_adapter'],forward_margin=spec['target_forward_margin']);mismatch=[]
    for r in driven:
        plan=r['plan'];assert plan['timestamp_us']==round(r['timestamp']*1e6)
        assert plan['execution_spec']['version']=='toolv2x_pdm_core_v2'
        if plan['plan_status']=='selected_feasible':
            assert plan['candidate_feasible'][plan['selected_index']]
            assert plan['rollout']['times_s'][-1]==2.
        if r['control_status']=='unconfirmed_track_brake':continue
        rear=np.array(r['tracked']['world_from_rear']);actor=np.array(r['state']['world_from_vehicle'])
        offset=float((actor[:3,3]-rear[:3,3])@rear[:3,0]);speed=float(np.linalg.norm(r['state']['velocity']))
        try:
            t=adapter.update(plan,rear,offset,speed)
            if r['target'] is None or r['target'].get('mode')!=t['mode']:mismatch.append(r['index']);continue
            assert abs(t['speed_kmh']-r['target']['speed_kmh'])<1e-9
            if t['world_xy'] is not None:assert np.allclose(t['world_xy'],r['target']['world_xy'],atol=1e-9,rtol=0)
        except ValueError:
            assert r['control_status']=='invalid_plan'
    assert not mismatch,mismatch
    speed=np.array([r['evaluation_only']['speed_mps'] for r in driven]);accel=np.array([r['tracked']['scene']['acceleration_mps2'] for r in driven])
    statuses=Counter(r['control_status'] for r in driven);saved=next(x for x in summary['outcomes'] if x['case']==case)
    progress=driven[-1]['evaluation_only']['progress_m'];lateral=max(r['evaluation_only']['lateral_error_m'] for r in driven)
    clearance=min(r['evaluation_only']['bumper_clearance_m'] for r in driven) if case!='empty' else None
    end=spec['release_step'] if case=='lead_release' else len(driven);held=bool(np.all(speed[end-40:end]<.1)) if case!='empty' else None
    release_progress=progress-driven[spec['release_step']-1]['evaluation_only']['progress_m'] if case=='lead_release' else None
    release_peak=float(max(speed[spec['release_step']:])) if case=='lead_release' else None
    passed=(not saved['collision_events'] and statuses['invalid_plan']==0 and statuses['hold_infeasible']==0 and statuses['unconfirmed_track_brake']==0
            and lateral<=.5 and max(abs(accel))<4 and progress>(8 if case=='empty' else 2))
    if case!='empty':passed=passed and clearance>.5 and held
    if case=='lead_release':passed=passed and release_progress>2 and release_peak>.5
    assert passed==saved['acceptance_pass']
    results[case]=dict(acceptance_recomputed=bool(passed),steps=len(driven),detections=len(rows),progress_m=progress,
        final_speed_mps=float(speed[-1]),max_abs_acceleration_mps2=float(max(abs(accel))),min_acceleration_mps2=float(min(accel)),
        max_lateral_error_m=lateral,min_clearance_m=clearance,sustained_hold_pass=held,release_progress_m=release_progress,
        release_peak_speed_mps=release_peak,status_counts=dict(statuses),candidate_switches=sum(a['plan']['selected_index']!=b['plan']['selected_index'] for a,b in zip(driven,driven[1:])),
        max_steer_input_rad=max(abs(r['tracked']['scene']['steering_angle_rad']) for r in driven),
        detector_misses=sum(not t['detector_hit'] for r in driven for t in r['tracked']['tracks']),
        target_replay_pass=True,frame_time_checks_pass=True,collisions=len(saved['collision_events']))
(base/'independent_audit.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
