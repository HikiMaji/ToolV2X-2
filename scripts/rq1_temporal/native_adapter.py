"""CPU adapters around the frozen local tracker, wire format and central front end.

Offline GT/attack construction is completed before replay. replay_online accepts
only public scans and frozen injected detections; truth attachment follows replay.
"""
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
from . import data

NATIVE = data.EVIDENCE/'mate_continuous_occurrence_2026_10_08'
OLD = data.ROOT/'.worktrees/oqea-h1-2026-10-30/scripts/oqea_joint'
STATIC = data.ROOT/'.worktrees/rq1-static-2026-11-10/scripts/rq1_static_trial'
CHECKPOINT = '84e37c565a9af221b925eaaa89dd12e276f062df3974b348e34b0e0215ae9921'


def imports():
    for path in (NATIVE,OLD,STATIC):
        if str(path) not in sys.path:
            sys.path.append(str(path))
    import native_runtime as native
    import run_native as original
    import recording_inputs as recording
    import extract as static
    return native, original, recording, static


def recording_spec(parent):
    inventory=json.loads((data.EVIDENCE/'dataset_inventory_2026_11_04/inventory.json').read_text())
    matches=[r for r in inventory['raw'] if r['split']+'/'+r['recording']==parent]
    if not matches:
        raise FileNotFoundError('not present in frozen inventory '+parent)
    # The inventory may contain duplicate asset copies; use the declared first copy.
    root=Path(matches[0]['path']); ids=sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.lstrip('-').isdigit())
    scene=parent.split('/')[1]
    detections=(NATIVE/'detections'/scene if parent.startswith('test/') else data.EVIDENCE/'oqea_expanded_test_2026_10_16/detections'/scene)
    frame_sets=[{int(p.stem.split('_')[0]) for p in detections.glob('*_'+str(sid)+'.npz')} for sid in ids]
    if not ids or any(s!=frame_sets[0] for s in frame_sets) or not frame_sets[0]:
        raise ValueError('frozen detection source/frame coverage mismatch '+parent)
    frames=sorted(frame_sets[0])
    if any(b-a!=2 for a,b in zip(frames,frames[1:])):
        raise ValueError('nonadjacent detection frames')
    return dict(parent=parent,source_ids=ids,root=str(root),detections=str(detections),frames=frames)


