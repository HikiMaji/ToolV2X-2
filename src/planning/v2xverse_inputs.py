"""Minimal single-vehicle sensor reader; no ground-truth actors or time guessing.

Pose/route values retain the dataset's native conventions. In particular theta
is the recorded compass value, not an already-converted rear-axle yaw.
"""
import json
from pathlib import Path
import re

import numpy as np


MEASUREMENT_FIELDS=('x','y','theta','speed','lidar_pose_x','lidar_pose_y',
                    'lidar_pose_z','x_command','y_command','command')


def load_vehicle_observation(sample_root, vehicle, frame):
    if not isinstance(vehicle,str) or re.fullmatch(r'ego_vehicle_[0-9]+',vehicle) is None:
        raise ValueError('only explicit vehicle sensor directories allowed; no RSU')
    if type(frame) is not int or frame<0:raise ValueError('nonnegative frame index required')
    root=Path(sample_root)/vehicle
    paths=[root/'measurements'/('%04d.json'%frame),root/'lidar'/('%04d.npy'%frame)]
    raw=json.loads(paths[0].read_text())
    measurement={k:raw[k] for k in MEASUREMENT_FIELDS}
    if not all(type(v) in (float,int) and np.isfinite(v) for v in measurement.values()):
        raise ValueError('invalid local measurement')
    lidar=np.load(paths[1],allow_pickle=False)
    if lidar.ndim!=2 or lidar.shape[1]!=4 or not np.isfinite(lidar).all():
        raise ValueError('finite Nx4 LiDAR required')
    return dict(version='toolv2x_v2xverse_sensor_v1',vehicle=vehicle,frame_index=frame,
        measurement=measurement,lidar=lidar,coordinate_frame='lidar_sensor_native',
        timestamp_seconds=None,timebase_status='not_bound',read_paths=[str(p) for p in paths])


def lidar_to_rear_axle(points, world_from_sensor, world_from_rear_axle):
    """CARLA LH sensor -> CARLA LH rear axle -> explicit RH planner frame.

    Both poses must refer to the same capture instant and come from declared
    localization/calibration. No simulator object is accessed here.
    """
    points=np.asarray(points,dtype=float)
    if points.ndim!=2 or points.shape[1]!=4 or not np.isfinite(points).all():
        raise ValueError('finite Nx4 LiDAR required')
    matrices=[]
    for pose in (world_from_sensor,world_from_rear_axle):
        pose=np.asarray(pose,dtype=float)
        if (pose.shape!=(4,4) or not np.isfinite(pose).all() or
                not np.allclose(pose[3],[0.,0.,0.,1.]) or
                not np.allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),atol=1e-6) or
                not np.isclose(np.linalg.det(pose[:3,:3]),1.)):
            raise ValueError('finite rigid poses in common CARLA frame required')
        matrices.append(pose)
    transform=np.linalg.inv(matrices[1])@matrices[0]
    output=points.copy()
    output[:,:3]=points[:,:3]@transform[:3,:3].T+transform[:3,3]
    output[:,1]*=-1.
    return output
