"""Rasterize already-admitted P/F into the CoDriving occupancy grid.

This pure converter does not query peers or verify receipts. Its caller must
supply admitted records in ONE source frame at the decision epoch. History
boxes already share that frame (never independently recentered historical poses).
Coordinates: x forward, y left, yaw CCW, metres, seconds, velocities m/s.
Output is a sidecar: the original six-channel planner is not changed here.
"""
import copy
import numpy as np

P_CHANNELS=('P_current_occupancy','P_history_occupancy','P_vx','P_vy','P_valid_mask')
# Inference box2occ is 192x96 at .25m, despite the dataset YAML's .125.
GRID=dict(version='codriving_occ_192x96_v1',height=192,width=96,resolution_m=.25,
          forward_m=36.,backward_m=12.,left_m=12.,right_m=12.,
          row_direction='backward',column_direction='right',origin='ego_actor')
FORWARD=36.-(np.arange(192)+.5)*.25
LEFT=12.-(np.arange(96)+.5)*.25
XX,YY=np.meshgrid(FORWARD,LEFT,indexing='ij')


def _array(value,shape):
    a=np.asarray(value,dtype=float)
    if a.shape!=shape or not np.isfinite(a).all():raise ValueError('finite aligned array required')
    return a


def _box(box,T):
    x,y,length,width,yaw=_array(box,(5,))
    if min(length,width)<=0:raise ValueError('positive box extents required')
    xy=T[:2,:2]@np.array([x,y])+T[:2,2]
    direction=T[:2,:2]@np.array([np.cos(yaw),np.sin(yaw)])
    return np.r_[xy,length,width,np.arctan2(direction[1],direction[0])]


def _mask(box):
    x,y,length,width,yaw=box;dx=XX-x;dy=YY-y;c=np.cos(yaw);s=np.sin(yaw)
    return (np.abs(c*dx+s*dy)<=length/2)&(np.abs(-s*dx+c*dy)<=width/2)


def _records(records):
    records=sorted(records,key=lambda r:(r['source'],r['track']))
    identities=[]
    for r in records:
        if not all(isinstance(r[k],str) and r[k] for k in ['source','track']):raise ValueError('source/track required')
        if not isinstance(r['refs'],list) or not r['refs']:raise ValueError('admitted field references required')
        identities.append((r['source'],r['track']))
        _array(r['velocity'],(2,))
        if type(r['velocity_valid']) is not bool:raise ValueError('explicit velocity validity required')
    if len(set(identities))!=len(identities):raise ValueError('duplicate source/track')
    return records


