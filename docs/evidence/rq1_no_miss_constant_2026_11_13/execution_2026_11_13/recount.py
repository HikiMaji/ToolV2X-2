#!/usr/bin/env python3
"""Independent recount of the frozen no-miss-constant development comparison.

Only Python standard library and saved artifacts are used. No production modules
are imported. Thresholds and model parameters are never estimated here.
Run the full recount once, only after the parent confirms run.complete.json.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

METHODS = ('D_old', 'I_old', 'J_old', 'D_zero', 'I_zero', 'J_zero', 'I_cut', 'MATE_policy')
PAIRS = {'D_zero': 'D_old', 'I_zero': 'I_old', 'J_zero': 'J_old'}
OLD_NAMES = {'D_old': 'D_head', 'I_old': 'I_Jmargin', 'J_old': 'J', 'MATE_policy': 'MATE_policy'}
STATES = ('accept', 'reject', 'unknown')
REGIMES = {
    'mixed': {'fit': ('F1', 'F2'), 'cal': ('F0', 'F1', 'F2'), 'eval': ('F0', 'F1', 'F2')},
    'F1_only': {'fit': ('F1',), 'cal': ('F1',), 'eval': ('F2',)},
    'F2_only': {'fit': ('F2',), 'cal': ('F2',), 'eval': ('F1',)},
}
TOL = 1e-10
SCORE_TOL = 1e-9
# Fixed identities already examined before this batch. Their old failure status
# is independently rechecked from source F2_only predictions during full recount.
PREDECLARED_KEYS = {('605ff9c3ca7bf3a5', 117, 212)} | {
    ('cf2ad1a17529d018', frame, 185) for frame in (117, 119, 121, 123, 125, 127)}


def read_json(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def read_lines(path, compact=False):
    rows = []
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if compact:
                    for key in ('method_status', 'contributions', 'sources'):
                        row.pop(key, None)
                rows.append(row)
    return rows


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def epoch(row):
    return row['parent'], row['job_id'], str(row['id']), str(row['epoch'])


def identity(row):
    return epoch(row) + (row['index'],)


def cell(row):
    return '%s/%s' % (row['family'], row['attack_k'])


def primary_class(row):
    if not row['query_present'] or row['newborn']:
        return None
    if row['kind'] == 'clean' and row['query_truth'] == 1:
        return 'true'
    if row['kind'] == 'attack' and row['attack_role'] == 'target' and row['query_truth'] == 0:
        return 'false'
    return None


def selected(row, regime, split):
    return row['kind'] == 'clean' or row['family'] in REGIMES[regime][split]


def weights(rows, false=False):
    """Mass one, true parent/epoch/scan; false family-k/parent/epoch/scan."""
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for index, row in enumerate(rows):
        groups[cell(row) if false else 'all'][row['parent']][epoch(row)].append(index)
    result = [0.0] * len(rows)
    for parents in groups.values():
        for epochs in parents.values():
            for indices in epochs.values():
                value = 1.0 / (len(groups) * len(parents) * len(epochs) * len(indices))
                for index in indices:
                    result[index] = value
    if rows and abs(math.fsum(result) - 1.0) > TOL:
        raise AssertionError('independent hierarchical weights do not sum to one')
    return result


def decide(row, method, policy):
    value = row['scores'][method]
    finite = row['finite'].get(method, False) if isinstance(row['finite'], dict) else row['finite']
    if not finite or value is None or not math.isfinite(value):
        return 'unknown'
    if not row['query_present'] or row['newborn']:
        return 'unknown'
    if policy['A'] is not None and row['accept_eligible'] and value >= policy['A']:
        return 'accept'
    if policy['R'] is not None and row['reject_eligible'] and value <= policy['R']:
        return 'reject'
    return 'unknown'


def class_summary(rows, method, false=False, decision_field='_decision'):
    mass = weights(rows, false)
    counts = Counter(row[decision_field][method] for row in rows)
    return {
        'n': len(rows), 'parents': len({row['parent'] for row in rows}),
        'epochs': len({epoch(row) for row in rows}),
        'injected_entities': len({row['job_id'] for row in rows}) if false else None,
        'counts': {state: counts[state] for state in STATES},
        'raw': {state: counts[state]/len(rows) if rows else None for state in STATES},
        'weighted': {state: math.fsum(w for row, w in zip(rows, mass)
                                    if row[decision_field][method] == state) if rows else None
                     for state in STATES},
    }


def summary(rows, method, decision_field='_decision'):
    true = [row for row in rows if primary_class(row) == 'true']
    false = [row for row in rows if primary_class(row) == 'false']
    result = {'true': class_summary(true, method, False, decision_field),
              'false': class_summary(false, method, True, decision_field)}
    ta, fr = result['true']['weighted']['accept'], result['false']['weighted']['reject']
    result['correct_definite'] = (ta + fr)/2 if ta is not None and fr is not None else None
    return result


def family_metrics(rows):
    result = {}
    for family in ('F0', 'F1', 'F2', 'F3'):
        for k in (1, 2, 3):
            key = '%s/%s' % (family, k)
            layer = [row for row in rows if row['family'] == family and row['attack_k'] == k]
            result[key] = {method: summary(layer, method) for method in METHODS}
    return result


def transitions(rows, candidate, baseline):
    result = {}
    for cls in ('true', 'false'):
        data = [row for row in rows if primary_class(row) == cls]
        mass = weights(data, cls == 'false')
        counts = Counter((row['_decision'][baseline], row['_decision'][candidate]) for row in data)
        result[cls] = {
            'n': len(data),
            'counts': {a: {b: counts[a, b] for b in STATES} for a in STATES},
            'weighted': {a: {b: math.fsum(w for row, w in zip(data, mass)
                                         if row['_decision'][baseline] == a
                                         and row['_decision'][candidate] == b) if data else None
                              for b in STATES} for a in STATES},
        }
    return result


def weighted_median(pairs):
    if not pairs:
        return None
    total = math.fsum(weight for _, weight in pairs)
    cumulative = 0.0
    for value, weight in sorted(pairs):
        cumulative += weight/total
        if cumulative >= .5 - 1e-15:
            return value
    return sorted(pairs)[-1][0]


def timing(rows, candidate, baseline):
    data = defaultdict(list)
    for row in rows:
        if primary_class(row) == 'true':
            data[epoch(row)].append(row)
    parents = Counter(key[0] for key in data)
    first = {}
    never = {candidate: 0.0, baseline: 0.0}
    for key, values in data.items():
        origin = min(row['timestamp'] for row in values)
        first[key] = {}
        for method in (candidate, baseline):
            times = [row['timestamp'] for row in values if row['_decision'][method] == 'accept']
            first[key][method] = min(times)-origin if times else None
            if not times:
                never[method] += 1/(len(parents)*parents[key[0]])
    common = [key for key in data if all(first[key][m] is not None for m in (candidate, baseline))]
    common_parents = Counter(key[0] for key in common)
    delays = [(first[key][candidate]-first[key][baseline],
               1/(len(common_parents)*common_parents[key[0]])) for key in common]
    return {
        'n_primary_true_epochs': len(data), 'n_parents': len(parents),
        'candidate_never': never[candidate] if data else None,
        'baseline_never': never[baseline] if data else None,
        'never_difference': never[candidate]-never[baseline] if data else None,
        'shared_ever_epochs': len(common), 'shared_parents': len(common_parents),
        'weighted_median_delay_difference_seconds': weighted_median(delays),
        'epochs': {
            '/'.join(key): dict(origin=min(row['timestamp'] for row in data[key]),
                                first_accept={m: None if first[key][m] is None else
                                              first[key][m]+min(row['timestamp'] for row in data[key])
                                              for m in (candidate, baseline)},
                                **({'delay_difference_seconds': first[key][candidate]-first[key][baseline],
                                    'paired_weight': 1/(len(common_parents)*common_parents[key[0]])}
                                   if key in common else {}))
            for key in data},
        'shared_epoch_delay_differences': [dict(parent=key[0], job_id=key[1], id=key[2], epoch=key[3],
                                              difference=first[key][candidate]-first[key][baseline])
                                          for key in common],
    }


def compare(actual, expected, path, errors, tol=TOL):
    """Strict recursive comparison, including every list element and mapping key."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            errors.append({'path': path, 'keys_independent': sorted(actual), 'keys_reported': sorted(expected)})
        for key in sorted(set(actual) & set(expected)):
            compare(actual[key], expected[key], path+'.'+str(key), errors, tol)
    elif isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            errors.append({'path': path, 'length_independent': len(actual), 'length_reported': len(expected)})
        for index, (a, b) in enumerate(zip(actual, expected)):
            compare(a, b, path+'.'+str(index), errors, tol)
    elif actual is None or expected is None or isinstance(actual, bool) or isinstance(expected, bool):
        if actual != expected:
            errors.append({'path': path, 'independent': actual, 'reported': expected})
    elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual-expected) > tol:
            errors.append({'path': path, 'independent': actual, 'reported': expected, 'tolerance': tol})
    elif actual != expected:
        errors.append({'path': path, 'independent': actual, 'reported': expected})


