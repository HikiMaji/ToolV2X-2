#!/usr/bin/env python3
"""PDM map/calibration smoke on a runtime capture, with EMPTY obstacle evidence.

This is not perception, closed-loop control, or a method-effect experiment.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from planning.carla_map_inputs import route_geometry
from planning.v2xverse_inputs import lidar_to_rear_axle
from planning.pdm_core import PDMCore


def main():
    parser=argparse.ArgumentParser();parser.add_argument('capture');parser.add_argument('output')
    args=parser.parse_args();source=Path(args.capture);dest=Path(args.output)
    if dest.exists():raise ValueError('output already exists')
    capture=json.loads(source.read_text());ego=capture['vehicles'][0]
    pose=np.asarray(ego['world_from_vehicle']);wheels=np.asarray(ego['wheel_positions'])/100.
    # CARLA runtime wheel positions are world-frame centimetres. Keep raw values
    # in the capture so this conversion and axle geometry are independently auditable.
    wheel_local=(wheels-pose[:3,3])@pose[:3,:3]
    front=wheel_local[:2,0].mean();rear=wheel_local[2:,0].mean()
    if not (1.<front-rear<5. and rear<0<front):raise ValueError('wheel calibration inconsistent')
    rear_pose=pose.copy();rear_pose[:3,3]+=pose[:3,0]*rear
    ext=ego['box_extent'];center=ego['box_location']
    geometry=dict(width=2*ext[1],front_length=center[0]+ext[0]-rear,
        rear_length=rear-(center[0]-ext[0]),wheel_base=front-rear,
        cog_position_from_rear_axle=ego['center_of_mass'][0]-rear,height=2*ext[2])
    scene=dict(version='toolv2x_pdm_scene_v1',coordinate_frame='ego_rear_axle_rh',
        timestamp_us=round(ego['sensor_timestamp']*1e6),
        speed_mps=max(0.,float(np.dot(ego['velocity'],pose[:3,0]))),
        acceleration_mps2=float(np.dot(ego['acceleration'],pose[:3,0])),
        steering_angle_rad=0.,vehicle=geometry,**route_geometry(capture['route_samples'],rear_pose),
        speed_limit_mps=3.,map_identity=dict(name=capture['map'],revision='CARLA_0.9.10.1',route=capture['route_identity']),
        objects=[],signal_constraints=[],input_kind='synthetic_contract')
    cloud=np.load(str(source.parent/'lidar_0.npy'),allow_pickle=False)
    transformed=lidar_to_rear_axle(cloud,ego['world_from_sensor'],rear_pose)
    result=PDMCore().plan(scene);original=PDMCore().plan(scene,original_cv=True)
    np.testing.assert_allclose(result['waypoints'],original['waypoints'],atol=1e-9,rtol=0)
    record=dict(scope='real map and own-state numerical integration with intentionally empty obstacle fixture; NOT sensor-based driving',
        source=str(source),world_from_rear_axle=rear_pose.tolist(),wheel_local_m=wheel_local.tolist(),
        sensor_frame_matches=all(v['frame']==capture['frame'] and v['sensor_timestamp']==v['snapshot_timestamp'] for v in capture['vehicles']),
        transformed_points=len(transformed),scene=scene,result=result,original_cv_waypoints_equal=True,
        assumptions=['stationary braked vehicle: zero steering', '3m/s test speed cap, not road speed metadata',
                     'no perception or traffic signal detection; empty fixture is not evidence of free space'])
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(geometry=geometry,waypoints=result['waypoints'],original_cv_equal=True)))

if __name__=='__main__':main()
