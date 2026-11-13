#!/usr/bin/env python3
"""Independent frozen-result audit. Standard library only; never fits or calibrates.

Only --self-test may be run before the parent confirms experiment completion.
Production statistical functions are neither imported nor read by this script.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import time
from datetime import datetime, timezone

METHODS = ('Count', 'CountQ', 'D_old', 'D_zero', 'I_zero', 'J_zero',
           'G_zero', 'Q_zero', 'MATE_policy')
OLD = ('D_old', 'D_zero', 'I_zero', 'J_zero', 'MATE_policy')
DECISIONS = ('accept', 'unknown', 'reject')
EPS = 1e-12


def read(path):
    return json.loads(Path(path).read_text())


def rows_at(path):
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def primary(row, truth):
    if not row.get('query_present') or row.get('newborn'):
        return False
    if truth == 1:
        return row['kind'] == 'clean' and row.get('query_truth') == 1
    return (row['kind'] == 'attack' and row.get('query_truth') == 0
            and row.get('attack_role') == 'target')


def epoch(row):
    return (row['job_id'], row['id'], row['epoch'])


def entity(row):
    return (row['job_id'], row.get('attack_role'))


def weights(rows, truth):
    """Class-normalized family/k -> parent -> query epoch -> unique time index."""
    layers = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    seen = set()
    for row in rows:
        layer = (row['family'], row['attack_k']) if truth == 0 else ('clean', 0)
        key = (row['parent'], epoch(row), row['index'])
        if key in seen:
            raise ValueError('duplicate primary epoch/index: ' + repr(key))
        seen.add(key)
        layers[layer][row['parent']][epoch(row)].add(row['index'])
    result = []
    for row in rows:
        layer = (row['family'], row['attack_k']) if truth == 0 else ('clean', 0)
        parents = layers[layer]
        epochs = parents[row['parent']]
        result.append(1.0 / (len(layers) * len(parents) * len(epochs)
                             * len(epochs[epoch(row)])))
    if result and abs(math.fsum(result) - 1.0) > EPS:
        raise ValueError('class weights do not sum to one')
    return result


def base_score(model, x):
    if model is None or x is None:
        return None
    lengths = {len(x), len(model['mean']), len(model['scale']), len(model['coef'])}
    if len(lengths) != 1:
        raise ValueError('head dimension mismatch')
    score = float(model['intercept']) + math.fsum(
        ((v - mean) / scale) * coef
        for v, mean, scale, coef in zip(x, model['mean'], model['scale'], model['coef']))
    if not math.isfinite(score):
        raise ValueError('nonfinite head score')
    return score


def increment_score(model, offset, value):
    if model is None or offset is None or value is None:
        return None
    score = offset + model['coefficient'] * value
    if not math.isfinite(score):
        raise ValueError('nonfinite increment score')
    return score


def count_inputs(feature):
    context = feature['context']
    x = feature['features'].get('D_head')
    if x is None:
        return None
    # Missing scans are absent from this actual U=0 list; w*d-n_plus is invalid.
    return [x[2], math.fsum(feature['n_minus']), *context]


def reconstruct_scores(feature, fitted):
    models = fitted['models']
    result = dict.fromkeys(METHODS)
    if not feature.get('finite', True):
        return result
    for method, source in [('D_old', 'D_head'), ('D_zero', 'D_head'),
                           ('I_zero', 'I_Jmargin'), ('G_zero', 'G')]:
        result[method] = base_score(models.get(method), feature['features'].get(source))
    result['Count'] = base_score(models.get('Count'), count_inputs(feature))
    result['J_zero'] = increment_score(models.get('J_zero'), result['I_zero'], feature.get('delta_T'))
    for method, baseline in [('CountQ', 'Count'), ('Q_zero', 'I_zero')]:
        offset = result[baseline]
        result[method] = increment_score(models.get(method), offset,
                                         None if offset is None else offset * offset)
    mean = feature.get('native_mean')
    if mean is not None and math.isfinite(mean):
        result['MATE_policy'] = mean - 0.5
    return result


def decide(row, score, policy):
    if score is None or not row.get('finite', True):
        return 'unknown'
    if (row['accept_eligible'] and policy['A'] is not None
            and score > 0 and score >= policy['A']):
        return 'accept'
    if (row['reject_eligible'] and policy['R'] is not None
            and score < 0 and score <= policy['R']):
        return 'reject'
    return 'unknown'


def six_cells(rows):
    result = {method: {} for method in METHODS}
    for truth, label in [(1, 'true'), (0, 'false')]:
        subset = [r for r in rows if primary(r, truth)]
        mass = weights(subset, truth)
        for method in METHODS:
            counts = Counter(r['decisions'][method] for r in subset)
            result[method][label] = dict(
                n=len(subset), parents=len({r['parent'] for r in subset}),
                epochs=len({epoch(r) for r in subset}),
                physical_entities=len({entity(r) for r in subset}) if truth == 0 else None,
                counts={d: counts[d] for d in DECISIONS},
                raw={d: counts[d] / len(subset) if subset else None for d in DECISIONS},
                weighted={d: math.fsum(w for r, w in zip(subset, mass)
                                       if r['decisions'][method] == d) if subset else None
                          for d in DECISIONS})
    for method in METHODS:
        t = result[method]['true']['weighted']['accept']
        f = result[method]['false']['weighted']['reject']
        result[method]['correct_definite'] = None if t is None or f is None else (t + f) / 2
    return result


def paired(rows, candidate, baseline):
    groups = defaultdict(list)
    for row in rows:
        if primary(row, 1):
            groups[(row['parent'], *epoch(row))].append(row)
    parent_counts = Counter(k[0] for k in groups)
    details = []
    never = {method: 0.0 if groups else None for method in (candidate, baseline)}
    for key, group in sorted(groups.items()):
        first = {method: min((r['timestamp'] for r in group
                              if r['decisions'][method] == 'accept'), default=None)
                 for method in (candidate, baseline)}
        weight = 1.0 / (len(parent_counts) * parent_counts[key[0]])
        for method in (candidate, baseline):
            if first[method] is None:
                never[method] += weight
        details.append(dict(parent=key[0], epoch=list(key[1:]), first_accept=first))
    shared = [r for r in details if all(v is not None for v in r['first_accept'].values())]
    shared_counts = Counter(r['parent'] for r in shared)
    values = sorted((r['first_accept'][candidate] - r['first_accept'][baseline],
                     1.0 / (len(shared_counts) * shared_counts[r['parent']])) for r in shared)
    median = None
    cumulative = 0.0
    for value, weight in values:
        cumulative += weight
        if cumulative >= .5:
            median = value
            break
    return dict(candidate=candidate, baseline=baseline, n_primary_true_epochs=len(groups),
                n_parents=len(parent_counts), never=never,
                never_difference=None if not groups else never[candidate] - never[baseline],
                shared_ever_epochs=len(shared), weighted_median_delay_difference_seconds=median,
                status='ok' if shared else 'insufficient_no_common_ever_adopted_epoch')


def missing_score(row, method):
    score = row['scores'].get(method)
    return score is None or not math.isfinite(score)


def expected_unknown_reason(row, method, global_status):
    """Two frozen semantic abstentions; neither exempts a numerical failure."""
    state = row.get('method_status', {}).get(method, {})
    allowed = (global_status in ('ok', 'reference') and row.get('finite') is True
               and method in row['scores'] and row['scores'][method] is None
               and state.get('status') == 'unavailable' and not row.get('error')
               and not state.get('error') and row['decisions'].get(method) == 'unknown')
    if not allowed:
        return None
    if row.get('accept_eligible') is False and row.get('reject_eligible') is False:
        return 'no_common_decision_eligibility'
    if (method == 'MATE_policy' and global_status == 'reference'
            and row.get('output_present') is False and 'native_mean' in row
            and row['native_mean'] is None and row.get('native_adopted') is False):
        return 'expected_reference_abstention'
    return None


def primary_integrity(rows, method, global_status):
    selected = [r for r in rows if primary(r, 0) or primary(r, 1)]
    raw_missing = raw_failed = blocking_missing = blocking_failed = 0
    reasons = Counter()
    states = Counter()
    for row in selected:
        state = row.get('method_status', {}).get(method, {}).get('status', 'absent')
        states[state] += 1
        missing = missing_score(row, method)
        failed = row.get('finite') is not True or state not in ('ok', 'reference')
        raw_missing += missing
        raw_failed += failed
        reason = expected_unknown_reason(row, method, global_status)
        if reason is not None:
            reasons[reason] += 1
        else:
            blocking_missing += missing
            blocking_failed += failed
    return dict(n_total=len(selected), n_missing_score=raw_missing, n_failed=raw_failed,
                states=dict(states), expected_unknown=sum(reasons.values()),
                expected_unknown_by_reason=dict(reasons), blocking_missing_score=blocking_missing,
                blocking_failed=blocking_failed)


def coverage(rows, fitted):
    false = [r for r in rows if primary(r, 0)]
    return dict(n_rows=len(rows), primary_true=sum(primary(r, 1) for r in rows),
                primary_false=len(false), primary_false_parents=len({r['parent'] for r in false}),
                primary_false_physical_entities=len({entity(r) for r in false}),
                primary_false_query_epochs=len({epoch(r) for r in false}),
                no_query=sum(not r.get('query_present') for r in rows),
                newborn=sum(bool(r.get('newborn')) for r in rows),
                unknown_labels=sum(r.get('query_truth') not in (0, 1) for r in rows),
                attack_true_background=sum(r['kind'] == 'attack' and r.get('query_truth') == 1 for r in rows),
                nonfinite_rows=sum(not r.get('finite', True) for r in rows),
                methods={m: dict(n_missing_score=sum(missing_score(r, m) for r in rows),
                                primary=primary_integrity(rows, m, fitted['method_status'].get(m, {}).get('status')),
                                states=dict(Counter(r.get('method_status', {}).get(m, {}).get('status', 'absent') for r in rows)))
                         for m in METHODS})


def summarize(rows, families, fitted):
    layers = [f + '/' + str(k) for f in families for k in (1, 2)]
    family_k = {}
    for layer in layers:
        family, k = layer.split('/')
        subset = [r for r in rows if r['family'] == family and r['attack_k'] == int(k)]
        family_k[layer] = dict(metrics=six_cells(subset), coverage=coverage(subset, fitted))
    return dict(system_query=six_cells(rows), coverage=coverage(rows, fitted), family_k=family_k,
                by_parent={p: six_cells([r for r in rows if r['parent'] == p])
                           for p in sorted({r['parent'] for r in rows})},
                first_windows={name: six_cells([r for r in rows if condition(r)])
                               for name, condition in [
                                   ('length_1', lambda r: r['w'] == 1),
                                   ('length_2_to_9', lambda r: 2 <= r['w'] <= 9),
                                   ('length_10', lambda r: r['w'] == 10)]},
                paired_timeliness={c + '_vs_' + b: paired(rows, c, b)
                                   for c, b in [('D_zero', 'D_old'), ('J_zero', 'I_zero')]})


def difference(a, b):
    return None if a is None or b is None else a - b


def criterion(value, limit, direction='max', denominator=None):
    status = 'insufficient' if value is None else (
        'pass' if (value <= limit + EPS if direction == 'max' else value >= limit - EPS) else 'fail')
    return dict(value=value, limit=limit, direction=direction, status=status, denominator=denominator)


def combine(criteria):
    states = [v['status'] for v in criteria.values()]
    return 'fail' if 'fail' in states else 'insufficient' if 'insufficient' in states else 'pass'


def adjudicate(metrics, regime, fitted, tasks, gates):
    main = metrics['system_query']
    def risk(method, required):
        c = dict(false_accept=criterion(main[method]['false']['weighted']['accept'], gates['false_accept_max'], denominator=main[method]['false']['n']),
                 true_reject=criterion(main[method]['true']['weighted']['reject'], gates['true_reject_max'], denominator=main[method]['true']['n']))
        for layer, values in metrics['family_k'].items():
            cov = values['coverage']
            c['false_accept_' + layer] = criterion(values['metrics'][method]['false']['weighted']['accept'],
                gates['family_k_false_accept_max'], denominator=cov)
            enough = (cov['primary_false_parents'] >= gates['false_cell_min_parents']
                      and cov['primary_false_physical_entities'] >= gates['false_cell_min_entities'])
            c['coverage_' + layer] = dict(value=cov, limit=dict(parents=3, physical_entities=3),
                                          status='pass' if enough else 'insufficient')
        for required_method in required:
            numerical = metrics['coverage']['methods'][required_method]['primary']
            available = fitted['method_status'].get(required_method, {}).get('status') in ('ok', 'reference')
            c['required_model/' + required_method] = criterion(int(available), 1, 'min')
            c['primary_missing_score/' + required_method] = criterion(numerical['blocking_missing_score'], 0)
            c['primary_failed/' + required_method] = criterion(numerical['blocking_failed'], 0)
        c['execution_complete'] = dict(value=tasks['status_counts'], status='pass' if tasks['execution_complete'] else 'insufficient')
        return c
    required_main = ['D_zero', 'D_old'] + (['MATE_policy', 'Count', 'CountQ'] if regime == 'mixed' else [])
    required_joint = ['J_zero', 'I_zero', 'G_zero', 'Q_zero'] + (['MATE_policy'] if regime == 'mixed' else [])
    c = risk('D_zero', required_main)
    ta = lambda m: main[m]['true']['weighted']['accept']
    cd = lambda m: main[m]['correct_definite']
    c['true_accept_drop_vs_D_old'] = criterion(difference(ta('D_old'), ta('D_zero')), gates['main_true_accept_drop_vs_D_old_max'])
    c['CD_drop_vs_D_old'] = criterion(difference(cd('D_old'), cd('D_zero')), gates['main_CD_drop_vs_D_old_max'])
    if regime == 'mixed':
        c['true_accept_gap_to_MATE'] = criterion(difference(ta('MATE_policy'), ta('D_zero')), gates['mixed_true_accept_gap_to_MATE_max'])
    timing = metrics['paired_timeliness']['D_zero_vs_D_old']
    c['never_adopted_increase'] = criterion(timing['never_difference'], gates['never_adopted_increase_max'], denominator=timing['n_primary_true_epochs'])
    c['paired_median_delay'] = criterion(timing['weighted_median_delay_difference_seconds'], gates['paired_median_delay_increase_seconds_max'], denominator=timing['shared_ever_epochs'])
    primary_result = dict(status=combine(c), criteria=c)
    conditional = dict(c)
    if regime == 'mixed':
        for control in ('Count', 'CountQ'):
            conditional['CD_gain_vs_' + control] = criterion(difference(cd('D_zero'), cd(control)), gates['mixed_condition_CD_gain_over_each_Count_Control_min'], direction='min')
    joint = risk('J_zero', required_joint)
    for control in ('I_zero', 'G_zero', 'Q_zero'):
        joint['CD_gain_vs_' + control] = criterion(difference(cd('J_zero'), cd(control)), gates['joint_CD_gain_over_each_I_G_Q_zero_min'], direction='min')
    joint['true_accept_drop_vs_I_zero'] = criterion(difference(ta('I_zero'), ta('J_zero')), gates['joint_true_accept_drop_vs_I_zero_max'])
    if regime == 'mixed':
        joint['true_accept_gap_to_MATE'] = criterion(difference(ta('MATE_policy'), ta('J_zero')), gates['mixed_true_accept_gap_to_MATE_max'])
    return dict(primary=primary_result, conditional=dict(status=combine(conditional), criteria=conditional),
                joint=dict(status=combine(joint), criteria=joint))


def task_status(out, config):
    details = []
    for job in config['jobs']:
        path = out / 'jobs' / job['job_id'] / 'complete.json'
        completion = read(path) if path.exists() else dict(status='MISSING')
        details.append(dict(job_id=job['job_id'], parent=job['parent'], family=job['family'],
                            attack_k=job['attack_k'], completion=completion))
    counts = Counter(x['completion']['status'] for x in details)
    complete = all(x['completion']['status'] in ('COMPLETE', 'UNREALIZABLE') for x in details)
    return dict(n_expected_jobs=len(config['jobs']), n_expected_parents=len(config['additional_eval_parents']),
                status_counts=dict(counts), execution_complete=complete, jobs=details,
                unrealizable_is_defense_success=False)


def construction_coverage(tasks, all_eval_rows):
    grouped = defaultdict(list)
    for row in all_eval_rows:
        if primary(row, 0):
            grouped[row['job_id']].append(row)
    entities = {}
    for job in tasks['jobs']:
        if job['family'] == 'clean':
            continue
        subset = grouped[job['job_id']]
        status = job['completion']['status']
        constructed = status == 'COMPLETE'
        entities[job['job_id'] + '/target'] = dict(
            parent=job['parent'], family=job['family'], attack_k=job['attack_k'],
            status=status, constructed=constructed, definite_false_query=bool(subset),
            query_epochs=len({epoch(row) for row in subset}), rows=len(subset),
            no_definite_query=constructed and not subset)
    return dict(entities=entities, attempts=len(entities),
                constructed=sum(e['constructed'] for e in entities.values()),
                definite_false_entities=sum(e['definite_false_query'] for e in entities.values()),
                constructed_without_definite_query=sum(e['no_definite_query'] for e in entities.values()),
                unrealizable=sum(e['status'] == 'UNREALIZABLE' for e in entities.values()))


def compare_construction(independent, supplied):
    errors = []
    for field in ('attempts', 'constructed', 'definite_false_entities', 'constructed_without_definite_query', 'unrealizable'):
        if independent[field] != supplied[field]:
            errors.append(dict(path='construction_coverage/' + field, expected=independent[field], actual=supplied[field]))
    if set(independent['entities']) != set(supplied['entities']):
        errors.append(dict(path='construction_coverage/entities', error='physical_entity_set_mismatch'))
    for key, entity_record in independent['entities'].items():
        if key not in supplied['entities']:
            continue
        for field, wanted in entity_record.items():
            actual = supplied['entities'][key][field]
            if actual != wanted:
                errors.append(dict(path='construction_coverage/entities/' + key + '/' + field, expected=wanted, actual=actual))
    return dict(n_errors=len(errors), errors=errors)


def close(a, b, tolerance=1e-9):
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)
    return a == b


def audit_split(out, config, regime, split, fitted, calibration):
    predictions = list(rows_at(out / 'predictions' / regime / (split + '.jsonl.gz')))
    feature_root = out / 'features' / split if split == 'eval' else Path(config['source_features']) / split
    if split == 'eval':
        candidates = config['jobs']
        families = config['regimes'][regime]['eval_false']
        jobs = {j['job_id'] for j in candidates
                if (j['kind'] == 'clean' or j['family'] in families)
                and (out / 'jobs' / j['job_id'] / 'complete.json').exists()
                and read(out / 'jobs' / j['job_id'] / 'complete.json')['status'] == 'COMPLETE'}
    else:
        candidates = read(config['source_manifest'])['jobs']
        families = calibration['cal_false']
        # Old completion definitions, rather than a glob, determine this source set.
        source_root = Path(config['source_manifest']).parent
        old_statuses = read(source_root / 'prepare.complete.json')['jobs']
        jobs = set()
        for job in candidates:
            if job['split'] != 'cal' or (job['kind'] != 'clean' and job['family'] not in families):
                continue
            status = old_statuses[job['job_id']]
            if status['status'] == 'COMPLETE' and status.get('rows', 0) > 0:
                jobs.add(job['job_id'])
    features = {}
    for job_id in sorted(jobs):
        for feature in rows_at(feature_root / (job_id + '.jsonl.gz')):
            key = tuple(feature['key'])
            if key in features:
                raise ValueError('duplicate feature key ' + repr(key))
            features[key] = feature
    errors = []
    max_error = dict.fromkeys(METHODS, 0.0)
    matched = set()
    for row in predictions:
        key = tuple(row['key'])
        if key in matched:
            raise ValueError('duplicate prediction key ' + repr(key))
        matched.add(key)
        feature = features[key]
        expected = reconstruct_scores(feature, fitted)
        for method in METHODS:
            actual = row['scores'].get(method)
            wanted = expected[method]
            if actual is not None and wanted is not None:
                max_error[method] = max(max_error[method], abs(actual - wanted))
            if not close(actual, wanted):
                errors.append(dict(key=list(key), method=method, field='score', expected=wanted, actual=actual))
            # Validate the saved score numerically, then apply its exact threshold.
            # Reassociating a dot product can shift a threshold tie by one ULP.
            state = decide(row, actual, calibration['policies'][method])
            if row['decisions'].get(method) != state:
                errors.append(dict(key=list(key), method=method, field='decision', expected=state, actual=row['decisions'].get(method)))
        if 'Count_inputs' in row and row['Count_inputs'] != count_inputs(feature):
            errors.append(dict(key=list(key), field='Count_inputs', expected=count_inputs(feature), actual=row['Count_inputs']))
        if 'n0' in row and row['n0'] != row['d'] - row['m']:
            errors.append(dict(key=list(key), field='n0'))
        for name in ('query_present', 'newborn', 'query_truth', 'kind', 'family', 'attack_k', 'attack_role', 'parent', 'epoch', 'index',
                     'accept_eligible', 'reject_eligible'):
            if row.get(name) != feature.get(name):
                errors.append(dict(key=list(key), field=name, expected=feature.get(name), actual=row.get(name)))
        for name, wanted in zip(('w', 'd', 'm'), feature['context']):
            if row.get(name) != wanted:
                errors.append(dict(key=list(key), field=name, expected=wanted, actual=row.get(name)))
    missing = sorted(set(features) - matched)
    if missing:
        errors.append(dict(field='prediction_population', n_missing=len(missing), sample=[list(k) for k in missing[:10]]))
    return predictions, dict(n_predictions=len(predictions), n_joined_features=len(matched),
                             n_expected_features=len(features), n_expected_jobs=len(jobs),
                             primary_class_counts={str(truth): sum(primary(r, truth) for r in predictions) for truth in (0, 1)},
                             actual_parents=sorted({r['parent'] for r in predictions}),
                             actual_families=sorted({r['family'] for r in predictions if r['kind'] == 'attack'}),
                             observed_false_layers=sorted({(r['family'], r['attack_k']) for r in predictions if primary(r, 0)}),
                             primary_integrity={m: primary_integrity(predictions, m, fitted['method_status'].get(m, {}).get('status')) for m in METHODS},
                             max_absolute_score_error=max_error, n_errors=len(errors), errors=errors[:100])


def compare_six(expected, actual, path, errors):
    for method in METHODS:
        for label in ('true', 'false'):
            for field in ('n', 'parents', 'epochs'):
                a, b = expected[method][label][field], actual[method][label][field]
                if not close(a, b):
                    errors.append(dict(path=path + '/' + method + '/' + label + '/' + field, expected=a, actual=b))
            for field in ('counts', 'raw', 'weighted'):
                for decision in DECISIONS:
                    a, b = expected[method][label][field][decision], actual[method][label][field][decision]
                    if not close(a, b):
                        errors.append(dict(path=path + '/' + method + '/' + label + '/' + field + '/' + decision, expected=a, actual=b))
        a, b = expected[method]['correct_definite'], actual[method]['correct_definite']
        if not close(a, b):
            errors.append(dict(path=path + '/' + method + '/CD', expected=a, actual=b))


def compare_primary_integrity(independent, supplied, prefix):
    errors = []
    aliases = dict(expected_unknown=('expected_unknown', 'n_expected_unknown'),
                   blocking_missing_score=('blocking_missing_score', 'n_blocking_missing_score', 'n_missing_score_blocking'),
                   blocking_failed=('blocking_failed', 'n_blocking_failed', 'n_failed_blocking'))
    for field, wanted in independent.items():
        if field == 'expected_unknown' and not any(name in supplied for name in aliases[field]):
            if sum(supplied['expected_unknown_by_reason'].values()) != wanted:
                errors.append(dict(path=prefix + '/' + field, expected=wanted, actual=supplied['expected_unknown_by_reason']))
            continue
        names = aliases.get(field, (field,))
        name = next((name for name in names if name in supplied), None)
        actual = supplied.get(name)
        if name is None or actual != wanted:
            errors.append(dict(path=prefix + '/' + field, expected=wanted, actual=actual))
    return errors


def compare_report(metrics, report, corrected=False):
    errors = []
    actual = report.get('metrics', report)
    if 'eval' in actual:
        actual = actual['eval']
    compare_six(metrics['system_query'], actual['system_query'], 'system_query', errors)
    for parent, value in metrics['by_parent'].items():
        compare_six(value, actual['by_parent'][parent], 'by_parent/' + parent, errors)
    for layer, value in metrics['family_k'].items():
        layer_actual = actual['family_k'][layer]
        compare_six(value['metrics'], layer_actual.get('metrics', layer_actual.get('methods')), 'family_k/' + layer, errors)
        support = layer_actual['support']
        expected_support = dict(parents=value['coverage']['primary_false_parents'],
                                entities=value['coverage']['primary_false_physical_entities'],
                                query_epochs=value['coverage']['primary_false_query_epochs'],
                                rows=value['coverage']['primary_false'])
        for field, wanted in expected_support.items():
            if support[field] != wanted:
                errors.append(dict(path='family_k/' + layer + '/support/' + field, expected=wanted, actual=support[field]))
    for name, value in metrics['first_windows'].items():
        if name not in actual['first_windows']:
            errors.append(dict(path='first_windows/' + name, error='missing_layer'))
        else:
            compare_six(value, actual['first_windows'][name], 'first_windows/' + name, errors)
    for candidate, baseline in [('D_zero', 'D_old'), ('J_zero', 'I_zero')]:
        independent = metrics['paired_timeliness'][candidate + '_vs_' + baseline]
        supplied = actual['paired_timeliness'][candidate]
        expected_pair = {field: independent[field] for field in
                         ('candidate', 'baseline', 'n_primary_true_epochs', 'n_parents',
                          'never_difference', 'shared_ever_epochs', 'weighted_median_delay_difference_seconds')}
        expected_pair.update(candidate_never=independent['never'][candidate], baseline_never=independent['never'][baseline])
        for field, wanted in expected_pair.items():
            if not close(wanted, supplied[field]):
                errors.append(dict(path='paired_timeliness/' + candidate + '/' + field, expected=wanted, actual=supplied[field]))
    for method in METHODS:
        independent = metrics['coverage']['methods'][method]
        supplied = actual['method_score_coverage'][method]
        expected_coverage = dict(n_total=metrics['coverage']['n_rows'],
                                 n_finite=metrics['coverage']['n_rows'] - independent['n_missing_score'],
                                 states=independent['states'])
        for field, wanted in expected_coverage.items():
            if wanted != supplied[field]:
                errors.append(dict(path='method_score_coverage/' + method + '/' + field, expected=wanted, actual=supplied[field]))
        if corrected:
            errors.extend(compare_primary_integrity(independent['primary'], supplied['primary'],
                                                     'method_score_coverage/' + method + '/primary'))
    return dict(n_errors=len(errors), errors=errors)


def compare_original_corrected(original, corrected):
    errors = []
    for split in ('cal', 'eval'):
        for field in ('system_query', 'first_windows', 'by_parent', 'family_k',
                      'paired_timeliness', 'transitions', 'coverage'):
            if original['metrics'][split][field] != corrected['metrics'][split][field]:
                errors.append(dict(path=split + '/' + field, error='original_corrected_changed'))
    for field in ('policies', 'calibration', 'fit_false', 'eval_false', 'method_status'):
        if original[field] != corrected[field]:
            errors.append(dict(path=field, error='original_corrected_changed'))
    return dict(n_errors=len(errors), errors=errors)


def old_unchanged(config, regime, fitted, calibration):
    original = read(Path(config['source_original_scores']) / 'models' / (regime + '.json'))
    zero = read(Path(config['source_zero_scores']) / 'models' / (regime + '.json'))
    source_policy = read(Path(config['source_zero_scores']) / 'calibration' / (regime + '.json'))['policies']
    errors = []
    for method in OLD:
        if calibration['policies'][method] != source_policy[method]:
            errors.append(method + ': policy changed')
        if method != 'MATE_policy':
            expected = original['models']['D_head'] if method == 'D_old' else zero['models'][method]
            if fitted['models'][method] != expected:
                errors.append(method + ': model changed')
    if fitted.get('old_fitted') != original:
        errors.append('old_fitted source changed')
    if fitted.get('zero_fitted') != zero:
        errors.append('zero_fitted source changed')
    return dict(status='pass' if not errors else 'fail', errors=errors, n_reused_methods=5)


def source_only_audit(config, regime, fitted, calibration, audits, source_rows):
    errors = []
    source_families = config['regimes'][regime]['fit_false']
    fit_parents = sorted(p for p, split in config['old_parent_splits'].items() if split == 'fit')
    cal_parents = sorted(p for p, split in config['old_parent_splits'].items() if split == 'cal')
    selected = [r for r in source_rows if primary(r, 1) or (primary(r, 0) and r['family'] in source_families)]
    true = [r for r in selected if primary(r, 1)]
    false = [r for r in selected if primary(r, 0)]
    selected = true + false
    mass = [w * .5 for w in weights(true, 1)] + [w * .5 for w in weights(false, 0)]
    def check(value, wanted, path):
        if isinstance(value, list) and isinstance(wanted, list) and len(value) == len(wanted):
            equal = all(close(a, b) for a, b in zip(value, wanted))
        else:
            equal = close(value, wanted)
        if not equal:
            errors.append(dict(path=path, expected=wanted, actual=value))
    check(fitted['fit_false'], source_families, 'fit_false')
    for method in ('Count', 'G_zero'):
        model = fitted['models'][method]
        check(model['train_parents'], fit_parents, method + '/train_parents')
        check(model['fit_false'], source_families, method + '/fit_false')
        check(model['n_samples'], len(selected), method + '/n_samples')
        check(model['false_cells'], sorted({r['family'] + '/' + str(r['attack_k']) for r in false}), method + '/false_cells')
        vectors = [count_inputs(r) if method == 'Count' else list(r['features']['G']) for r in selected]
        if method == 'G_zero':
            for x in vectors:
                x[4] = 0.0
            check(model['coef'][4], 0.0, 'G_zero/d_fixed')
            if model['coef'][0] < -EPS or model['coef'][1] < -EPS:
                errors.append(dict(path='G_zero/sign_constraints'))
        mean = [math.fsum(w * x[i] for w, x in zip(mass, vectors)) for i in range(len(vectors[0]))]
        std = [math.sqrt(math.fsum(w * (x[i] - mean[i]) ** 2 for w, x in zip(mass, vectors))) for i in range(len(mean))]
        check(model['mean'], mean, method + '/mean_source_only')
        check(model['scale'], [s if s >= 1e-6 else 1.0 for s in std], method + '/scale_source_only')
    for method, baseline in [('CountQ', 'Count'), ('Q_zero', 'I_zero')]:
        model = fitted['models'][method]
        offsets = [base_score(fitted['models'][baseline], count_inputs(r) if baseline == 'Count' else r['features']['I_Jmargin']) for r in selected]
        rms = math.sqrt(math.fsum(w * s ** 4 for w, s in zip(mass, offsets)))
        check(model['rms'], rms, method + '/RMS_fixed_source_offset')
        check(model['n_samples'], len(selected), method + '/n_samples')
        check(model['coefficient'], model['coef_std'] / rms, method + '/coefficient_scaling')
        check(model['scaling'], 'weighted_RMS_no_centering', method + '/scaling')
    expected_cal_false = ['F0', 'F1', 'F2'] if regime == 'mixed' else source_families
    check(calibration['cal_false'], expected_cal_false, 'cal_false')
    check(calibration['cal_parents'], cal_parents, 'cal_parents')
    check(audits['cal']['actual_parents'], cal_parents, 'actual_cal_parents')
    check(audits['cal']['actual_families'], expected_cal_false, 'actual_cal_false')
    check(calibration['observed_layers'], [list(x) for x in audits['cal']['observed_false_layers']], 'observed_cal_layers')
    check(sorted({r['parent'] for r in selected}), fit_parents, 'actual_fit_parents')
    if set(config['additional_eval_parents']) & set(config['old_parent_splits']):
        errors.append(dict(path='parent_split_overlap'))
    return dict(status='pass' if not errors else 'fail', n_errors=len(errors), errors=errors,
                n_fit_true=len(true), n_fit_false=len(false), fit_parents=fit_parents,
                source_false_families=source_families, calibration_false_families=expected_cal_false,
                scope='parameter lineage, normalization and offset RMS verification; no optimization or calibration')


def compare_retention(metrics, regime, fitted, tasks, gates, audits, supplied):
    errors = []
    table = metrics['system_query']
    verdict = lambda checks: {'pass': 'retained', 'fail': 'not_retained', 'insufficient': 'evidence_insufficient'}[combine(checks)]
    for kind, candidate, baseline, controls in [('main', 'D_zero', 'D_old', ('Count', 'CountQ')),
                                                 ('joint', 'J_zero', 'I_zero', ('I_zero', 'G_zero', 'Q_zero'))]:
        both = table[candidate]['true']['n'] > 0 and table[candidate]['false']['n'] > 0
        calibrated = all(audits['cal']['primary_class_counts'][str(t)] > 0 for t in (0, 1))
        available = fitted['method_status'][candidate]['status'] in ('ok', 'reference')
        n_finite = metrics['coverage']['n_rows'] - metrics['coverage']['methods'][candidate]['n_missing_score']
        estimable = available and n_finite > 0 and both and calibrated and tasks['execution_complete']
        numeric = metrics['coverage']['methods'][candidate]['states'].get('numeric_failure', 0)
        checks = dict(estimable=criterion(float(estimable), 1., 'min'),
                      numeric_failures=criterion(numeric, 0.), both_classes=criterion(float(both), 1., 'min'),
                      calibration_classes=criterion(float(calibrated), 1., 'min'),
                      tasks_complete=criterion(float(tasks['execution_complete']), 1., 'min'),
                      false_accept=criterion(table[candidate]['false']['weighted']['accept'], gates['false_accept_max']),
                      true_reject=criterion(table[candidate]['true']['weighted']['reject'], gates['true_reject_max']))
        for layer, record in metrics['family_k'].items():
            cov = record['coverage']
            enough = cov['primary_false_parents'] >= 3 and cov['primary_false_physical_entities'] >= 3
            checks[layer + '/coverage'] = criterion(float(enough), 1., 'min')
            if not enough:
                checks[layer + '/coverage']['status'] = 'insufficient'
            if cov['primary_false']:
                checks[layer + '/false_accept'] = criterion(record['metrics'][candidate]['false']['weighted']['accept'], gates['family_k_false_accept_max'])
        ta = lambda m: table[m]['true']['weighted']['accept']
        cd = lambda m: table[m]['correct_definite']
        checks['TA_drop_vs_' + baseline] = criterion(difference(ta(baseline), ta(candidate)), .02)
        if kind == 'main':
            checks['CD_drop_vs_D_old'] = criterion(difference(cd(baseline), cd(candidate)), .02)
            timing = metrics['paired_timeliness']['D_zero_vs_D_old']
            checks['never_adopted_increase'] = criterion(timing['never_difference'], .05)
            checks['paired_median_delay_increase'] = criterion(timing['weighted_median_delay_difference_seconds'], .5)
        if regime == 'mixed':
            checks['TA_gap_to_MATE'] = criterion(difference(ta('MATE_policy'), ta(candidate)), .05)
        required = [candidate, baseline] if kind == 'main' else [candidate, *controls]
        if regime == 'mixed':
            required += ['MATE_policy'] + (list(controls) if kind == 'main' else [])
        for method in required:
            p = metrics['coverage']['methods'][method]['primary']
            checks['primary_missing_score/' + method] = criterion(p['blocking_missing_score'], 0.)
            checks['primary_failed/' + method] = criterion(p['blocking_failed'], 0.)
            checks['required_model/' + method] = criterion(float(fitted['method_status'][method]['status'] in ('ok', 'reference')), 1., 'min')
        risk_verdict = verdict(checks)
        if kind == 'joint' or regime == 'mixed':
            for control in controls:
                checks['CD_gain_over_' + control] = criterion(difference(cd(candidate), cd(control)), .01, 'min')
        given = supplied[kind]
        if set(checks) != set(given['checks']):
            errors.append(dict(path=kind + '/check_names', expected=sorted(checks), actual=sorted(given['checks'])))
        for name, expected in checks.items():
            actual = given['checks'].get(name, {})
            for field in ('value', 'limit', 'direction', 'status'):
                if not close(expected[field], actual.get(field)):
                    errors.append(dict(path=kind + '/' + name + '/' + field, expected=expected[field], actual=actual.get(field)))
        for field, expected in [('status', verdict(checks)), ('risk_utility_status', risk_verdict)]:
            if given[field] != expected:
                errors.append(dict(path=kind + '/' + field, expected=expected, actual=given[field]))
    return dict(n_errors=len(errors), errors=errors)


def self_test():
    def r(parent, job, ident, step, truth=1, family='clean', k=0, decisions=None):
        return dict(parent=parent, job_id=job, id=ident, epoch=0, index=step,
                    query_present=True, newborn=False, kind='clean' if truth else 'attack',
                    query_truth=truth, family=family, attack_k=k, attack_role=None if truth else 'target',
                    timestamp=step * .1, decisions=decisions or dict.fromkeys(METHODS, 'unknown'))
    true = [r('p1', 'j1', 1, i) for i in range(2)] + [r('p1', 'j1', 2, 0), r('p2', 'j2', 1, 0)]
    assert weights(true, 1) == [.125, .125, .25, .5]
    false = [r('p1', 'a1', 1, 0, 0, 'F1', 1), r('p1', 'a1', 2, 0, 0, 'F1', 1),
             r('p2', 'a2', 1, 0, 0, 'F1', 1), r('p1', 'a3', 1, 0, 0, 'F2', 2)]
    assert weights(false, 0) == [.125, .125, .25, .5]
    assert len({entity(x) for x in false}) == 3 and len({epoch(x) for x in false}) == 4
    true[0]['decisions'] = dict.fromkeys(METHODS, 'accept')
    false[-1]['decisions'] = dict.fromkeys(METHODS, 'reject')
    cells = six_cells(true + false)
    assert cells['D_zero']['true']['weighted']['accept'] == .125
    assert cells['D_zero']['false']['weighted']['reject'] == .5
    assert cells['D_zero']['correct_definite'] == .3125
    assert criterion(.06, .05)['status'] == 'fail'
    assert criterion(None, .05)['status'] == 'insufficient'
    f = dict(context=[3, 2, 1], features=dict(D_head=[0, 0, 2, 3, 2, 1]), n_minus=[1])
    assert count_inputs(f) == [2, 1., 3, 2, 1]  # NOT [2, 4, 3, 2, 1]
    model = dict(intercept=.5, mean=[1, 2], scale=[2, 1], coef=[4, -1])
    assert base_score(model, [3, 4]) == 2.5
    assert increment_score(dict(coefficient=.25), 2., 4.) == 3.
    row = dict(finite=True, accept_eligible=True, reject_eligible=True)
    policy = dict(A=.2, R=-.2)
    assert decide(row, .2, policy) == 'accept' and decide(row, -.2, policy) == 'reject'
    assert decide(row, 0., dict(A=0., R=0.)) == 'unknown'
    assert decide(dict(row, finite=False), 5., policy) == 'unknown'
    excluded = dict(true[0], newborn=True)
    assert not primary(excluded, 1)
    assert six_cells([excluded])['D_zero']['true']['weighted']['accept'] is None
    abstain = dict(true[0], finite=True, accept_eligible=False, reject_eligible=False,
                   scores=dict.fromkeys(METHODS), decisions=dict.fromkeys(METHODS, 'unknown'),
                   method_status={m: dict(status='unavailable') for m in METHODS}, error=None,
                   output_present=False, native_mean=None, native_adopted=False)
    assert expected_unknown_reason(abstain, 'D_zero', 'ok') == 'no_common_decision_eligibility'
    reference = dict(abstain, reject_eligible=True)
    assert expected_unknown_reason(reference, 'MATE_policy', 'reference') == 'expected_reference_abstention'
    assert expected_unknown_reason(reference, 'D_zero', 'ok') is None
    assert expected_unknown_reason(reference, 'MATE_policy', 'unestimable') is None
    for broken in [dict(abstain, finite=False), dict(abstain, error='failed'),
                   dict(abstain, scores=dict(abstain['scores'], D_zero=float('nan'))),
                   dict(abstain, scores=dict(abstain['scores'], D_zero=float('inf'))),
                   dict(abstain, method_status=dict(abstain['method_status'], D_zero=dict(status='numeric_failure')))]:
        assert expected_unknown_reason(broken, 'D_zero', 'ok') is None
    integrity = primary_integrity([abstain, dict(reference, index=7)], 'D_zero', 'ok')
    assert integrity['n_total'] == 2 and integrity['n_missing_score'] == 2 and integrity['n_failed'] == 2
    assert integrity['expected_unknown'] == 1 and integrity['blocking_missing_score'] == 1 and integrity['blocking_failed'] == 1
    print(json.dumps(dict(status='pass', scope='hand_calculated_fixture_only', production_data_read=False)))


def main():
    start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--report-dir', type=Path, help='Report directory, absolute or relative to --out')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.config is None or args.out is None:
        parser.error('--config and --out required')
    out = args.out
    report_dir = out / 'report' if args.report_dir is None else (
        args.report_dir if args.report_dir.is_absolute() else out / args.report_dir)
    corrected = report_dir.resolve() != (out / 'report').resolve()
    if not (out / 'run.complete.json').exists():
        raise RuntimeError('formal run not complete; independent recount must wait')
    config = read(args.config)
    tasks = task_status(out, config)
    source_root = Path(config['source_manifest']).parent
    folds = read(source_root / 'features.complete.json')['folds']
    source_rows = []
    for fold in folds:
        source_rows.extend(rows_at(source_root / fold['features']))
    result = dict(schema='rq1_report_freeze_independent_recount_v1', tasks=tasks,
                  report_dir=str(report_dir), regimes={}, started_at=started_at,
                  checker_schema_adaptations=[
                      'no_common_decision_eligibility reason name',
                      'blocking fields n_missing_score_blocking and n_failed_blocking',
                      'expected_unknown total is the sum of reason counts',
                      'old prepare.complete job states and nonempty row definitions',
                      'models carry no standalone provenance field; verify saved parameters and old source inputs'])
    all_eval_rows = None
    for regime, spec in config['regimes'].items():
        fitted = read(out / 'models' / (regime + '.json'))
        calibration = read(out / 'calibration' / (regime + '.json'))
        audits = {}
        for split in ('cal', 'eval'):
            rows, audits[split] = audit_split(out, config, regime, split, fitted, calibration)
            if split == 'eval':
                metrics = summarize(rows, spec['eval_false'], fitted)
                if regime == 'mixed':
                    all_eval_rows = rows
        supplied_report = read(report_dir / (regime + '.json'))
        if corrected:
            for method in METHODS:
                errors = compare_primary_integrity(audits['cal']['primary_integrity'][method],
                    supplied_report['metrics']['cal']['method_score_coverage'][method]['primary'],
                    'cal/method_score_coverage/' + method + '/primary')
                audits['cal']['n_errors'] += len(errors)
                audits['cal']['errors'].extend(errors)
        result['regimes'][regime] = dict(metrics=metrics, score_decision_audit=audits,
            old_unchanged=old_unchanged(config, regime, fitted, calibration),
            production_report=compare_report(metrics, supplied_report, corrected),
            original_corrected_unchanged=compare_original_corrected(read(out / 'report' / (regime + '.json')), supplied_report),
            source_only=source_only_audit(config, regime, fitted, calibration, audits, source_rows),
            production_retention=compare_retention(metrics, regime, fitted, tasks, config['gates'], audits, supplied_report['retention']),
            retention=adjudicate(metrics, regime, fitted, tasks, config['gates']))
    result['construction_coverage'] = construction_coverage(tasks, all_eval_rows)
    result['production_construction'] = compare_construction(result['construction_coverage'],
                                                            read(report_dir / 'metrics.json')['construction_coverage'])
    error_count = sum(sum(a['n_errors'] for a in r['score_decision_audit'].values())
                      + len(r['old_unchanged']['errors']) + r['production_report']['n_errors'] + r['original_corrected_unchanged']['n_errors']
                      + r['source_only']['n_errors'] + r['production_retention']['n_errors']
                      for r in result['regimes'].values()) + result['production_construction']['n_errors']
    result['n_audit_errors'] = error_count
    result['status'] = 'pass' if error_count == 0 else 'fail'
    result['n_prediction_rows'] = sum(a['n_predictions'] for r in result['regimes'].values() for a in r['score_decision_audit'].values())
    result['wall_seconds'] = time.perf_counter() - start
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    destination = Path(__file__).resolve().parent
    (destination / 'recount.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 独立结果复核', '', '本复核仅使用Python标准库，未导入生产统计函数，未拟合或校准。',
             '', '统计与分数复核状态为' + result['status'] + '，差异数为' + str(error_count) + '。',
             '核对预测行数' + str(result['n_prediction_rows']) + '，耗时' + f"{result['wall_seconds']:.3f}" + '秒。',
             '开始与结束UTC时间分别为' + started_at + '、' + result['finished_at'] + '。',
             '', '物理假实体使用job_id与target角色，query epoch仅作统计层级。不可构造和技术未完成均不算防御成功。', '']
    for regime, r in result['regimes'].items():
        lines += ['## ' + regime, '', '|方法|真采纳|真拒绝|假采纳|假拒绝|CD|', '|---|---:|---:|---:|---:|---:|']
        def fmt(x):
            return '不足' if x is None else f'{100*x:.4f}%'
        for method in METHODS:
            m = r['metrics']['system_query'][method]
            lines.append('|' + '|'.join([method, fmt(m['true']['weighted']['accept']), fmt(m['true']['weighted']['reject']),
                                        fmt(m['false']['weighted']['accept']), fmt(m['false']['weighted']['reject']), fmt(m['correct_definite'])]) + '|')
        lines += ['', '主候选 ' + r['retention']['primary']['status'] + '。条件增量 ' + r['retention']['conditional']['status']
                  + '。联合增量 ' + r['retention']['joint']['status'] + '。', '']
    lines += ['本批是额外开发评价，不是未见终测，不推翻旧k3及旧迁移失败。统计一致不表示候选通过研究门槛或获得部署风险保证。',
              '检查器只适配了JSON显示字段，详细适配记录、分层、分母、合法Unknown和逐项门槛保留在recount.json。', '']
    (destination / 'result_review.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=result['status'], n_prediction_rows=result['n_prediction_rows'], n_audit_errors=error_count,
                          wall_seconds=result['wall_seconds'], destination=str(destination))))
    if error_count:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
