"""Native CoDriving geometry and explicit sample identity, without model imports.

Sensor boxes are in the upstream detector's native frame. World coordinates
retain dataset handedness; reflect y only on entry to an actor forward/left
frame. This module does not confer a receipt on offline probe evidence.
"""
from dataclasses import asdict, dataclass
import copy
import operator
from pathlib import Path
import re
import numpy as np


@dataclass(frozen=True)
class NativeInputSpec:
    version: str = 'codriving_native_inputs_v1'
    dt_seconds: float = .2
    history_steps: int = 11
    source_self_radius_m: float = 1.4
    receiver_self_radius_m: float = 3.
    input_frames: int = 5
    skip_frames: int = 1
    output_points: int = 10
    time_binding: str = 'v2xverse_saved_frames_0p2s_v1'

    def __post_init__(self):
        if self.version != 'codriving_native_inputs_v1':
            raise ValueError('unknown native input spec version')
        for name in ('dt_seconds','source_self_radius_m','receiver_self_radius_m'):
            value=getattr(self,name)
            if type(value) not in (int,float) or not np.isfinite(value) or value<=0:
                raise ValueError('positive finite '+name+' required')
        for name,minimum in (('history_steps',2),('input_frames',1),('skip_frames',1),('output_points',1)):
            if type(getattr(self,name)) is not int or getattr(self,name)<minimum:
                raise ValueError('invalid '+name)
        if not isinstance(self.time_binding,str) or not self.time_binding.strip():
            raise ValueError('explicit capture time binding required')

    def to_dict(self):
        return asdict(self)


def _rotation(m):
    values=np.asarray([m[k] for k in ('x','y','theta','lidar_pose_x','lidar_pose_y')],float)
    if not np.isfinite(values).all():raise ValueError('finite current localization required')
    angle=float(m['theta'])-np.pi/2
    c,s=np.cos(angle),np.sin(angle)
    return np.array([[c,-s],[s,c]]),angle


def _boxes(boxes):
    b=np.asarray(boxes,dtype=float)
    if b.shape==(0,):b=b.reshape(0,7)
    if b.ndim!=2 or b.shape[1]!=7 or not np.isfinite(b).all() or np.any(b[:,3:6]<=0):
        raise ValueError('finite Nx7 boxes with positive dimensions required')
    return b.copy()


def sensor_boxes_to_world(boxes, measurement):
    """Same planar transform as upstream x_to_world; no extra 1.3 m shift."""
    b=_boxes(boxes);r,yaw=_rotation(measurement)
    b[:,:2]=b[:,:2]@r.T+[measurement['lidar_pose_x'],measurement['lidar_pose_y']]
    b[:,6]=np.arctan2(np.sin(b[:,6]+yaw),np.cos(b[:,6]+yaw))
    # z is already world height in probe_v2xverse_detector.native_points.
    return b


def world_boxes_to_actor(boxes, measurement):
    b=_boxes(boxes);r,yaw=_rotation(measurement)
    b[:,:2]=(b[:,:2]-[measurement['x'],measurement['y']])@r
    b[:,1]*=-1
    b[:,6]=np.arctan2(np.sin(yaw-b[:,6]),np.cos(yaw-b[:,6]))
    return b


def source_to_receiver_transform(source_measurement,receiver_measurement):
    """Proper SE(2) between two actor forward/left frames at the same epoch."""
    rs,_=_rotation(source_measurement);rr,_=_rotation(receiver_measurement)
    reflection=np.diag([1.,-1.]);t=np.eye(3)
    t[:2,:2]=reflection@rr.T@rs@reflection
    delta=np.array([source_measurement['x']-receiver_measurement['x'],
                    source_measurement['y']-receiver_measurement['y']])
    t[:2,2]=reflection@rr.T@delta
    return t


def filter_source_self(world_boxes,source_measurement,spec):
    """Current localization radius proxy; experiment values live in spec.

    Receiver is kept in the complete provider context, excluded as a returned
    target later. A target outside receiver's ROI still belongs to context.
    """
    b=_boxes(world_boxes);_rotation(source_measurement)
    return np.linalg.norm(b[:,:2]-[source_measurement['x'],source_measurement['y']],axis=1)>spec.source_self_radius_m


def sample_binding(scene,receiver,start_frame,spec):
    if (not isinstance(scene,str) or not scene or '/' in scene or '\\' in scene
        or not isinstance(receiver,str) or re.fullmatch(r'ego_vehicle_[0-9]+',receiver) is None
        or type(start_frame) is not int or start_frame<0):
        raise ValueError('explicit scene, vehicle and nonnegative start frame required')
    decision=start_frame+(spec.input_frames-1)*spec.skip_frames
    return dict(scene=scene,receiver=receiver,start_frame=start_frame,decision_frame=decision,
        decision_time=decision*spec.dt_seconds,
        input_frames=list(range(start_frame,decision+1,spec.skip_frames)),
        label_frames=[decision+i*spec.skip_frames for i in range(1,spec.output_points+1)],
        execution_spec=spec.to_dict())


def resolve_planner_sample(dataset,index,spec):
    """Resolve nested torch Subsets without importing torch or dropping identity."""
    index=operator.index(index)
    if index<0:raise ValueError('nonnegative sample index required')
    while hasattr(dataset,'indices') and hasattr(dataset,'dataset'):
        index=operator.index(dataset.indices[index]);dataset=dataset.dataset
    for attribute,expected in (('input_frame',spec.input_frames),('skip_frames',spec.skip_frames),('output_points',spec.output_points)):
        if hasattr(dataset,attribute) and getattr(dataset,attribute)!=expected:
            raise ValueError('planner sampling differs from execution spec')
    scene,frame=dataset.route_frames[index]
    ego=Path(scene['ego'])
    return sample_binding(ego.parent.name,ego.name,operator.index(frame),spec)