def difference(a, b):
    return a-b if a is not None and b is not None else None


def gate(value, bound, direction='le'):
    status = 'insufficient' if value is None else ('pass' if
        (value <= bound+1e-12 if direction == 'le' else value >= bound-1e-12) else 'fail')
    return {'value': value, 'bound': bound, 'direction': direction, 'status': status}


def candidate_gates(results, candidate, baseline, cfg, models_available):
    t = cfg['thresholds']
    result = {}
    for regime in REGIMES:
        block = results[regime]['eval']
        own, old = block['methods'][candidate], block['methods'][baseline]
        prefix = regime+'.'
        result[prefix+'model_available'] = {'status': 'pass' if models_available[regime][candidate] else 'insufficient'}
        result[prefix+'true_reject'] = gate(own['true']['weighted']['reject'], t['risk'])
        result[prefix+'false_accept'] = gate(own['false']['weighted']['accept'], t['risk'])
        for key, layer in block['family_k'].items():
            # Empty cells stay visible as untested coverage, but only nonempty
            # cells are conjunctive risk gates in the frozen protocol.
            if layer[candidate]['false']['n']:
                result[prefix+key+'.false_accept'] = gate(layer[candidate]['false']['weighted']['accept'], t['risk'])
        result[prefix+'TA_drop'] = gate(difference(old['true']['weighted']['accept'], own['true']['weighted']['accept']), t['max_TA_drop'])
        result[prefix+'CD_drop'] = gate(difference(old['correct_definite'], own['correct_definite']), t['max_CD_drop'])
        time = block['timing'][candidate]
        result[prefix+'never_increase'] = gate(time['never_difference'], t['max_never_adopted_increase'])
        result[prefix+'paired_delay_seconds'] = gate(time['weighted_median_delay_difference_seconds'], t['max_paired_delay_seconds'])
    mixed = results['mixed']['eval']['methods']
    result['mixed.MATE_TA_deficit'] = gate(difference(mixed['MATE_policy']['true']['weighted']['accept'], mixed[candidate]['true']['weighted']['accept']), t['max_mixed_MATE_TA_deficit'])
    cd_gain = gate(difference(mixed[candidate]['correct_definite'], mixed[baseline]['correct_definite']), t['min_mixed_CD_gain'], 'ge')
    reverse = results['F2_only']['eval']['family_k']['F1/3']
    new_fa = reverse[candidate]['false']['weighted']['accept']
    old_fa = reverse[baseline]['false']['weighted']['accept']
    reduction = gate(difference(old_fa, new_fa), t['min_reverse_F1_k3_FA_reduction'], 'ge')
    final_risk = gate(new_fa, t['risk'])
    alternative = 'pass' if reduction['status'] == final_risk['status'] == 'pass' else (
        'fail' if 'fail' in (reduction['status'], final_risk['status']) else 'insufficient')
    improvement = 'pass' if 'pass' in (cd_gain['status'], alternative) else (
        'fail' if cd_gain['status'] == alternative == 'fail' else 'insufficient')
    result['actual_improvement'] = {'status': improvement, 'mixed_CD_gain': cd_gain,
                                    'reverse_F1_k3_FA_reduction': reduction, 'reverse_F1_k3_final_FA': final_risk}
    statuses = [value['status'] for value in result.values()]
    result['overall'] = 'fail' if 'fail' in statuses else ('insufficient' if 'insufficient' in statuses else 'pass')
    return result


