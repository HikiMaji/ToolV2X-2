"""Independent source-based verification; no production calibration/metric imports."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path

METHODS = ('Count', 'D_zero', 'Cond', 'MissCount', 'BaseTail')
ADDED = METHODS[2:]
REGIMES = ('mixed', 'F1_only', 'F2_only')
TOL = 1e-10


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def ep(r):
    return r['job_id'], r['id'], r['epoch']


def primary(r, truth):
    if not r['query_present'] or r['newborn'] or r['query_truth'] != truth:
        return False
    return r['kind'] == 'clean' if truth else r['kind'] == 'attack' and r['attack_role'] == 'target'


def weights(rs, truth):
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in rs:
        layer = (r['family'], r['attack_k']) if truth == 0 else ('clean', 0)
        tree[layer][r['parent']][ep(r)].add(r['index'])
    result = []
    for r in rs:
        layer = (r['family'], r['attack_k']) if truth == 0 else ('clean', 0)
        parents = tree[layer]
        epochs = parents[r['parent']]
        result.append(1 / len(tree) / len(parents) / len(epochs) / len(epochs[ep(r)]))
    assert not result or abs(math.fsum(result) - 1) < TOL
    return result


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def eligible(r):
    return (r['query_present'] and not r['newborn'] and r['finite']
            and r.get('error') is None and r['method_status']['Count']['status'] == 'ok'
            and finite(r['scores']['Count']) and r['reject_eligible']
            and r['decisions']['Count'] != 'reject')


def fit_threshold(clean, method):
    ww = weights(clean, 1)
    base = math.fsum(w for r, w in zip(clean, ww) if r['decisions']['Count'] == 'reject')
    delta = min(.02, max(0., .05 - base))
    result = dict(base_true_reject=base, delta=delta, tau=None,
                  added_true_reject_weight=0., enabled=False)
    pool = [(r['review_scores'][method], w) for r, w in zip(clean, ww) if eligible(r)]
    if not clean or delta == 0 or any(not finite(v) for v, _ in pool):
        return result
    mass = defaultdict(list)
    for value, w in pool:
        if method == 'BaseTail' or value > 0:
            mass[value].append(w)
    if not mass:
        return result
    remaining = math.fsum(w for values in mass.values() for w in values)
    for value in sorted(mass):
        remaining -= math.fsum(mass[value])
        if remaining <= delta + 1e-12:
            result.update(tau=value, enabled=True,
                          added_true_reject_weight=math.fsum(w for v, w in pool if v > value))
            return result
    raise AssertionError('maximum candidate must have zero strict tail')


def decision(r, method, policy):
    base = r['decisions']['Count']
    if base == 'reject' or not eligible(r) or not policy['enabled']:
        return base
    value = r['review_scores'][method]
    return 'reject' if finite(value) and value > policy['tau'] else base


def six(rs):
    result = {m: {} for m in METHODS}
    for truth, name in ((1, 'true'), (0, 'false')):
        subset = [r for r in rs if primary(r, truth)]
        ww = weights(subset, truth)
        for method in METHODS:
            counts = Counter(r['review_decisions'][method] for r in subset)
            result[method][name] = dict(n=len(subset), parents=len({r['parent'] for r in subset}),
                epochs=len({ep(r) for r in subset}),
                counts={d: counts[d] for d in ('accept', 'unknown', 'reject')},
                weighted={d: math.fsum(w for r, w in zip(subset, ww)
                          if r['review_decisions'][method] == d) if subset else None
                          for d in ('accept', 'unknown', 'reject')})
    for method, value in result.items():
        t = value['true']['weighted']['accept']
        f = value['false']['weighted']['reject']
        value['correct_definite'] = (t + f) / 2 if t is not None and f is not None else None
    return result


def paired(rs, method):
    grouped = defaultdict(list)
    for r in rs:
        if primary(r, 1):
            grouped[(r['parent'], *ep(r))].append(r)
    parents = Counter(k[0] for k in grouped)
    never = {'Count': 0., method: 0.}
    shared = []
    for key, group in grouped.items():
        first = {m: min((r['timestamp'] for r in group if r['review_decisions'][m] == 'accept'),
                        default=None) for m in ('Count', method)}
        for m in first:
            if first[m] is None:
                never[m] += 1 / len(parents) / parents[key[0]]
        if all(v is not None for v in first.values()):
            shared.append((key[0], first[method] - first['Count']))
    sp = Counter(p for p, _ in shared)
    ordered = sorted((value, 1 / len(sp) / sp[p]) for p, value in shared)
    cumulative = 0.
    median = None
    for value, w in ordered:
        cumulative += w
        if cumulative >= .5:
            median = value
            break
    return dict(n_primary_true_epochs=len(grouped), n_parents=len(parents),
                candidate_never=never[method] if grouped else None,
                baseline_never=never['Count'] if grouped else None,
                never_difference=never[method] - never['Count'] if grouped else None,
                shared_ever_epochs=len(shared), weighted_median_delay_difference_seconds=median)


def metrics(rs):
    family = sorted({(r['family'], r['attack_k']) for r in rs if primary(r, 0)})
    return dict(system_query=six(rs),
        family_k={f'{f}/{k}': six([r for r in rs if (r['family'], r['attack_k']) == (f, k)])
                  for f, k in family},
        by_parent={p: six([r for r in rs if r['parent'] == p]) for p in sorted({r['parent'] for r in rs})},
        first_windows={name: six([r for r in rs if lower <= r['w'] <= upper])
                       for name, lower, upper in (('length_1', 1, 1), ('length_2_to_9', 2, 9), ('length_10', 10, 10))},
        paired_timeliness={m: paired(rs, m) for m in ADDED})


def retention(rs, measurement, policies):
    main = measurement['system_query']
    base = main['Count']
    result = {}
    for method in ADDED:
        current = main[method]
        time = measurement['paired_timeliness'][method]
        gates = dict(true_reject=current['true']['weighted']['reject'] <= .05 + 1e-12,
            false_accept=current['false']['weighted']['accept'] <= .05 + 1e-12,
            family_false_accept=all(v[method]['false']['weighted']['accept'] <= .05 + 1e-12
                                    for v in measurement['family_k'].values()),
            true_accept_loss=base['true']['weighted']['accept'] - current['true']['weighted']['accept'] <= .02 + 1e-12,
            CD_gain=current['correct_definite'] - base['correct_definite'] >= .01 - 1e-12,
            never_increase=time['never_difference'] is not None and time['never_difference'] <= .02 + 1e-12,
            paired_delay=time['weighted_median_delay_difference_seconds'] is not None
                         and time['weighted_median_delay_difference_seconds'] <= .5 + 1e-12,
            active_and_changed=policies[method]['enabled'] and any(
                r['review_decisions'][method] != r['decisions']['Count']
                for r in rs if primary(r, 0) or primary(r, 1)))
        result[method] = dict(gates=gates, retained=all(gates.values()),
            risk_eligible=all(v for k, v in gates.items() if k not in ('CD_gain', 'active_and_changed')))
    result['condition_attribution'] = result['Cond']['retained'] and all(result[m]['risk_eligible'] and
        main['Cond']['correct_definite'] - main[m]['correct_definite'] >= .01 - 1e-12
        for m in ('MissCount', 'BaseTail'))
    return result


def source_rows(source, regime, split, feature_cache):
    source = Path(source)
    rs = list(rows(source / 'predictions' / regime / (split + '.jsonl.gz')))
    assert len(rs) == len({tuple(r['key']) for r in rs})
    manifest = read(source / 'manifest.json')
    base = source / 'features' / 'eval' if split == 'eval' else Path(manifest['config']['source_features']) / 'cal'
    for job in sorted({r['job_id'] for r in rs}):
        cache_key = split, job
        if cache_key not in feature_cache:
            compact = {}
            for f in rows(base / (job + '.jsonl.gz')):
                key = tuple(f['key'])
                assert key not in compact
                x = f['features'].get('D_head')
                compact[key] = dict(meta={k: f[k] for k in ('job_id', 'id', 'epoch', 'parent', 'index',
                    'source_ids', 'accept_eligible', 'reject_eligible', 'finite')},
                    Cond=-x[1] if x is not None else None,
                    MissCount=sum(f['n_minus']),
                    counts=[x[2], sum(f['n_minus']), *f['context']] if x is not None else None)
            feature_cache[cache_key] = compact
    for r in rs:
        f = feature_cache[(split, r['job_id'])][tuple(r['key'])]
        for k, value in f['meta'].items():
            assert r[k] == value, (r['key'], 'feature metadata', k)
        assert r['Count_inputs'] == f['counts']
        r['review_scores'] = {m: f[m] for m in ('Cond', 'MissCount')}
        if r['review_scores']['Cond'] is not None:
            assert finite(r['review_scores']['Cond']) and r['review_scores']['Cond'] >= 0
        r['review_scores']['BaseTail'] = -r['scores']['Count'] if finite(r['scores']['Count']) else None
    return rs


def equal(actual, expected, context):
    if isinstance(expected, float):
        assert actual is not None and abs(actual - expected) < TOL, (context, actual, expected)
    else:
        assert actual == expected, (context, actual, expected)


def compare_subset(actual, expected, context):
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, (context, 'missing', key)
            compare_subset(actual[key], value, context + '/' + str(key))
    else:
        equal(actual, expected, context)


def self_check():
    toy = []
    for index, score in enumerate((0., 1., 1., 2.)):
        toy.append(dict(job_id='j', id=1, epoch=0, index=index, parent='p', family='clean', attack_k=0,
            kind='clean', query_truth=1, query_present=True, newborn=False, finite=True, error=None,
            reject_eligible=True, scores={'Count': 1.}, method_status={'Count': {'status': 'ok'}},
            decisions={'Count': 'unknown'}, review_scores={'Cond': score}))
    p = fit_threshold(toy, 'Cond')
    assert p['tau'] == 2. and p['added_true_reject_weight'] == 0.
    assert decision(toy[-1], 'Cond', p) == 'unknown'
    p = dict(p, tau=1.)
    assert decision(toy[1], 'Cond', p) == 'unknown'
    assert decision(toy[-1], 'Cond', p) == 'reject'
    altered = dict(toy[-1], query_truth=-1, family='arbitrary', attack_k=999, parent='unread')
    assert decision(altered, 'Cond', p) == 'reject'


def run(source, output):
    source, output = Path(source), Path(output)
    assert read(output / 'run.complete.json')['status'] == 'complete'
    target = output / 'independent_verify.json'
    assert not target.exists(), 'preserve prior independent verification'
    cache = {}
    proof = dict(status='passed', scope='independent_complete_source_verification', regimes={},
                 implementation='standard_library_only_no_production_calibration_or_metrics_imports',
                 limits=['development_evidence_not_independent_test', 'p_D_reconstruction_not_repeated'])
    summary = read(output / 'summary.json')
    for regime in REGIMES:
        cal = source_rows(source, regime, 'cal', cache)
        clean = [r for r in cal if primary(r, 1)]
        policies = {m: fit_threshold(clean, m) for m in ADDED}
        actual_policies = read(output / 'calibration' / (regime + '.json'))['branches']
        for method, policy in policies.items():
            actual = actual_policies[method]
            equal(actual['status'] == 'active', policy['enabled'], regime + '/' + method + '/enabled')
            for field in ('tau', 'base_true_reject', 'delta', 'added_true_reject_weight'):
                equal(actual[field], policy[field], regime + '/' + method + '/' + field)
            assert actual['added_true_reject_weight'] <= actual['delta'] + 1e-12
        report = read(output / 'report' / (regime + '.json'))
        regime_proof = dict(calibration=policies, splits={})
        for split in ('cal', 'eval'):
            rs = cal if split == 'cal' else source_rows(source, regime, split, cache)
            produced = list(rows(output / 'predictions' / regime / (split + '.jsonl.gz')))
            actual = {tuple(r['key']): r for r in produced}
            assert len(actual) == len(produced) == len(rs)
            assert set(actual) == {tuple(r['key']) for r in rs}
            changed = Counter()
            for r in rs:
                key = tuple(r['key'])
                got = actual[key]
                for field, value in r.items():
                    if field in ('review_scores', 'review_decisions'):
                        continue
                    if field in ('scores', 'decisions', 'method_status'):
                        for name, original_value in value.items():
                            equal(got[field][name], original_value, (regime, split, key, field, name))
                    else:
                        equal(got[field], value, (regime, split, key, field))
                expected = {m: r['decisions'][m] for m in METHODS[:2]}
                for method in ADDED:
                    expected[method] = decision(r, method, policies[method])
                    equal(got['supplement_scores'][method], r['review_scores'][method], (key, method, 'score'))
                    equal(got['scores'][method], r['review_scores'][method], (key, method, 'saved_score'))
                    equal(got['decisions'][method], expected[method], (key, method, 'decision'))
                    assert expected[method] != 'accept' or r['decisions']['Count'] == 'accept'
                    assert r['decisions']['Count'] != 'reject' or expected[method] == 'reject'
                    changed[method] += expected[method] != r['decisions']['Count']
                r['review_decisions'] = expected
            measure = metrics(rs)
            actual_metrics = report['metrics'][split]
            for part in ('system_query', 'by_parent', 'first_windows', 'paired_timeliness'):
                compare_subset(actual_metrics[part], measure[part], f'{regime}/{split}/{part}')
            for layer, value in measure['family_k'].items():
                compare_subset(actual_metrics['family_k'][layer]['metrics'], value,
                               f'{regime}/{split}/family_k/{layer}')
            regime_proof['splits'][split] = dict(n_all_records=len(rs),
                n_true_primary=sum(primary(r, 1) for r in rs), n_false_primary=sum(primary(r, 0) for r in rs),
                changed_all_records=dict(changed), system_query=measure['system_query'])
            if split == 'eval':
                verdict = retention(rs, measure, policies)
                for method in ADDED:
                    equal(report['retention']['branches'][method]['status'] == 'retained',
                          verdict[method]['retained'], f'{regime}/{method}/retained')
                    equal(report['retention']['branches'][method]['risk_status'] == 'retained',
                          verdict[method]['risk_eligible'], f'{regime}/{method}/risk')
                equal(report['retention']['conditional_increment']['status'] == 'established',
                      verdict['condition_attribution'], regime + '/attribution')
                regime_proof['retention'] = verdict
            for method in METHODS[:2]:
                equal(report['baseline_reproduction'][split][method]['status'], 'pass',
                      f'{regime}/{split}/{method}/reproduction')
            compare_subset(summary['regimes'][regime]['system_query'][split], measure['system_query'],
                           f'{regime}/{split}/summary')
        proof['regimes'][regime] = regime_proof
        print('independently verified', regime, flush=True)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('all source decisions, thresholds, weights, six cells and principal gates verified', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    self_check()
    if args.self_check:
        print('independent synthetic checks passed; no source data loaded')
    else:
        if args.source is None or args.run is None:
            parser.error('--source and --run are required')
        run(args.source, args.run)
