"""Offline-only quality check of already purchased evidence; no model calls.

GT is used only here, never to change archived online associations or input.
"""
import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path

import numpy as np
from common import v2v4real_meta as M
from planning.structured_inputs import StructuredDriverSpec, _associate


def match_anchors(boxes, truth, ids):
    def track(box):
        return dict(records=dict(anchor=dict(value=dict(box=list(box)))))
    spec = StructuredDriverSpec()
    pairs, ambiguous, _ = _associate([track(b) for b in boxes],
                                      [track(b) for b in truth], spec)
    matches = {i: j for i, j in pairs}
    return [dict(status='ambiguous' if ('local', i) in ambiguous else
                 'matched' if i in matches else 'unmatched',
                 gt_id=int(ids[matches[i]]) if i in matches else None,
                 current_error_m=float(np.linalg.norm(np.asarray(b)[:2]-truth[matches[i], :2]))
                    if i in matches else None) for i, b in enumerate(boxes)]


def score_forecast(paths, scores, target, valid):
    paths, target, valid = np.asarray(paths), np.asarray(target), np.asarray(valid, bool)
    if not valid.any():
        return None
    errors = np.linalg.norm(paths[:, valid]-target[None, valid], axis=-1).mean(-1)
    return dict(top_ADE=float(errors[int(np.argmax(scores))]), minADE=float(errors.min()),
                valid_steps=int(valid.sum()))


def stats(values):
    return dict(n=len(values), mean=float(np.mean(values)), median=float(np.median(values))) if values else dict(n=0)


@lru_cache(maxsize=2048)
def gt_frame(split, g):
    boxes, ids = M.load_gt(split, g)
    return boxes, ids, M.load_pose(split, g)


def aligned_truth(split, g, offset):
    _, _, start, end = M.seq_of(g, split)
    if not start <= g+offset < end:
        return {}
    boxes, ids, pose = gt_frame(split, g+offset)
    origin = gt_frame(split, g)[2]
    aligned = M.boxes_to_ego(M.boxes_to_world(boxes, pose), origin)
    return {int(k): box for k, box in zip(ids, aligned)}


