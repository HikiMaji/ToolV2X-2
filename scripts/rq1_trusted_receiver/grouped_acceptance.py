"""Cal-only screen for stricter grouped remote acceptance; no eval or new predictions."""
import argparse
import copy
import json
from pathlib import Path

from scripts.rq1_temporal import data, run as original
from . import run

METHODS = ('LocalCount', 'LocalCond')
REGIMES = ('mixed', 'F1_only', 'F2_only')
RISK = .05
MAX_LOSS = .02
TOL = 1e-12


def screen_method(rows, policy, method):
    """Raise only tauC, keeping complete primary denominators and fixed local risk."""
    if method not in METHODS or any(r.get('split') != 'cal' for r in rows):
        raise ValueError('screen accepts only declared methods and cal rows')
    required = sorted({(str(f), int(k)) for f, k in policy['required_layers']})
    if not required:
        raise ValueError('declared false layers required')
    old = [run.decide(run._public(r), policy, method) for r in rows]
    for row, decision in zip(rows, old):
        if 'decisions' in row and row['decisions'].get(method) != decision['decision']:
            raise ValueError('source cal decision does not match frozen policy')
        if 'decision_reasons' in row and row['decision_reasons'].get(method) != decision['reason']:
            raise ValueError('source cal reason does not match frozen policy')
    decisions = {id(r): d for r, d in zip(rows, old)}
    true = [r for r in rows if original.primary(r, 1)]
    false = [r for r in rows if original.primary(r, 0)]
    if any((r['family'], r['attack_k']) not in required for r in false):
        raise ValueError('undeclared false layer in cal source')
    groups = {'overall': false}
    missing = []
    for family, k in required:
        name = family+'/'+str(k)
        group = [r for r in false if (r['family'], r['attack_k']) == (family, k)]
        groups[name] = group
        if not group:
            missing.append(name)
        for parent in sorted({r['parent'] for r in group}):
            groups[name+'/'+parent] = [r for r in group if r['parent'] == parent]
    remote = lambda r: decisions[id(r)]['reason'] == 'message_support'
    adopted = lambda r: decisions[id(r)]['decision'] == 'accept'
    tw = original.weights(true, 1)
    local_true = run._mass(true, tw, lambda r: adopted(r) and not remote(r))
    true_tail = run._tails(true, tw, 'C', remote)
    fixed, tails = {}, {}
    for name, group in groups.items():
        weights = original.weights(group, 0)
        fixed[name] = run._mass(group, weights, lambda r: adopted(r) and not remote(r)) if group else None
        tails[name] = run._tails(group, weights, 'C', remote)
    def measured(tau):
        return dict(true_accept=local_true+true_tail(tau) if true else None,
            remote_true_accept=true_tail(tau) if true else None,
            false_accept={name: None if fixed[name] is None else fixed[name]+tails[name](tau)
                          for name in groups})
    def risk_ok(measurement):
        return not missing and all(value is not None and value <= RISK+TOL
                                  for value in measurement['false_accept'].values())
    old_tau = run._tau(policy, 'tauC')
    before = measured(old_tau)
    local_infeasible = any(value is not None and value > RISK+TOL for value in fixed.values())
    tau, status = float('inf'), 'candidate'
    if risk_ok(before):
        tau, status = old_tau, 'unchanged'
    elif missing:
        status = 'not_estimable_missing_layers'
    elif local_infeasible:
        status = 'infeasible_local_risk'
    else:
        candidates = {old_tau, float('inf')}
        candidates.update(float(r['C']) for r in true+false
                          if remote(r) and run._finite(r.get('C')) and r['C'] >= old_tau)
        feasible = [t for t in candidates if risk_ok(measured(t))]
        if feasible:
            best = max(local_true+true_tail(t) for t in feasible)
            tau = max(t for t in feasible if local_true+true_tail(t) >= best-TOL)
        else:
            status = 'infeasible_risk'
    candidate = copy.deepcopy(policy)
    candidate['tauC'] = tau
    after = measured(tau)
    loss = None if before['true_accept'] is None else before['true_accept']-after['true_accept']
    checks = dict(risk=risk_ok(after), true_accept_loss=loss is not None and loss <= MAX_LOSS+TOL,
        remote_true_accept=after['remote_true_accept'] is not None and after['remote_true_accept'] > 0,
        local_feasible=not local_infeasible, false_coverage=not missing)
    transitions = {a+'/'+b: 0 for a in original.DECISIONS for b in original.DECISIONS}
    for row, previous in zip(rows, old):
        current = run.decide(run._public(row), candidate, method)
        a, b = previous['decision'], current['decision']
        if a != b and (a, b) != ('accept', 'unknown'):
            raise AssertionError('raising tauC changed a rejection or expanded adoption')
        transitions[a+'/'+b] += 1
    report = dict(status=status, go=all(checks.values()), checks=checks,
        old_tauC=old_tau, new_tauC=tau, old=before, new=after,
        true_accept_loss=loss, missing_layers=missing,
        local_false_accept=fixed, group_support={name: run._support(group) for name, group in groups.items()},
        true_support=run._support(true), transitions=transitions,
        limits=dict(false_accept=RISK, true_accept_loss=MAX_LOSS))
    return candidate, report


def screen(source_run, out):
    """Read exactly the three cal prediction files and three policy files."""
    source, out = Path(source_run).resolve(), Path(out).resolve()
    if source == out or source in out.parents or out in source.parents:
        raise ValueError('screen output overlaps source')
    if out.exists():
        raise FileExistsError('screen requires a new output directory')
    paths = [source/'predictions'/regime/'cal.jsonl.gz' for regime in REGIMES]
    paths += [source/'calibration'/(regime+'.json') for regime in REGIMES]
    binding = dict(schema='rq1_grouped_acceptance_cal_screen_v1', source_run=str(source),
        sources=[data.source_record(p) for p in paths],
        code=[data.source_record(p) for p in (__file__, run.__file__, original.__file__, data.__file__)],
        limits=dict(false_accept=RISK, true_accept_loss=MAX_LOSS),
        scope='cal only; source scores and tauF/tauP/tauR fixed; no eval read or predictions written')
    data.atomic_json(out/'binding.json', binding)
    reports, candidates = {}, {}
    for regime in REGIMES:
        rows = list(data.read_rows(source/'predictions'/regime/'cal.jsonl.gz'))
        if len({tuple(r['key']) for r in rows}) != len(rows):
            raise ValueError('duplicate cal keys')
        policies = json.loads((source/'calibration'/(regime+'.json')).read_text())
        candidates[regime], methods = {}, {}
        for method in METHODS:
            if any(method not in r.get('decisions', {}) or method not in r.get('decision_reasons', {}) for r in rows):
                raise ValueError('incomplete source cal predictions')
            candidates[regime][method], methods[method] = screen_method(rows, policies[method], method)
        reports[regime] = dict(go=all(r['go'] for r in methods.values()), methods=methods)
    result = dict(status='COMPLETE', regimes=reports,
        go_regimes=[r for r in REGIMES if reports[r]['go']],
        scope='empirical cal screen, not eval evidence or population risk guarantee')
    data.atomic_json(out/'candidate_policies.json', run._encode_thresholds(candidates))
    data.atomic_json(out/'screen.json', run._encode_thresholds(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    screen(args.source, args.out)


if __name__ == '__main__':
    main()
