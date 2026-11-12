"""Conditional report evidence under the frozen declared synthetic models.

Bernoulli mixtures provide the true-side construction (Bae & Iscoe, 2014).
The pointwise false envelope follows the composite-null likelihood principle
in Universal Inference; it is a conservative control, not a posterior or an
out-of-distribution guarantee. All parameters here are declared, not learned.
"""
import itertools
import math

from rq1_common_factor import decide

METHODS = ('I0', 'J0', 'Ic', 'Jc', 'Gc', 'JcF', 'Ec')
STATES = ('adopt', 'unknown', 'reject')
REFERENCE = {'theta': .8, 'accuracy': .8}
FALSE_RATES = (.1, .2, .4)
RBAR = .425
TOL = 1e-12


def _probability(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('probability must be finite and in [0, 1]')
    return value


def _log(value):
    return math.log(value) if value else -math.inf


def _bern_log(bit, p):
    return _log(p if bit else 1 - p)


def _logmix(first, second, weight):
    terms = (_log(weight) + first, _log(1 - weight) + second)
    maximum = max(terms)
    if maximum == -math.inf:
        return maximum
    return maximum + math.log(sum(math.exp(t - maximum) for t in terms))


def visibility_weight(c, theta, accuracy):
    _probability(theta)
    _probability(accuracy)
    if c not in (0, 1):
        raise ValueError('cue must be 0 or 1')
    numerator = theta * (accuracy if c else 1 - accuracy)
    denominator = numerator + (1 - theta) * (1 - accuracy if c else accuracy)
    if denominator == 0:
        raise ValueError('zero-probability cue')
    return numerator / denominator


def cue_distribution(groups, theta, accuracy):
    _probability(theta)
    _probability(accuracy)
    p = theta * accuracy + (1 - theta) * (1 - accuracy)
    return [(bits, mass) for bits in itertools.product((0, 1), repeat=len(groups))
            if (mass := math.prod(p if c else 1 - p for c in bits)) > 0]


def true_logprob(events, groups, p_clear, p_blocked, theta, accuracy, cues,
                 use_cue=True, joint=True):
    """Anchor cancels; missing peers, including whole groups, integrate to one."""
    total = 0.
    for index, group in enumerate(groups):
        ids = sorted(i for i in group if i in events)
        if not ids:
            continue
        w = visibility_weight(cues[index], theta, accuracy) if use_cue else theta
        if joint:
            total += _logmix(sum(_bern_log(events[i], p_clear[i]) for i in ids),
                             sum(_bern_log(events[i], p_blocked[i]) for i in ids), w)
        else:
            total += sum(_bern_log(events[i], w * p_clear[i] + (1 - w) * p_blocked[i]) for i in ids)
    return total


def false_probabilities(events, registered_peers):
    bits = [events[i] for i in sorted(registered_peers) if i in events]
    return tuple(math.prod(r if bit else 1 - r for bit in bits) for r in FALSE_RATES) + (float(all(bits)),)


def actual_false_probability(events, registered_peers, attack):
    peers = tuple(sorted(registered_peers))
    if attack['kind'] == 'independent':
        r = _probability(attack['r'])
        return math.prod(r if events[i] else 1 - r for i in peers if i in events)
    if attack['kind'] != 'partial' or not peers:
        raise ValueError('unknown attack or empty registered peer set')
    # Choose the cooperating ID before masking: a hidden forced report integrates out.
    return sum((0. if events.get(j, 1) != 1 else
                math.prod(.2 if events[i] else .8 for i in peers if i != j and i in events))
               for j in peers) / len(peers)


def _difference(log_t, log_f):
    if log_t == log_f == -math.inf:
        return None
    return log_t - log_f


def _safe_sum(values):
    if any(v is None for v in values) or (math.inf in values and -math.inf in values):
        return None
    return sum(values)


def _score(raw, e, delta, gamma):
    if raw is not None and math.isnan(raw):
        raise ArithmeticError('NaN evidence is forbidden')
    value = round(raw, 12) if raw is not None and math.isfinite(raw) else raw
    return {'score': 0. if value == 0 else value, 'raw_score': raw,
            'supported': raw is not None, 'e_i': e, 'delta_g': delta, 'gamma': gamma}


def _validate_context(context, events, reference_params):
    anchor = context['anchor']
    groups = context['groups']
    peers = [i for group in groups for i in group]
    if any(not group for group in groups) or len(peers) != len(set(peers)) or anchor in peers:
        raise ValueError('peer groups must partition registered peers and exclude anchor')
    if events.get(anchor) != 1 or set(events) - ({anchor} | set(peers)):
        raise ValueError('anchor must report and events must use registered IDs')
    if set(events) - set(context['observed']) or any(bit not in (0, 1) for bit in events.values()):
        raise ValueError('events must be observed binary reports')
    if len(context['C']) != len(groups) or any(c not in (0, 1) for c in context['C']):
        raise ValueError('one binary cue per registered group is required')
    for key in ('p_clear', 'p_blocked'):
        if not set(peers) <= set(context[key]):
            raise ValueError('missing peer quality parameter')
        for i in peers:
            _probability(context[key][i])
    _probability(reference_params['theta'])
    _probability(reference_params['accuracy'])


def score_methods(context, events, reference_params):
    """Read public inputs and frozen reference parameters only, never generation truth."""
    _validate_context(context, events, reference_params)
    group_cues = sorted((tuple(sorted(group)), c) for group, c in zip(context['groups'], context['C']))
    groups, cues = tuple(g for g, _ in group_cues), tuple(c for _, c in group_cues)
    peers = tuple(i for g in groups for i in g)
    observed = sorted(i for i in peers if i in events)
    theta, accuracy = reference_params['theta'], reference_params['accuracy']
    clear, blocked = context['p_clear'], context['p_blocked']
    pf = false_probabilities(events, peers)
    log_q, log_m = _log(sum(pf) / 4), _log(max(pf))
    log_b = sum(_bern_log(events[i], RBAR) for i in observed)
    gamma = _difference(log_b, log_q)
    models = {}
    for use_cue in (False, True):
        e, deltas = {}, []
        for index, group in enumerate(groups):
            ids = sorted(i for i in group if i in events)
            w = visibility_weight(cues[index], theta, accuracy) if use_cue else theta
            single = {}
            for i in ids:
                single[i] = _bern_log(events[i], w * clear[i] + (1 - w) * blocked[i])
                e[i] = _difference(single[i], _bern_log(events[i], RBAR))
            log_joint = true_logprob(events, (group,), clear, blocked, theta, accuracy,
                                     (cues[index],) if use_cue else (), use_cue, True)
            deltas.append(_difference(log_joint, sum(single.values())))
        log_joint = true_logprob(events, groups, clear, blocked, theta, accuracy, cues, use_cue, True)
        log_independent = true_logprob(events, groups, clear, blocked, theta, accuracy, cues, use_cue, False)
        suffix = 'c' if use_cue else '0'
        models['I' + suffix] = _score(_difference(log_independent, log_b), e, [], 0.)
        models['J' + suffix] = _score(_difference(log_joint, log_q), e, deltas, gamma)
        if use_cue:
            means = [_safe_sum([e[i] for i in group if i in e]) / len([i for i in group if i in e])
                     if all(e[i] is not None for i in group if i in e) else None
                     for group in groups if any(i in e for i in group)]
            models['Gc'] = _score(_safe_sum(means), e, [], 0.)
            models['JcF'] = _score(_difference(log_independent, log_q), e, [], gamma)
            models['Ec'] = _score(_difference(log_joint, log_m), e, deltas, _difference(log_b, log_m))
    return {name: models[name] for name in METHODS}


def disabled_policy():
    return {'adopt_enabled': False, 'reject_enabled': False, 'tau_A': math.inf, 'tau_R': -math.inf}


def _class_metrics(states, weight):
    masses = {s: 0. for s in STATES}
    denominator, unsupported = 0., 0.
    for row, state, supported in states:
        mass = weight(row)
        denominator += mass
        masses[state] += mass
        if not supported:
            unsupported += mass
    return {'denominator': denominator, 'masses': masses,
            'rates': {s: masses[s] / denominator if denominator else None for s in STATES},
            'unsupported': unsupported / denominator if denominator else None,
            'undefined_reason': None if denominator else 'zero_denominator'}


def evaluate_policy(rows, method, policy, eligible_only=True, event_conditioned=False):
    selected = [r for r in rows if r['eligible'] or not eligible_only]
    states = [(r, decide(r['scores'][method]['score'], r['scores'][method]['supported'], r['eligible'], policy),
               r['scores'][method]['supported']) for r in selected]
    result = {'true': _class_metrics(states, lambda r: r['wT']),
              'Fk': [_class_metrics(states, lambda r, k=k: r['wFk'][k]) for k in range(4)],
              'Q_F': _class_metrics(states, lambda r: sum(r['wFk']) / 4)}
    if selected and all('wActualF' in r for r in selected):
        result['actual_F'] = _class_metrics(states, lambda r: r['wActualF'])
    per_context = {}
    for row, state, _ in states:
        context = per_context.setdefault(row['context_id'], {'weight': row['context_weight'], 'eligible': row['eligible'],
                                                            'totals': [0.] * 4, 'adopt': [0.] * 4, 'reject': [0.] * 4})
        for k in range(4):
            context['totals'][k] += row['wFk'][k]
            if state in ('adopt', 'reject'):
                context[state][k] += row['wFk'][k]
    complete = all(all(abs(mass - c['weight']) <= TOL for mass in c['totals']) for c in per_context.values())
    denominator = result['Q_F']['denominator']
    reason = ('event_conditioned_stratum' if event_conditioned or not complete else
              'zero_denominator' if not denominator else None)
    result['context_extrema_undefined_reason'] = reason
    result['context_worst_false_adopt'] = (sum(max(c['adopt']) for c in per_context.values()) / denominator if reason is None else None)
    result['context_worst_false_reject'] = (sum(min(c['reject']) for c in per_context.values()) / denominator if reason is None else None)
    result['max_context_false_adopt'] = (max((max(c['adopt']) / c['weight'] for c in per_context.values() if c['weight'] and c['eligible']), default=None)
                                         if reason is None else None)
    t, f = result['true']['rates'], result['Q_F']['rates']
    result['correct_clear'] = (t['adopt'] + f['reject']) / 2 if t['adopt'] is not None and f['reject'] is not None else None
    worst_reject = result['context_worst_false_reject']
    result['conservative_correct_clear'] = ((t['adopt'] + worst_reject) / 2
                                           if t['adopt'] is not None and worst_reject is not None else None)
    result['max_error'] = max(t['reject'], f['adopt']) if result['correct_clear'] is not None else None
    return result


def fit_policy(rows, method, epsilon, robust=False):
    _probability(epsilon)
    policy = disabled_policy()
    eligible = [r for r in rows if r['eligible']]
    baseline = evaluate_policy(eligible, method, policy, True)
    if baseline['context_extrema_undefined_reason'] == 'event_conditioned_stratum':
        raise ValueError('fit_policy requires complete context pattern populations')
    if baseline['correct_clear'] is None:
        return {'status': 'not_estimable', 'epsilon': epsilon, 'policy': policy, 'metrics': baseline}
    for branch, positive in (('adopt', True), ('reject', False)):
        candidates = sorted({r['scores'][method]['score'] for r in eligible
                             if r['scores'][method]['supported'] and r['scores'][method]['score'] is not None
                             and (r['scores'][method]['score'] > 0 if positive else r['scores'][method]['score'] < 0)},
                            reverse=positive)
        best = (0., 0., 0.)
        for threshold in candidates:
            trial = dict(policy)
            trial[branch + '_enabled'] = True
            trial['tau_A' if positive else 'tau_R'] = threshold
            metrics = evaluate_policy(eligible, method, trial, True)
            t, f = metrics['true']['rates'], metrics['Q_F']['rates']
            gain = t['adopt'] if positive else (metrics['context_worst_false_reject'] if robust else f['reject'])
            error = (metrics['context_worst_false_adopt'] if robust else f['adopt']) if positive else t['reject']
            secondary = f['reject'] if robust and not positive else 0.
            if error > epsilon + TOL or (gain <= TOL and secondary <= TOL):
                continue
            if (gain > best[0] + TOL or
                    (abs(gain - best[0]) <= TOL and (secondary > best[1] + TOL or
                     (abs(secondary - best[1]) <= TOL and error < best[2] - TOL)))):
                policy = trial
                best = (gain, secondary, error)
    return {'status': 'ok', 'epsilon': epsilon, 'policy': policy,
            'metrics': evaluate_policy(rows, method, policy, True)}
