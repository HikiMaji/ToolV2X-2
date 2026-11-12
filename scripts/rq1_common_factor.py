"""Declared Bernoulli mixture mechanism; no data fitting or truth-dependent scoring."""
import math
from dataclasses import dataclass

import numpy as np

TOL = 1e-12
SCORE_DECIMALS = 12
STATES = ('adopt', 'unknown', 'reject')


def _probability(value):
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('probability must be finite and in [0, 1]')


@dataclass
class Model:
    marginals: dict
    groups: tuple
    rho: dict

    def __post_init__(self):
        self.marginals = dict(self.marginals)
        self.groups = tuple(sorted(tuple(sorted(g)) for g in self.groups))
        self.rho = {tuple(sorted(g)): value for g, value in self.rho.items()}
        ids = [i for g in self.groups for i in g]
        if any(not g for g in self.groups) or len(ids) != len(set(ids)) or set(ids) != set(self.marginals):
            raise ValueError('groups must completely partition source IDs')
        if set(self.rho) != set(self.groups):
            raise ValueError('rho must specify every group exactly once')
        for value in list(self.marginals.values()) + list(self.rho.values()):
            _probability(value)


def proxy_groups(angles, threshold=15):
    if not math.isfinite(threshold) or not 0 <= threshold <= 180:
        raise ValueError('invalid circular angle threshold')
    if any(not math.isfinite(x) for x in angles.values()):
        raise ValueError('angles must be finite')
    pending, groups = set(angles), []
    while pending:
        members, todo = set(), [min(pending)]
        while todo:
            i = todo.pop()
            if i in members:
                continue
            members.add(i)
            for j in sorted(pending - members):
                difference = abs((angles[i] - angles[j]) % 360)
                if min(difference, 360 - difference) <= threshold:
                    todo.append(j)
        pending -= members
        groups.append(tuple(sorted(members)))
    return tuple(sorted(groups))


def _validate_events(events, marginals):
    if not set(events) <= set(marginals) or any(u not in (0, 1) for u in events.values()):
        raise ValueError('events must be registered binary observations')


def _log(value):
    return math.log(value) if value > 0 else -math.inf


def _group_log_probability(events, marginals, rho):
    _probability(rho)
    for z in marginals.values():
        _probability(z)
    _validate_events(events, marginals)
    if not events:
        return 0.
    independent = sum(_log(marginals[i] if events[i] else 1 - marginals[i]) for i in sorted(events))
    upper = min((marginals[i] for i in events if events[i]), default=1.)
    lower = max((marginals[i] for i in events if not events[i]), default=0.)
    common = _log(max(0., upper - lower))
    return float(np.logaddexp(_log(1 - rho) + independent, _log(rho) + common))


def group_probability(events, marginals, rho):
    return math.exp(_group_log_probability(events, marginals, rho))


def _group_logs(model, events, anchor):
    _validate_events(events, model.marginals)
    if anchor not in model.marginals or events.get(anchor) != 1:
        raise ValueError('anchor must be a registered observed report')
    if model.marginals[anchor] <= 0:
        raise ValueError('anchor conditioning has zero probability')
    logs = []
    for group in model.groups:
        value = _group_log_probability({i: events[i] for i in group if i in events}, model.marginals, model.rho[group])
        if anchor in group:
            value -= math.log(model.marginals[anchor])
        logs.append(value)
    return logs


def conditional_log_probability(model, events, anchor):
    return sum(_group_logs(model, events, anchor))


def anchor_conditioned_marginals(model, anchor):
    if anchor not in model.marginals or model.marginals[anchor] <= 0:
        raise ValueError('anchor conditioning has zero probability')
    result = dict(model.marginals)
    group = next(g for g in model.groups if anchor in g)
    rho, za = model.rho[group], model.marginals[anchor]
    for i in group:
        result[i] = (1 - rho) * model.marginals[i] + rho * min(za, model.marginals[i]) / za
    result[anchor] = 1.
    return result


def _difference(log_t, log_f):
    if log_t == -math.inf and log_f == -math.inf:
        return {'score': None, 'supported': False}
    return {'score': log_t - log_f, 'supported': True}


def _sum_evidence(values):
    if any(v is None for v in values) or (math.inf in values and -math.inf in values):
        return {'score': None, 'supported': False}
    return {'score': sum(values), 'supported': True}


def _canonical_score(result):
    raw = result['score']
    result['raw_score'] = raw
    if raw is not None and math.isfinite(raw):
        rounded = round(raw, SCORE_DECIMALS)
        result['score'] = 0. if rounded == 0 else rounded
    return result


def score_correct_model(actual_true, actual_false, events, anchor):
    logs_t = _group_logs(actual_true, events, anchor)
    logs_f = _group_logs(actual_false, events, anchor)
    result = _difference(sum(logs_t), sum(logs_f))
    # Differing actual partitions have no one-to-one group attribution.
    contributions = []
    attribution_supported = result['supported'] and actual_true.groups == actual_false.groups
    if attribution_supported:
        contributions = [a - b for a, b in zip(logs_t, logs_f)]
    result.update(group_contributions=contributions,
                  attribution_supported=attribution_supported,
                  positive=sum(max(x, 0.) for x in contributions) if attribution_supported else None,
                  negative=sum(max(-x, 0.) for x in contributions) if attribution_supported else None)
    return _canonical_score(result)