def base_score(model, values):
    if model.get('status') != 'ok' or not model.get('optimizer_ok') or values is None:
        return None
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        return None
    return model['intercept'] + math.fsum(c*(x-m)/s for c, x, m, s in
                                         zip(model['coef'], values, model['mean'], model['scale']))


def raw_parameters(model):
    coef = [c/s for c, s in zip(model['coef'], model['scale'])]
    intercept = model['intercept'] - math.fsum(c*m for c, m in zip(coef, model['mean']))
    return intercept, coef


def fit_moments(rows, feature_name):
    true = [row for row in rows if primary_class(row) == 'true']
    false = [row for row in rows if primary_class(row) == 'false']
    data = true+false
    mass = [w*.5 for w in weights(true)] + [w*.5 for w in weights(false, True)]
    mean = [math.fsum(w*row['features'][feature_name][j] for row, w in zip(data, mass)) for j in range(6)]
    std = [math.sqrt(math.fsum(w*(row['features'][feature_name][j]-mean[j])**2
                               for row, w in zip(data, mass))) for j in range(6)]
    return data, mass, mean, std


def audit_fitted(regime, fit_rows, old, fitted, errors):
    """Reconstruct source-only supervision/scaler moments, without fitting."""
    rows = [row for row in fit_rows if primary_class(row) and selected(row, regime, 'fit')]
    true = [row for row in rows if primary_class(row) == 'true']
    false = [row for row in rows if primary_class(row) == 'false']
    parents = sorted({row['parent'] for row in rows})
    false_cells = sorted({cell(row) for row in false})
    prefix = 'models.'+regime
    compare(fitted['fit_false'], list(REGIMES[regime]['fit']), prefix+'.fit_false', errors)
    compare(fitted['n_supervision'], len(rows), prefix+'.n_supervision', errors)
    result = {'n_supervision': len(rows), 'true': len(true), 'false': len(false),
              'parents': parents, 'false_cells': false_cells, 'models': {}}
    availability = {}
    for name, old_name in (('D_zero', 'D_head'), ('I_zero', 'I_Jmargin')):
        mod, original = fitted['models'][name], old['models'][old_name]
        available = mod.get('status') == 'ok' and bool(mod.get('optimizer_ok'))
        availability[name] = available
        if not available:
            result['models'][name] = {'available': False, 'saved_status': mod.get('status')}
            continue
        data, mass, mean, std = fit_moments(rows, old_name)
        invalid = [identity(row) for row in data if len(row['features'][old_name]) != 6 or
                   not all(math.isfinite(value) for value in row['features'][old_name])]
        compare(invalid, [], prefix+'.'+name+'.unusable_supervision', errors)
        for field, expected in [('train_parents', parents), ('false_cells', false_cells),
                                ('fit_false', list(REGIMES[regime]['fit'])),
                                ('n_samples', len(rows)), ('class_weight', [.5, .5]),
                                ('weight_sum', 1.0), ('structurally_fixed', ['d'])]:
            compare(mod[field], expected, prefix+'.'+name+'.'+field, errors)
        projected_mean, projected_std = list(mean), list(std)
        projected_mean[4] = projected_std[4] = 0.0
        constant = [value <= 1e-6 for value in projected_std]
        scale = [1.0 if fixed else value for fixed, value in zip(constant, projected_std)]
        for field, expected in [('mean', projected_mean), ('std', projected_std),
                                ('constant', constant), ('scale', scale)]:
            compare(mod[field], expected, prefix+'.'+name+'.'+field, errors)
        for field, expected in [('original_d_mean', mean[4]), ('original_d_std', std[4]),
                                ('original_d_variance', std[4]**2),
                                ('free_parameters', 1+sum(not value for value in constant))]:
            compare(mod[field], expected, prefix+'.'+name+'.'+field, errors)
        for field in ('mean', 'std', 'scale', 'constant'):
            compare([mod[field][j] for j in (0, 1, 2, 3, 5)],
                    [original[field][j] for j in (0, 1, 2, 3, 5)],
                    prefix+'.'+name+'.five_unprojected_columns_match_old.'+field, errors)
        raw_intercept, raw_coef = raw_parameters(mod)
        # Exact structural zero is stronger than a floating tolerance check.
        if mod['coef'][4] != 0.0 or raw_coef[4] != 0.0:
            errors.append({'path': prefix+'.'+name+'.gamma', 'error': 'structural d coefficient is not exactly zero'})
        if any(raw_coef[j] < 0 for j in (0, 1)):
            errors.append({'path': prefix+'.'+name+'.sign', 'error': 'negative constrained evidence coefficient'})
        for j, fixed in enumerate(constant):
            if fixed and mod['coef'][j] != 0.0:
                errors.append({'path': prefix+'.'+name+'.constant.'+str(j), 'error': 'constant-column coefficient is nonzero'})
        compare(mod['miss_condition_active'], raw_coef[1] > 0, prefix+'.'+name+'.miss_condition_active', errors)
        coverage = fitted['method_status'][name]['coverage']
        for field, expected in [('n_supervision', len(rows)), ('n_usable', len(rows)),
                                ('n_excluded', 0), ('expected_parents', parents),
                                ('usable_parents', parents), ('missing_usable_parents', [])]:
            compare(coverage[field], expected, prefix+'.'+name+'.coverage.'+field, errors)
        counts = Counter(row['parent'] for row in rows)
        for parent, count in counts.items():
            for field in ('n_supervision', 'n_usable'):
                compare(coverage['by_parent'][parent][field], count,
                        prefix+'.'+name+'.coverage.'+parent+'.'+field, errors)
        result['models'][name] = {'available': True, 'original_d_mean': mean[4],
                                  'original_d_std': std[4], 'projected_d_mean': 0.0,
                                  'projected_d_std': 0.0, 'raw_intercept': raw_intercept,
                                  'raw_coefficients': raw_coef, 'gamma_exact_zero': raw_coef[4] == 0.0,
                                  'conditional_miss_term_active': raw_coef[1] > 0,
                                  'scaler': {'mean': projected_mean, 'std': projected_std, 'scale': scale}}
    increment = fitted['models']['J_zero']
    availability['J_zero'] = increment.get('status') == 'ok' and bool(increment.get('optimizer_ok')) and availability['I_zero']
    data = true+false
    mass = [w*.5 for w in weights(true)]+[w*.5 for w in weights(false, True)]
    values = [row['delta_T'] for row in data]
    if availability['J_zero']:
        rms = math.sqrt(math.fsum(w*v*v for w, v in zip(mass, values)))
        mean = math.fsum(w*v for w, v in zip(mass, values))
        std = math.sqrt(math.fsum(w*(v-mean)**2 for w, v in zip(mass, values)))
        for field, expected in [('rms', rms), ('std', std), ('n_samples', len(rows)),
                                ('coefficient', increment['coef_std']/rms)]:
            compare(increment[field], expected, prefix+'.J_zero.'+field, errors)
        compare(increment['rms'], old['models']['J']['rms'], prefix+'.J_zero.same_delta_scaling.rms', errors)
        compare(increment['std'], old['models']['J']['std'], prefix+'.J_zero.same_delta_scaling.std', errors)
        result['models']['J_zero'] = {'available': True, 'rms': rms, 'std': std,
                                     'coefficient': increment['coefficient'],
                                     'interval_reestimated': False}
    else:
        result['models']['J_zero'] = {'available': False, 'saved_status': increment.get('status')}
    return result, availability


