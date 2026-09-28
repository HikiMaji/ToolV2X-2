"""Static single-lane CARLA route geometry; no World or actor access.

First runtime gate only: callers must select a signal-free, non-junction lane.
This does not reconstruct an unknown recorded route or supply perception.
"""
import numpy as np
from shapely.geometry import Polygon


def route_geometry(samples, world_from_rear_axle):
    pose=np.asarray(world_from_rear_axle,dtype=float)
    if (pose.shape!=(4,4) or not np.isfinite(pose).all() or
        not np.allclose(pose[3],[0,0,0,1]) or
        not np.allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),atol=1e-6) or
        not np.isclose(np.linalg.det(pose[:3,:3]),1) or
        not np.allclose(pose[2,:3],[0,0,1],atol=1e-5)):
        raise ValueError('planar proper rigid rear axle calibration required')
    if len(samples)<2:raise ValueError('route requires at least two samples')
    keys={'x','y','yaw','width','road_id','section_id','lane_id'}
    if any(set(s)!=keys for s in samples):raise ValueError('static route sample whitelist mismatch')
    lanes={(s['road_id'],s['section_id'],s['lane_id']) for s in samples}
    if len(lanes)!=1:raise ValueError('first adapter supports one non-junction lane only')
    data=np.asarray([[s[k] for k in ('x','y','yaw','width')] for s in samples],dtype=float)
    if not np.isfinite(data).all() or np.any(data[:,3]<=0):raise ValueError('invalid route geometry')
    yaw=np.deg2rad(data[:,2]);normal=np.column_stack([-np.sin(yaw),np.cos(yaw)])
    left=data[:,:2]+normal*data[:,3:4]/2;right=data[:,:2]-normal*data[:,3:4]/2
    def local(xy):
        p=(xy-pose[:2,3])@pose[:2,:2]
        p[:,1]*=-1
        return p
    xy=local(data[:,:2])
    if np.any(np.linalg.norm(np.diff(xy,axis=0),axis=1)<1e-6):raise ValueError('duplicate route samples')
    heading=np.arctan2(pose[1,0],pose[0,0])-yaw
    heading=np.arctan2(np.sin(heading),np.cos(heading))
    polygon=local(np.concatenate([left,right[::-1]],axis=0))
    poly=Polygon(polygon)
    if not poly.is_valid or poly.area<=0:raise ValueError('invalid sampled lane polygon')
    token=':'.join(str(v) for v in next(iter(lanes)))
    return dict(centerline=np.column_stack([xy,heading]).tolist(),
                drivable_lanes={token:polygon.tolist()},route_lane_ids=[token],intersections=[])