def preprocess_new(out, spec):
    """One PCD read per scan for missing FOV and (fit only) all GT echo counts."""
    native, original, recording, _=imports(); out=Path(out)
    destination=out/'parents'/spec['parent'].replace('/','__')/'scans.jsonl.gz'
    if destination.exists() and (destination.parent/'provenance.json').exists():
        return destination
    if destination.exists():
        # The atomic scan cache is complete; recover only the missing provenance boundary.
        for _ in data.read_rows(destination):
            pass
        data.atomic_json(destination.parent/'provenance.json',dict(spec=spec,recovered_scan_cache=True,
                         checkpoint_sha256=CHECKPOINT,echo_supervision='clean fit GT OBB raw return proxy'))
        return destination
    ids=spec['source_ids']; scene=spec['parent'].split('/')[1]
    fov_path=data.EVIDENCE/'mate_coverage_correction_2026_10_08/native_corrected'/(scene+'.jsonl')
    cached=iter(data.read_rows(fov_path)) if fov_path.exists() else None
    estimator=native.FastRayTraceBevLidarFovEstimator(z_min=-3,z_max=3)
    counts=Counter(); provenance=[]
    with data.atomic_rows(destination) as write:
        for index,frame in enumerate(spec['frames']):
            t=index*.1; old=next(cached,None) if cached is not None else None
            if cached is not None and (old is None or old['frame']!=frame):
                raise ValueError('FOV cache frame mismatch')
            scans=[dict(source_id=sid,pcd_path=str(Path(spec['root'])/str(sid)/('%06d.pcd'%frame))) for sid in ids]
            try:
                gt=recording._gt_frame(dict(scans=scans))
            except OSError as exc:
                gt=dict(status='GT_UNAVAILABLE',available=False,reason=str(exc),boxes=[])
            messages=[]; echo={}
            for scan in scans:
                sid=scan['source_id']; npz=Path(spec['detections'])/('%06d_%s.npz'%(frame,sid))
                with np.load(npz,allow_pickle=False) as c:
                    if str(c['checkpoint_sha256'].item())!=CHECKPOINT:
                        raise ValueError('checkpoint mismatch '+str(npz))
                    pose=c['lidar_pose'].tolist()
                    provenance.append(dict(data.source_record(npz),raw_pcd_sha256=str(c['raw_pcd_sha256'].item()),checkpoint_sha256=CHECKPOINT,
                                           annotation=data.source_record(Path(scan['pcd_path']).with_suffix('.yaml')) if Path(scan['pcd_path']).with_suffix('.yaml').exists() else None))
                points=None
                if cached is None or data.SPLITS[spec['parent']]=='fit':
                    try:
                        points=original.load_points(Path(scan['pcd_path'])); counts['pcd_read']+=1
                    except (OSError,ValueError,AssertionError) as exc:
                        if cached is None:
                            raise RuntimeError('FOV cannot be computed '+str(exc))
                        counts['pcd_missing']+=1
                if cached is not None:
                    boundary=old['fov_boundaries'][str(sid)]
                else:
                    ref=original.ref_from_pose(np.asarray(pose),t); calib=native.LidarCalibration(ref)
                    pc=native.LidarData(t,frame,native.PointMatrix3D(points@original.S,calib),calib,sid,n_features=3)
                    boundary=np.asarray(estimator(pc,in_global=True).boundary).tolist()
                if data.SPLITS[spec['parent']]=='fit' and gt['available'] and points is not None:
                    echo[str(sid)]=data.obb_counts(data.points_world(points,pose,recording.rotation),gt['boxes'])
                ref=original.ref_from_pose(np.asarray(pose),t)
                r=original.S@recording.rotation(pose[3:])@original.S
                messages.append(dict(source_id=sid,frame=frame,timestamp=t,pose_xyz=ref.x.tolist(),yaw=float(np.arctan2(r[1,0],r[0,0])),tracks=[],fov_boundary=boundary))
            write(dict(frame=frame,index=index,timestamp=t,messages=messages,gt=gt,echo=echo))
        if cached is not None and next(cached,None) is not None:
            raise ValueError('extra FOV frame')
    data.atomic_json(destination.parent/'provenance.json',dict(spec=spec,counts=dict(counts),detections=provenance,
                     fov_source=data.source_record(fov_path) if cached is not None else 'native PCD FOVEstimator',
                     echo_supervision='clean fit GT OBB raw return proxy; no detection ROI'))
    return destination


def legacy_echo(out, job):
    _,original,recording,_=imports(); out=Path(out); destination=out/'echo'/(job['job_id']+'.jsonl.gz')
    if destination.exists():
        return destination
    rows=list(data.read_rows(out/'legacy'/(job['job_id']+'.jsonl.gz')))
    wanted=defaultdict(set)
    for r in rows:
        if r.get('query_gt_id') is not None:
            wanted[r['frame']].add(r['query_gt_id'])
    gt_path=data.EVIDENCE/'oqea_h1_retrain_2026_10_30_envfix1/run_001/offline_gt/offline_gt.json'
    ground=json.loads(gt_path.read_text()); gt=next(r for r in ground['recordings'] if r['recording']==job['parent'])
    byframe={f['frame']:f for f in gt['frames']}; del ground
    inventories=json.loads((data.EVIDENCE/'dataset_inventory_2026_11_04/inventory.json').read_text())['raw']
    raw=Path(next(r['path'] for r in inventories if r['split']+'/'+r['recording']==job['parent']))
    config=json.loads(Path(job['config']).read_text())
    with data.atomic_rows(destination) as write:
        for packet in data.read_rows(config['sender_path']):
            frame=packet['frame']; ground=byframe.get(frame,dict(available=False,boxes=[]))
            boxes=[b for b in ground['boxes'] if b['gt_id'] in wanted[frame]]
            if not boxes:
                continue
            for msg in packet['messages']:
                sid=msg['source_id']; pcd=raw/str(sid)/('%06d.pcd'%frame); counts=None
                if ground['available']:
                    try:
                        # Original YAML extrinsics, not the already-flipped message pose.
                        pose=recording._read_yaml(pcd.with_suffix('.yaml'))['lidar_pose']
                        pose=np.asarray(pose,float); points=original.load_points(pcd)
                        counts=data.obb_counts(data.points_world(points,pose,recording.rotation),boxes)
                    except (OSError,ValueError,AssertionError,KeyError):
                        counts=None
                for gid in sorted(wanted[frame]):
                    count=None if counts is None else counts.get(gid)
                    write(dict(parent=job['parent'],frame=frame,index=packet['index'],timestamp=packet['timestamp'],
                               source_id=sid,gt_id=gid,gt_available=ground['available'],pcd_available=counts is not None,
                               count=count,Z=-1 if count is None else int(count>0)))
    return destination