def score_reconstruction(feature, old, fitted):
    result = {}
    for name, model_name in (('D_old', 'D_head'), ('I_old', 'I_Jmargin')):
        result[name] = base_score(old['models'][model_name], feature['features'][model_name])
    for name, model_name in (('D_zero', 'D_head'), ('I_zero', 'I_Jmargin')):
        result[name] = base_score(fitted['models'][name], feature['features'][model_name])
    for name, base, model in (('J_old', 'I_old', old['models']['J']),
                              ('J_zero', 'I_zero', fitted['models']['J_zero'])):
        delta = feature['delta_T']
        result[name] = (result[base] + model['coefficient']*delta
                        if result[base] is not None and delta is not None and math.isfinite(delta)
                        and model.get('status') == 'ok' and model.get('optimizer_ok') else None)
    _, original_coef = raw_parameters(old['models']['I_Jmargin'])
    d, m = feature['features']['I_Jmargin'][4:6]
    result['I_cut'] = result['I_old']-original_coef[4]*(d-m) if result['I_old'] is not None else None
    native = feature['native_mean']
    result['MATE_policy'] = native-.5 if native is not None and math.isfinite(native) else None
    return result


def independent_evaluation(rows, policies, old_policy):
    for row in rows:
        row['_decision'] = {method: decide(row, method, policies[method]) for method in METHODS}
        row['_fixed_old_I_decision'] = {'I_cut': decide(row, 'I_cut', old_policy)}
    result = {'methods': {method: summary(rows, method) for method in METHODS},
              'family_k': family_metrics(rows),
              'timing': {candidate: timing(rows, candidate, baseline) for candidate, baseline in PAIRS.items()},
              'transitions': {candidate: transitions(rows, candidate, baseline)
                              for candidate, baseline in list(PAIRS.items())+[('I_cut', 'I_old')]},
              'I_cut_old_I_policy': summary(rows, 'I_cut', '_fixed_old_I_decision'),
              'n_rows': len(rows), 'primary_class_counts': dict(Counter(primary_class(row) or 'excluded' for row in rows))}
    result['by_parent'] = {parent: {method: summary([row for row in rows if row['parent'] == parent], method)
                                    for method in METHODS} for parent in sorted({row['parent'] for row in rows})}
    result['descriptive_layers'] = {}
    for axis in ('w', 'm', 'n0'):
        result['descriptive_layers'][axis] = {
            str(value): {method: summary([row for row in rows if
                        (row['d']-row['m'] if axis == 'n0' else row[axis]) == value], method)
                         for method in METHODS}
            for value in sorted({row['d']-row['m'] if axis == 'n0' else row[axis] for row in rows})}
    result['window_layers'] = {}
    for name, lower, upper in (('first', 1, 1), ('short', 2, 9), ('full', 10, 10)):
        layer = [row for row in rows if lower <= row['w'] <= upper]
        result['window_layers'][name] = {method: summary(layer, method) for method in METHODS}
    counts = Counter((row['w'], row['d'], row['m'], row['d']-row['m']) for row in rows)
    result['context_counts'] = [dict(w=key[0], d=key[1], m=key[2], n0=key[3], n=count)
                                for key, count in sorted(counts.items())]
    result['method_score_coverage'] = {
        method: dict(n_finite=sum(row['scores'][method] is not None and math.isfinite(row['scores'][method]) for row in rows),
                     n_total=len(rows), states=dict(Counter(row['method_status'][method]['status'] for row in rows)))
        for method in METHODS}
    result['predeclared_records'] = [
        {field: row[field] for field in ('key', 'w', 'd', 'm', 'scores', 'decisions', 'contributions', 'I_cut_removed')}
        for row in rows if tuple(row['key']) in PREDECLARED_KEYS]
    # The raw predictions remain the source for these records. Their changed
    # outcomes are descriptive, never a source for refitting or threshold choice.
    return result