def run(source, out):
    out.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    rows = [r for r in rows if r['checkpoint_step']==500]
    records, pairs, associations = [], [], []
    for row in rows:
        g = row['g']; split = 'train'
        truth, ids, _ = gt_frame(split,g)
        past = [aligned_truth(split,g,k) for k in range(-10,1)]
        future = [aligned_truth(split,g,k) for k in range(5,31,5)]
        # GT co-moving with ego across all available causal history, not current distance alone.
        ego_consistent = []
        for identity in ids:
            centers=[]
            for k in range(-10,1):
                boxes, names, _ = gt_frame(split,g+k)
                ix=np.flatnonzero(names==identity)
                if len(ix): centers.append(float(np.linalg.norm(boxes[ix[0],:2])))
            if len(centers)==11 and max(centers)<=1.5: ego_consistent.append(int(identity))
        for arm in ('Ego','P','F','PF'):
            task_path = Path(row['source_tasks'][arm]['source_task'])
            task = json.loads(task_path.read_text())
            if task['row'].get('physical_split', 'train') != split:
                raise ValueError('unexpected physical split')
            prepared = task['episode']['plans'][-1]['prepared']
            by_source={}
            for entity in prepared['entities']:
                for obs in entity['observations']:
                    by_source.setdefault(obs['source'],[]).append((entity,obs))
            matched={}; arm_records=[]
            for source_name, entries in by_source.items():
                boxes=np.array([o['value']['states'][-1] for _,o in entries])
                matches=match_anchors(boxes,truth,ids)
                for (entity, obs), match in zip(entries,matches):
                    identity=match['gt_id']; value=obs['value']; history=[]
                    if identity is not None:
                        for k in range(11):
                            if value['valid'][k] and identity in past[k]:
                                history.append(float(np.linalg.norm(np.asarray(value['states'][k])[:2]-past[k][identity][:2])))
                    target=np.array([f.get(identity,np.zeros(7))[:2] for f in future])
                    valid=np.array([identity is not None and identity in f for f in future])
                    forecasts=[]
                    for f in entity['forecast_sets']:
                        if f['source']==source_name:
                            forecasts.append(dict(score=score_forecast(f['forecast'],f['forecast_scores'],target,valid),
                                forecast=f['forecast'],scores=f['forecast_scores'], model_used=f['model_used']))
                    r=dict(sample_id=row['sample_id'],g=g,recording=row['recording'],arm=arm,
                        entity_id=entity['entity_id'],online_role=entity['role'],source=source_name,
                        source_role=obs['source_role'],track_handle=obs['anchor_ref']['track_handle'],
                        admitted=entity['tensor_index'] is not None,match=match,
                        ego_consistent_gt=identity in ego_consistent,
                        near_origin=float(np.linalg.norm(boxes[len(arm_records)*0,:2])) if False else
                            float(np.linalg.norm(np.asarray(value['states'][-1])[:2]))<=1.5,
                        history_error=stats(history),forecast_scores=forecasts,
                        target=target.tolist(),valid=valid.tolist())
                    matched[(entity['entity_id'],source_name)]=r
                    arm_records.append(r)
            for entity in prepared['entities']:
                obs=entity['observations']
                if len(obs)==2:
                    a,b=[matched[(entity['entity_id'],o['source'])] for o in obs]
                    associations.append(dict(g=g,arm=arm,entity_id=entity['entity_id'],
                        gt_ids=[a['match']['gt_id'],b['match']['gt_id']],
                        both_matched=all(x['match']['gt_id'] is not None for x in (a,b))))
            local={r['match']['gt_id']:r for r in arm_records if r['source_role']=='local' and r['match']['gt_id'] is not None}
            for r in arm_records:
                if r['source_role']!='remote':continue
                gt_id=r['match']['gt_id']; other=local.get(gt_id)
                r['missing_from_local']=gt_id is not None and other is None
                if other is None or r['ego_consistent_gt']:continue
                if r['match']['current_error_m'] is not None:
                    pair=dict(g=g,arm=arm,gt_id=gt_id,recording=row['recording'],
                        remote_entity=r['entity_id'],local_entity=other['entity_id'],
                        local_current_m=other['match']['current_error_m'],remote_current_m=r['match']['current_error_m'],
                        local_history=other['history_error'],remote_history=r['history_error'],forecasts=[])
                    for a in other['forecast_scores']:
                        for b in r['forecast_scores']:
                            if a['score'] and b['score']:
                                assert other['valid']==r['valid']
                                pair['forecasts'].append(dict(local=a['score'],remote=b['score']))
                    pairs.append(pair)
            records.extend(arm_records)
    summary={}
    for arm in ('P','F','PF'):
        remote=[r for r in records if r['arm']==arm and r['source_role']=='remote' and r['admitted']]
        ps=[p for p in pairs if p['arm']==arm]
        fp=[f for p in ps for f in p['forecasts']]
        ass=[a for a in associations if a['arm']==arm and a['both_matched']]
        summary[arm]=dict(remote_count=len(remote),match_status=dict(Counter(r['match']['status'] for r in remote)),
            ego_consistent=sum(r['ego_consistent_gt'] for r in remote),
            near_origin_unresolved=sum(r['near_origin'] and r['online_role']=='unresolved' for r in remote),
            near_origin_unresolved_ego_consistent=sum(r['near_origin'] and r['online_role']=='unresolved' and r['ego_consistent_gt'] for r in remote),
            missing_from_local_obstacles=sum(r['missing_from_local'] and not r['ego_consistent_gt'] for r in remote),
            checked_online_associations=len(ass),wrong_online_associations=sum(a['gt_ids'][0]!=a['gt_ids'][1] for a in ass),
            paired_current_local=stats([p['local_current_m'] for p in ps]),
            paired_current_remote=stats([p['remote_current_m'] for p in ps]),
            paired_F_local_top_ADE=stats([p['local']['top_ADE'] for p in fp]),
            paired_F_remote_top_ADE=stats([p['remote']['top_ADE'] for p in fp]),
            paired_F_local_minADE=stats([p['local']['minADE'] for p in fp]),
            paired_F_remote_minADE=stats([p['remote']['minADE'] for p in fp]),
            F_remote_better=sum(p['remote']['top_ADE']<p['local']['top_ADE'] for p in fp))
    result=dict(version='offline_evidence_quality_v1',frames=len(rows),physical_split='train',
        source=str(source),scope='Frozen purchased-evidence quality, offline GT matching; no online input changes.',
        matching_spec=StructuredDriverSpec().to_dict(),ego_consistency=dict(radius_m=1.5,causal_frames=11),
        summary=summary,records=records,pairs=pairs,associations=associations)
    (out/'quality.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();run(args.source,args.out)