def entity_box(center, yaw=0., bottom=None, role='target'):
    center=np.asarray(center,float).copy()
    if bottom is not None:
        center[2]=bottom+.8
    c,s=np.cos(yaw),np.sin(yaw); rotation=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
    xyz=center.copy(); xyz[2]-=.8
    # Native geometry and associate_gt both use bottom translation for tracks.
    local=np.array([[2.25,.9,1.6],[-2.25,.9,1.6],[-2.25,-.9,1.6],[2.25,-.9,1.6],
                    [2.25,.9,0],[-2.25,.9,0],[-2.25,-.9,0],[2.25,-.9,0]])
    return dict(xyz=xyz.tolist(),hwl=[1.6,1.8,4.5],yaw=float(yaw),rotation=rotation.tolist(),
                where_is_t='bottom',corners=(local@rotation.T+xyz).tolist(),role=role)


def compatible(a,b,recording):
    return (np.linalg.norm(np.asarray(a['xyz'])[:2]-np.asarray(b['xyz'])[:2])<=3 or
            recording._polygon(a).intersects(recording._polygon(b)))


def construct_attack(job, scans):
    """At most 64 deterministic proposals; no defense output enters this function."""
    _,_,recording,static=imports()
    from scripts.rq1_real_cue import geometry
    if len(scans)<80:
        return dict(status='UNREALIZABLE',reason='fewer than 80 frozen frames',attempted=0)
    ids=[m['source_id'] for m in scans[0]['messages']]; k=job['attack_k']; normal=ids[k]; controlled=ids[:k]
    active_start=15 if job['family']=='F3' else 20
    if any(not s['gt']['available'] for s in scans[active_start:60]):
        return dict(status='UNREALIZABLE',reason='GT unavailable in construction horizon',attempted=0)
    anchor_boxes=sorted(scans[20]['gt']['boxes'],key=lambda b:b['gt_id'])
    proposals=[(b,float(distance),angle) for b in anchor_boxes for distance in (6,10,14) for angle in np.arange(8)*np.pi/4]
    order=np.random.RandomState(0).permutation(len(proposals))[:64]
    failures=Counter()
    for number,p in enumerate(order,1):
        anchor,distance,angle=proposals[p]; offset=np.array([distance*np.cos(angle),distance*np.sin(angle),0.])
        entities=[]; valid=True
        for index,scan in enumerate(scans[:80]):
            lookup={b['gt_id']:b for b in scan['gt']['boxes']}
            b=(lookup.get(anchor['gt_id']) if 20<=index<60 else anchor) if job['family']=='F2' else anchor
            if b is None:
                valid=False; failures['anchor_missing']+=1; break
            if job['family']=='F2' and index>=60:
                prev={x['gt_id']:x for x in scans[58]['gt']['boxes']}.get(anchor['gt_id'])
                last={x['gt_id']:x for x in scans[59]['gt']['boxes']}.get(anchor['gt_id'])
                if prev is None or last is None:
                    valid=False;break
                center=np.asarray(last['xyz'])+offset+(index-59)*(np.asarray(last['xyz'])-np.asarray(prev['xyz']))
                bottom=center[2]-last['hwl'][0]/2; yaw=last['yaw']
            else:
                center=np.asarray(b['xyz'])+offset; bottom=b['xyz'][2]-b['hwl'][0]/2; yaw=b['yaw'] if job['family']=='F2' else 0.
            target=entity_box(center,yaw,bottom)
            frame_entities=[target]
            if job['family']=='F3':
                sensor=np.asarray(scans[20]['messages'][k]['pose_xyz']); oc=np.asarray(target['xyz']).copy()
                oc[:2]=(sensor[:2]+np.asarray(target['xyz'][:2]))/2
                frame_entities.append(entity_box(oc,bottom=target['xyz'][2],role='occluder'))
            entities.append(frame_entities)
        if not valid:
            continue
        blockage=0
        for index in range(15 if job['family']=='F3' else 20,60):
            scan=scans[index]; active=entities[index] if index>=20 else entities[index][1:]
            for entity in active:
                if any(compatible(entity,g,recording) for g in scan['gt']['boxes']):
                    valid=False; failures['GT_compatible']+=1; break
                for sid in controlled:
                    msg=next(m for m in scan['messages'] if m['source_id']==sid)
                    _,_,eligible=static.source_features(dict(entity,Pxy_trace=0.),msg,None,scan['timestamp'])
                    if not eligible:
                        valid=False; failures['no_report_opportunity']+=1;break
            if len(active)>1 and compatible(active[0],active[1],recording):
                valid=False; failures['entity_compatible']+=1
            if not valid:
                break
            if index>=20 and job['family'] in ('F2','F3'):
                blocker=(next((g for g in scan['gt']['boxes'] if g['gt_id']==anchor['gt_id']),None) if job['family']=='F2' else entities[index][1])
                if blocker is None:
                    valid=False;break
                if 'corners' not in blocker:
                    h,w,l=blocker['hwl']; local=np.array([[l/2,w/2,h/2],[-l/2,w/2,h/2],[-l/2,-w/2,h/2],[l/2,-w/2,h/2],[l/2,w/2,-h/2],[-l/2,w/2,-h/2],[-l/2,-w/2,-h/2],[l/2,-w/2,-h/2]])
                    blocker=dict(blocker,corners=(local@np.asarray(blocker['rotation']).T+blocker['xyz']).tolist())
                target=dict(entities[index][0],id=-100); blocker=dict(blocker,id=-101)
                poses={normal:next(m['pose_xyz'] for m in scan['messages'] if m['source_id']==normal)}
                cue,_=geometry.frame_cues([target,blocker],poses)
                blockage+=cue[-100][normal]['C']>=1/3
        if valid and job['family'] in ('F2','F3') and blockage<32:
            valid=False;failures['blockage_under_80pct']+=1
        if valid:
            return dict(status='VALID',attempted=number,anchor_gt_id=anchor['gt_id'],controlled_sources=controlled,
                        normal_source=normal,entities=entities,blockage_frames=blockage,failure_counts=dict(failures))
    return dict(status='UNREALIZABLE',reason='64-or-fewer frozen candidates exhausted',attempted=len(order),failure_counts=dict(failures))