def audit_rows(regime, split, rows, features, old_rows, old_model, fitted, calibration, old_cal, parent_splits, errors):
    prefix = regime+'.'+split
    saved = {identity(row): row for row in rows}
    original = {identity(row): row for row in old_rows}
    allowed = {key: row for key, row in features.items() if selected(row, regime, split)}
    if len(saved) != len(rows):
        errors.append({'path': prefix, 'error': 'duplicate prediction identity'})
    compare(sorted(saved), sorted(allowed), prefix+'.feature_prediction_keys', errors)
    compare(sorted(saved), sorted(original), prefix+'.old_prediction_keys', errors)
    score_max_difference = {method: 0.0 for method in METHODS}
    metadata = ('key', 'parent', 'split', 'job_id', 'id', 'epoch', 'index', 'frame',
                'timestamp', 'kind', 'family', 'attack_k', 'attack_role', 'query_present',
                'newborn', 'query_truth', 'query_gt_id', 'output_present', 'output_truth',
                'identity_ok', 'accept_eligible', 'reject_eligible', 'n_frames', 'context')
    for key, row in saved.items():
        if key not in allowed or key not in original:
            continue
        feature, old_row = allowed[key], original[key]
        path = prefix+'.'+str(key)
        if parent_splits[row['parent']] != split:
            errors.append({'path': path, 'error': 'parent split mismatch'})
        for field in metadata:
            compare(row[field], feature[field], path+'.metadata.'+field, errors)
            compare(row[field], old_row[field], path+'.old_metadata.'+field, errors)
        compare([row['w'], row['d'], row['m']], feature['features']['I_Jmargin'][3:6], path+'.window_context', errors)
        compare(row['n0'], row['d']-row['m'], path+'.n0', errors)
        _, original_coef = raw_parameters(old_model['models']['I_Jmargin'])
        removed = original_coef[4]*(row['d']-row['m'])
        compare(row['I_cut_removed'], removed, path+'.I_cut_removed', errors, SCORE_TOL)
        compare(row['contributions']['I_cut']['removed_gamma_n0'], removed, path+'.I_cut_contribution', errors, SCORE_TOL)
        expected_scores = score_reconstruction(feature, old_model, fitted)
        compare(row['scores'], expected_scores, path+'.scores', errors, SCORE_TOL)
        for method in METHODS:
            a, b = row['scores'][method], expected_scores[method]
            if a is not None and b is not None:
                score_max_difference[method] = max(score_max_difference[method], abs(a-b))
            expected_decision = decide(row, method, calibration['policies'][method])
            compare(row['decisions'][method], expected_decision, path+'.decisions.'+method, errors)
        for method, old_name in OLD_NAMES.items():
            compare(row['scores'][method], old_row['scores'][old_name], path+'.old_scores.'+method, errors, SCORE_TOL)
            compare(row['decisions'][method], old_row['decisions'][old_name], path+'.old_decisions.'+method, errors)
        if isinstance(row['finite'], dict):
            old_finite = old_row['finite']
            for method, old_name in OLD_NAMES.items():
                expected = old_finite[old_name] if isinstance(old_finite, dict) else old_finite
                compare(row['finite'][method], expected, path+'.old_finite.'+method, errors)
        else:
            compare(row['finite'], old_row['finite'], path+'.old_finite', errors)
    result = independent_evaluation(rows, calibration['policies'], old_cal['policies']['I_Jmargin'])
    result['coverage'] = {'feature_rows': len(allowed), 'prediction_rows': len(rows),
                          'old_prediction_rows': len(old_rows), 'keys_matched': len(set(saved)&set(allowed)&set(original)),
                          'max_score_reconstruction_difference': score_max_difference}
    return result


def compare_summary(actual, expected, path, errors):
    for cls in ('true', 'false'):
        for field in ('n', 'parents', 'epochs', 'counts', 'raw', 'weighted'):
            compare(actual[cls][field], expected[cls][field], path+'.'+cls+'.'+field, errors)
    compare(actual['correct_definite'], expected['correct_definite'], path+'.correct_definite', errors)


