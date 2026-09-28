"""Offline fixed-state interventions; never a counterfactual closed-loop result."""
import copy, json, sys
from collections import Counter, deque
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from planning.pdm_core import PDMCore, PDMExecutionSpec, PDMScorer, PDMGenerator
from planning.pdm_control import control_target
from tracking.lidar_tracks import plan_objects
OUT=Path(__file__).resolve().parent
score_original=PDMScorer.score_proposals
trajectory_original=PDMGenerator.generate_trajectory
scoring={}
forced_index=None

def score(self,*args,**kwargs):
    result=score_original(self,*args,**kwargs)
    scoring.update(multi_metrics=self._multi_metrics.tolist(),weighted_metrics=self._weighted_metrics.tolist())
    return result

def trajectory(self,index):
    return trajectory_original(self,index if forced_index is None else forced_index)

PDMScorer.score_proposals=score
PDMGenerator.generate_trajectory=trajectory
summary={};replays=[]
for case in ['empty','lead']:
    rows=[json.loads(s) for s in (ROOT/'outputs/pdm_closedloop_2026_09_22_v3'/case/'frames.jsonl').read_text().splitlines()]
    rows=[r for r in rows if r['phase']=='driving'];errors=deque(maxlen=10);pid_errors=[]
    speeds=np.array([r['evaluation_only']['speed_mps'] for r in rows])
    targets=np.array([r['target']['speed_kmh']/3.6 for r in rows])
    frozen=copy.deepcopy(rows[0]['tracked']['tracks'])
    for t in frozen:t['velocity']=[0.,0.]
    for r in rows:
        velocity=np.array(r['state']['velocity'])
        error=r['target']['speed_kmh']-np.linalg.norm(velocity)*3.6;errors.append(error)
        u=np.clip(error+(.05*sum(errors)*.05 if len(errors)>1 else 0),-1,1)
        expected=[min(max(u,0),.75),min(max(-u,0),.3)]
        actual=[r['applied_control'][k] for k in ['throttle','brake']]
        pid_errors.append(float(np.max(np.abs(np.array(expected)-actual))))
    info=dict(steps=len(rows),candidate_counts=dict(Counter(r['plan']['selected_index'] for r in rows)),
        candidate_switches=sum(a['plan']['selected_index']!=b['plan']['selected_index'] for a,b in zip(rows,rows[1:])),
        detector_misses=sum(not t['detector_hit'] for r in rows for t in r['tracked']['tracks']),
        track_id_sets=[list(k) for k in set(tuple(t['id'] for t in r['tracked']['tracks']) for r in rows)],
        zero_score_frames=sum(max(r['plan']['proposal_scores'])==0 for r in rows),
        pid_reconstruction_max_error=max(pid_errors),speed_target_rmse=float(np.sqrt(np.mean((targets-speeds)**2))),
        tail60_speed_range=[float(min(speeds[-60:])),float(max(speeds[-60:]))],
        tail60_target_range=[float(min(targets[-60:])),float(max(targets[-60:]))],
        max_abs_acceleration=max(abs(r['tracked']['scene']['acceleration_mps2']) for r in rows),
        tail60_stop_indices=[r['index'] for r in rows[-60:] if r['evaluation_only']['speed_mps']<.01],
        variants={})
    variants=['base'] if case=='empty' else ['base','zero_object_velocity','frozen_first_observation','force_candidate_4','zero_ego_steering']
    for variant in variants:
        selected=rows if variant=='base' else rows[-60:]
        speeds_out=[];delta=[];zeros=0;indices=[];max_replay_error=0
        for r in selected:
            scene=copy.deepcopy(r['tracked']['scene']);forced_index=4 if variant=='force_candidate_4' else None
            if variant=='zero_object_velocity':
                for o in scene['objects']:o['velocity']=[0.,0.]
            if variant=='frozen_first_observation':scene['objects']=plan_objects(frozen,r['tracked']['world_from_rear'],'ego0')
            if variant=='zero_ego_steering':scene['steering_angle_rad']=0.
            result=PDMCore().plan(scene)
            pose=np.asarray(r['tracked']['world_from_rear']);actor=np.asarray(r['state']['world_from_vehicle'])
            offset=float((actor[:3,3]-pose[:3,3])@pose[:3,0])
            target=control_target(result['waypoints'],pose,offset,result['waypoint_headings_rad'],result['times'])
            v=target['speed_kmh']/3.6;speeds_out.append(v);delta.append(v-r['target']['speed_kmh']/3.6)
            zeros+=max(result['proposal_scores'])==0;indices.append(result['selected_index'])
            if variant=='base':
                difference=float(np.max(np.abs(np.array(result['waypoints'])-r['plan']['waypoints'])))
                max_replay_error=max(max_replay_error,difference)
                assert difference<1e-9 and result['selected_index']==r['plan']['selected_index']
            replays.append(dict(case=case,variant=variant,index=r['index'],target_speed_mps=v,
                selected_index=result['selected_index'],executed_index=forced_index if forced_index is not None else result['selected_index'],
                emergency=result['emergency_brake'],scores=result['proposal_scores'],**copy.deepcopy(scoring)))
        info['variants'][variant]=dict(frames=len(selected),target_range=[min(speeds_out),max(speeds_out)],
            mean_abs_target_delta=float(np.mean(np.abs(delta))),max_abs_target_delta=float(np.max(np.abs(delta))),
            max_replay_waypoint_error=max_replay_error if variant=='base' else None,zero_score_frames=int(zeros),candidate_switches=sum(a!=b for a,b in zip(indices,indices[1:])))
    summary[case]=info
(OUT/'v3_diagnosis.json').write_text(json.dumps(summary,indent=2)+'\n')
(OUT/'v3_replays.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in replays))
print(json.dumps(summary,indent=2))
