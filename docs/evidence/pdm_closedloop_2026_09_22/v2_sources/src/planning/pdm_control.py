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


def control_target(waypoints,world_from_rear,rear_to_actor_x,headings,speeds,forward_margin=.5):
    """Convert RH rear-axle path to actor-origin targets for CARLA's native PID.

    Longitudinal setpoint is the first original PDM sample's rear-axle speed.
    This probe uses forward-only paths and a longitudinal rear-to-actor offset.
    """
    points=np.asarray(waypoints,dtype=float);pose=np.asarray(world_from_rear,dtype=float)
    headings=np.asarray(headings,dtype=float);speeds=np.asarray(speeds,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all():raise ValueError('finite trajectory required')
    if (headings.shape!=(len(points),) or speeds.shape!=(len(points),)
            or not np.isfinite(headings).all() or not np.isfinite(speeds).all()
            or np.any(speeds<0)):raise ValueError('finite aligned headings and nonnegative speeds required')
    if pose.shape!=(4,4) or not np.isfinite(pose).all() or not np.isfinite(rear_to_actor_x):raise ValueError('finite current calibration required')
    if np.any(points[:,0]<-1e-5):raise ValueError('reverse trajectory forbidden in forward-only probe')
    actor_points=points+rear_to_actor_x*np.column_stack((np.cos(headings),np.sin(headings)))
    ahead=np.flatnonzero(actor_points[:,0]>rear_to_actor_x+forward_margin)
    if not len(ahead):
        # A short forward path is still a valid target, not a stop command.
        ahead=np.flatnonzero(actor_points[:,0]>rear_to_actor_x+1e-5)[-1:]
    if not len(ahead):
        return dict(speed_kmh=0.,world_xy=(pose[:2,3]+pose[:2,0]*(rear_to_actor_x+2.)).tolist(),mode='hold_no_forward_target')
    target=actor_points[ahead[0]].copy();target[1]*=-1
    return dict(speed_kmh=float(speeds[0]*3.6),
        world_xy=(target@pose[:2,:2].T+pose[:2,3]).tolist(),mode='track')