def compare_evaluation(actual, expected, path, errors):
    for method in METHODS:
        compare_summary(actual['methods'][method], expected['system_query'][method], path+'.system_query.'+method, errors)
    for key, methods in actual['family_k'].items():
        for method in METHODS:
            compare_summary(methods[method], expected['family_k'][key]['metrics'][method], path+'.family_k.'+key+'.'+method, errors)
        compare(methods['D_old']['false']['n'], expected['family_k'][key]['n_primary_false'], path+'.family_k.'+key+'.n_primary_false', errors)
        compare('observed' if methods['D_old']['false']['n'] else 'not_tested', expected['family_k'][key]['status'], path+'.family_k.'+key+'.status', errors)
    for own, saved in [('by_parent', 'by_parent')]:
        compare(sorted(actual[own]), sorted(expected[saved]), path+'.'+saved+'.keys', errors)
        for key, methods in actual[own].items():
            for method in METHODS:
                compare_summary(methods[method], expected[saved][key][method], path+'.'+saved+'.'+key+'.'+method, errors)
    for axis in ('w', 'm', 'n0'):
        layers = actual['descriptive_layers'][axis]
        compare(sorted(layers), sorted(expected['by_'+axis]), path+'.by_'+axis+'.keys', errors)
        for key, methods in layers.items():
            for method in METHODS:
                compare_summary(methods[method], expected['by_'+axis][key][method], path+'.by_'+axis+'.'+key+'.'+method, errors)
    for own, saved in [('first', 'length_1'), ('short', 'length_2_to_9'), ('full', 'length_10')]:
        for method in METHODS:
            compare_summary(actual['window_layers'][own][method], expected['first_windows'][saved][method], path+'.first_windows.'+saved+'.'+method, errors)
    compare(actual['context_counts'], expected['context_counts'], path+'.context_counts', errors)
    compare(actual['method_score_coverage'], expected['method_score_coverage'], path+'.method_score_coverage', errors)
    compare(actual['predeclared_records'], expected['predeclared_records'], path+'.predeclared_records', errors)
    compare_summary(actual['I_cut_old_I_policy'], expected['I_cut_old_policy'], path+'.I_cut_old_policy', errors)
    for candidate, baseline in PAIRS.items():
        own, saved = actual['timing'][candidate], expected['paired_timeliness'][candidate]
        for field in ('n_primary_true_epochs', 'n_parents', 'candidate_never', 'baseline_never',
                      'never_difference', 'shared_ever_epochs', 'weighted_median_delay_difference_seconds'):
            compare(own[field], saved[field], path+'.timing.'+candidate+'.'+field, errors)
        normalized = {'/'.join((row['parent'], row['epoch'][0], str(row['epoch'][1]), str(row['epoch'][2]))):
                      {key: value for key, value in row.items() if key not in ('parent', 'epoch')}
                      for row in saved['epochs']}
        compare(own['epochs'], normalized, path+'.timing.'+candidate+'.epochs', errors)
    for candidate, baseline in list(PAIRS.items())+[('I_cut', 'I_old')]:
        for cls, label in [('true', '1'), ('false', '0')]:
            own = actual['transitions'][candidate][cls]
            saved = expected['transitions'][candidate][label]
            compare(own['n'], saved['n'], path+'.transitions.'+candidate+'.'+cls+'.n', errors)
            for a in STATES:
                for b in STATES:
                    compare(own['counts'][a][b], saved['cells'][a+'/'+b]['n'], path+'.transitions.'+candidate+'.'+cls+'.'+a+'/'+b+'.n', errors)
                    compare(own['weighted'][a][b], saved['cells'][a+'/'+b]['weighted'], path+'.transitions.'+candidate+'.'+cls+'.'+a+'/'+b+'.weighted', errors)


def compare_retention(actual, expected, path, errors):
    for key, own in actual.items():
        if key in ('overall', 'actual_improvement') or key.endswith('.model_available'):
            continue
        name = key.replace('.', '/').replace('/paired_delay_seconds', '/paired_delay')
        saved = expected['checks'][name]
        compare(own['value'], saved['value'], path+'.'+name+'.value', errors)
        compare(own['bound'], saved['limit'], path+'.'+name+'.limit', errors)
        compare(own['status'], saved['status'], path+'.'+name+'.status', errors)
        compare('max' if own['direction'] == 'le' else 'min', saved['direction'], path+'.'+name+'.direction', errors)
    own, saved = actual['actual_improvement'], expected['checks']['actual_improvement']
    compare(own['status'], saved['status'], path+'.actual_improvement.status', errors)
    for own_key, saved_value in [('mixed_CD_gain', saved['alternatives']['mixed_CD_gain']),
                                ('reverse_F1_k3_FA_reduction', saved['alternatives']['reverse_F1_k3']['checks']['reduction']),
                                ('reverse_F1_k3_final_FA', saved['alternatives']['reverse_F1_k3']['checks']['final_risk'])]:
        for a, b in [('value', 'value'), ('bound', 'limit'), ('status', 'status')]:
            compare(own[own_key][a], saved_value[b], path+'.actual_improvement.'+own_key+'.'+a, errors)
    mapped = {'pass': 'retained', 'fail': 'not_retained', 'insufficient': 'not_tested'}[actual['overall']]
    compare(mapped, expected['status'], path+'.status', errors)


