#!/usr/bin/env python3
"""Replay each local detector independently, audit self removal, export PDM scenes.

Only current own-state files are read for each vehicle. No peer/GT association.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tracking.lidar_tracks import exclude_self,FixedRateTracker,plan_objects
from planning.carla_map_inputs import route_geometry


def calibration(state,max_tilt_rad):
    pose=np.array(state['world_from_vehicle'],dtype=float)
    sensor=np.array(state['world_from_sensor'],dtype=float)
    for p in (pose,sensor):
        if p.shape!=(4,4) or not np.isfinite(p).all() or not np.allclose(p[:3,:3].T@p[:3,:3],np.eye(3),atol=1e-5):
            raise ValueError('invalid rigid calibration')
        if np.arccos(np.clip(p[2,2],-1,1))>max_tilt_rad:raise ValueError('planar-probe tilt limit exceeded')
    yaw=np.arctan2(pose[1,0],pose[0,0]);c=np.cos(yaw);s=np.sin(yaw)
    planar=pose.copy();planar[:3,:3]=[[c,-s,0],[s,c,0],[0,0,1]]
    wheels=(np.array(state['wheel_positions'])/100.-pose[:3,3])@pose[:3,:3]
    front=wheels[:2,0].mean();rear=wheels[2:,0].mean()
    if not 1.<front-rear<5.:raise ValueError('wheel calibration inconsistent')
    rear_pose=planar.copy();rear_pose[:3,3]+=planar[:3,0]*rear
    ext=np.asarray(state['box_extent']);loc=np.asarray(state['box_location'])
    center=pose[:3,:3]@loc+pose[:3,3]
    own_box=np.r_[center,2*ext,yaw]
    vehicle=dict(width=2*ext[1],front_length=loc[0]+ext[0]-rear,rear_length=rear-loc[0]+ext[0],
        wheel_base=front-rear,cog_position_from_rear_axle=state['center_of_mass'][0]-rear,height=2*ext[2])
    network_yaw=np.arctan2(sensor[1,0],sensor[0,0])+np.pi/2
    return rear_pose,own_box,vehicle,network_yaw,sensor[:2,3]


def tracking_step(record,state,tracker,spec,ownpath="live_own_state"):
    vehicle=state["vehicle"];i=state["index"]
    rear,own,geometry,yaw,origin=calibration(state,spec['max_tilt_rad'])
    boxes=np.asarray(record['classes'][0]['boxes_lwh'],dtype=float).reshape(-1,7)
    scores=np.asarray(record['classes'][0]['scores'])
    rot=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
    world=boxes.copy();world[:,:2]=boxes[:,:2]@rot.T+origin
    world[:,6]=np.arctan2(np.sin(boxes[:,6]+yaw),np.cos(boxes[:,6]+yaw))
    keep,audit=exclude_self(world,own,spec['self_iou'])
    tracks=tracker.update(world[keep],scores[keep],state['timestamp'],state['frame'])
    for t in tracks:t['parent_refs']=['ego_vehicle_%d:%s'%(vehicle,ref) for ref in t['parent_refs']]
    scene=dict(version='toolv2x_pdm_scene_v1',coordinate_frame='ego_rear_axle_rh',
        timestamp_us=round(state['timestamp']*1e6),speed_mps=max(0.,float(np.dot(state['velocity'][:2],rear[:2,0]))),
        acceleration_mps2=float(np.dot(state['acceleration'][:2],rear[:2,0])),steering_angle_rad=state['steering_angle_rad'],
        vehicle=geometry,**route_geometry(state['route_samples'],rear),speed_limit_mps=spec['planning_speed_cap_mps'],
        map_identity=state['map_identity'],objects=plan_objects(tracks,rear,'ego%d'%vehicle),
        signal_constraints=[],input_kind='causal_sensor_scene')
    return dict(vehicle=vehicle,index=i,frame=state['frame'],timestamp=state['timestamp'],own_state_path=str(ownpath),
        own_box_world=own.tolist(),raw_world_boxes=world.tolist(),self_filter=audit,
        tracker_inputs=world[keep].tolist(),tracks=tracks,scene=scene,
        unknown_velocity_track_ids=[t['id'] for t in tracks if not t['velocity_observed']])


def run(args):
    output=Path(args.output)
    if output.exists():raise ValueError('new output directory required')
    root=Path(args.capture);records=json.loads(Path(args.detections).read_text())
    spec=dict(version='toolv2x_local_tracking_probe_v1',dt=.05,self_iou=.5,max_tilt_rad=.05,
              tracker='existing AB3DMOT Hungarian GIoU3D',association_threshold=-.2,min_hits=3,max_age=2,
              planning_speed_cap_mps=4.,forecast='causal_tracking_state_motion_proxy',
              scope='controlled local chain only, no P/F/LLM/closed-loop')
    output.mkdir(parents=True);rows=[]
    for vehicle in sorted({r['vehicle'] for r in records}):
        tracker=FixedRateTracker(dt=spec['dt'])
        local=[r for r in records if r['vehicle']==vehicle]
        # Preserve input order. Out-of-order or skipped frames are rejected below.
        for record in local:
            i=record['frame_index'];ownpath=root/('ego_vehicle_%d/own_state/%04d.json'%(vehicle,i))
            state=json.loads(ownpath.read_text())
            expected=(root/('ego_vehicle_%d/lidar/%04d.npy'%(vehicle,i))).resolve()
            if (Path(record['read_paths'][0]).resolve()!=expected or state['index']!=i or state['vehicle']!=vehicle
                or record['record_len']!=[1]):raise ValueError('capture/detection provenance mismatch')
            rows.append(tracking_step(record,state,tracker,spec,str(ownpath)))
    (output/'tracks_scenes.json').write_text(json.dumps(rows,indent=2)+'\n')
    summary=dict(execution_spec=spec,rows=len(rows),removed_self=sum(a['excluded'] for r in rows for a in r['self_filter']),
        retained_detections=sum(len(r['tracker_inputs']) for r in rows),emitted_track_states=sum(len(r['tracks']) for r in rows),
        detector_miss_states=sum(not t['detector_hit'] for r in rows for t in r['tracks']),
        causal_time_checked=True,initial_velocity_semantics='zero initialization, flagged unknown until at least two detector updates',
        consumed_remote_fields=0,gt_actor_future_access=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',required=True);p.add_argument('--detections',required=True);p.add_argument('--output',required=True)
    run(p.parse_args())
