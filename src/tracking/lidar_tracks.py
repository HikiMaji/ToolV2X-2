"""Local causal AB3DMOT bridge; no remote, GT or future input access."""
import numpy as np
from shapely.geometry import Polygon


def footprint(box):
    x,y,_,length,width,_,yaw=box
    r=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
    return Polygon(np.array([[1,1],[1,-1],[-1,-1],[-1,1]])*[length/2,width/2]@r.T+[x,y])


def exclude_self(boxes,own_box,iou_threshold):
    boxes=np.asarray(boxes,dtype=float).reshape(-1,7);own=np.asarray(own_box,dtype=float)
    if own.shape!=(7,) or not np.isfinite(own).all() or not np.isfinite(boxes).all():raise ValueError('finite boxes required')
    if not 0<iou_threshold<=1 or min(own[3:6])<=0 or np.any(boxes[:,3:6]<=0):raise ValueError('positive geometry and IoU threshold required')
    own_poly=footprint(own);audit=[];keep=[]
    for i,box in enumerate(boxes):
        poly=footprint(box);iou=poly.intersection(own_poly).area/poly.union(own_poly).area
        excluded=iou>=iou_threshold;keep.append(not excluded)
        audit.append(dict(detection_index=i,own_iou=float(iou),excluded=excluded,
                          reason='own_vehicle_overlap' if excluded else 'retained'))
    return np.array(keep,dtype=bool),audit


def to_camera(boxes):
    b=np.asarray(boxes,dtype=float).reshape(-1,7)
    # Camera: x=world x, y=-world z (bottom), z=world y; roty has opposite yaw.
    return np.column_stack([b[:,5],b[:,4],b[:,3],b[:,0],-b[:,2]+b[:,5]/2,b[:,1],-b[:,6]])


def from_camera(boxes):
    b=np.asarray(boxes,dtype=float).reshape(-1,7)
    return np.column_stack([b[:,3],b[:,5],-b[:,4]+b[:,0]/2,b[:,2],b[:,1],b[:,0],-b[:,6]])


class FixedRateTracker:
    def __init__(self,dt):
        if not np.isfinite(dt) or dt<=0:raise ValueError('positive capture period required')
        from tracking.run_ab3dmot import make_tracker
        self.tracker=make_tracker();self.dt=dt;self.last_time=None;self.last_frame=None
        self.frame_count=0;self.refs={}

    def update(self,boxes,scores,timestamp,frame):
        if timestamp is None or not np.isfinite(timestamp) or timestamp<0 or type(frame) is not int:
            raise ValueError('explicit timestamp and integer frame required')
        if self.last_time is not None and (abs(timestamp-self.last_time-self.dt)>1e-5 or frame!=self.last_frame+1):
            raise ValueError('fixed capture period/frame continuity required; no time guessing')
        boxes=np.asarray(boxes,dtype=float).reshape(-1,7);scores=np.asarray(scores,dtype=float)
        if scores.shape!=(len(boxes),) or not np.isfinite(boxes).all() or not np.isfinite(scores).all() or np.any(boxes[:,3:6]<=0):
            raise ValueError('invalid detection boxes/scores')
        info=np.zeros((len(boxes),7));info[:,0]=scores
        result,_=self.tracker.track(dict(dets=to_camera(boxes),info=info),self.frame_count,'local')
        self.last_time=timestamp;self.last_frame=frame;self.frame_count+=1
        active={t.id:t for t in self.tracker.trackers};rows=[]
        # Tentative tracks also consume detections before their first emission.
        for ident,t in active.items():
            if t.time_since_update==0:
                self.refs.setdefault(ident,[]).append('local_detection_frame:%d'%frame)
        for raw in result[0]:
            ident=int(raw[7]);t=active[ident];hit=t.time_since_update==0
            velocity=np.asarray(t.get_velocity()).reshape(-1)
            rows.append(dict(id=ident,box=from_camera(raw[None,:7])[0].tolist(),
                velocity=(velocity[[0,2]]/self.dt).tolist(),velocity_observed=t.hits>=2,
                detector_hit=hit,time_since_update=int(t.time_since_update),hits=int(t.hits),
                score=float(raw[8]),parent_refs=list(self.refs[ident])))
        return rows


def plan_objects(tracks,world_from_rear_axle,source):
    pose=np.asarray(world_from_rear_axle,dtype=float);yaw=np.arctan2(pose[1,0],pose[0,0]);out=[]
    for row in tracks:
        box=np.array(row['box'],dtype=float);xy=(box[:2]-pose[:2,3])@pose[:2,:2];xy[1]*=-1
        velocity=np.asarray(row['velocity'])@pose[:2,:2];velocity[1]*=-1
        box[:2]=xy;box[6]=np.arctan2(np.sin(yaw-box[6]),np.cos(yaw-box[6]))
        out.append(dict(token='%s:%s'%(source,row['id']),box=box.tolist(),velocity=velocity.tolist(),
                        forecast=None,parent_refs=row['parent_refs']))
    return out