def injection_at(attack,index):
    if attack is None or attack.get('status')!='VALID':
        return []
    entities=attack['entities'][index]
    if 20<=index<60:
        return entities
    if 15<=index<20:
        return [e for e in entities if e['role']=='occluder']
    return []


def replay_online(job, spec, public_scans, attack=None):
    """Only scans without GT/echo reach here. Queries precede central update."""
    native,original,_,static=imports()
    import quaternion
    from avstack.modules.tracking.tracks import TrackEncoder, TrackDecoder, TrackBase
    from avstack.geometry.fov import Polygon
    from scripts.rq1_real_cue.run import extract_frame
    # Match a fresh per-job process so IDs do not depend on which jobs were resumed.
    TrackBase.ID_counter=0
    ids=spec['source_ids']; local={sid:native.BasicBoxTracker3D(check_reference=False) for sid in ids}
    fused=native.MeasurementBasedMultiTracker(native.BasicBoxTracker3D(run_clustering=True)); _,hook=original.config_model()
    previous=[]; counts={sid:{} for sid in ids}; history={}
    for scan in public_scans:
        frame,index,t=scan['frame'],scan['index'],scan['timestamp']; packet=copy.deepcopy(scan); tracks={}; dets={}; fovs={};agents={};matches={}
        queries=static.predict_queries(previous,t)
        for message in packet['messages']:
            sid=message['source_id']; npz=Path(spec['detections'])/('%06d_%s.npz'%(frame,sid))
            with np.load(npz,allow_pickle=False) as cache:
                ref=original.ref_from_pose(cache['lidar_pose'],t); ds=original.make_detections(cache,ref,frame,t,sid)
            additions=[]
            if attack is not None and sid in attack['controlled_sources']:
                for entity in injection_at(attack,index):
                    box=native.Box3D(native.Position(np.asarray(entity['xyz']),native.GlobalOrigin3D),
                         native.Attitude(quaternion.from_rotation_matrix(np.asarray(entity['rotation']).T),native.GlobalOrigin3D),entity['hwl'],where_is_t='bottom',obj_type='car')
                    additions.append(native.BoxDetection(data=box,noise=np.array([1,1,1,.25,.25,.25])**2,
                                     source_identifier=str(sid),reference=native.GlobalOrigin3D,obj_type='car',score=1.))
            ds=native.DataContainer(frame,t,list(ds)+additions,str(sid))
            sender_tracks=local[sid](detections=ds,platform=native.GlobalOrigin3D,check_reference=False)
            message['tracks']=[json.dumps(tr,cls=TrackEncoder) for tr in sender_tracks]
            restored=[json.loads(w,cls=TrackDecoder) for w in message['tracks']]
            fresh,_=static.fresh_tracks(restored,counts[sid],t);matches[sid]=static.associate_fresh(queries,fresh)
            tracks[sid]=native.DataContainer(frame,t,restored,str(sid))
            converted=[native.BoxDetection(data=tr.box,noise=np.array([1,1,1,.25,.25,.25])**2,source_identifier=str(sid),reference=native.GlobalOrigin3D,obj_type=tr.obj_type,score=1.) for tr in restored]
            dets[sid]=native.DataContainer(frame,t,converted,str(sid))
            fovs[sid]=Polygon(np.asarray(message['fov_boundary']),native.GlobalOrigin3D,frame,t)
            agents[sid]=SimpleNamespace(position=native.Position(np.asarray(message['pose_xyz']),native.GlobalOrigin3D))
        events=[]
        for qi,q in enumerate(queries):
            geometry=original.track_json(q); geometry['Pxy_trace']=float(np.trace(q.P[:2,:2]))
            e=dict(id=int(q.ID),query_geometry=geometry,U=[],X=[],G=[],unsupported_positive=False)
            for message in packet['messages']:
                sid=message['source_id']; key=(int(q.ID),sid); x,g,eligible=static.source_features(geometry,message,history.get(key),t)
                supported=qi in matches[sid]; u=int(supported) if eligible else -1
                e['U'].append(u);e['X'].append(x if eligible else None);e['G'].append(g if eligible else None)
                e['unsupported_positive'] |= supported and not eligible
                if u>=0:
                    history[key]=dict(U=u,timestamp=t)
            events.append(e)
        central=fused(dets,fovs);hook(agents=agents,fov_agents=fovs,tracks_agents=tracks,tracks_fused=central)
        outputs={int(tr.ID):original.track_json(tr) for tr in central}; previous_ids={int(tr.ID) for tr in previous}
        result=[]
        for e in events:
            target=outputs.get(e['id']); e.update(output_geometry=target,output_present=target is not None,newborn=False,
                identity_ok=bool(target is not None and np.linalg.norm(np.asarray(e['query_geometry']['xyz'])[:2]-np.asarray(target['xyz'])[:2])<=3))
            result.append(e)
        for tid,target in outputs.items():
            if tid not in previous_ids:
                result.append(dict(id=tid,query_geometry=None,output_geometry=target,output_present=True,newborn=True,identity_ok=False,U=[-1]*len(ids),X=[None]*len(ids),G=[None]*len(ids)))
        trusted=set() if hook.tracks_trusted is None else {int(tr.ID) for tr in hook.tracks_trusted}
        for e in result:
            tid=e['id']; dist=None if hook.trust_tracks is None or tid not in hook.trust_tracks.keys() else hook.trust_tracks[tid]
            e.update(key=[job['job_id'],frame,tid],job_id=job['job_id'],frame=frame,index=index,timestamp=t,source_ids=ids,native_adopted=tid in trusted,native_mean=None if dist is None else float(dist.mean))
        cues,_=extract_frame(result,packet,ids)
        byid={r['id']:r for r in cues}
        for e in result:
            yield dict(e,**byid[e['id']])
        previous=list(central)