def score_methods(reference_true, reference_false, events, anchor, proxy_groups):
    j = score_correct_model(reference_true, reference_false, events, anchor)
    pt = anchor_conditioned_marginals(reference_true, anchor)
    pf = anchor_conditioned_marginals(reference_false, anchor)
    contributions = {}
    for i in sorted(events):
        if i != anchor:
            u = events[i]
            contributions[i] = _difference(_log(pt[i] if u else 1 - pt[i]),
                                            _log(pf[i] if u else 1 - pf[i]))['score']
    independent = _canonical_score(_sum_evidence(list(contributions.values())))
    weighted = {'score': None if independent['score'] is None else .5 * independent['score'],
                'raw_score': None if independent['raw_score'] is None else .5 * independent['raw_score'],
                'supported': independent['supported']}
    means = []
    for group in proxy_groups:
        values = [contributions[i] for i in group if i in contributions]
        if values:
            subtotal = _sum_evidence(values)['score']
            means.append(None if subtotal is None else subtotal / len(values))
    return {'I': independent, 'W': weighted, 'G': _canonical_score(_sum_evidence(means)), 'J': j}


def decide(score, supported, eligible, policy):
    if not supported or not eligible or score is None or score == 0:
        return 'unknown'
    if math.isnan(score):
        raise ValueError('NaN score is forbidden')
    if score > 0 and policy['adopt_enabled'] and score >= policy['tau_A']:
        return 'adopt'
    if score < 0 and policy['reject_enabled'] and score <= policy['tau_R']:
        return 'reject'
    return 'unknown'


def _metrics(rows, method, policy, eligible_only):
    selected = [r for r in rows if r['eligible'] or not eligible_only]
    denominators = {'true': sum(r['wT'] for r in selected), 'false': sum(r['wF'] for r in selected)}
    masses = {f'{truth}_{state}': 0. for truth in ('true', 'false') for state in STATES}
    unsupported = {'true': 0., 'false': 0.}
    for row in selected:
        score = row['scores'][method]
        state = decide(score['score'], score['supported'], row['eligible'], policy)
        for truth, key in (('true', 'wT'), ('false', 'wF')):
            masses[f'{truth}_{state}'] += row[key]
            if not score['supported']:
                unsupported[truth] += row[key]
    result = {'denominators': denominators, 'masses': masses}
    for truth in denominators:
        d = denominators[truth]
        for state in STATES:
            result[f'{truth}_{state}'] = masses[f'{truth}_{state}'] / d if d else None
    result['unsupported'] = {truth: unsupported[truth] / d if d else None for truth, d in denominators.items()}
    estimable = all(denominators.values())
    result['undefined_reason'] = None if estimable else 'zero_denominator'
    result['correct_clear'] = (result['true_adopt'] + result['false_reject']) / 2 if estimable else None
    result['max_error'] = max(result['false_adopt'], result['true_reject']) if estimable else None
    return result


def fit_frontier(rows, method, epsilon):
    _probability(epsilon)
    policy = {'adopt_enabled': False, 'reject_enabled': False, 'tau_A': math.inf, 'tau_R': -math.inf}
    dt = sum(r['wT'] for r in rows if r['eligible'])
    df = sum(r['wF'] for r in rows if r['eligible'])
    if not dt or not df:
        return {'status': 'not_estimable', 'epsilon': epsilon, 'policy': policy,
                'metrics': _metrics(rows, method, policy, True)}
    for branch, sign, correct_key, error_key, dc, de, threshold_key in (
            ('adopt', 1, 'wT', 'wF', dt, df, 'tau_A'),
            ('reject', -1, 'wF', 'wT', df, dt, 'tau_R')):
        eligible = [r for r in rows if r['eligible'] and r['scores'][method]['supported']
                    and r['scores'][method]['score'] * sign > 0]
        thresholds = sorted({r['scores'][method]['score'] for r in eligible}, reverse=sign > 0)
        best_correct, best_error = 0., 0.
        for threshold in thresholds:
            selected = [r for r in eligible if (r['scores'][method]['score'] >= threshold if sign > 0
                                                else r['scores'][method]['score'] <= threshold)]
            correct = sum(r[correct_key] for r in selected) / dc
            error = sum(r[error_key] for r in selected) / de
            if error > epsilon + TOL:
                continue
            if correct > best_correct + TOL or (abs(correct - best_correct) <= TOL and error < best_error - TOL):
                policy[branch + '_enabled'] = True
                policy[threshold_key] = threshold
                best_correct, best_error = correct, error
    return {'status': 'ok', 'epsilon': epsilon, 'policy': policy,
            'metrics': _metrics(rows, method, policy, True)}


def summarize(rows, policies, strata):
    def summarize_part(part):
        return {m: {scope: _metrics(part, m, p, scope == 'eligible') for scope in ('all', 'eligible')}
                for m, p in policies.items()}
    result = {'overall': summarize_part(rows), 'strata': {}}
    for field in strata:
        values = sorted({r[field] for r in rows}, key=str)
        result['strata'][field] = {str(v): summarize_part([r for r in rows if r[field] == v]) for v in values}
    return result