def validate_context_binding(sample,context):
    spec=NativeInputSpec(**sample['execution_spec'])
    if sample!=sample_binding(sample['scene'],sample['receiver'],sample['start_frame'],spec):
        raise ValueError('sample start/input/decision/label frames are inconsistent')
    if (context['scene']!=sample['scene'] or context['receiver']!=sample['receiver']
        or context['source']==context['receiver'] or context['g']!=sample['decision_frame']
        or context['decision_time']!=sample['decision_time']
        or context['coordinate_frame']!='source_actor_at_t' or context['axes']!='x_forward_y_left'
        or context['execution_spec']!=sample['execution_spec']):
        raise ValueError('scene/source/decision time/coordinate context mismatch')


def raster_for_sample(sample,context,*,tool,target_ids,predictor=None,predictor_version=None):
    """Bound offline replay connector, NOT a substitute for paid receipt/ledger.

    A real F predictor is called once on the complete source context before
    selection. Test fixtures may inject predictors but are not model evidence.
    """
    from planning.codriving_causal_context import records_for_targets,to_mtr_window
    from planning.codriving_pf_bev import rasterize_pf
    from tools.task_spec import _version_pair
    validate_context_binding(sample,context)
    if tool not in ('P','F','PF'):raise ValueError('expected P/F/PF probe tool')
    prediction=None
    if tool in ('F','PF'):
        if not callable(predictor):raise ValueError('explicit full-context predictor required for F')
        _version_pair(predictor_version)
        window=to_mtr_window(context)
        supplied=copy.deepcopy(window)
        prediction=predictor(supplied)
        if set(supplied)!=set(window) or any(not np.array_equal(supplied[k],window[k]) for k in window):
            raise ValueError('predictor mutated complete source context')
        count=len(window['track_ids'])
        if (not np.array_equal(prediction['track_ids'],window['track_ids'])
            or np.shape(prediction['states'])!=(count,7)
            or not np.allclose(prediction['states'],window['states'][:,-1])
            or np.shape(prediction['means'])!=(count,6,50,2)
            or np.shape(prediction['scores'])!=(count,6)
            or np.shape(prediction['model_used'])!=(count,)
            or np.asarray(prediction['model_used']).dtype.kind!='b'
            or not np.isfinite(prediction['means']).all() or not np.isfinite(prediction['scores']).all()):
            raise ValueError('full-context predictor target/state/output mismatch')
    records=records_for_targets(context,target_ids)
    forecasts=[]
    if prediction is not None:
        index={int(ident):i for i,ident in enumerate(context['track_ids'])}
        for record in records:
            i=index[int(record['track'])]
            ref=dict(record['refs'][-1],field_kind='forecast',producer_version=dict(predictor_version))
            forecasts.append(dict(record,refs=record['refs']+[ref],
                forecast=np.asarray(prediction['means'])[i].tolist(),
                forecast_scores=np.asarray(prediction['scores'])[i].tolist(),
                forecast_times=(np.arange(1,51)*.1).tolist(),
                model_used=bool(prediction['model_used'][i])))
    spec=NativeInputSpec(**sample['execution_spec'])
    transform=source_to_receiver_transform(context['source_measurement'],context['receiver_measurement'])
    raster=rasterize_pf(records if tool in ('P','PF') else [],forecasts,transform,
        future_times=np.arange(1,spec.output_points+1)*spec.skip_frames*spec.dt_seconds,
        time_binding=spec.time_binding,decision_time=sample['decision_time'])
    raster['sample_key']={key:sample[key] for key in ('scene','receiver','decision_frame')}
    raster['execution_spec']=spec.to_dict()
    raster['probe_scope']='offline_preparation_not_paid_receipt'
    raster['audit']['complete_predictor_context_ids']=list(context['track_ids']) if prediction is not None else []
    return raster


def attach_context_batch(batch,dataset,indices,contexts,*,tool,target_ids,predictor=None,predictor_version=None):
    """Offline CoDriving integration using each real Dataset/Subset sample key.

    Preserves official fields and exposes non-null identities for metric rows.
    Production paid evidence continues to use records_from_ledger separately.
    """
    from planning.codriving_pf_bev import attach_pf_sidecar
    if not contexts or len(indices)!=len(contexts) or len(target_ids)!=len(contexts):
        raise ValueError('one context and target list per explicit dataset sample required')
    rasters=[]
    for index,context,targets in zip(indices,contexts,target_ids):
        spec=NativeInputSpec(**context['execution_spec'])
        sample=resolve_planner_sample(dataset,index,spec)
        rasters.append(raster_for_sample(sample,context,tool=tool,target_ids=targets,
            predictor=predictor,predictor_version=predictor_version))
    attached=attach_pf_sidecar(batch,rasters)
    attached['toolv2x_sample_keys']=[r['sample_key'] for r in rasters]
    return attached


def validate_recording_split(training_samples,evaluation_samples):
    """Reject same physical recording across roles, including different egos."""
    def scenes(samples):
        values=[r['scene'] for r in samples]
        if any(not isinstance(v,str) or not v.strip() for v in values):
            raise ValueError('recording identities required')
        return set(values)
    if scenes(training_samples)&scenes(evaluation_samples):
        raise ValueError('physical recording overlaps training and evaluation')
