"""Frozen three-parent confirmation through the existing native preparation."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from scripts.rq1_temporal import data, native_adapter as native
from scripts.rq1_report_freeze import prepare as frozen


def validate_config(config):
    parents = config['additional_eval_parents']
    old = config['old_parent_splits']
    existing = config['existing_eval_parents']
    data.validate_splits(old)
    if (len(parents) != 3 or len(set(parents)) != 3
            or len(existing) != 6 or len(set(existing)) != 6
            or set(parents) & (set(old) | set(existing))
            or set(existing) & set(old)):
        raise ValueError('confirmation parents collide with frozen roles')
    for parent, role in old.items():
        if data.SPLITS.get(parent) != role:
            raise ValueError('old parent role changed '+parent)
    selected = set(old) | set(existing) | set(parents)
    if any(set(pair) <= selected for pair in config['known_protected_overlap']):
        raise ValueError('protected overlapping parents selected')
    if (config['window'] != 10 or config['attack'] != dict(
            seed=0, max_proposals=64, total_scans=80, active_indices=[20, 60],
            controlled_selection='first_k_sorted_source_ids', new_seeds_on_failure=False)):
        raise ValueError('frozen construction changed')
    if set(config['parent_specs']) != set(parents):
        raise ValueError('frozen parent specs differ from confirmation list')
    expected = []
    for parent in parents:
        spec = config['parent_specs'][parent]
        ids, frames = spec['source_ids'], spec['frames']
        if (spec['parent'] != parent or len(ids) != 3 or ids != sorted(set(ids))
                or len(frames) < 80 or any(b-a != 2 for a, b in zip(frames, frames[1:]))):
            raise ValueError('invalid frozen source/frame spec '+parent)
        for family, k in [('clean', 0), ('F1', 1), ('F1', 2), ('F2', 1), ('F2', 2)]:
            expected.append(dict(parent=parent, family=family, attack_k=k,
                kind='clean' if k == 0 else 'attack', split='eval', seed=0,
                job_id=data.job_id(parent, family, k), origin='report_freeze'))
    if config['jobs'] != expected:
        raise ValueError('expected exactly the fifteen frozen confirmation attempts')
    # Directory metadata only; native imports and point-cloud reads happen later.
    for parent in parents:
        if native.recording_spec(parent) != config['parent_specs'][parent]:
            raise ValueError('current recording differs from frozen spec '+parent)


def _binding(config):
    code = data.code_record()
    code['files'] += [data.source_record(__file__), data.source_record(frozen.__file__)]
    return dict(config=config, code_files=code['files'])


def prepare(config, out, workers=3):
    validate_config(config)
    if not isinstance(workers, int) or not 1 <= workers <= 3:
        raise ValueError('workers must be 1..3')
    out = Path(out).resolve()
    with frozen._lock(out/'.prepare.lock'):
        path = out/'manifest.json'
        manifest = frozen.read(path) if path.exists() else None
        if manifest is not None and (manifest['config'] != config or manifest['jobs'] != config['jobs']):
            raise ValueError('confirmation manifest changed')
        binding = _binding(config)
        binding_path = out/'binding.json'
        if binding_path.exists():
            if frozen.read(binding_path) != binding:
                raise ValueError('confirmation source/config binding changed')
        else:
            data.atomic_json(binding_path, binding)
        frozen.register_parents(config)
        if manifest is None:
            tasks = [(config, str(out), p) for p in config['additional_eval_parents']]
            if workers == 1:
                parents = dict(frozen.parent_worker(task) for task in tasks)
            else:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    parents = dict(pool.map(frozen.parent_worker, tasks))
            for parent, value in parents.items():
                if value['spec'] != config['parent_specs'][parent]:
                    raise ValueError('prepared parent differs from frozen spec '+parent)
            manifest = dict(schema='rq1_joint_confirmation_manifest_v1', config=config,
                jobs=config['jobs'], parents=parents,
                parent_splits=dict(config['old_parent_splits'],
                    **{p: 'eval' for p in config['additional_eval_parents']}))
            data.atomic_json(path, manifest)
        else:
            if (set(manifest['parents']) != set(config['additional_eval_parents'])
                    or any(v['spec'] != config['parent_specs'][p] for p, v in manifest['parents'].items())):
                raise ValueError('confirmation parent binding changed')
        pending = []
        for job in manifest['jobs']:
            if (out/'jobs'/job['job_id']/'complete.json').exists():
                frozen.worker(out, job['job_id'])
            else:
                pending.append((str(out), job['job_id']))
        if workers == 1:
            for task in pending:
                frozen._job_worker(task)
        elif pending:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                list(pool.map(frozen._job_worker, pending))
        statuses = {j['job_id']: frozen.read(out/'jobs'/j['job_id']/'complete.json')
                    for j in manifest['jobs']}
        if any(s['status'] not in ('COMPLETE', 'UNREALIZABLE') for s in statuses.values()):
            raise RuntimeError('nonterminal confirmation task')
        result = dict(status='COMPLETE', jobs=statuses, planned_jobs=len(manifest['jobs']))
        complete = out/'prepare.complete.json'
        if complete.exists():
            if frozen.read(complete) != result:
                raise ValueError('confirmation completion changed')
        else:
            data.atomic_json(complete, result)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    prepare(json.loads(Path(args.config).read_text()), args.out, args.workers)


if __name__ == '__main__':
    main()
