"""Only the frozen extra parents and jobs; native replay precedes labels."""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[_name]='1'

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import traceback
from scripts.rq1_temporal import data, native_adapter as native
from scripts.rq1_score_revision.prepare import _public, _lock


def read(path):
    return json.loads(Path(path).read_text())


def register_parents(config):
    for parent, role in config['old_parent_splits'].items():
        if data.SPLITS.get(parent) != role:
            raise ValueError('old role changed '+parent)
    for parent in config['additional_eval_parents']:
        if parent in config['old_parent_splits'] or data.SPLITS.get(parent, 'eval') != 'eval':
            raise ValueError('new parent role collision '+parent)
        data.SPLITS[parent]='eval'


def parent_worker(args):
    config, destination, parent=args
    register_parents(config)
    spec=native.recording_spec(parent)
    if spec['source_ids'] != sorted(spec['source_ids']) or len(spec['source_ids']) < 3:
        raise ValueError('sorted sources with k=2 normal probe required')
    path=native.preprocess_new(Path(destination), spec)
    scans=list(data.read_rows(path))
    if len(scans) != len(spec['frames']) or len(scans) < 80:
        raise ValueError('synchronous scan coverage differs from spec')
    for i,s in enumerate(scans):
        if (s['index'] != i or s['frame'] != spec['frames'][i] or abs(s['timestamp']-.1*i)>1e-6
                or [m['source_id'] for m in s['messages']] != spec['source_ids']):
            raise ValueError('parent scan correspondence mismatch')
    return parent,dict(spec=spec,scan_path=str(path.resolve()),source_ids=spec['source_ids'])


def worker(out, job_id):
    out=Path(out);manifest=read(out/'manifest.json')
    if 'config' in manifest: register_parents(manifest['config'])
    job=next(j for j in manifest['jobs'] if j['job_id']==job_id)
    dest=out/'jobs'/job_id
    with _lock(dest/'.prepare.lock'):
        marker=dest/'complete.json'
        if marker.exists():
            status=read(marker)['status']
            if status not in ('COMPLETE','UNREALIZABLE'): raise RuntimeError('invalid completion marker')
            if status=='COMPLETE' and any(not (dest/p).is_file() for p in ('online.jsonl.gz','rows.jsonl.gz','entity_coverage.jsonl.gz','attack.json')):
                raise RuntimeError('completed job artifacts missing')
            return read(marker)
        try:
            binding=manifest['parents'][job['parent']]
            scans=list(data.read_rows(binding['scan_path']))
            if job['kind']=='attack': scans=scans[:80]
            attack_path=dest/'attack.json'
            if attack_path.exists(): frozen=read(attack_path)
            else:
                frozen=native.construct_attack(job,scans) if job['kind']=='attack' else dict(status='CLEAN')
                data.atomic_json(attack_path,frozen)
            if frozen['status']=='UNREALIZABLE':
                result=dict(frozen,origin='report_freeze',job_id=job_id)
                data.atomic_json(marker,result);return result
            attack=None if job['kind']=='clean' else frozen
            if attack is not None:
                ids=binding['spec']['source_ids'];k=job['attack_k']
                if (attack['status']!='VALID' or attack['controlled_sources']!=ids[:k] or attack['normal_source']!=ids[k]):
                    raise ValueError('construction roles mismatch')
            online=dest/'online.jsonl.gz'
            if not online.exists():
                with data.atomic_rows(online) as write:
                    for row in native.replay_online(job,binding['spec'],_public(scans),attack): write(row)
            rows=dest/'rows.jsonl.gz';coverage=dest/'entity_coverage.jsonl.gz'
            diagnostics=Counter();diagnostics['public_occlusion_frames']=set()
            if not rows.exists() or not coverage.exists():
                with ExitStack() as stack:
                    write=stack.enter_context(data.atomic_rows(rows)) if not rows.exists() else None
                    cover=stack.enter_context(data.atomic_rows(coverage)) if not coverage.exists() else None
                    for row in native.attach_labels(data.read_rows(online),scans,job,attack,diagnostics,cover):
                        row['origin']='report_freeze'
                        if write: write(row)
            counts=Counter();n=0
            for row in data.read_rows(rows):
                n+=1;counts['query_truth_'+str(row['query_truth'])]+=1
            diagnostics['public_occlusion_frames']=len(diagnostics['public_occlusion_frames'])
            result=dict(status='COMPLETE',job_id=job_id,origin='report_freeze',rows=n,scans=len(scans),counts=dict(counts),
                        attack_constructed=attack is not None,actual_construction=dict(diagnostics),entity_coverage=native.coverage_summary(data.read_rows(coverage)))
            data.atomic_json(marker,result);return result
        except Exception as exc:
            error=dest/'error.json'
            if not error.exists(): data.atomic_json(error,dict(error=str(exc),traceback=traceback.format_exc()))
            raise


def _job_worker(args):
    return worker(*args)


def prepare(config, out, workers=4):
    from .run import bind, validate_config
    validate_config(config);out=Path(out).resolve();bind(config,out);register_parents(config)
    if not 1<=workers<=6: raise ValueError('workers must be 1..6')
    with _lock(out/'.prepare.lock'):
        path=out/'manifest.json'
        if path.exists():
            manifest=read(path)
            if manifest['config']!=config or manifest['jobs']!=config['jobs']: raise ValueError('manifest changed')
        else:
            tasks=[(config,str(out),p) for p in config['additional_eval_parents']]
            if workers==1: parents=dict(parent_worker(t) for t in tasks)
            else:
                with ProcessPoolExecutor(max_workers=workers) as pool: parents=dict(pool.map(parent_worker,tasks))
            manifest=dict(schema='rq1_report_freeze_manifest_v1',config=config,jobs=config['jobs'],parents=parents,
                          parent_splits=dict(config['old_parent_splits'],**{p:'eval' for p in config['additional_eval_parents']}))
            data.atomic_json(path,manifest)
        pending=[]
        for job in manifest['jobs']:
            marker=out/'jobs'/job['job_id']/'complete.json'
            if marker.exists(): worker(out,job['job_id'])
            else: pending.append((str(out),job['job_id']))
        if workers==1:
            for task in pending: _job_worker(task)
        elif pending:
            with ProcessPoolExecutor(max_workers=workers) as pool: list(pool.map(_job_worker,pending))
        statuses={j['job_id']:read(out/'jobs'/j['job_id']/'complete.json') for j in manifest['jobs']}
        if any(s['status'] not in ('COMPLETE','UNREALIZABLE') for s in statuses.values()): raise RuntimeError('nonterminal task')
        result=dict(status='COMPLETE',jobs=statuses,planned_jobs=len(manifest['jobs']))
        if not (out/'prepare.complete.json').exists(): data.atomic_json(out/'prepare.complete.json',result)
        return manifest
