"""Standard-library audit of saved policies/predictions; never fits or changes policies.

Run: python independent_verify.py --run /absolute/path/to/run_002
Only independent_verify.json is created. No project code is imported.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path

METHODS = ('Local', 'LocalCount', 'LocalCond')
DECISIONS = ('accept', 'unknown', 'reject')
TOL = 1e-10


def primary(r, truth):
    causal = r['query_present'] and not r['newborn']
    if truth:
        return causal and r['kind'] == 'clean' and r['query_truth'] == 1
    return causal and r['kind'] == 'attack' and r['query_truth'] == 0 and r['attack_role'] == 'target'


def epoch(r):
    return (r['job_id'], r['id'], r['epoch'])


def weights(rows, truth):
    hierarchy = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in rows:
        layer = (r['family'], r['attack_k']) if not truth else ('clean', 0)
        hierarchy[layer][r['parent']][epoch(r)].add(r['index'])
    out = []
    for r in rows:
        layer = (r['family'], r['attack_k']) if not truth else ('clean', 0)
        parents = hierarchy[layer]
        tracks = parents[r['parent']]
        out.append(1 / (len(hierarchy) * len(parents) * len(tracks) * len(tracks[epoch(r)])))
    return out


def finite(v):
    return isinstance(v, (float, int)) and math.isfinite(v)


def decision(r, p, method):
    """Direct independent transcription of the frozen decision specification."""
    tau = {k: float(p[k]) for k in ('tauF', 'tauP', 'tauR', 'tauC')}
    if r['input_fault']:
        state, choice, reason = 'input_fault', 'unknown', 'input_fault'
    elif not r['query_present'] or r['newborn']:
        state, choice, reason = 'no_query', 'unknown', 'no_causal_query'
    else:
        pos = r['I_eligible'] and finite(r['I']) and r['I'] > 0 and r['I'] >= tau['tauP']
        neg = r['F_eligible'] and finite(r['F']) and r['F'] > tau['tauF']
        if pos and neg:
            state, choice, reason = 'conflict', 'unknown', 'local_conflict'
        elif neg:
            state, choice, reason = 'refutation', 'reject', 'local_refutation'
        elif pos and not r['output_present']:
            state, choice, reason = 'support_no_output', 'unknown', 'local_support_no_output'
        elif pos and not r['identity_ok']:
            state, choice, reason = 'support_identity_unavailable', 'unknown', 'local_support_identity_unavailable'
        elif pos:
            state, choice, reason = 'support', 'accept', 'local_support'
        else:
            state, choice, reason = 'unknown', 'unknown', 'local_unknown'
    if p['status'] == 'infeasible_local_risk':
        return 'unknown', 'infeasible_local_risk', state
    if state != 'unknown' or method == 'Local':
        return choice, reason, state
    score = r['MissCount'] if method == 'LocalCount' else r['R']
    if r['reject_eligible'] and finite(score) and score > tau['tauR']:
        return 'reject', 'message_refutation', state
    if r['accept_eligible'] and r['output_present'] and r['identity_ok'] and finite(r['C']) and r['C'] >= tau['tauC']:
        return 'accept', 'message_support', state
    return 'unknown', 'message_undetermined', state


def six(rows):
    result = {m: {} for m in METHODS}
    for truth, label in ((1, 'true'), (0, 'false')):
        group = [r for r in rows if primary(r, truth)]
        w = weights(group, truth)
        if group:
            assert abs(math.fsum(w)-1) < TOL
        for m in METHODS:
            counts = Counter(r['decisions'][m] for r in group)
            result[m][label] = dict(n=len(group), parents=len({r['parent'] for r in group}),
                epochs=len({epoch(r) for r in group}), counts={d: counts[d] for d in DECISIONS},
                raw={d: counts[d]/len(group) if group else None for d in DECISIONS},
                weighted={d: math.fsum(v for r, v in zip(group, w) if r['decisions'][m] == d) if group else None for d in DECISIONS})
    for m in METHODS:
        t, f = result[m]['true']['weighted']['accept'], result[m]['false']['weighted']['reject']
        result[m]['correct_definite'] = None if t is None or f is None else (t+f)/2
    return result


def support(rows):
    entities = {('injected', r['job_id']) if r['kind'] == 'attack' else
        ('true', r['parent'], r['query_gt_id']) if r['query_gt_id'] is not None else ('query_epoch',)+epoch(r) for r in rows}
    return dict(rows=len(rows), parents=len({r['parent'] for r in rows}), entities=len(entities),
                epochs=len({epoch(r) for r in rows}))


def paired(rows, method):
    groups = defaultdict(list)
    for r in rows:
        if primary(r, 1):
            groups[(r['parent'],)+epoch(r)].append(r)
    parents = Counter(k[0] for k in groups)
    entries = []
    for k, group in sorted(groups.items()):
        first = {m: min((r['timestamp'] for r in group if r['decisions'][m] == 'accept'), default=None)
                 for m in (method, 'LocalCount')}
        entries.append((k[0], first))
    never = {m: math.fsum(1/(len(parents)*parents[p]) for p, first in entries if first[m] is None) if parents else None
             for m in (method, 'LocalCount')}
    common = [(p, first) for p, first in entries if all(v is not None for v in first.values())]
    cp = Counter(p for p, _ in common)
    delays = sorted((first[method]-first['LocalCount'], 1/(len(cp)*cp[p])) for p, first in common)
    mass, median = 0, None
    for d, w in delays:
        mass += w
        if mass >= .5:
            median = d
            break
    return dict(status='ok' if common else 'insufficient_no_common_ever_adopted_epoch',
        candidate=method, baseline='LocalCount', n_primary_true_epochs=len(groups), n_parents=len(parents),
        candidate_never=never[method], baseline_never=never['LocalCount'],
        never_difference=never[method]-never['LocalCount'] if groups else None,
        shared_ever_epochs=len(common), weighted_median_delay_difference_seconds=median)


def check(value, limit, direction='max'):
    ok = value is not None and (value <= limit+1e-12 if direction == 'max' else value >= limit-1e-12)
    return dict(status='insufficient' if value is None else 'pass' if ok else 'fail', value=value, limit=limit, direction=direction)


def verdict(measured, policies, criteria):
    out = {}
    base = measured['system_query']['LocalCount']
    for m in ('Local', 'LocalCond'):
        cur = measured['system_query'][m]
        pair = measured['paired_timeliness'][m]
        c = dict(true_reject=check(cur['true']['weighted']['reject'], criteria['max_TR_global']),
            false_accept=check(cur['false']['weighted']['accept'], criteria['max_FA_global_and_layer']),
            true_accept_loss=check(base['true']['weighted']['accept']-cur['true']['weighted']['accept'], criteria['max_TA_loss_vs_LocalCount']),
            CD_gain=check(cur['correct_definite']-base['correct_definite'], criteria['min_CD_gain_vs_LocalCount'], 'min'),
            never_adopt_increase=check(pair['never_difference'], criteria['max_never_adopt_increase']),
            paired_median_delay=check(pair['weighted_median_delay_difference_seconds'], criteria['max_paired_median_delay_seconds']),
            calibration=check(int(policies[m]['status'] == 'active'), 1, 'min'))
        for layer, group in measured['family_k'].items():
            c['false_accept_'+layer] = check(group['metrics'][m]['false']['weighted']['accept'], criteria['max_FA_global_and_layer'])
            c['parents_'+layer] = check(group['support']['parents'], criteria['min_eval_parents_per_layer'], 'min')
            c['entities_'+layer] = check(group['support']['entities'], criteria['min_eval_entities_per_layer'], 'min')
        statuses = {v['status'] for v in c.values()}
        out[m] = dict(status='not_retained' if 'fail' in statuses else 'evidence_insufficient' if 'insufficient' in statuses else 'retained', checks=c)
    return out


def main(root):
    report = json.loads((root/'evaluate.report.json').read_text())
    config = json.loads((root/'method_inputs.json').read_text())
    resolution = json.loads((root.parent/'run_001/input_resolution.json').read_text())
    errors, comparisons, largest = [], 0, 0.
    def compare(actual, expected, label):
        nonlocal comparisons, largest
        if isinstance(actual, dict):
            for k, v in actual.items():
                if k not in expected:
                    errors.append(label+'/'+k+': missing field')
                else:
                    compare(v, expected[k], label+'/'+k)
        else:
            comparisons += 1
            if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
                diff = abs(actual-expected)
                largest = max(largest, diff)
                if diff > TOL:
                    errors.append(f'{label}: {actual!r} != {expected!r}')
            elif actual != expected:
                errors.append(f'{label}: {actual!r} != {expected!r}')
    result = dict(schema='trusted_receiver_independent_audit_v1', tolerance=TOL,
        implementation='stdlib only; no project imports; no threshold selection',
        input_resolution=resolution, regimes={}, total_prediction_rows=0, decision_checks=0)
    assert Counter(resolution['all_statuses'].values()) == resolution['statuses']
    assert sum(resolution['statuses'].values()) == resolution['planned'] == 87
    assert resolution['statuses'] == {'COMPLETE': 69, 'UNREALIZABLE': 18}
    assert {j['job_id'] for j in config['jobs']} == {j for j, s in resolution['all_statuses'].items() if s == 'COMPLETE'}
    for reg, spec in config['regimes'].items():
        policies = json.loads((root/'calibration'/f'{reg}.json').read_text())
        result['regimes'][reg] = {}
        for split in ('cal', 'eval'):
            path = root/'predictions'/reg/f'{split}.jsonl.gz'
            with gzip.open(path, 'rt') as stream:
                rows = [json.loads(line) for line in stream]
            result['total_prediction_rows'] += len(rows)
            assert len({tuple(r['key']) for r in rows}) == len(rows)
            assert all(r['split'] == split and (r['kind'] == 'clean' or r['family'] in spec[split+'_families']) for r in rows)
            assert all(resolution['all_statuses'][r['job_id']] == 'COMPLETE' for r in rows)
            for r in rows:
                for m in METHODS:
                    d, why, state = decision(r, policies[m], m)
                    compare(dict(decision=d, reason=why, state=state), dict(decision=r['decisions'][m],
                        reason=r['decision_reasons'][m], state=r['local_state']), f'{reg}/{split}/{r["key"]}/{m}')
                    result['decision_checks'] += 1
            measured = dict(system_query=six(rows), family_k={}, paired_timeliness={m: paired(rows, m) for m in ('Local', 'LocalCond')},
                local_unknown=six([r for r in rows if r['local_state'] == 'unknown']))
            for family in spec[split+'_families']:
                for k in config['required_k']:
                    group = [r for r in rows if r['family'] == family and r['attack_k'] == k]
                    false = [r for r in group if primary(r, 0)]
                    measured['family_k'][family+'/'+str(k)] = dict(status='observed' if false else 'not_tested',
                        support=support(false), metrics=six(group))
            compare(measured, report['regimes'][reg][split], reg+'/'+split)
            measured['primary_true_support'] = support([r for r in rows if primary(r, 1)])
            measured['primary_false_support'] = support([r for r in rows if primary(r, 0)])
            measured['non_primary_accounting'] = dict(total=len(rows),
                primary_true=sum(primary(r, 1) for r in rows), primary_false=sum(primary(r, 0) for r in rows),
                unknown_labels=sum(r['query_truth'] not in (0, 1) for r in rows),
                attack_true_background=sum(r['kind'] == 'attack' and r['query_truth'] == 1 for r in rows),
                no_query=sum(not r['query_present'] for r in rows), newborn=sum(r['newborn'] for r in rows),
                input_fault=sum(r['input_fault'] for r in rows))
            # These coverage categories intentionally overlap; they are not class denominators.
            compare({k: v for k, v in measured['non_primary_accounting'].items() if k not in ('total', 'input_fault')},
                report['regimes'][reg][split]['coverage'], reg+'/'+split+'/coverage')
            if split == 'cal':
                for m in METHODS:
                    compare(measured['system_query'][m]['true']['weighted']['reject'], policies[m]['budget']['final_true_reject'], reg+'/cal/'+m+'/final_TR')
                    compare(measured['system_query'][m]['false']['weighted']['accept'], policies[m]['budget']['final_false_accept']['overall'], reg+'/cal/'+m+'/final_FA')
                    for layer, g in measured['family_k'].items():
                        compare(g['metrics'][m]['false']['weighted']['accept'], policies[m]['budget']['final_false_accept'][layer], reg+'/cal/'+m+'/'+layer+'/final_FA')
                measured['calibration_actual_TR'] = {m: measured['system_query'][m]['true']['weighted']['reject'] for m in METHODS}
                measured['same_budget_is_not_same_actual_rate'] = dict(total_limit=.05,
                    LocalCount=policies['LocalCount']['budget']['final_true_reject'],
                    LocalCond=policies['LocalCond']['budget']['final_true_reject'])
            result['regimes'][reg][split] = measured
        ev = result['regimes'][reg]['eval']
        judged = verdict(ev, policies, config['criteria'])
        compare(judged, report['regimes'][reg]['verdict'], reg+'/verdict')
        result['regimes'][reg]['verdict'] = judged
        c, b = ev['system_query']['LocalCond'], ev['system_query']['LocalCount']
        result['regimes'][reg]['summary'] = dict(CD_gain_pp=100*(c['correct_definite']-b['correct_definite']),
            true_accept_loss_pp=100*(b['true']['weighted']['accept']-c['true']['weighted']['accept']),
            true_reject_percent=100*c['true']['weighted']['reject'], false_accept_percent=100*c['false']['weighted']['accept'],
            failed_checks=[k for k, v in judged['LocalCond']['checks'].items() if v['status'] == 'fail'])
    result.update(status='PASS' if not errors else 'FAIL', errors=errors, compared_scalar_fields=comparisons,
                  max_absolute_numeric_difference=largest,
                  source_report_sha256=hashlib.sha256((root/'evaluate.report.json').read_bytes()).hexdigest(),
                  audit_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  not_checked=['raw PCD/pose geometry', 'original labels', 'upstream C/R recomputation',
                      'threshold optimality or recalibration', 'population guarantees and causal attribution'])
    (root/'independent_verify.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'total_prediction_rows', 'decision_checks', 'compared_scalar_fields', 'max_absolute_numeric_difference')}, ensure_ascii=False))
    for reg, v in result['regimes'].items():
        print(reg, json.dumps(v['summary'], ensure_ascii=False), 'cal_TR', v['cal']['calibration_actual_TR'])
    if errors:
        print('\n'.join(errors[:20]))
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    main(parser.parse_args().run)
