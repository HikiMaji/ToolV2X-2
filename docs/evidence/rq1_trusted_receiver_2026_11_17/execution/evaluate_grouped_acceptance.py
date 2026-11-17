"""One development evaluation of cal-approved grouped acceptance thresholds."""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from scripts.rq1_temporal import data, run as original
from scripts.rq1_trusted_receiver import run as core
from scripts.rq1_score_revision import run as legacy

REMOTE = ('LocalCount', 'LocalCond')
NOTE = ('Policy budget diagnostics are copied from run_002, not recalculated for the new tauC; '
        'actual new cal statistics are in report/REGIME/cal.json. Group constraints are empirical cal constraints, '
        'not guarantees for new recordings. Local is a descriptive reference.')


def validate_policies(old, new):
    if old['Local'] != new['Local']:
        raise ValueError('Local reference policy changed')
    for method in REMOTE:
        if ({k: v for k, v in old[method].items() if k != 'tauC'} !=
                {k: v for k, v in new[method].items() if k != 'tauC'}
                or core._tau(new[method], 'tauC') < core._tau(old[method], 'tauC')):
            raise ValueError('only an increased tauC is allowed')


def reapply(rows, old, new):
    validate_policies(old, new)
    if len({tuple(r['key']) for r in rows}) != len(rows):
        raise ValueError('duplicate source candidate keys')
    result = []
    for row in rows:
        updated = dict(row, previous_decisions=dict(row['decisions']),
            previous_decision_reasons=dict(row['decision_reasons']), decisions={}, decision_reasons={})
        for method in core.METHODS:
            before = core.decide(core._public(row), old[method], method)
            if (before['decision'] != row['decisions'][method]
                    or before['reason'] != row['decision_reasons'][method]):
                raise ValueError('saved source decision differs from original policy')
            after = core.decide(core._public(row), new[method], method)
            a, b = before['decision'], after['decision']
            if a != b and (a, b) != ('accept', 'unknown'):
                raise AssertionError('decision changed beyond acceptance to unknown')
            updated['decisions'][method], updated['decision_reasons'][method] = b, after['reason']
            updated['local_state'] = after['local_state']
        result.append(updated)
    return result


def comparisons(rows):
    result = {m: dict(old={}, new={}, unknown_increase={}) for m in REMOTE}
    for truth, label in ((1, 'true'), (0, 'false')):
        selected = [r for r in rows if original.primary(r, truth)]
        weights = original.weights(selected, truth)
        for method in REMOTE:
            record = result[method]
            for name, field in (('old', 'previous_decisions'), ('new', 'decisions')):
                record[name][label] = {d: core._mass(selected, weights,
                    lambda r: r[field][method] == d) if selected else None for d in original.DECISIONS}
            record['unknown_increase'][label] = legacy._difference(
                record['new'][label]['unknown'], record['old'][label]['unknown'])
            if truth:
                record['true_accept_loss'] = legacy._difference(record['old'][label]['accept'], record['new'][label]['accept'])
                record['remote_true_accept'] = core._mass(selected, weights,
                    lambda r: r['decision_reasons'][method] == 'message_support') if selected else None
    return result


def grouped_false(rows):
    false = [r for r in rows if original.primary(r, 0)]
    groups = {}
    keys = sorted({(r['family'], r['attack_k'], r['parent']) for r in false})
    for family, k, parent in keys:
        group = [r for r in false if (r['family'], r['attack_k'], r['parent']) == (family, k, parent)]
        groups[family+'/'+str(k)+'/'+parent] = dict(support=core._support(group), methods=comparisons(group))
    worst = {}
    for method in REMOTE:
        risks = {key: group['methods'][method]['new']['false']['accept'] for key, group in groups.items()}
        maximum = max(risks.values()) if risks else None
        worst[method] = dict(false_accept=maximum,
            groups=[key for key, risk in risks.items() if risk == maximum])
    return dict(groups=groups, worst=worst)


def judge(measured, policies, criteria, own):
    # Only the conditional candidate is assessed for improvement over new LocalCount.
    conditional = core._judge(measured, policies, criteria)['LocalCond']
    checks = dict(conditional['checks'])
    for method in REMOTE:
        checks['own_TA_loss_'+method] = legacy._check(own[method]['true_accept_loss'], .02)
        remote = own[method]['remote_true_accept']
        checks['remote_TA_'+method] = dict(status='insufficient' if remote is None else 'pass' if remote > 0 else 'fail', value=remote, requirement='positive')
        # Keep the count comparator within the same original risk requirements.
        stats = measured['system_query'][method]
        checks['TR_'+method] = legacy._check(stats['true']['weighted']['reject'], criteria.get('max_TR_global', .05))
        checks['FA_'+method] = legacy._check(stats['false']['weighted']['accept'], criteria.get('max_FA_global_and_layer', .05))
        for layer, group in measured['family_k'].items():
            checks['FA_'+method+'_'+layer] = legacy._check(group['metrics'][method]['false']['weighted']['accept'], criteria.get('max_FA_global_and_layer', .05))
    return dict(status=legacy._verdict(checks), checks=checks,
        conditional_comparison=conditional, Local_reference='descriptive_only')