def attach_labels(events, scans, job, attack=None, diagnostics=None):
    _,_,recording,_=imports(); byframe={s['frame']:s for s in scans}; seen=defaultdict(set)
    # Frame grouping retains one-to-one matches separately for query and output.
    import itertools
    for frame,group in itertools.groupby(data.assign_epochs(events),key=lambda r:r['frame']):
        rows=list(group); scan=byframe[frame]; ground=scan['gt']; index=scan['index']; values={}
        for side in ('query','output'):
            candidates=[r for r in rows if r.get(side+'_geometry') is not None]
            labels=recording.associate_gt([r[side+'_geometry'] for r in candidates],ground['boxes'],ground['available'])
            fake_candidates=[]; fake_rows=[]
            for row,label in zip(candidates,labels):
                values[(row['id'],side)]=dict(label,role=None,reason='GT_MATCH' if label['truth']==1 else 'UNMATCHED')
                if label['any_gt_compatible'] is False and attack is not None and 15<=index<80:
                    fake_rows.append(row);fake_candidates.append(row[side+'_geometry'])
            if fake_rows:
                entities=attack['entities'][index]
                if index<20:
                    entities=[e for e in entities if e['role']=='occluder']
                fake_gt=[dict(e,gt_id=1 if e['role']=='target' else 2) for e in entities]
                associations=recording.associate_gt(fake_candidates,fake_gt,True)
                for row,candidate,label in zip(fake_rows,fake_candidates,associations):
                    key=(job['job_id'],row['id'],row['epoch']); compatible_roles=[e['role'] for e in entities if compatible(candidate,e,recording)]
                    role='target' if label['gt_id']==1 else 'occluder' if label['gt_id']==2 else None
                    valid=role is not None and len(compatible_roles)==1
                    if index>=60:
                        valid=valid and role in seen[key]
                    if valid:
                        values[(row['id'],side)]=dict(truth=0,gt_id=None,any_gt_compatible=False,role=role,reason='INJECTED_ENTITY' if index<60 else 'STOPPED_ENTITY_BOUNDED_EXTRAPOLATION')
                        if index<60:
                            seen[key].add(role)
                    elif len(compatible_roles)>1:
                        values[(row['id'],side)]['reason']='INJECTED_ROLE_AMBIGUITY'
        for row in rows:
            q=values.get((row['id'],'query'),dict(truth=-1,gt_id=None,role=None,reason='NO_QUERY'))
            o=values.get((row['id'],'output')); role=q['role'] if row['query_present'] else (None if o is None else o['role'])
            row.update({k:job[k] for k in ('parent','kind','family','attack_k','split')})
            row.update(query_truth=q['truth'],query_gt_id=q['gt_id'],query_label_reason=q['reason'],
                       output_truth=None if o is None else o['truth'],output_gt_id=None if o is None else o['gt_id'],attack_role=role,
                       label_conflict=bool(o and q['truth'] in (0,1) and o['truth'] in (0,1) and q['truth']!=o['truth']),
                       gt_identity_conflict=bool(o and q['gt_id'] is not None and o['gt_id'] is not None and q['gt_id']!=o['gt_id']))
            if o is not None and q['role'] and o['role'] and q['role']!=o['role']:
                row.update(query_truth=-1,output_truth=-1,attack_role=None,label_conflict=True,query_label_reason='QUERY_OUTPUT_ROLE_CONFLICT')
            if diagnostics is not None and attack is not None:
                if row['query_truth']==0:
                    diagnostics[str(row['attack_role'])+'_query_rows']+=1
                if job['family']=='F3' and row['query_truth']==0 and row['attack_role']=='target' and 20<=index<60:
                    sid=attack['normal_source']; j=row['source_ids'].index(sid)
                    blocker=row.get('main_blocker_ids',[None]*len(row['source_ids']))[j]
                    blocked=values.get((blocker,'query'),{}).get('role')=='occluder'
                    if blocked and not row['C_missing'][j] and row['C'][j]>=1/3:
                        diagnostics['public_occlusion_frames'].add(frame)
            gid=row['query_gt_id']; echo=scan['echo']
            row['Z']=[int(echo[str(sid)][str(gid)]>0) if gid is not None and str(sid) in echo and str(gid) in echo[str(sid)] else -1 for sid in row['source_ids']]
            yield data.compact(row)