def full_recount(args):
    out, source = args.out.resolve(), args.source.resolve()
    if not (out/'run.complete.json').is_file():
        raise ValueError('run.complete.json absent; no full recount is authorized before completion')
    errors = []
    cfg = read_json(args.config)
    binding = read_json(out/'binding.json')
    compare(binding['config'], cfg, 'binding.config', errors)
    compare(cfg['methods'], list(METHODS), 'config.methods', errors)
    compare(cfg['candidate_baselines'], PAIRS, 'config.candidate_baselines', errors)
    for regime in REGIMES:
        for split in ('fit', 'cal', 'eval'):
            compare(cfg['regimes'][regime][split+'_false'], list(REGIMES[regime][split]), 'config.'+regime+'.'+split, errors)
    manifest = read_json(source/'manifest.json')
    parent_splits = manifest['parent_splits']
    report = {'schema': 'independent_rq1_no_miss_constant_recount_v1',
              'independence': {'stdlib_only': True, 'production_statistics_imported_or_read': False,
                               'thresholds_reselected': False, 'model_heads_refitted': False,
                               'normal_refitted': False, 'new_research_experiments': False,
                               'scope': 'seen development; constant constraint evaluation; no joint novelty or deployment guarantee'},
              'inputs': {'source': str(source), 'out': str(out), 'config_sha256': digest(args.config),
                         'script_sha256': digest(__file__), 'metrics_sha256': digest(out/'report/metrics.json')},
              'fit_audit': {}, 'regimes': {}}
    features = {}
    for split in ('fit', 'cal', 'eval'):
        rows = []
        for item in binding['features'][split]:
            path = source/item['path']
            rows.extend(read_lines(path, compact=True))
        features[split] = {identity(row): row for row in rows}
        if len(features[split]) != len(rows):
            errors.append({'path': 'features.'+split, 'error': 'duplicate feature identity'})
        for row in rows:
            if parent_splits[row['parent']] != split or row['split'] != split:
                errors.append({'path': 'features.'+split, 'error': 'source parent split mismatch', 'parent': row['parent']})
        print('Loaded saved source '+split+' features: '+str(len(rows)), flush=True)
    expected_report = read_json(out/'report/metrics.json')
    availability = {}
    for regime in REGIMES:
        old_model = read_json(source/'models'/(regime+'.json'))
        fitted = read_json(out/'models'/(regime+'.json'))
        report['fit_audit'][regime], availability[regime] = audit_fitted(regime, list(features['fit'].values()), old_model, fitted, errors)
        calibration = read_json(out/'calibration'/(regime+'.json'))
        old_cal = read_json(source/'calibration'/(regime+'.json'))
        compare(calibration['cal_false'], list(REGIMES[regime]['cal']), regime+'.cal_false', errors)
        for method, old_name in OLD_NAMES.items():
            compare(calibration['policies'][method], old_cal['policies'][old_name], regime+'.old_policy.'+method, errors)
        for method in METHODS:
            policy = calibration['policies'][method]
            if (policy['A'] is not None and policy['A'] <= 0) or (policy['R'] is not None and policy['R'] >= 0):
                errors.append({'path': regime+'.policy.'+method, 'error': 'threshold sign violation'})
        block = {}
        for split in ('cal', 'eval'):
            rows = read_lines(out/'predictions'/regime/(split+'.jsonl.gz'))
            old_rows = read_lines(source/'report/predictions'/regime/(split+'.jsonl.gz'), compact=True)
            if regime == 'F2_only' and split == 'eval':
                old_failures = [row for row in old_rows if primary_class(row) == 'false' and row['decisions']['J'] == 'accept']
                compare(sorted(tuple(row['key']) for row in old_failures),
                        sorted(key for key in PREDECLARED_KEYS if key[0] == 'cf2ad1a17529d018'),
                        'source.F2_only.old_J_false_accept_keys', errors)
            block[split] = audit_rows(regime, split, rows, features[split], old_rows, old_model, fitted, calibration, old_cal, parent_splits, errors)
            compare_evaluation(block[split], expected_report['regimes'][regime]['metrics'][split], regime+'.'+split, errors)
            if split == 'cal':
                compare(sorted({row['parent'] for row in rows}), calibration['cal_parents'], regime+'.cal_parents', errors)
                compare(sorted({row['job_id'] for row in rows}), calibration['cal_job_ids'], regime+'.cal_job_ids', errors)
                empty = [[fam, k] for fam, k in calibration['expected_layers']
                         if not block['cal']['family_k']['%s/%s' % (fam, k)]['D_old']['false']['n']]
                for method in METHODS:
                    compare(calibration['policies'][method]['missing_layers'], empty, regime+'.'+method+'.missing_cal_layers', errors)
            print('Recounted '+regime+'/'+split+': '+str(len(rows))+' saved predictions', flush=True)
        report['regimes'][regime] = block
    report['retention'] = {candidate: candidate_gates(report['regimes'], candidate, baseline, cfg, availability)
                           for candidate, baseline in PAIRS.items()}
    for candidate in PAIRS:
        compare_retention(report['retention'][candidate], expected_report['retention'][candidate], 'retention.'+candidate, errors)
    report['errors'] = errors
    report['statistical_recount_status'] = 'PASS' if not errors else 'FAIL'
    return report, expected_report


