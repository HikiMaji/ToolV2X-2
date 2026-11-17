"""Prepare only the sixteen frozen missing cal attacks using existing workers."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import itertools
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.rq1_temporal import data
from scripts.rq1_score_revision import prepare as frozen


def run_one(args):
    out, job_id = args
    frozen._worker(Path(out), job_id)
    result = json.loads((Path(out)/'jobs'/job_id/'complete.json').read_text())
    if result['status'] not in ('COMPLETE', 'UNREALIZABLE'):
        raise RuntimeError('nonterminal calibration task '+job_id)
    return job_id, result


def prepare(batch_path, workers):
    batch_path = Path(batch_path)
    batch = json.loads(batch_path.read_text())
    tasks = [j for j in batch['calibration_tasks'] if j['action'] == 'missing_plan_once']
    if len(tasks) != 16 or not 1 <= workers <= 4:
        raise ValueError('expected sixteen frozen attempts and at most four workers')
    out = Path(batch['output'])/'calibration_extension'
    source = data.EVIDENCE/'rq1_temporal_2026_11_12/run_001/manifest.json'
    old_jobs = json.loads(source.read_text())['jobs']
    parents_by_name = {p['parent']: p for p in batch['parents']}
    record = dict(batch=data.source_record(batch_path), source=data.source_record(source),
        offline_gt=data.source_record(frozen.LEGACY_GT),
        code=[data.source_record(__file__), data.source_record(frozen.__file__),
              data.source_record(frozen.native.__file__)])
    binding = out/'binding.json'
    if binding.exists():
        if json.loads(binding.read_text()) != record:
            raise ValueError('frozen calibration preparation binding changed')
    else:
        data.atomic_json(binding, record)
    manifest_path = out/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        ground = {r['recording']: r['frames'] for r in json.loads(frozen.LEGACY_GT.read_text())['recordings']}
        parents = {}
        for parent in sorted({j['parent'] for j in tasks}):
            declared = parents_by_name[parent]
            clean = next(j for j in old_jobs if j['parent'] == parent and j['kind'] == 'clean')
            if declared['split'] != 'cal' or clean['split'] != 'cal':
                raise ValueError('cal role mismatch')
            cfg = json.loads(Path(clean['config']).read_text())
            if cfg['source_ids'] != declared['source_ids']:
                raise ValueError('source IDs differ from frozen clean source')
            packets = list(itertools.islice(data.read_rows(cfg['sender_path']), 80))
            scans = frozen._legacy_scans(packets, ground[parent], cfg['source_ids'], cfg['expected_frames'][:80])
            if len(scans) != 80 or [s['frame'] for s in scans] != declared['frames'][:80]:
                raise ValueError('cal horizon/frame mismatch')
            scan_path = out/'parents'/parent.replace('/', '__')/'scans.jsonl.gz'
            if not scan_path.exists():
                with data.atomic_rows(scan_path) as write:
                    for scan in scans:
                        write(scan)
            elif list(data.read_rows(scan_path)) != scans:
                raise ValueError('resumed scan cache differs')
            spec = {k: declared[k] for k in ('parent', 'source_ids', 'root', 'detections')}
            spec['frames'] = declared['frames'][:80]
            parents[parent] = dict(scan_path=str(scan_path), spec=spec,
                source_clean_job_id=clean['job_id'], sender=data.source_record(cfg['sender_path']),
                clean_config=data.source_record(clean['config']), offline_gt=str(frozen.LEGACY_GT))
        jobs = []
        for task in tasks:
            if task['receiver_id'] in task['controlled_sources']:
                raise ValueError('receiver was declared controlled')
            if (task['seed'], task['max_proposals'], task['scans'], task['active_indices']) != (0, 64, 80, [20, 60]):
                raise ValueError('construction settings differ')
            jobs.append(dict(task, kind='attack', split='cal', origin='score_revision'))
        manifest = dict(schema='trusted_receiver_calibration_extension_v1', jobs=jobs, parents=parents)
        data.atomic_json(manifest_path, manifest)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = dict(pool.map(run_one, [(str(out), j['job_id']) for j in manifest['jobs']]))
    summary = dict(status='COMPLETE', planned_attempts=len(tasks), jobs=results)
    path = out/'prepare.complete.json'
    if not path.exists():
        data.atomic_json(path, summary)
    elif json.loads(path.read_text()) != summary:
        raise ValueError('completed calibration summary differs')
    print(json.dumps({k: sum(r['status'] == k for r in results.values())
                      for k in ('COMPLETE', 'UNREALIZABLE')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    prepare(args.batch, args.workers)
