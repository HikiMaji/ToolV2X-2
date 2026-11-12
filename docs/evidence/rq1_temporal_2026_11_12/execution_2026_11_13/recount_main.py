"""Independent recount of final main predictions; stdlib only, no fitting/replay."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

METHODS = ('D', 'B', 'C', 'T', 'J', 'Jind', 'G', 'MATE_policy')
DECISIONS = ('accept', 'unknown', 'reject')


def decision(row, method, policy):
    value = row['scores'][method]
    if not row['finite'] or value is None:
        return 'unknown'
    if not math.isfinite(value):
        raise ValueError('nonfinite score in JSON')
    if row['accept_eligible'] and policy['A'] is not None and value > 0 and value >= policy['A']:
        return 'accept'
    if row['reject_eligible'] and policy['R'] is not None and value < 0 and value <= policy['R']:
        return 'reject'
    return 'unknown'


def add(groups, row, decisions):
    key = (row['family'], row['attack_k'], row['parent'], row['job_id'], row['id'], row['epoch'])
    if key not in groups:
        groups[key] = dict(indices=set(), counts={m: Counter() for m in METHODS})
    group = groups[key]
    if row['index'] in group['indices']:
        raise ValueError('duplicate primary epoch/time: ' + str(key))
    group['indices'].add(row['index'])
    for method in METHODS:
        group['counts'][method][decisions[method]] += 1


def cells(groups):
    """Mean within epoch, then parent, then family/k; never drop unknown."""
    layers = defaultdict(lambda: defaultdict(list))
    for key, group in groups.items():
        layers[key[:2]][key[2]].append(group)
    n = sum(len(g['indices']) for g in groups.values())
    result = {}
    for method in METHODS:
        counts = {d: sum(g['counts'][method][d] for g in groups.values()) for d in DECISIONS}
        weighted = {}
        for d in DECISIONS:
            layer_means = []
            for parents in layers.values():
                parent_means = []
                for epochs in parents.values():
                    epoch_means = [g['counts'][method][d] / len(g['indices']) for g in epochs]
                    parent_means.append(math.fsum(epoch_means) / len(epoch_means))
                layer_means.append(math.fsum(parent_means) / len(parent_means))
            weighted[d] = math.fsum(layer_means) / len(layer_means) if n else None
        result[method] = dict(n=n, parents=len({key[2] for key in groups}), epochs=len(groups),
                              counts=counts, raw={d: counts[d] / n if n else None for d in DECISIONS},
                              weighted=weighted)
    return result


def six(groups):
    by_truth = {t: cells(groups[t]) for t in (0, 1)}
    result = {}
    for method in METHODS:
        true, false = by_truth[1][method], by_truth[0][method]
        a, r = true['weighted']['accept'], false['weighted']['reject']
        result[method] = dict(true=true, false=false,
                              correct_definite=None if a is None or r is None else (a + r) / 2)
    return result


def self_check():
    # One hand example: layer F1 has parent means 1/2 and 0, F2 has 1.
    groups = {}
    cases = [('F1', 'p', 1, 0, 'accept'), ('F1', 'p', 1, 1, 'accept'),
             ('F1', 'p', 2, 0, 'unknown'), ('F1', 'q', 1, 0, 'reject'),
             ('F2', 'r', 1, 0, 'accept')]
    for family, parent, epoch, index, value in cases:
        add(groups, dict(family=family, attack_k=1, parent=parent, job_id=parent,
                         id=1, epoch=epoch, index=index), {m: value for m in METHODS})
    result = cells(groups)['J']
    assert result['counts'] == dict(accept=3, unknown=1, reject=1)
    assert result['weighted'] == dict(accept=.625, unknown=.125, reject=.25)
    assert (result['n'], result['parents'], result['epochs']) == (5, 3, 4)
    print('one hand-weight example PASS: raw accept=0.6, hierarchical accept=0.625')


def recount(run_out):
    report = run_out / 'report'
    for path in (run_out / 'report.complete.json', report / 'predictions.jsonl.gz', report / 'metrics.json'):
        if not path.exists():
            raise FileNotFoundError('final report required: ' + str(path))
    original = json.loads((report / 'metrics.json').read_text())
    main = original['variants']['main']
    groups = {s: {0: {}, 1: {}} for s in ('cal', 'eval')}
    layers = {s: set() for s in groups}
    diagnostics = {s: dict(n_rows=0, numeric_failure=0, unknown_labels=0, failure_reasons=Counter(),
                          n_finite=Counter(), statuses={m: Counter() for m in METHODS}) for s in groups}
    epochs = {s: {} for s in groups}
    mismatches = []
    mismatch_count = 0

    def check(path, actual, expected):
        nonlocal mismatch_count
        equal = (math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
                 if isinstance(actual, (int, float)) and isinstance(expected, (int, float))
                 else actual == expected)
        if not equal:
            mismatch_count += 1
            if len(mismatches) < 40:
                mismatches.append(dict(field=path, recounted=actual, reported=expected))

    with gzip.open(report / 'predictions.jsonl.gz', 'rt') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            split = row['split']
            if split not in groups:
                continue
            diag = diagnostics[split]
            diag['n_rows'] += 1
            diag['numeric_failure'] += not row['finite']
            if not row['finite']:
                diag['failure_reasons'][row.get('error') or 'unspecified'] += 1
            diag['unknown_labels'] += row['query_truth'] not in (0, 1)
            layers[split].add((row['family'], row['attack_k']))
            decisions = {m: decision(row, m, main['policies'][m]) for m in METHODS}
            for method in METHODS:
                check(split + '.stored_decision.' + method, row['decisions'][method], decisions[method])
                score = row['scores'][method]
                status = row['method_status'][method]
                diag['statuses'][method][status['status']] += 1
                diag['n_finite'][method] += score is not None and math.isfinite(score)
                if not row['finite'] or status['status'] == 'unestimable':
                    check(split + '.unavailable_score.' + method, score, None)
                    check(split + '.unavailable_decision.' + method, decisions[method], 'unknown')
                if method in original['method_status'] and original['method_status'][method]['status'] == 'unestimable':
                    check(split + '.global_unestimable.' + method, score, None)
            valid = row['query_present'] and not row['newborn']
            if not valid:
                continue
            key = (row['job_id'], row['id'], row['epoch'])
            entry = epochs[split].setdefault(key, dict(first=None, accepted={}, primary=set(), false_accepted=set()))
            time = (row['index'], row['timestamp'])
            if entry['first'] is None or time < entry['first']:
                entry['first'] = time
            for method in METHODS:
                if decisions[method] == 'accept' and (method not in entry['accepted'] or time < entry['accepted'][method]):
                    entry['accepted'][method] = time
            truth = (1 if row['kind'] == 'clean' and row['query_truth'] == 1 else
                     0 if row['kind'] == 'attack' and row['query_truth'] == 0 and row['attack_role'] == 'target' else None)
            if truth is not None:
                entry['primary'].add(truth)
                if truth == 0:
                    entry['false_accepted'].update(m for m in METHODS if decisions[m] == 'accept')
                add(groups[split][truth], row, decisions)

    recounted = {}
    for split in groups:
        table = six(groups[split])
        joint = {}
        for family, k in sorted(layers[split]):
            chosen = {t: {key: v for key, v in groups[split][t].items() if key[:2] == (family, k)} for t in (0, 1)}
            joint[family + '/' + str(k)] = six(chosen)
        trajectories = {}
        for method in METHODS:
            trajectories[method] = {}
            for truth in (0, 1):
                selected = [e for e in epochs[split].values() if truth in e['primary']]
                delays = [e['accepted'][method][1] - e['first'][1] for e in selected if method in e['accepted']]
                trajectories[method][str(truth)] = dict(n=len(selected), n_accepted=len(delays),
                    never_accepted=len(selected) - len(delays), accepted_delay_median=statistics.median(delays) if delays else None,
                    ever_false_accept=sum(method in e['false_accepted'] for e in selected) if truth == 0 else None)
        recounted[split] = dict(system_query=table, family_k=joint, trajectories=trajectories, diagnostics=diagnostics[split])
        expected = main['metrics'][split]
        for method in METHODS:
            for label in ('true', 'false'):
                a, b = table[method][label], expected['system_query'][method][label]
                for name in ('n', 'parents', 'epochs'):
                    check(f'{split}.{method}.{label}.{name}', a[name], b[name])
                for name in ('counts', 'raw', 'weighted'):
                    for d in DECISIONS:
                        check(f'{split}.{method}.{label}.{name}.{d}', a[name][d], b[name][d])
            check(f'{split}.{method}.correct_definite', table[method]['correct_definite'], expected['system_query'][method]['correct_definite'])
            for truth in ('0', '1'):
                for name, value in trajectories[method][truth].items():
                    check(f'{split}.trajectories.{method}.{truth}.{name}', value, expected['trajectories'][method][truth][name])
            coverage = expected['method_score_coverage'][method]
            check(f'{split}.{method}.score_coverage', diagnostics[split]['n_finite'][method], coverage['n_finite'])
        check(split + '.family_k_keys', sorted(joint), sorted(expected['family_k']))
        for layer, methods in joint.items():
            for method in METHODS:
                for name in ('n', 'parents', 'epochs', 'counts', 'raw', 'weighted'):
                    actual = methods[method]['false'][name]
                    target = expected['family_k'][layer]['methods'][method]['false'][name]
                    if isinstance(actual, dict):
                        for d in DECISIONS:
                            check(f'{split}.{layer}.{method}.{name}.{d}', actual[d], target[d])
                    else:
                        check(f'{split}.{layer}.{method}.{name}', actual, target)
        for name in ('n_rows', 'numeric_failure', 'unknown_labels'):
            check(split + '.' + name, diagnostics[split][name], expected[name])

    risks = {}
    for method in METHODS:
        table = recounted['cal']['system_query'][method]
        values = dict(true_reject=table['true']['weighted']['reject'], false_accept=table['false']['weighted']['accept'])
        for layer, tables in recounted['cal']['family_k'].items():
            for label, wrong in (('true', 'reject'), ('false', 'accept')):
                risk = tables[method][label]['weighted'][wrong]
                if risk is not None:
                    values[layer + '/' + label + '_' + wrong] = risk
        risks[method] = dict(actual_risks=values, above_five_percent={k: v for k, v in values.items() if v is not None and v > .05 + 1e-10},
                             missing_cal_layers=main['policies'][method]['missing_layers'])
        check('cal.' + method + '.five_percent_budget', bool(risks[method]['above_five_percent']), False)

    differences = {}
    table = recounted['eval']['system_query']
    def subtract(a, b):
        return None if a is None or b is None else a - b
    for comparator, label in (('T', 'joint_vs_temporal'), ('G', 'joint_vs_group')):
        a, b = table['J'], table[comparator]
        diff = dict(correct_definite_difference=subtract(a['correct_definite'], b['correct_definite']),
                    true_accept_difference=subtract(a['true']['weighted']['accept'], b['true']['weighted']['accept']),
                    false_accept_difference=subtract(a['false']['weighted']['accept'], b['false']['weighted']['accept']),
                    accepted_delay_median_difference=subtract(recounted['eval']['trajectories']['J']['1']['accepted_delay_median'],
                                                              recounted['eval']['trajectories'][comparator]['1']['accepted_delay_median']))
        diff['family_k_false_accept_difference'] = {layer: subtract(v['J']['false']['weighted']['accept'], v[comparator]['false']['weighted']['accept']) for layer, v in recounted['eval']['family_k'].items()}
        for field, value in diff.items():
            expected = main['method_decisions'][label][field]
            if isinstance(value, dict):
                for layer, delta in value.items():
                    check(label + '.' + field + '.' + layer, delta, expected[layer])
            else:
                check(label + '.' + field, value, expected)
        differences['J-' + comparator] = diff
    return dict(status='PASS' if not mismatch_count else 'MISMATCH', mismatch_count=mismatch_count,
                first_mismatches=mismatches, recounted=recounted, calibration=risks, differences=differences,
                model_status=original['method_status'], policies=main['policies'],
                sources=dict(run_out=str(run_out.resolve()), predictions_bytes=(report / 'predictions.jsonl.gz').stat().st_size,
                             metrics_bytes=(report / 'metrics.json').stat().st_size,
                             recount_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
                limits='Main W10/s0.9 only. No refit, threshold search, replay or bootstrap. Calibration risks are development point estimates. Delay is conditional on adoption; never-adopted counts are reported. PASS certifies recount agreement, not method retention or risk guarantees.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--run-out', type=Path)
    parser.add_argument('--output', type=Path, help='new JSON file outside the original report directory')
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        if args.run_out is None:
            parser.error('--run-out is required unless --self-check')
        if args.output:
            try:
                args.output.resolve().relative_to((args.run_out / 'report').resolve())
            except ValueError:
                pass
            else:
                parser.error('--output must be outside the original report directory')
        result = recount(args.run_out)
        content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            with args.output.open('x') as stream:
                stream.write(content)
        else:
            print(content, end='')
        raise SystemExit(0 if result['status'] == 'PASS' else 1)