def write_results(report, destination):
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'recount.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    pct = lambda value: '不足' if value is None else '%.4f%%' % (100*value)
    main = report['regimes']['mixed']['eval']
    lines = ['# 常数约束批次独立结果重计', '',
             '统计重计 '+report['statistical_recount_status']+'，差异 '+str(len(report['errors']))+' 项。', '',
             '本次只用标准库与保存产物，独立重建主分母、真假分级权重、固定门限判决、真假六格、各非空family/k风险、配对真实epoch时效及对应旧方法的决策转移。未读取或导入本批生产统计实现，未重新拟合normal或评分头，未重选门限。', '',
             '模型检查包括三方案的源族筛选、父及family/k支持、gamma严格为0、原d方差单列、其余五列scaler与旧模型逐元素相等、J_zero无中心RMS，以及I_cut原尺度移除量。旧D/I/J/MATE校准及逐条分数、资格、标签和决策与原产物比较。', '',
             '## mixed主评价', '',
             '|方法|真采纳|真拒绝|真未知|假采纳|假拒绝|假未知|CD|',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for method in METHODS:
        block = main['methods'][method]
        values = [block[cls]['weighted'][state] for cls in ('true', 'false') for state in STATES]
        values.append(block['correct_definite'])
        lines.append('|'+method+'|'+'|'.join(pct(value) for value in values)+'|')
    lines += ['', '## 冻结保留判据', '']
    for candidate, baseline in PAIRS.items():
        checks = report['retention'][candidate]
        lines.append('- '+candidate+' 对 '+baseline+' 的裁决为 '+checks['overall']+'。'+('这是主裁决。' if candidate == 'D_zero' else '这是预声明次要裁决。'))
        for key, value in checks.items():
            if key != 'overall' and value['status'] != 'pass':
                lines.append('  - '+key+' 为 '+value['status']+'，数值 '+str(value.get('value'))+'，门槛 '+str(value.get('bound'))+'。')
    lines += ['', '实际改善的两种分支及全部通过、失败、不足项均保留在recount.json。候选分别裁决，不用另一候选的改善抵消失败。', '',
              '## 双向迁移与实际代价', '',
              '|方案|方法|真采纳|真拒绝|假采纳|假拒绝|CD|',
              '|---|---|---:|---:|---:|---:|---:|']
    for regime in ('F1_only', 'F2_only'):
        for method in METHODS:
            block = report['regimes'][regime]['eval']['methods'][method]
            values = [block['true']['weighted']['accept'], block['true']['weighted']['reject'],
                      block['false']['weighted']['accept'], block['false']['weighted']['reject'], block['correct_definite']]
            lines.append('|'+regime+'|'+method+'|'+'|'.join(pct(value) for value in values)+'|')
    lines += ['', 'F2_only评价F1/k3的假采纳如下。', '']
    for method in METHODS:
        layer = report['regimes']['F2_only']['eval']['family_k']['F1/3'][method]['false']
        lines.append('- '+method+' 为 '+pct(layer['weighted']['accept'])+'，原始记录 '+str(layer['n'])+'，父 '+str(layer['parents'])+'。')
    lines += ['', '## 固定参数移除诊断', '',
              '|方案|I_cut门限|真采纳|真拒绝|假采纳|假拒绝|CD|',
              '|---|---|---:|---:|---:|---:|---:|']
    for regime in REGIMES:
        for name, block in [('重新校准', report['regimes'][regime]['eval']['methods']['I_cut']),
                             ('沿用旧I', report['regimes'][regime]['eval']['I_cut_old_I_policy'])]:
            values = [block['true']['weighted']['accept'], block['true']['weighted']['reject'],
                      block['false']['weighted']['accept'], block['false']['weighted']['reject'], block['correct_definite']]
            lines.append('|'+regime+'|'+name+'|'+'|'.join(pct(value) for value in values)+'|')
    lines += ['', 'I_cut保持旧模型其余参数，是固定参数诊断；D_zero/I_zero还重新拟合剩余参数。两者不能合并解释为同一个因果效果。', '',
              '## 检查范围及研究边界', '',
              '空层、未校准层、标签未知、无query及方法不可估均按原分母规则保留。Unknown不计作正确明确判断。cal经验预算不提供迁移域或部署风险保证。', '',
              '本批使用已经查看过的开发资料。窗口时刻、query epoch和注入实体不增加独立父录制数。多控单父及F3缺失限制仍在。c没有可用区间，本次没有重抽或重拟合，不能把常数约束的开发评价称为联合创新。', '',
              '本次没有独立重跑优化器、normal或感知模型，没有重新证明在线特征的全部因果合法性。统计重计PASS只表示上述产物间及独立统计一致。', '',
              '初次入口曾在拟合前因完成标记大小写检查退出，历史error.json保留。后续run.complete和实际产物单独判断，不把历史入口失败误当作本次数值比较失败。', '']
    for regime in REGIMES:
        for split in ('cal', 'eval'):
            coverage = report['regimes'][regime][split]['coverage']
            lines.append('- '+regime+'/'+split+'核对预测 '+str(coverage['prediction_rows'])+' 条，匹配原特征与旧预测 '+str(coverage['keys_matched'])+' 条。')
    if report['errors']:
        lines += ['', '## 差异', '', '以下差异尚未消除，不能宣称数值验收通过。', '']
        lines.extend('- '+json.dumps(value, ensure_ascii=False) for value in report['errors'][:20])
    (destination/'result_review.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def self_check():
    def row(parent, ident, index, family='F1', k=1):
        return dict(parent=parent, job_id=parent, id=ident, epoch=0, index=index,
                    family=family, attack_k=k, kind='clean', query_present=True,
                    newborn=False, query_truth=1, attack_role=None)
    data = [row('a', 1, 0), row('a', 1, 1), row('a', 2, 0), row('b', 1, 0)]
    assert weights(data) == [.125, .125, .25, .5]
    assert weights(data+[row('a', 3, 0, 'F2', 2)], True) == [.0625, .0625, .125, .25, .5]
    assert weighted_median([(2, .5), (1, .5)]) == 1
    errors = []
    compare([.5000000000000001, .5], [.5, .5], 'list', errors)
    assert not errors
    compare([.5, .500001], [.5, .5], 'list', errors)
    assert len(errors) == 1 and errors[0]['path'] == 'list.1'
    probe = dict(data[0], scores={'I_zero': 2}, finite=True,
                 accept_eligible=True, reject_eligible=True)
    assert decide(probe, 'I_zero', {'A': 1, 'R': -1}) == 'accept'
    probe['newborn'] = True
    assert decide(probe, 'I_zero', {'A': 1, 'R': -1}) == 'unknown'
    assert primary_class(probe) is None
    for index, r in enumerate(data):
        r['timestamp'] = .4 if index == 1 else 0.0
        r['_decision'] = {method: 'unknown' for method in METHODS}
        r['_decision']['I_old'] = 'accept' if index != 1 else 'unknown'
        r['_decision']['I_zero'] = 'accept' if index in (1, 3) else 'unknown'
    time = timing(data, 'I_zero', 'I_old')
    assert time['never_difference'] == .25
    assert time['weighted_median_delay_difference_seconds'] == 0.0
    trans = transitions(data, 'I_zero', 'I_old')
    assert trans['true']['counts']['accept']['unknown'] == 2
    assert trans['true']['weighted']['accept']['unknown'] == .375
    assert summary(data, 'I_zero')['false']['n'] == 0
    assert gate(None, .05)['status'] == 'insufficient'
    assert gate(.051, .05)['status'] == 'fail'
    assert gate(.01, .01, 'ge')['status'] == 'pass'
    model = dict(status='ok', optimizer_ok=True, coef=[0, 2, 3, 4, 0, 6],
                 scale=[1, 2, 3, 4, 1, 6], mean=[0]*6, intercept=5)
    assert raw_parameters(model) == (5.0, [0.0, 1.0, 1.0, 1.0, 0.0, 1.0])
    assert base_score(model, [1]*6) == 9.0
    print('SELF_CHECK_PASS: primary, weights, fixed decisions, transitions, paired timing, lists and raw parameters')


def run(args):
    report, _ = full_recount(args)
    write_results(report, args.destination.resolve())
    print(json.dumps({'status': report['statistical_recount_status'], 'differences': len(report['errors']),
                      'retention': {key: value['overall'] for key, value in report['retention'].items()},
                      'output': str(args.destination.resolve()/'recount.json')}, ensure_ascii=False), flush=True)
    return 0 if not report['errors'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent.parent/'run_001')
    parser.add_argument('--source', type=Path, default=Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_score_revision_2026_11_13/run_001'))
    parser.add_argument('--destination', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--config', type=Path, default=Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-score-revision-2026-11-13/docs/REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/config.json'))
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
