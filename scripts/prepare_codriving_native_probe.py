#!/usr/bin/env python3
"""Rebuild corrected P inputs from SAVED detections, without a learned model.

Uses existing AB3DMOT, local causal poses, explicit decision keys and versioned
sampling. This is offline preparation, not paid tool/receipt or planning gain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from planning.codriving_native_inputs import NativeInputSpec,sensor_boxes_to_world,filter_source_self,sample_binding,raster_for_sample
from planning.codriving_causal_context import build_context,records_for_targets,to_mtr_window


def read_localization(root,vehicle,frame):
    if re.fullmatch(r'ego_vehicle_[0-9]+',vehicle) is None or type(frame) is not int or frame<0:
        raise ValueError('explicit vehicle and nonnegative frame required')
    raw=json.loads((root/vehicle/'measurements'/('%04d.json'%frame)).read_text())
    return {key:raw[key] for key in ('x','y','theta','lidar_pose_x','lidar_pose_y')}


def check_detection(record,root,source):
    frame=record['frame_index'];vehicle='ego_vehicle_%d'%record['vehicle']
    expected=[root/source/'lidar'/('%04d.npy'%frame),root/source/'measurements'/('%04d.json'%frame)]
    if (vehicle!=source or record['record_len']!=[1]
        or record['coordinate_frame']!='original_v2xverse_rotated_sensor_xy_world_height'
        or [Path(p).resolve() for p in record['read_paths']]!=[p.resolve() for p in expected]):
        raise ValueError('detector route/source/frame provenance mismatch')


def prepare(args):
    from tracking.lidar_tracks import FixedRateTracker
    root=Path(args.route_root);out=Path(args.output)
    spec=NativeInputSpec(**json.loads(Path(args.spec).read_text())) if args.spec else NativeInputSpec()
    if args.spec is None and '_w0_' not in root.name:
        raise ValueError('default time binding is weather-0 only; explicit spec required')
    if args.source==args.receiver:raise ValueError('source must differ from receiver')
    decisions=sorted(set(args.decisions))
    if len(decisions)!=len(args.decisions) or not decisions or decisions[0]<(spec.input_frames-1)*spec.skip_frames:
        raise ValueError('unique decisions with full planner input history required')
    raw=json.loads(Path(args.detections).read_text())
    if any(re.fullmatch(r'ego_vehicle_[0-9]+',v) is None for v in (args.source,args.receiver)):
        raise ValueError('explicit vehicle identities required')
    source=int(args.source.split('_')[-1])
    local=[r for r in raw if r['vehicle']==source and r['frame_index']<=decisions[-1]]
    local.sort(key=lambda r:r['frame_index'])
    if not local or not set(decisions)<={r['frame_index'] for r in local}:
        raise ValueError('every decision requires a saved source detector frame')
    if out.exists():raise ValueError('new output directory required; preserve old runs')
    out.mkdir(parents=True);(out/'rasters').mkdir()
    tracker=FixedRateTracker(spec.dt_seconds);frames=[];contexts=[];samples=[]
    for record in local:
        check_detection(record,root,args.source);frame=record['frame_index']
        sm=read_localization(root,args.source,frame);rm=read_localization(root,args.receiver,frame)
        cls=record['classes'][0]
        if cls['class_index']!=0:raise ValueError('vehicle class record required')
        world=sensor_boxes_to_world(cls['boxes_lwh'],sm)
        keep=filter_source_self(world,sm,spec)
        tracks=tracker.update(world[keep],np.asarray(cls['scores'])[keep],frame*spec.dt_seconds,frame)
        row=dict(frame=frame,scene=root.name,source=args.source,receiver=args.receiver,
            source_measurement=sm,receiver_measurement=rm,tracks=tracks,
            source_self_excluded=int((~keep).sum()),raw_detection_count=len(world))
        frames.append(row)
        if frame not in decisions:continue
        context=build_context(frames,scene=root.name,source=args.source,receiver=args.receiver,decision_frame=frame,spec=spec)
        targets=[ident for ident in context['track_ids'] if ident not in context['receiver_track_ids']]
        sample=sample_binding(root.name,args.receiver,frame-(spec.input_frames-1)*spec.skip_frames,spec)
        raster=raster_for_sample(sample,context,tool='P',target_ids=targets)
        model_window=to_mtr_window(context)  # shape/mask preparation only, no model invocation
        name='%s_%s_g%04d.npz'%(root.name,args.receiver,frame)
        np.savez_compressed(str(out/'rasters'/name),**{k:raster[k] for k in ('P','F','F_CV','F_valid')})
        samples.append(dict(sample=sample,context_version=context['context_version'],raster='rasters/'+name,
            p_records=records_for_targets(context,targets),raster_audit=raster['audit'],
            context_ids=context['track_ids'],receiver_excluded_ids=context['receiver_track_ids'],
            returned_ids=targets,p_occupancy_pixels=int(np.count_nonzero(raster['P'][0])),
            mtr_context_shape=list(model_window['states'].shape)))
        contexts.append(context)
    summary=dict(scope='corrected_saved_detection_preparation_no_model_or_training',
        scene=root.name,source=args.source,receiver=args.receiver,execution_spec=spec.to_dict(),
        time_origin='recording_relative_frame_times_config_period_not_sensor_timestamp',
        detector_sha256=hashlib.sha256(Path(args.detections).read_bytes()).hexdigest(),
        decisions=decisions,tracking_frames=len(frames),samples=len(samples),
        source_self_excluded=sum(r['source_self_excluded'] for r in frames),
        receiver_target_exclusions=sum(len(r['receiver_excluded_ids']) for r in samples),
        empty_return_samples=sum(not r['returned_ids'] for r in samples),
        empty_current_raster_samples=sum(r['p_occupancy_pixels']==0 for r in samples),
        learned_model_calls=0,training_updates=0)
    for name,value in [('tracking',frames),('contexts',contexts),('samples',samples),('summary',summary)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--route-root',required=True);p.add_argument('--detections',required=True)
    p.add_argument('--source',default='ego_vehicle_1');p.add_argument('--receiver',default='ego_vehicle_0')
    p.add_argument('--decisions',type=int,nargs='+',required=True);p.add_argument('--spec')
    p.add_argument('--output',required=True)
    prepare(p.parse_args())