def prepare(out):
    out=Path(out); spec=json.loads((out/'manifest.json').read_text())
    if not (out/'native_runtime.json').exists():
        import inspect
        import scipy
        import shapely
        native,_,_,_=imports()
        classes=(native.BasicBoxTracker3D,native.MeasurementBasedMultiTracker,native.FastRayTraceBevLidarFovEstimator,
                 native.ViewBasedPsm,native.TrustUpdater,native.TrustFusionHook)
        files=sorted({inspect.getfile(cls) for cls in classes})
        data.atomic_json(out/'native_runtime.json',dict(executable=sys.executable,python=sys.version,numpy=np.__version__,scipy=scipy.__version__,
                         shapely=shapely.__version__,class_sources=[data.source_record(path) for path in files]))
    for job in spec['jobs']:
        if job['origin']!='legacy':
            continue
        dest=out/'jobs'/job['job_id']; complete=dest/'complete.json'
        if complete.exists():
            continue
        echo={}
        if job['split']=='fit' and job['kind']=='clean':
            path=legacy_echo(out,job)
            echo={(r['frame'],r['source_id'],r['gt_id']):r['Z'] for r in data.read_rows(path)}
        count=0
        if (dest/'rows.jsonl.gz').exists():
            count=sum(1 for _ in data.read_rows(dest/'rows.jsonl.gz'))
        else:
            with data.atomic_rows(dest/'rows.jsonl.gz') as write:
                for row in data.attach_z(data.read_rows(out/'legacy'/(job['job_id']+'.jsonl.gz')),echo):
                    write(row);count+=1
        data.atomic_json(complete,dict(status='COMPLETE',rows=count,origin='legacy'))
        print('prepared',job['job_id'],count,flush=True)
    for parent in data.NEW_PARENTS:
        parent_spec=recording_spec(parent); scan_path=preprocess_new(out,parent_spec); scans=list(data.read_rows(scan_path))
        for job in [j for j in spec['jobs'] if j['parent']==parent]:
            dest=out/'jobs'/job['job_id']; complete=dest/'complete.json'
            if complete.exists():
                continue
            attack=None; used=scans if job['kind']=='clean' else scans[:80]
            try:
                if job['kind']=='attack':
                    frozen=dest/'attack.json'
                    attack=json.loads(frozen.read_text()) if frozen.exists() else construct_attack(job,scans)
                    if not frozen.exists():
                        data.atomic_json(frozen,attack)
                    if attack['status']=='UNREALIZABLE':
                        data.atomic_json(complete,attack);print('unrealizable',job['job_id'],attack['reason'],flush=True);continue
                public=({k:s[k] for k in ('frame','index','timestamp','messages')} for s in used)
                # Complete public output before opening the offline label path.
                online_path=dest/'online.jsonl.gz'
                if not online_path.exists():
                    with data.atomic_rows(online_path) as write:
                        for event in replay_online(job,parent_spec,public,attack):
                            write(event)
                n=0;counts=Counter();diagnostics=Counter();diagnostics['public_occlusion_frames']=set()
                if (dest/'rows.jsonl.gz').exists():
                    for row in data.read_rows(dest/'rows.jsonl.gz'):
                        n+=1;counts['query_truth_'+str(row['query_truth'])]+=1
                else:
                    with data.atomic_rows(dest/'rows.jsonl.gz') as write:
                        for row in attach_labels(data.read_rows(online_path),used,job,attack,diagnostics):
                            write(row);n+=1;counts['query_truth_'+str(row['query_truth'])]+=1
                if job['family']=='F3':
                    # Reconstruct bounded diagnostics after an interrupted pure label stage.
                    if (dest/'rows.jsonl.gz').exists() and n and not diagnostics.get('target_query_rows'):
                        for _ in attach_labels(data.read_rows(online_path),used,job,attack,diagnostics):
                            pass
                occlusion_frames=len(diagnostics.pop('public_occlusion_frames'))
                diagnostics['public_occlusion_frames']=occlusion_frames
                data.atomic_json(complete,dict(status='COMPLETE',rows=n,counts=dict(counts),origin='native',attack_constructed=attack is not None,
                                 actual_construction=dict(diagnostics),
                                 F3_public_blocking_effective=None if job['family']!='F3' else bool(occlusion_frames)))
                print('prepared',job['job_id'],n,flush=True)
            except Exception as exc:
                if not (dest/'error.json').exists():
                    data.atomic_json(dest/'error.json',dict(error=type(exc).__name__+': '+str(exc)))
                raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    prepare(parser.parse_args().out)
