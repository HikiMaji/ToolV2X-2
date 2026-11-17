"""Run the reviewed Task1 snapshot per parent, preserving the serial attempt."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.rq1_temporal import data


def link_same(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not os.path.samefile(source, target):
            raise ValueError('existing cache is not the declared source '+str(target))
    else:
        os.link(source, target)


def one_parent(args):
    source, destination, name = map(Path, args)
    sys.path.insert(0, str(source/'execution'))
    from trusted_receiver_prepare_snapshot import run as frozen
    full = json.loads((source/'method_inputs.json').read_text())
    chosen = str(name)
    config = copy.deepcopy(full)
    config['parents'] = [p for p in full['parents'] if p['split'] == 'fit' or p['parent'] == chosen]
    selected = {p['parent'] for p in config['parents']}
    config['jobs'] = [j for j in full['jobs'] if j['parent'] in selected]
    shard = destination/'parent_shards'/chosen.replace('/', '__')
    for parent in config['parents']:
        relative = Path('parents')/parent['parent'].replace('/', '__')/'receiver.jsonl.gz'
        link_same(source/relative, shard/relative)
    link_same(source/'shape.json', shard/'shape.json')
    result = frozen.prepare(config, shard)
    jobs = [j for j in config['jobs'] if j['parent'] == chosen]
    for job in jobs:
        relative = Path('jobs')/job['job_id']/'local.jsonl.gz'
        link_same(shard/relative, destination/relative)
    return chosen, {j['job_id']: result['jobs'][j['job_id']] for j in jobs}


def prepare(source, destination, workers):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('parallel output must be a separate run directory')
    if not 1 <= workers <= 12:
        raise ValueError('at most twelve parent workers')
    config = json.loads((source/'method_inputs.json').read_text())
    binding = dict(source_method_inputs=data.source_record(source/'method_inputs.json'),
        source_shape=data.source_record(source/'shape.json'),
        reviewed_snapshot=json.loads((source/'execution/prepare_source.json').read_text()),
        driver=data.source_record(__file__), workers=workers,
        reason='same mathematics and inputs; parallelize independent parents')
    for path, value in ((destination/'parallel.binding.json', binding),
                        (destination/'method_inputs.json', config),
                        (destination/'prepare.config.json', config)):
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise ValueError('parallel binding changed '+str(path))
        else:
            data.atomic_json(path, value)
    link_same(source/'shape.json', destination/'shape.json')
    for parent in config['parents']:
        relative = Path('parents')/parent['parent'].replace('/', '__')/'receiver.jsonl.gz'
        link_same(source/relative, destination/relative)
    fits = {p['parent'] for p in config['parents'] if p['split'] == 'fit'}
    summary = {j['job_id']: dict(rows=0, status='SHAPE_ONLY') for j in config['jobs'] if j['parent'] in fits}
    targets = [p['parent'] for p in config['parents'] if p['split'] != 'fit']
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_parent, (str(source), str(destination), name)) for name in targets]
        for future in as_completed(futures):
            name, result = future.result()
            if set(summary) & set(result):
                raise ValueError('parent job collision')
            summary.update(result)
            print('completed parent', name, 'jobs', len(result), flush=True)
    if set(summary) != {j['job_id'] for j in config['jobs']}:
        raise ValueError('incomplete parent coverage')
    result = dict(status='COMPLETE', jobs=summary,
        shape_hwl=json.loads((source/'shape.json').read_text())['shape_hwl'],
        schema='rq1_trusted_receiver_local_v1')
    marker = destination/'prepare.complete.json'
    if marker.exists():
        if json.loads(marker.read_text()) != result:
            raise ValueError('parallel completion differs')
    else:
        data.atomic_json(marker, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    prepare(args.source, args.out, args.workers)