def rasterize_pf(p_records,f_records,ego_from_source,*,future_times,time_binding,decision_time):
    """P [5,H,W], F and matched F-CV [K,H,W], float32, decision-frame grid.

    Occupancy/validity are 0/1; velocity is signed m/s. History is union of
    valid past footprints, excluding current. P_valid_mask marks known current
    velocity support, not free space or detector visibility. Overlap velocity
    uses the closest current box centre per cell, ties by source/track.

    Top-1 score ties use the first mode. F and F-CV share target set, dimensions,
    fixed current yaw, rasterizer and support mask; future yaw is not transmitted.
    Linear interpolation includes current anchor at t=0; no extrapolation.
    No score normalization or multiplication into occupancy is performed.
    """
    T=_array(ego_from_source,(3,3));R=T[:2,:2]
    if not np.allclose(T[2],[0,0,1]) or not np.allclose(R.T@R,np.eye(2)) or not np.isclose(np.linalg.det(R),1):
        raise ValueError('explicit proper planar rigid transform required')
    times=np.asarray(future_times,dtype=float)
    if times.ndim!=1 or not len(times) or not np.isfinite(times).all() or times[0]<=0 or np.any(np.diff(times)<=0):raise ValueError('increasing future sample times required')
    if not isinstance(time_binding,str) or not time_binding.strip() or not np.isfinite(decision_time):raise ValueError('explicit physical time binding required')
    ps=_records(p_records);fs=_records(f_records)
    p=np.zeros((5,192,96),np.float32);f=np.zeros((len(times),192,96),np.float32);cv=np.zeros_like(f)
    nearest=np.full((192,96),np.inf);valid=np.ones(len(times),bool);selected=[];support=[]
    for r in ps:
        box=_box(r['box'],T);mask=_mask(box);p[0][mask]=1
        if r['velocity_valid']:
            distance=(XX-box[0])**2+(YY-box[1])**2;owned=mask&(distance<nearest)
            velocity=R@_array(r['velocity'],(2,));p[2][owned]=velocity[0];p[3][owned]=velocity[1];p[4][owned]=1;nearest[owned]=distance[owned]
        last=-np.inf
        for h in r.get('history',[]):
            stamp=float(h['time'])
            if not np.isfinite(stamp) or stamp>0 or stamp<=last or type(h['valid']) is not bool:raise ValueError('ordered causal relative history required')
            last=stamp
            if h['valid'] and stamp<0:p[1][_mask(_box(h['box'],T))]=1
    for r in fs:
        if not r['velocity_valid']:raise ValueError('matched F-CV requires causal valid current velocity')
        if type(r['model_used']) is not bool:raise ValueError('forecast model_used required')
        ft=np.asarray(r['forecast_times'],dtype=float);paths=np.asarray(r['forecast'],dtype=float);scores=np.asarray(r['forecast_scores'],dtype=float)
        if (ft.ndim!=1 or not len(ft) or not np.isfinite(ft).all() or ft[0]<=0 or np.any(np.diff(ft)<=0)
            or paths.ndim!=3 or paths.shape[1:]!=(len(ft),2) or not len(paths)
            or scores.shape!=(len(paths),) or not np.isfinite(paths).all() or not np.isfinite(scores).all()):raise ValueError('finite forecast modes/time grid required')
        mode=int(np.argmax(scores));selected.append(mode)
        box=_box(r['box'],T);xy=paths[mode]@R.T+T[:2,2];xy=np.vstack([box[:2],xy]);axis=np.r_[0.,ft]
        velocity=R@_array(r['velocity'],(2,));supported=times<=ft[-1];support.append(supported.tolist());valid&=supported
        for k,t in enumerate(times):
            if not supported[k]:continue
            fb=box.copy();fb[:2]=[np.interp(t,axis,xy[:,j]) for j in range(2)];f[k][_mask(fb)]=1
            cb=box.copy();cb[:2]+=velocity*t;cv[k][_mask(cb)]=1
    # A partially represented scene must not masquerade as a fully valid future.
    f[~valid]=0;cv[~valid]=0
    return dict(version='toolv2x_codriving_pf_bev_v1',P=p,F=f,F_CV=cv,F_valid=valid,
        grid=copy.deepcopy(GRID),p_channels=list(P_CHANNELS),future_times=times.tolist(),
        decision_time=float(decision_time),time_binding=time_binding,
        audit=dict(p_targets=[r['source']+':'+r['track'] for r in ps],f_targets=[r['source']+':'+r['track'] for r in fs],
                   selected_modes=selected,forecast_support=support,model_used=[r['model_used'] for r in fs],
                   p_refs=[copy.deepcopy(r['refs']) for r in ps],f_refs=[copy.deepcopy(r['refs']) for r in fs],
                   footprint='current dimensions and yaw held fixed for both F and F-CV',
                   raster='pixel-centre inclusion, binary; not bitwise identical to upstream antialiasing',
                   evidence_presence=dict(P=bool(ps),F=bool(fs)),planner_consumed=False))


def attach_pf_sidecar(batch, rasters):
    """Attach NumPy evidence batch without changing any original planner input.

    Original WaypointPlanner_e2e ignores the added key. A later input adaptation
    and training step must explicitly consume it; this API alone adds no gain.
    """
    shape=tuple(batch['occupancy'].shape)
    if len(shape)!=5 or shape[1:]!=(5,6,192,96) or shape[0]!=len(rasters) or not rasters:
        raise ValueError('expected CoDriving B,5,6,192,96 and one raster per sample')
    if 'toolv2x_pf_bev' in batch:raise ValueError('evidence already attached')
    first=rasters[0]
    if len(first['future_times'])!=10:raise ValueError('CoDriving planner requires ten future sample channels')
    for r in rasters:
        if r['version']!=first['version'] or r['grid']!=first['grid'] or r['future_times']!=first['future_times']:
            raise ValueError('mixed raster contracts/time axes')
    result=dict(batch)
    result['toolv2x_pf_bev']={k:np.stack([r[k] for r in rasters]) for k in ['P','F','F_CV','F_valid']}
    result['toolv2x_pf_bev']['records']=[{k:copy.deepcopy(v) for k,v in r.items() if k not in ['P','F','F_CV','F_valid']} for r in rasters]
    return result