def evaluate(source, screen):
    source, screen = Path(source).resolve(), Path(screen).resolve()
    out = screen/'evaluation'
    if source == out or source in out.parents or out in source.parents:
        raise ValueError('evaluation output overlaps source')
    if out.exists():
        raise FileExistsError('evaluation requires a new output directory')
    screened = json.loads((screen/'screen.json').read_text())
    go = screened['go_regimes']
    if len(set(go)) != len(go) or any(r not in ('mixed', 'F1_only', 'F2_only') for r in go):
        raise ValueError('invalid screened regimes')
    result = dict(schema='rq1_grouped_acceptance_development_evaluation_v1', regimes={},
        go_regimes=go, scope='previously seen development eval; fixed cal-selected thresholds', policy_budget_note=NOTE)
    paths = [screen/'screen.json']
    expected_cal = {}
    if go:
        binding = json.loads((screen/'binding.json').read_text())
        if Path(binding['source_run']).resolve() != source:
            raise ValueError('screen source differs')
        expected_cal = {r['path']: r for r in binding['sources']}
        config = json.loads((source/'evaluate.binding.json').read_text())['config']
        candidates = json.loads((screen/'candidate_policies.json').read_text())
        paths += [screen/'binding.json', screen/'candidate_policies.json', source/'evaluate.binding.json']
        paths += [source/'calibration'/(r+'.json') for r in go]
        paths += [source/'predictions'/r/(s+'.jsonl.gz') for r in go for s in ('cal', 'eval')]
    records = [data.source_record(p) for p in paths]
    for record in records:
        path = Path(record['path'])
        if path.parent.parent == source/'predictions' and path.name == 'cal.jsonl.gz' or path.parent == source/'calibration':
            if expected_cal.get(record['path']) != record:
                raise ValueError('screened cal inputs changed')
    data.atomic_json(out/'evaluate.binding.json', dict(source=str(source), screen=str(screen),
        sources=records,
        code=[data.source_record(p) for p in (__file__, core.__file__, original.__file__, legacy.__file__, data.__file__)]))
    started = time.monotonic()
    for regime in go:
        old = json.loads((source/'calibration'/(regime+'.json')).read_text())
        if set(candidates[regime]) != set(REMOTE):
            raise ValueError('candidate remote methods differ')
        new = dict(Local=copy.deepcopy(old['Local']), **candidates[regime])
        if set(new) != set(core.METHODS):
            raise ValueError('candidate methods differ')
        validate_policies(old, new)
        data.atomic_json(out/'calibration'/(regime+'.json'), new)
        measured = {}
        for split in ('cal', 'eval'):
            rows = list(data.read_rows(source/'predictions'/regime/(split+'.jsonl.gz')))
            if any(r['split'] != split for r in rows):
                raise ValueError('source split mismatch')
            revised = reapply(rows, old, new)
            with data.atomic_rows(out/'predictions'/regime/(split+'.jsonl.gz')) as write:
                for row in revised: write(row)
            spec = config['regimes'][regime]
            layers = [(f, k) for f in spec['cal_families' if split == 'cal' else 'eval_families'] for k in config['required_k']]
            actual = core.measurements(revised, layers, config.get('domains'))
            actual.update(own_comparison=comparisons(revised), by_group=grouped_false(revised),
                domain_own_comparison={name: comparisons([r for r in revised if r['parent'] in parents])
                    for name, parents in config.get('domains', {}).items()}, policy_budget_note=NOTE)
            data.atomic_json(out/'report'/regime/(split+'.json'), actual)
            measured[split] = actual
        result['regimes'][regime] = dict(measured, verdict=judge(measured['eval'], new,
            config.get('criteria', {}), measured['eval']['own_comparison']))
    result['seconds'] = time.monotonic()-started
    data.atomic_json(out/'evaluate.report.json', result)
    data.atomic_json(out/'evaluate.complete.json', dict(status='COMPLETE' if go else 'NO_GO', regimes=go))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--screen', required=True)
    args = parser.parse_args()
    evaluate(args.source, args.screen)
