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


def control_target(waypoints,world_from_rear,rear_to_actor_x,headings,times,forward_margin=.5):
    """Convert RH rear-axle path to actor-origin targets for CARLA's native PID.

    Longitudinal setpoint is displacement / time between the first two actor
    path samples. Original PDM generator velocity slots are unpopulated zeros.
    This probe uses forward-only paths and a longitudinal rear-to-actor offset.
    """
    points=np.asarray(waypoints,dtype=float);pose=np.asarray(world_from_rear,dtype=float)
    headings=np.asarray(headings,dtype=float);times=np.asarray(times,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.isfinite(points).all():raise ValueError('finite trajectory required')
    if (headings.shape!=(len(points),) or times.shape!=(len(points),)
            or not np.isfinite(headings).all() or not np.isfinite(times).all()
            or times[0]<=0 or np.any(np.diff(times)<=0)):raise ValueError('finite aligned headings and increasing future times required')
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
    return dict(speed_kmh=float(np.linalg.norm(actor_points[1]-actor_points[0])/(times[1]-times[0])*3.6),
        world_xy=(target@pose[:2,:2].T+pose[:2,3]).tolist(),mode='track')


class PDMControlAdapter:
    """Convert a causal dense simulated rollout into one native PID target."""
    def __init__(self,speed_preview_s=.5,stop_speed_mps=.2,stop_distance_m=.3,
                 release_speed_mps=.4,release_distance_m=.6,forward_margin=.5):
        values=np.asarray([speed_preview_s,stop_speed_mps,stop_distance_m,
            release_speed_mps,release_distance_m,forward_margin],dtype=float)
        if (not np.isfinite(values).all() or min(values)<=0
                or speed_preview_s>2. or stop_speed_mps>=release_speed_mps
                or stop_distance_m>=release_distance_m):
            raise ValueError('positive ordered control adapter thresholds required')
        self.spec=dict(speed_preview_s=float(speed_preview_s),
            stop_speed_mps=float(stop_speed_mps),stop_distance_m=float(stop_distance_m),
            release_speed_mps=float(release_speed_mps),release_distance_m=float(release_distance_m),
            forward_margin=float(forward_margin))
        self.stopped=False

    @staticmethod
    def _hold(mode):
        return dict(speed_kmh=0.,world_xy=None,mode=mode)

    def update(self,plan,world_from_rear,rear_to_actor_x,current_speed_mps):
        pose=np.asarray(world_from_rear,dtype=float)
        current_speed_mps=float(current_speed_mps)
        if (pose.shape!=(4,4) or not np.isfinite(pose).all()
                or not np.isfinite(rear_to_actor_x) or not np.isfinite(current_speed_mps)
                or current_speed_mps<0):
            raise ValueError('finite current calibration and nonnegative speed required')
        if not isinstance(plan,dict):raise ValueError('PDM v2 plan required')
        status=plan.get('plan_status')
        if status=='no_feasible_candidate':return self._hold('hold_infeasible')
        if status=='emergency_brake':return self._hold('hold_emergency')
        if status!='selected_feasible':raise ValueError('unknown PDM v2 plan status')
        if not isinstance(plan.get('selected_index'),int) or not isinstance(plan.get('rollout'),dict):
            raise ValueError('selected feasible plan requires rollout and index')

        rollout=plan['rollout']
        required={'source','times_s','xy_rear_axle_m','headings_rad','speed_mps','acceleration_mps2'}
        if not required<=set(rollout) or rollout['source']!='selected_scored_simulation':
            raise ValueError('selected scored simulation rollout required')
        times=np.asarray(rollout['times_s'],dtype=float)
        points=np.asarray(rollout['xy_rear_axle_m'],dtype=float)
        headings=np.asarray(rollout['headings_rad'],dtype=float)
        speeds=np.asarray(rollout['speed_mps'],dtype=float)
        accelerations=np.asarray(rollout['acceleration_mps2'],dtype=float)
        expected=np.arange(0.,2.01,.1)
        if (times.shape!=expected.shape or not np.allclose(times,expected,rtol=0,atol=1e-9)
                or points.shape!=(len(times),2) or headings.shape!=times.shape
                or speeds.shape!=times.shape or accelerations.shape!=times.shape
                or not all(np.isfinite(x).all() for x in (points,headings,speeds,accelerations))
                or np.any(speeds<0) or not np.allclose(points[0],[0.,0.],rtol=0,atol=1e-8)
                or not np.isclose(headings[0],0.,rtol=0,atol=1e-8)
                or np.any(points[:,0]<-1e-5)):
            raise ValueError('invalid anchored 0.1s dense rollout')

        offset=float(rear_to_actor_x)
        distance=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())
        cfg=self.spec;max_speed=float(speeds.max())
        if self.stopped:
            if max_speed>=cfg['release_speed_mps'] or distance>=cfg['release_distance_m']:
                self.stopped=False
            else:
                return self._hold('hold_stopped')
        elif (current_speed_mps<=cfg['stop_speed_mps']
                and max_speed<=cfg['stop_speed_mps']
                and distance<=cfg['stop_distance_m']):
            self.stopped=True
            return self._hold('hold_stopped')

        if distance<=1e-5 or np.max(points[:,0])<=1e-5:
            raise ValueError('selected rollout has no forward path')
        actor_points=points+offset*np.column_stack((np.cos(headings),np.sin(headings)))
        segments=np.linalg.norm(np.diff(actor_points,axis=0),axis=1)
        actor_distance=float(segments.sum())
        cumulative=np.r_[0.,np.cumsum(segments)]
        target_distance=min(cfg['forward_margin'],actor_distance)
        index=int(np.searchsorted(cumulative,target_distance,side='left'))
        ratio=(target_distance-cumulative[index-1])/segments[index-1]
        target=actor_points[index-1]+ratio*(actor_points[index]-actor_points[index-1])
        target[1]*=-1
        speed=float(np.interp(cfg['speed_preview_s'],times,speeds))
        return dict(speed_kmh=speed*3.6,
            world_xy=(target@pose[:2,:2].T+pose[:2,3]).tolist(),mode='track')
