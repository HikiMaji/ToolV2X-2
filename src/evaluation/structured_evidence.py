"""Frozen-model, fixed-receipt diagnostics; never a provider or training entrypoint."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from evaluation.planning import trajectory_metrics
from planning.driver_contract import validate_numeric_episode
from planning.structured_driver import collate_structured_inputs
from planning.train_structured_driver import _read_features, load_structured_planner
from tools.task_spec import validate_plan

VERSION = 'toolv2x_fixed_evidence_diagnostic_v1'
CONDITIONS = ('Ego', 'P', 'F', 'PF')
METRICS = ('ADE3', 'FDE3', 'got_prefix_L2_avg')


def with_prior(batch, prior):
    result = dict(batch)
    result['previous_plan'] = (torch.zeros_like(batch['previous_plan']) if prior is None
                               else prior.detach().clone())
    result['previous_plan_valid'] = torch.full_like(batch['previous_plan_valid'], prior is not None)
    return result


def without_evidence(batch, kind):
    """Tensor intervention only; does not manufacture a new valid receipt."""
    if kind not in ('remote', 'forecasts', 'scene', 'environment'):
        raise ValueError('unknown evidence intervention')
    out = {key: value.clone() for key, value in batch.items()}
    if kind in ('remote', 'environment'):
        mask = (out['observation_sources'] == 1 if kind == 'remote'
                else torch.ones_like(out['observation_sources'], dtype=torch.bool))
        out['observation_mask'] &= ~mask.unsqueeze(-1)
        out['observations'].masked_fill_(mask[..., None, None], 0.)
    if kind in ('remote', 'forecasts', 'environment'):
        mask = (out['forecast_context'][..., 0] == 0 if kind == 'remote'
                else torch.ones_like(out['forecast_context'][..., 0], dtype=torch.bool))
        out['forecast_mask'] &= ~mask[..., None, None]
        out['forecasts'].masked_fill_(mask[..., None, None, None], 0.)
        out['forecast_context'].masked_fill_(mask[..., None], 0.)
    if kind in ('scene', 'environment'):
        out['scene_mask'].fill_(False)
        out['scene_patches'].zero_()
    if kind in ('remote', 'forecasts', 'environment'):
        out['entity_mask'] &= (out['observation_mask'].any(dim=-1).any(dim=-1) |
                              out['forecast_mask'].flatten(2).any(dim=-1))
    return out


def paired_effect(reference, changed, threshold_m):
    result = dict(outcome='invalid_pair', ade_delta_m=None, trajectory_mean_delta_m=None,
                  trajectory_max_delta_m=None)
    if not reference['valid_plan'] or not changed['valid_plan']:
        return result
    distances = np.linalg.norm(np.asarray(changed['waypoints'])-reference['waypoints'], axis=-1)
    result.update(trajectory_mean_delta_m=float(distances.mean()),
                  trajectory_max_delta_m=float(distances.max()))
    if reference['metrics'].get('ADE3') is None or changed['metrics'].get('ADE3') is None:
        return result
    delta = changed['metrics']['ADE3'] - reference['metrics']['ADE3']
    result.update(ade_delta_m=delta, outcome=('improved' if delta < -threshold_m else
        'harmed' if delta > threshold_m else 'within_threshold'))
    return result


def _measure(points, label, execution_spec):
    points = points.detach().cpu().double().numpy()
    result = dict(waypoints=points.tolist(), valid_plan=True, invalid_reason=None, metrics={})
    try:
        validate_plan(result['waypoints'], execution_spec)
    except (ValueError, TypeError, KeyError) as exc:
        result.update(valid_plan=False, invalid_reason=str(exc))
    if np.isfinite(points).all():
        result['metrics'] = trajectory_metrics(result['waypoints'], label, None)
    return result


def _mean(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def _summary(rows):
    outputs, pairs = defaultdict(list), defaultdict(list)
    for row in rows:
        for name, value in row['outputs'].items():
            outputs[name].append(value)
        for name, value in row['pairs'].items():
            pairs[name].append(value)
    return dict(frames=len(rows), outputs={name: dict(frames=len(values),
        invalid=sum(not v['valid_plan'] for v in values),
        **{m: _mean([v['metrics'].get(m) for v in values if v['valid_plan']]) for m in METRICS})
        for name, values in outputs.items()}, pairs={name: dict(frames=len(values),
        outcomes=dict(Counter(v['outcome'] for v in values)),
        **{m: _mean([v.get(m) for v in values]) for m in
           ('ade_delta_m', 'trajectory_mean_delta_m', 'trajectory_max_delta_m')})
        for name, values in pairs.items()})


def _content(prepared, motion_base, radius_m):
    """Causal proximity proxies; forecast quality requires a separate target GT join."""
    spec, raw = prepared['driver_spec'], prepared['tensor_inputs']
    forecasts, masks = np.asarray(raw['forecasts']), np.asarray(raw['forecast_mask'])
    obs, obs_mask = np.asarray(raw['observations']), np.asarray(raw['observation_mask'])
    contexts, details = np.asarray(raw['forecast_context']), []
    for entity in prepared['entities']:
        index = entity.get('tensor_index')
        if index is None:
            continue
        valid_history = np.flatnonzero(obs_mask[index, 1])
        remote_sets = np.flatnonzero(masks[index].any(axis=(1, 2)) & (contexts[index, :, 0] == 0))
        if not len(valid_history) and not len(remote_sets):
            continue
        distance = float(np.linalg.norm(entity['representative_anchor']['box'][:2]))
        paths, sources = [], []
        if len(valid_history) >= 2:
            prev, last = obs[index, 1, valid_history[-2:]]
            dt = (last[9]-prev[9])*spec['time_scale_s']
            if dt > 0:
                velocity = (last[:2]-prev[:2])*spec['position_scale_m']/dt
                paths.append(last[:2]*spec['position_scale_m'] +
                             np.arange(1, 7)[:, None]*.5*velocity)
                sources.append('causal_tracking_state_motion_proxy')
        for column in remote_sets:
            mode = int(np.argmax(forecasts[index, column, :, 0, 3]))
            paths.append(forecasts[index, column, mode, :, :2]*spec['position_scale_m'])
            sources.append('F_top_score_mode')
        closest = min((float(np.linalg.norm(path-motion_base, axis=-1).min())
                       for path in paths), default=None)
        details.append(dict(entity_id=entity['entity_id'], aliases=entity['aliases'],
            role=entity['role'], remote_observation_points=len(valid_history),
            remote_forecast_sets=len(remote_sets), local_observation=bool(obs_mask[index, 0].any()),
            anchor_distance_m=distance, near_origin_unresolved=bool(entity['role']=='unresolved' and
                distance <= spec['ego_position_threshold_m']), proxy_sources=sources,
            closest_synchronous_center_distance_m=closest,
            interaction_proxy=closest is not None and closest <= radius_m))
    return dict(remote_entities=details,
        remote_histories=sum(v['remote_observation_points'] >= 2 for v in details),
        remote_forecast_sets=sum(v['remote_forecast_sets'] for v in details),
        remote_only_entities=sum(not v['local_observation'] for v in details),
        near_origin_unresolved=sum(v['near_origin_unresolved'] for v in details),
        obstacle_interaction_proxy=any(v['role']=='obstacle' and v['interaction_proxy'] for v in details))


def _cohort(rows):
    roles, final = defaultdict(set), {}
    for row in rows:
        roles[row['recording']].add(row['role'])
        if row['role'] == 'validation':
            previous = final.get(row['source_task'])
            if previous is None or row['stage'] > previous['stage']:
                final[row['source_task']] = row
    if any(len(v) != 1 for v in roles.values()):
        raise ValueError('recording role leakage')
    frames = defaultdict(list)
    for row in final.values():
        frames[(row['scene'], row['g'])].append(row)
    if not frames or any(len(v) != 4 for v in frames.values()):
        raise ValueError('complete four-task development frames required')
    return [frames[key] for key in sorted(frames)]


def run(source, output, checkpoints, device, time_limit_seconds=1800):
    start = time.perf_counter()
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    rows = [json.loads(line) for line in (source/'rows.jsonl').read_text().splitlines()]
    frames = _cohort(rows)
    execution_spec = json.loads((source/'execution_spec.json').read_text())
    coverage = json.loads((source/'coverage.json').read_text())
    if len(frames) != coverage['frames']['validation']:
        raise ValueError('development coverage disagrees with source manifest')
    models, states, metadata = {}, {}, {}
    for step in checkpoints:
        path = source/'training'/('checkpoint_%06d.pt' % step)
        planner = load_structured_planner(path, device=device)
        model = planner.model.eval().requires_grad_(False)
        models[step] = model
        states[step] = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        metadata[str(step)] = dict(checkpoint=str(path), size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns, provenance=planner.provenance)
    config = dict(version=VERSION, source=str(source), output=str(output),
        started_utc=datetime.now(timezone.utc).isoformat(), checkpoints=metadata,
        primary_checkpoint=500, frames=len(frames), execution_spec=execution_spec,
        source_coverage=coverage, threshold_m=.01, interaction_proxy_radius_m=8.,
        device=device, torch_version=torch.__version__, threads=torch.get_num_threads(),
        time_limit_seconds=time_limit_seconds, source_rows='rows.jsonl',
        scope='Fixed acquired evidence replay; no new provider/MTR/LLM calls or optimizer steps. '
              'Archived PF is not full evidence or an upper bound. Tensor ablations may be OOD.')
    (output/'run.json').write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n')
    snapshot = output/'source'; snapshot.mkdir()
    for path in (Path(__file__), Path(__file__).parents[1]/'planning/structured_driver.py',
                 Path(__file__).parents[1]/'planning/structured_inputs.py',
                 Path(__file__).parents[1]/'planning/train_structured_driver.py'):
        shutil.copy2(path, snapshot/path.name)
    results = []
    audit = dict(validated_tasks=0, initial_inputs_equal=0, shared_features_equal=0,
        deterministic_repeat_checks=0, invalid_common_priors=0, actual_model_forwards=0,
        model_parameters_unchanged=False, checkpoint_files_unchanged=False,
        new_optimizer_steps=0, new_provider_calls=0, new_mtr_calls=0, new_llm_calls=0)
    trace = (output/'predictions.jsonl').open('x')
    try:
        for fi, selected in enumerate(frames):
            if time.perf_counter()-start > time_limit_seconds:
                raise TimeoutError('predeclared diagnostic wall limit reached')
            batches, prepared, tasks = {}, {}, {}
            canonical_features, initial, label = None, None, None
            for row in selected:
                task = json.loads(Path(row['source_task']).read_text())
                arm, ep = task['arm'], task['episode']
                if arm not in CONDITIONS or arm in tasks or task['status'] != 'completed':
                    raise ValueError('ambiguous or noncompleted source arm')
                if any(task['row'][k] != row[k] for k in ('sample_id', 'scene', 'g', 'role')):
                    raise ValueError('source task / row identity mismatch')
                if ep['limits']['execution_spec'] != execution_spec or row['stage'] != len(ep['plans'])-1:
                    raise ValueError('source execution spec / final stage mismatch')
                validate_numeric_episode(ep)
                receipt_tools = {r['request']['tool'] for r in
                    ep['ledger_snapshots'][ep['plans'][-1]['ledger_snapshot']]['receipts']}
                if (''.join(c for c in ('P','F') if c in receipt_tools) or 'Ego') != arm:
                    raise ValueError('source arm disagrees with acquired receipts')
                audit['validated_tasks'] += 1
                features = _read_features(row['inputs']['feature_path'])
                first = with_prior(collate_structured_inputs([features], [ep['plans'][0]['prepared']]), None)
                if canonical_features is None:
                    canonical_features, initial, label = features, first, row['supervision']
                else:
                    if not all(np.array_equal(v, features[k]) for k,v in canonical_features.items()):
                        raise ValueError('same frame has different ego feature arrays')
                    if not all(torch.equal(v, first[k]) for k,v in initial.items()):
                        raise ValueError('same frame initial model inputs differ')
                    if label != row['supervision']:
                        raise ValueError('same frame has different offline labels')
                    audit['shared_features_equal'] += 1
                    audit['initial_inputs_equal'] += 1
                prepared[arm] = ep['plans'][-1]['prepared']
                batches[arm] = with_prior(collate_structured_inputs([features], [prepared[arm]], device), None)
                tasks[arm] = dict(source_task=row['source_task'], stage=row['stage'],
                    requests=len(ep['requests']), archived_cost=ep['cost'])
                del ep, task, first, features
            for step, model in models.items():
                frame_start = time.perf_counter()
                outputs, pairs = {}, {}
                def predict(batch):
                    audit['actual_model_forwards'] += 1
                    with torch.inference_mode():
                        return model(batch).detach()
                def save(name, value):
                    outputs[name] = _measure(value[0], label, execution_spec)
                with torch.inference_mode():
                    base = model._causal_motion_base(batches['Ego']).detach()
                save('constant_motion', base)
                for arm in CONDITIONS:
                    value = predict(batches[arm]); save(arm+'_once', value)
                    if arm == 'Ego':
                        ego_prior = value
                if not outputs['Ego_once']['valid_plan']:
                    ego_prior = None
                    audit['invalid_common_priors'] += 1
                shared = {arm: with_prior(batches[arm], ego_prior) for arm in CONDITIONS}
                for arm in CONDITIONS:
                    second = predict(shared[arm]); save(arm+'_shared_prior', second)
                    fixed = second - shared[arm]['previous_plan'] + base if ego_prior is not None else second
                    save(arm+'_fixed_base_diagnostic', fixed)
                    repeat_prior = second if outputs[arm+'_shared_prior']['valid_plan'] else None
                    save(arm+'_repeat', predict(with_prior(batches[arm], repeat_prior)))
                    save(arm+'_without_forecasts', predict(without_evidence(shared[arm], 'forecasts')))
                    if arm != 'Ego':
                        save(arm+'_without_remote', predict(without_evidence(shared[arm], 'remote')))
                for intervention in ('scene', 'environment'):
                    save('Ego_without_'+intervention, predict(without_evidence(shared['Ego'], intervention)))
                if fi == 0:
                    repeated = predict(shared['Ego'])[0].cpu().tolist()
                    if repeated != outputs['Ego_shared_prior']['waypoints']:
                        raise ValueError('identical eval tensor input did not reproduce exact output')
                    audit['deterministic_repeat_checks'] += 1
                def pair(name, ref, changed):
                    pairs[name] = paired_effect(outputs[ref], outputs[changed], config['threshold_m'])
                for arm in CONDITIONS:
                    pair(arm+'_once_vs_motion', 'constant_motion', arm+'_once')
                    pair(arm+'_revision_effect', arm+'_once', arm+'_shared_prior')
                    pair(arm+'_repeat_effect', arm+'_shared_prior', arm+'_repeat')
                    pair(arm+'_fixed_base_effect', arm+'_shared_prior', arm+'_fixed_base_diagnostic')
                    pair(arm+'_forecast_removal', arm+'_shared_prior', arm+'_without_forecasts')
                    if arm != 'Ego':
                        pair(arm+'_once_evidence', 'Ego_once', arm+'_once')
                        pair(arm+'_shared_evidence', 'Ego_shared_prior', arm+'_shared_prior')
                        pair(arm+'_remote_removal', arm+'_shared_prior', arm+'_without_remote')
                        pair(arm+'_stripped_vs_ego', 'Ego_shared_prior', arm+'_without_remote')
                for intervention in ('scene','environment'):
                    pair('Ego_'+intervention+'_removal', 'Ego_shared_prior', 'Ego_without_'+intervention)
                content = {arm: _content(prepared[arm], base[0].cpu().numpy(), 8.) for arm in CONDITIONS}
                result = dict(sample_id=selected[0]['sample_id'], scene=selected[0]['scene'],
                    g=selected[0]['g'], recording=selected[0]['recording'], role='validation',
                    checkpoint_step=step, label=label, source_tasks=tasks,
                    common_prior_valid=ego_prior is not None, outputs=outputs, pairs=pairs,
                    content=content, seconds=time.perf_counter()-frame_start)
                trace.write(json.dumps(result, ensure_ascii=False, allow_nan=False)+'\n'); trace.flush()
                results.append(result)
            print(json.dumps(dict(frame=fi+1, total=len(frames), g=selected[0]['g'],
                seconds=round(time.perf_counter()-start,2), forwards=audit['actual_model_forwards'])), flush=True)
        audit['model_parameters_unchanged'] = all(all(torch.equal(v.detach().cpu(), states[s][k])
            for k,v in m.state_dict().items()) for s,m in models.items())
        audit['checkpoint_files_unchanged'] = all(Path(v['checkpoint']).stat().st_size == v['size'] and
            Path(v['checkpoint']).stat().st_mtime_ns == v['mtime_ns'] for v in metadata.values())
        if not audit['model_parameters_unchanged'] or not audit['checkpoint_files_unchanged']:
            raise ValueError('frozen model/checkpoint changed')
        summaries = {}
        for step in checkpoints:
            group = [r for r in results if r['checkpoint_step']==step]
            summaries[str(step)] = dict(all=_summary(group), recordings={recording: _summary(
                [r for r in group if r['recording']==recording]) for recording in sorted({r['recording'] for r in group})},
                obstacle_interaction_proxy=_summary([r for r in group if any(
                    r['content'][arm]['obstacle_interaction_proxy'] for arm in ('P','F','PF'))]),
                no_obstacle_interaction_proxy=_summary([r for r in group if not any(
                    r['content'][arm]['obstacle_interaction_proxy'] for arm in ('P','F','PF'))]))
        (output/'summary.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        audit.update(state='completed', rows=len(results), wall_seconds=time.perf_counter()-start)
        (output/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')
    except Exception as exc:
        (output/'failure.json').write_text(json.dumps(dict(error=repr(exc),audit=audit,
            completed_rows=len(results),wall_seconds=time.perf_counter()-start),indent=2)+'\n')
        raise
    finally:
        trace.close()
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--checkpoints', nargs='+', type=int, default=[500,0,3200])
    args = parser.parse_args()
    print(json.dumps(run(args.source,args.output,args.checkpoints,args.device)), flush=True)


if __name__ == '__main__':
    main()
