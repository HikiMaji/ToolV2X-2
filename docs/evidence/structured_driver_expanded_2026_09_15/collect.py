"""Bounded real integration runner; never trains or reads future labels."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter
import traceback

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')

def main():
    import torch
    from planning.train_structured_driver import initialize, _load
    from planning.run_framework import _load_interaction_runtime, _save_method_json
    from planning.method_episode import run_task_episode, diagnostic_policy
    from planning.method_controls import make_control_policy
    from planning.method_run_spec import freeze_method_run_spec, validate_runtime_binding, QUERY_SPEC
    from evaluation.structured import audit_structured_episode
    from tools.task_spec import validate_plan

    name = sys.argv[1]
    out = BASE / name
    assert out.parent == BASE and not out.exists()
    package = ROOT / 'configs/structured_driver_readiness_v1'
    ready = json.loads((package / 'readiness.json').read_text())
    ready['driver_spec']['version'] = 'toolv2x_structured_driver_v2'
    rows = json.loads((BASE / 'selected_frames.json').read_text())
    assert len(rows) == 200 and sum(r['role'] == 'train' for r in rows) == 160
    assert ready['collection']['conditions'] == dict(Ego='stop', P='p_current', F='f_current', PF='p_current_f_current')
    free = shutil.disk_usage(BASE).free
    assert free > 20 * 1024**3, '20 GiB initial capacity for expanded collection and training'
    out.mkdir()
    for part in ('tasks', 'inputs', 'specs', 'runtime'):
        (out / part).mkdir()
    shutil.copytree(package, out / 'predeclared_package')
    save(out / 'executed_readiness.json', ready)
    shutil.copy2(__file__, out / 'run_acceptance.py')
    # A literal snapshot is retained and checked before models or samples are read.
    for part in ('src', 'vendor/cmp_mtr', 'vendor/v2vgot_llava'):
        shutil.copytree(ROOT / part, out / 'code_snapshot' / part,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for path in (out / 'code_snapshot' / part).rglob('*'):
            if path.is_file():
                assert path.read_bytes() == (ROOT / part / path.relative_to(out / 'code_snapshot' / part)).read_bytes()
    torch.set_num_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    checkpoint = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else out / 'initialized_seed7.pt'
    if len(sys.argv) == 2:
        initialize(checkpoint, ready['driver_spec'], seed=7)
    state = _load(checkpoint)
    assert state['driver_spec'] == ready['driver_spec']
    model_version = state['model_version']
    del state
    limits = dict(version='toolv2x_interaction_v2', max_calls=2, policy_id='stop',
        driver_version={k:model_version[k] for k in ('name','revision')},
        execution_spec=ready['execution_spec'], receiver_spec=ready['driver_spec'])
    config = dict(version='toolv2x_structured_acceptance_execution_v1',
        source_root=str(ROOT), checkpoint=str(checkpoint),
        mtr_checkpoint=str(ROOT / 'outputs/mtr_stability_v1/full_seed20/best_model.pth'),
        samples=rows, spec=dict(limits=limits, local_provenance=ready['local_provenance']),
        conditions=ready['collection']['conditions'], control=ready['controls']['feedback'],
        training=False, gt_labels_read_online=False, free_bytes_preflight=free,
        scope='200-frame expanded driver dataset; not method benefit')
    save(out / 'launch.json', config)
    expected = [dict(sample_id=r['sample_id'], arm=arm, path='tasks/g%d_%s.json' % (r['g'],arm))
        for r in rows for arm in config['conditions']]
    (out / 'tasks.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in expected))
    (out / 'selected_index.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
    progress = dict(status='loading_models', expected_tasks=len(expected), attempted_tasks=0,
        failed_tasks=0, started_utc=datetime.now(timezone.utc).isoformat(), training=False)
    save(out / 'progress.json', progress)
    start = perf_counter()
    runtime = _load_interaction_runtime(out / 'runtime', config)
    save(out / 'models.json', dict(runtime.provenance, loading_wall_seconds=perf_counter()-start))
    print('Real MTR and shared numeric driver loaded', perf_counter()-start, flush=True)
    actual = dict(driver=runtime.driver.provenance, predictor=runtime.predictor.descriptor)
    # Utility is schema-only, unused by fixed collection policies.
    utility = dict(version='toolv2x_query_utility_v1', label_coverage='all_six',
        quality_weights=dict(ADE3=1., FDE3=0.),
        cost_weights=dict(request_bytes=0.,response_bytes=0.,total_compute_seconds=0.), failure_loss=100.)
    specs = {}
    for arm, policy in config['conditions'].items():
        arm_limits = dict(limits, policy_id=policy)
        value = dict(version='toolv2x_method_run_spec_v1', limits=arm_limits,
            local_provenance=ready['local_provenance'], control=config['control'], utility_spec=utility,
            recording_roles=ready['recording_roles'],
            recording_folds={g: role for g,role in ready['recording_roles'].items()},
            runtime_binding=actual, query_spec=QUERY_SPEC)
        specs[arm] = freeze_method_run_spec(value, rows)
        validate_runtime_binding(actual, specs[arm])
        save(out / 'specs' / (arm+'.json'), specs[arm])
    diagnostics = []
    for row in rows:
        assert shutil.disk_usage(BASE).free > 6 * 1024**3, 'free-space reserve reached; partial collection retained'
        for arm in config['conditions']:
            key = 'g%d_%s' % (row['g'],arm)
            path = out / 'tasks' / (key+'.json')
            directory = out / 'inputs' / key
            directory.mkdir()
            task = dict(row=row, arm=arm, status='started', episode=None, configuration='specs/'+arm+'.json')
            _save_method_json(path, task)
            progress.update(status='running', current_task=key)
            save(out / 'progress.json', progress)
            begin = perf_counter()
            service = None
            audit = None
            try:
                validate_runtime_binding(actual, specs[arm])
                inputs = runtime.load_inputs(row, directory)
                metadata = inputs.pop('metadata')
                task['inputs'] = dict(metadata, artifact_root=str(directory), factory_fresh=True, provider_fresh=True)
                service = inputs['service']
                def persist(ep):
                    task.update(episode=ep, status='running')
                    _save_method_json(path, task)
                ep = run_task_episode(**inputs, predictor=runtime.predictor, driver=runtime.driver,
                    policy=make_control_policy(config['control'], diagnostic_policy),
                    limits=specs[arm]['limits'], local_provenance=ready['local_provenance'],
                    sample_id=row['sample_id'], branch_id=arm, control_spec=config['control'], on_progress=persist)
                task.update(episode=ep, status='completed' if ep['status']=='completed' else 'failed')
                audit = audit_structured_episode(ep)
                save(directory / 'structured_audit.json', audit)
            except Exception as exc:
                task.update(status='failed', error=dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc()))
            if service is not None:
                save(directory / 'provider_records.json', dict(primitive_records=service.task_records,
                    bundle_records=service.bundle_records, peer_context_loaded=service._task_window is not None))
            task['wall_seconds'] = perf_counter()-begin
            _save_method_json(path, task)
            ep = task.get('episode') or {}
            plans = ep.get('plans', [])
            valid_initial = False
            validity_error = None
            try:
                validate_plan(plans[0]['output']['waypoints'], ready['execution_spec'])
                valid_initial = plans[0]['status'] == 'valid'
            except Exception as exc:
                validity_error = str(exc)
            item = dict(g=row['g'], arm=arm, status=task['status'], wall_seconds=task['wall_seconds'],
                driver_attempts=len(plans), requests=[x['tool'] for x in ep.get('requests',[])],
                initial_plan_valid=valid_initial, initial_validity_error=validity_error,
                audit_pass=audit is not None, failure=task.get('error') or ep.get('error'))
            diagnostics.append(item)
            progress['attempted_tasks'] += 1
            progress['failed_tasks'] += task['status']=='failed'
            save(out / 'diagnostics.json', diagnostics)
            save(out / 'progress.json', progress)
            print(json.dumps(item), flush=True)
    progress.update(status='completed', wall_seconds=perf_counter()-start,
        finished_utc=datetime.now(timezone.utc).isoformat())
    save(out / 'progress.json', progress)
    print(json.dumps(progress), flush=True)

if __name__ == '__main__':
    main()
