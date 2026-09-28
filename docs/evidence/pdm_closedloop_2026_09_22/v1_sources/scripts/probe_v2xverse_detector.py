#!/usr/bin/env python3
"""Independent single-CAV inference using original V2Xverse detector modules.

Read only local LiDAR + current sensor height. No GT targets, peer input,
tracking, planning, or AP computation. Requires the optional original model env.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np


def native_points(raw, height):
    raw=np.asarray(raw)
    if raw.ndim!=2 or raw.shape[1]!=4 or not np.isfinite(raw).all() or not np.isfinite(height):
        raise ValueError('finite Nx4 points and sensor height required')
    out=np.zeros(raw.shape,dtype=np.float32)
    out[:,0]=raw[:,1];out[:,1]=-raw[:,0];out[:,2:]=raw[:,2:];out[:,2]+=height
    return out


def load_local_input(root,vehicle,frame):
    if type(vehicle) is not int or vehicle<0 or type(frame) is not int or frame<0:
        raise ValueError('explicit nonnegative vehicle/frame required')
    p=Path(root)/('ego_vehicle_%d'%vehicle)
    paths=[p/'lidar'/('%04d.npy'%frame),p/'measurements'/('%04d.json'%frame)]
    raw=np.load(str(paths[0]),allow_pickle=False)
    height=json.loads(paths[1].read_text())['lidar_pose_z']
    return raw,height,[str(p) for p in paths]


def load_detector(args):
    sys.path.insert(0,args.source_root)
    import torch,yaml
    import opencood.utils
    # Reuse installed ABI-compatible compiled overlap extension only. All Python
    # model, voxelization, decoding and NMS code comes from the source root.
    opencood.utils.__path__.append(args.overlap_extension_dir)
    from opencood.models.center_point_codriving import centerpointcodriving
    from opencood.data_utils.pre_processor.sp_voxel_preprocessor import SpVoxelPreprocessor
    from opencood.data_utils.post_processor.voxel_postprocessor import VoxelPostprocessor
    from opencood.utils.pcd_utils import mask_ego_points_v2,shuffle_points
    from opencood.utils.box_utils import corner_to_center
    import opencood.utils.box_overlaps as overlap
    model_dir=Path(args.model_dir)
    config=yaml.load((model_dir/'config.yaml').read_text(),Loader=yaml.Loader)
    np.random.seed(0);torch.manual_seed(0);torch.set_num_threads(4)
    model=centerpointcodriving(config['model']['args'])
    state=torch.load(str(model_dir/'net_epoch_bestval_at16.pth'),map_location='cpu')
    model.load_state_dict(state,strict=True);model.cuda().eval()
    pre=SpVoxelPreprocessor(config['preprocess'],train=False)
    post=VoxelPostprocessor(config['postprocess'],train=False)
    def infer(raw,height):
        # Same three operations/order as original base + intermediate dataset.
        lidar=mask_ego_points_v2(shuffle_points(native_points(raw,height)))
        processed=pre.collate_batch([pre.preprocess(lidar)])
        data=dict(processed_lidar={k:t.cuda() for k,t in processed.items()},
            record_len=torch.tensor([1],device='cuda'),
            pairwise_t_matrix=torch.eye(4,device='cuda').repeat(1,5,5,1,1))
        torch.cuda.synchronize();start=time.perf_counter()
        with torch.no_grad():
            output=model(data);torch.cuda.synchronize();elapsed=time.perf_counter()-start
            classes=[]
            for i in range(3):
                result={'ego':{'cls_preds':output['cls_preds'][:,i:i+1],
                              'reg_preds':output['reg_preds_multiclass'][:,i]}}
                boxes,scores=post.post_process({'ego':{'transformation_matrix':torch.eye(4,device='cuda'),
                                                     'anchor_box':None}},result)
                corners=[] if boxes is None else boxes.cpu().numpy()
                if boxes is not None and (not np.isfinite(corners).all() or not torch.isfinite(scores).all()):
                    raise ValueError('nonfinite detections')
                classes.append(dict(class_index=i,corners=np.asarray(corners).tolist(),
                    boxes_lwh=[] if boxes is None else corner_to_center(corners,order='lwh').tolist(),
                    scores=[] if scores is None else scores.cpu().tolist()))
        return dict(classes=classes,model_seconds=elapsed,points=len(raw),post_ego_mask_points=len(lidar),voxel_count=len(processed['voxel_coords']))
    metadata=dict(checkpoint_parameter_entries=len(state),strict_loading=True,source_root=args.source_root,config=config['postprocess'],compiled_overlap_extension=overlap.__file__,torch_version=torch.__version__)
    return infer,metadata


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',required=True)
    parser.add_argument('--model-dir',required=True)
    parser.add_argument('--sample-root',required=True)
    parser.add_argument('--overlap-extension-dir',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--frames',type=int,nargs='+',default=list(range(10,15)))
    parser.add_argument('--vehicles',type=int,nargs='+',default=[0,1])
    args=parser.parse_args();out=Path(args.output)
    if out.exists():raise ValueError('new output directory required')
    infer,metadata=load_detector(args)
    out.mkdir(parents=True);rows=[]
    for vehicle in args.vehicles:
        for frame in args.frames:
            raw,height,paths=load_local_input(args.sample_root,vehicle,frame)
            result=infer(raw,height)
            classes=result["classes"];elapsed=result["model_seconds"]
            rows.append(dict(vehicle=vehicle,frame_index=frame,timestamp_seconds=None,
                coordinate_frame='original_v2xverse_rotated_sensor_xy_world_height',
                read_paths=paths,used_measurement_fields=['lidar_pose_z'],record_len=[1],
                points=len(raw),post_ego_mask_points=result['post_ego_mask_points'],voxel_count=result['voxel_count'],
                model_seconds=elapsed,classes=classes))
            (out/'detections.json').write_text(json.dumps(rows,indent=2)+'\n')
            print(vehicle,frame,[len(c['boxes_lwh']) for c in classes],flush=True)
    summary=dict(scope='real pretrained independent local detection only; no tracking, GT metric, P/F or planning',
        **metadata,
        single_vehicle_only=True,frame_count=len(rows),capture_time_binding='unknown; frame index not converted to time',
        vehicles=args.vehicles,frames=args.frames,
        vehicle_detection_counts=[len(r['classes'][0]['boxes_lwh']) for r in rows],
        total_model_seconds=sum(r['model_seconds'] for r in rows),timing_scope='forward only, includes cold first call; not end-to-end latency')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':main()
