"""Startup and waypoint-to-native-PID conventions for bounded runtime probes."""
import numpy as np


class StartupGate:
    def __init__(self,min_frames,max_acceleration,min_track_hits):
        self.min_frames=min_frames;self.max_acceleration=max_acceleration
        self.min_track_hits=min_track_hits;self.stable=0
    def update(self,acceleration,tracks):
        ready=np.isfinite(acceleration) and abs(acceleration)<=self.max_acceleration
        ready=ready and all(t['hits']>=self.min_track_hits and t['detector_hit'] for t in tracks)
        self.stable=self.stable+1 if ready else 0
        return self.stable>=self.min_frames


def control_target(waypoints,world_from_rear,body_center_x,sample_dt=.5,forward_margin=.5):
    points=np.asarray(waypoints,dtype=float);pose=np.asarray(world_from_rear,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all():raise ValueError('finite trajectory required')
    if np.any(points[:,0]<-1e-5):raise ValueError('reverse trajectory forbidden in forward-only probe')
    ahead=np.flatnonzero(points[:,0]>body_center_x+forward_margin)
    if not len(ahead):
        return dict(speed_kmh=0.,world_xy=(pose[:2,3]+pose[:2,0]*(body_center_x+2.)).tolist(),mode='hold_no_forward_target')
    target=points[ahead[0]].copy();target[1]*=-1
    return dict(speed_kmh=float(np.linalg.norm(points[1]-points[0])/sample_dt*3.6),
        world_xy=(target@pose[:2,:2].T+pose[:2,3]).tolist(),mode='track')
