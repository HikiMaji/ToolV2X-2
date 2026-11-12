"""Frozen inputs, streaming legacy join, offline echo supervision and epochs."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import numpy as np

ROOT = Path('/root/autodl-tmp/ToolV2X')
EVIDENCE = ROOT / 'docs/evidence'
LEGACY = EVIDENCE / 'rq1_static_trial_2026_11_10/run_001'
FEATURES = EVIDENCE / 'rq1_real_cue_2026_11_11/run_001/features'
RUNTIME = Path('/root/autodl-tmp/ToolV2X_resources/mate_continuous_2026_10_08/runtime/bin/python')
DEFAULT_OUT = EVIDENCE / 'rq1_temporal_2026_11_12/run_001'
SPLITS = {
    **{'train/'+s:'fit' for s in ('2021_08_16_22_26_54','2021_08_22_10_10_40','2021_08_22_10_46_58','2021_08_23_11_22_46','2021_08_24_21_29_28','2021_08_23_22_31_01')},
    **{'train/'+s:'cal' for s in ('2021_08_18_22_16_12','2021_08_20_20_39_00','2021_08_21_22_21_37','2021_08_22_22_30_58')},
    'test/2021_08_22_07_52_02':'cal', 'train/2021_08_23_23_08_17':'eval',
    'test/2021_08_24_07_45_41':'eval','validate/2021_08_20_21_48_35':'eval'}
NEW_PARENTS = ('train/2021_08_23_22_31_01','test/2021_08_22_07_52_02','test/2021_08_24_07_45_41','validate/2021_08_20_21_48_35')
FIELDS = ('key','job_id','id','frame','index','timestamp','source_ids','U','X','C','C_missing','groups',
          'query_present','newborn','output_present','identity_ok','native_adopted','native_mean','parent','kind',
          'family','attack_k','attack_role','split','query_truth','query_gt_id','query_label_reason',
          'output_truth','output_gt_id','label_conflict','gt_identity_conflict','Z','epoch')


def read_rows(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def finite_json(value):
    if isinstance(value, dict):
        return {str(k):finite_json(v) for k,v in value.items()}
    if isinstance(value, (list,tuple,np.ndarray)):
        return [finite_json(v) for v in value]
    if isinstance(value, (float,np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def atomic_json(path, obj):
    path = Path(path)
    if path.exists():
        raise FileExistsError('refusing overwrite '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.partial')
    with temp.open('w') as stream:
        json.dump(finite_json(obj), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)


@contextmanager
def atomic_rows(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError('refusing overwrite '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.partial')
    with gzip.open(temp,'wt') as stream:
        yield lambda row:stream.write(json.dumps(finite_json(row),allow_nan=False)+'\n')
    temp.replace(path)


def source_record(path):
    path = Path(path).resolve(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def code_record():
    cwd = Path(__file__).resolve().parents[2]
    files = sorted(Path(__file__).parent.glob('*.py'))
    files += [cwd/'scripts/rq1_real_cue/geometry.py', cwd/'scripts/rq1_real_cue/run.py']
    native=EVIDENCE/'mate_continuous_occurrence_2026_10_08'
    old=ROOT/'.worktrees/oqea-h1-2026-10-30/scripts/oqea_joint'
    files += [native/'native_runtime.py',native/'run_native.py',old/'recording_inputs.py',old/'message_conditions.py',old/'native_frontend.py',old/'cbm.py',
              ROOT/'.worktrees/rq1-static-2026-11-10/scripts/rq1_static_trial/extract.py']
    return dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=cwd,text=True).strip(),
                files=[source_record(p) for p in files])


def validate_splits(splits):
    if Counter(splits.values()) != Counter(fit=6,cal=5,eval=3):
        raise ValueError('expected six fit, five cal and three eval parents')
    if 'train/2021_08_22_06_43_37' in splits:
        raise ValueError('protected overlapping parent must remain excluded')


def job_id(parent, family='clean', k=0):
    return hashlib.sha256(json.dumps([parent,family,k,0]).encode()).hexdigest()[:16]


def manifest(out):
    out = Path(out); path = out/'manifest.json'; current = code_record()
    if path.exists():
        old = json.loads(path.read_text())
        if old['code']['files'] != current['files']:
            raise RuntimeError('frozen prepare code changed; use a new output directory')
        return old
    old = json.loads((LEGACY/'manifest.json').read_text()); validate_splits(SPLITS)
    jobs = [dict(j,split=SPLITS[j['parent']],family='F0' if j['kind']=='attack' else 'clean',
                 attack_k=1 if j['kind']=='attack' else 0,origin='legacy') for j in old['jobs']]
    if len(jobs) != 39 or len({j['job_id'] for j in jobs}) != 39:
        raise ValueError('legacy 39-job contract')
    for parent in NEW_PARENTS:
        jobs.append(dict(job_id=job_id(parent),parent=parent,split=SPLITS[parent],kind='clean',family='clean',attack_k=0,origin='native'))
        if SPLITS[parent] != 'fit':
            for family in ('F1','F2','F3'):
                for k in (1,2,3):
                    jobs.append(dict(job_id=job_id(parent,family,k),parent=parent,split=SPLITS[parent],kind='attack',family=family,attack_k=k,seed=0,origin='native'))
    inputs = [source_record(LEGACY/'manifest.json'),source_record(LEGACY/'labelled.jsonl.gz'),
              source_record(EVIDENCE/'dataset_inventory_2026_11_04/inventory.json'),
              source_record(EVIDENCE/'oqea_h1_retrain_2026_10_30_envfix1/run_001/offline_gt/offline_gt.json')]
    inputs += [source_record(FEATURES/(j['job_id']+'.jsonl.gz')) for j in jobs if j['origin']=='legacy']
    result = dict(schema=1,code=current,jobs=jobs,parent_splits=SPLITS,input_sources=inputs,
                  specifications=dict(W=10,s=.9,seed=0,alpha=.05,obb_tolerance=1e-6,attack_max=27),
                  scope='used development recordings; not independent unseen evaluation')
    atomic_json(path,result)
    return result


def compact(row):
    return {k:row[k] for k in FIELDS if k in row}


def assign_epochs(rows):
    history = {}; epochs = defaultdict(int)
    for original in rows:
        row = dict(original); key = (row['job_id'],row['id']); previous = history.get(key)
        present = row.get('query_present',False) and not row.get('newborn',False)
        if previous is not None:
            legal = (present and previous.get('query_present',False) and not previous.get('newborn',False)
                     and row['index']==previous['index']+1 and abs(row['timestamp']-previous['timestamp']-.1)<=1e-6
                     and row['source_ids']==previous['source_ids'])
            if not legal:
                epochs[key] += 1
        row['epoch'] = epochs[key]; history[key] = row
        yield row


def join_legacy(label_path, feature_paths, jobs):
    """Consume one feature per label and force every gzip iterator through EOF."""
    iterators = {j:iter(read_rows(p)) for j,p in feature_paths.items()}
    counts = Counter()
    for labelled in read_rows(label_path):
        jid = labelled['job_id']
        if jid not in iterators:
            raise ValueError('unknown labelled job '+jid)
        feature = next(iterators[jid],None)
        if feature is None:
            raise ValueError('extra label '+jid)
        for field in ('key','source_ids','U','frame','index','timestamp'):
            if feature[field] != labelled[field]:
                raise ValueError('legacy join mismatch '+field)
        metadata = jobs[jid]
        if any(labelled[k] != metadata[k] for k in ('parent','kind')):
            raise ValueError('legacy job metadata mismatch')
        row = dict(feature, **{k:labelled.get(k) for k in ('query_truth','query_gt_id','query_label_reason','output_truth','output_gt_id','label_conflict','gt_identity_conflict','native_mean')})
        row.update({k:metadata[k] for k in ('parent','kind','split','family','attack_k')})
        row.update(attack_role='target' if metadata['kind']=='attack' else None,Z=[-1]*len(row['source_ids']))
        counts[jid]+=1
        yield compact(row)
    for jid,it in iterators.items():
        if next(it,None) is not None:
            raise ValueError('unlabelled feature '+jid)
        if not counts[jid]:
            raise ValueError('empty legacy job '+jid)


def prepare_legacy(out, spec):
    from contextlib import ExitStack
    out = Path(out); jobs = {j['job_id']:j for j in spec['jobs'] if j['origin']=='legacy'}
    paths = {jid:FEATURES/(jid+'.jsonl.gz') for jid in jobs}
    pending = {jid for jid in jobs if not (out/'legacy'/ (jid+'.jsonl.gz')).exists()}
    if not pending:
        return
    # Completed jobs are still consumed in the source join, never rewritten.
    counts = Counter()
    with ExitStack() as stack:
        writers = {jid:stack.enter_context(atomic_rows(out/'legacy'/(jid+'.jsonl.gz'))) for jid in pending}
        for row in assign_epochs(join_legacy(LEGACY/'labelled.jsonl.gz',paths,jobs)):
            if row['job_id'] in writers:
                writers[row['job_id']](row); counts[row['job_id']]+=1
    for jid in sorted(pending):
        print('legacy joined',jid,counts[jid],flush=True)


def points_world(points, pose, rotation):
    return (np.asarray(points) @ rotation(pose[3:]).T + np.asarray(pose[:3])) @ np.diag([1.,-1.,1.])


def obb_counts(world, boxes, tolerance=1e-6):
    """AABB prefilter followed by exact full-rotation center OBB test."""
    world = np.asarray(world,float).reshape(-1,3); result = {}
    for box in boxes:
        xyz=np.asarray(box['xyz']); r=np.asarray(box['rotation']); half=np.asarray(box['hwl'])[[2,1,0]]/2
        bounds = np.abs(r) @ half + tolerance
        nearby = world[np.all(np.abs(world-xyz)<=bounds,axis=1)]
        local = (nearby-xyz) @ r
        result[int(box['gt_id'])] = int(np.all(np.abs(local)<=half+tolerance,axis=1).sum())
    return result


def attach_z(rows, echo):
    for row in rows:
        row=dict(row); gid=row.get('query_gt_id')
        row['Z']=[echo.get((row['frame'],sid,gid),-1) if gid is not None else -1 for sid in row['source_ids']]
        yield row


def all_rows(out, split=None):
    spec=json.loads((Path(out)/'manifest.json').read_text())
    for job in spec['jobs']:
        if split is not None and job['split'] != split:
            continue
        status_path=Path(out)/'jobs'/job['job_id']/'complete.json'
        if not status_path.exists():
            raise RuntimeError('job not completed '+job['job_id'])
        status=json.loads(status_path.read_text())
        if status['status']=='UNREALIZABLE':
            continue
        yield from read_rows(Path(out)/'jobs'/job['job_id']/'rows.jsonl.gz')
