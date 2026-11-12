"""Exact finite-window report likelihoods; these functions read online fields only."""
from itertools import product
import math
import numpy as np
from scipy.special import logsumexp

METHODS = ('D', 'B', 'C', 'T', 'J', 'Jind', 'G')


def _groups(groups, n):
    groups = [list(g) for g in groups]
    if sorted(i for g in groups for i in g) != list(range(n)):
        raise ValueError('groups must partition source indices')
    return groups


def _bern_logs(u, p):
    u, p = np.asarray(u), np.asarray(p, float)
    valid = (u == 0) | (u == 1)
    out = np.zeros(len(u))
    with np.errstate(divide='ignore'):
        out[valid] = np.where(u[valid] == 1, np.log(p[valid]), np.log1p(-p[valid]))
    return out


def _propagate(b, trans, n):
    b = b.reshape([2] * n)
    for i in range(n):
        b = np.moveaxis(np.moveaxis(b, i, -1) @ trans[i], -1, i)
    return b.reshape(-1)


def _emission_log(u, probs, groups, rho):
    """One log emission per joint state, marginalizing unknown coordinates."""
    out = np.zeros(len(probs))
    for group in groups:
        ones = [i for i in group if u[i] == 1]
        zeros = [i for i in group if u[i] == 0]
        independent = np.zeros(len(probs))
        if ones:
            independent += np.log(probs[:, ones]).sum(axis=1)
        if zeros:
            independent += np.log1p(-probs[:, zeros]).sum(axis=1)
        if rho == 0:
            out += independent
            continue
        low = probs[:, zeros].max(axis=1) if zeros else np.zeros(len(probs))
        high = probs[:, ones].min(axis=1) if ones else np.ones(len(probs))
        common = np.maximum(0., high-low)
        with np.errstate(divide='ignore'):
            out += np.logaddexp(math.log1p(-rho) + independent, math.log(rho) + np.log(common)) if rho < 1 else np.log(common)
    return out


def normal_window(predictions, groups, rho, mode='J'):
    """Return full-window log likelihood and pre-observation marginal diagnostics.

    groups may be a fixed partition or one partition per prediction. ``mode=T``
    sets rho to zero; otherwise the supplied rho governs emission and filtering.
    """
    predictions = list(predictions)
    if not predictions:
        return dict(loglik=0., steps=[], posterior=[])
    n = len(predictions[0]['u'])
    if not 1 <= n <= 7:
        raise ValueError('exact normal forward supports 1..7 sources')
    if not 0 <= rho <= 1:
        raise ValueError('rho must lie in [0,1]')
    if mode not in ('T', 'J'):
        raise ValueError('normal mode must be T or J')
    rho = 0. if mode == 'T' else rho
    # A time-varying partition has one extra nesting level.
    dynamic = bool(groups) and bool(groups[0]) and isinstance(groups[0][0], (list, tuple, np.ndarray))
    partitions = groups if dynamic else [groups] * len(predictions)
    if len(partitions) != len(predictions):
        raise ValueError('one partition required per prediction')
    states = np.asarray(list(product((0, 1), repeat=n)), dtype=int)
    h = np.asarray(predictions[0]['hC'], float)
    b = np.prod(np.where(states, h, 1-h), axis=1)
    total, steps = 0., []
    for t, (pred, group) in enumerate(zip(predictions, partitions)):
        u = np.asarray(pred['u'], int)
        if len(u) != n or np.any(~np.isin(u, [-1,0,1])):
            raise ValueError('invalid source events')
        if t:
            b = _propagate(b, np.asarray(pred['trans'], float), n)
        emit = np.asarray(pred['emit'], float)
        probs = emit[np.arange(n)[None, :], states]
        p = b @ probs
        marginal = _bern_logs(u, p)
        emission = _emission_log(u, probs, _groups(group, n), rho)
        with np.errstate(divide='ignore'):
            logpost = np.log(b) + emission
        # No observation has exactly unit likelihood and does not reweight state.
        ll = float(logsumexp(logpost)) if np.any(u >= 0) else 0.
        if not np.isfinite(ll):
            raise ValueError('normal event has zero or invalid likelihood')
        if np.any(u >= 0):
            b = np.exp(logpost-ll)
        total += ll
        steps.append(dict(loglik=ll, p=p.tolist(), marginal_loglik=marginal.tolist(),
                          delta=float(ll-marginal.sum())))
    return dict(loglik=float(total), steps=steps, posterior=b.tolist())


def false_window(U, s=.9):
    """Four fixed-family Markov likelihood, once over the complete source set."""
    U = np.asarray(U, int)
    if U.ndim != 2 or not U.shape[1] or np.any(~np.isin(U, [-1,0,1])):
        raise ValueError('U must be nonempty time by source events')
    if not 0 <= s <= 1:
        raise ValueError('s must lie in [0,1]')
    n = U.shape[1]
    rates = (.1, .2, .4, .2)
    states = [np.tile([1-r, r], (n if f < 3 else 1, 1)) for f, r in enumerate(rates)]
    logw = np.full(4, -math.log(4))
    total, steps = 0., []
    for t, u in enumerate(U):
        family_ll, family_q = [], []
        for f, r in enumerate(rates):
            if t:
                states[f] = s*states[f] + (1-s)*np.array([1-r, r])
            q = states[f][:, 1]
            family_q.append(np.repeat(q, n) if f == 3 else q.copy())
            observed = np.flatnonzero(u >= 0)
            if f < 3:
                ll = float(_bern_logs(u, q).sum())
            elif not len(observed):
                ll = 0.
            elif np.all(u[observed] == u[observed[0]]):
                value = states[f][0, u[observed[0]]]
                ll = math.log(value) if value > 0 else -math.inf
            else:
                ll = -math.inf
            family_ll.append(ll)
        q = np.exp(logw) @ np.asarray(family_q)
        marginal = _bern_logs(u, q)
        ll = float(logsumexp(logw + family_ll)) if np.any(u >= 0) else 0.
        if not np.isfinite(ll):
            raise ValueError('false reference has zero or invalid likelihood')
        if np.any(u >= 0):
            logw = logw + family_ll - ll
        # An impossible shared family stays at zero; never normalize its state.
        for f in range(4):
            if not np.isfinite(logw[f]):
                continue
            if f < 3:
                for i in np.flatnonzero(u >= 0):
                    states[f][i] = [1-u[i], u[i]]
            elif np.any(u >= 0):
                event = u[u >= 0][0]
                states[f][0] = [1-event, event]
        total += ll
        steps.append(dict(loglik=ll, q=q.tolist(), marginal_loglik=marginal.tolist(),
                          delta=float(ll-marginal.sum()), family_weights=np.exp(logw).tolist()))
    return dict(loglik=float(total), steps=steps, family_weights=np.exp(logw).tolist())


def windows(rows, W=10):
    """Yield one causal window per input row; never inspect offline labels."""
    if W < 1:
        raise ValueError('W must be positive')
    histories = {}
    for row in rows:
        key = (row['job_id'], row['id'])
        old = histories.get(key, [])
        present = bool(row.get('query_present', True))
        if old:
            prev = old[-1]
            continuous = (row['index'] == prev['index']+1 and
                          abs(row['timestamp']-prev['timestamp']-.1) <= 1e-6 and
                          row['source_ids'] == prev['source_ids'] and
                          row.get('epoch') == prev.get('epoch'))
            if not continuous:
                old = []
        if not present or row.get('newborn', False):
            histories.pop(key, None)
            yield [row]
        else:
            history = (old+[row])[-W:]
            histories[key] = history
            yield history


def _score_window(window, models, rho, W=10, s=.9):
    """Recompute available methods on the same causal window and false side."""
    from .fit import predict_row, method_status
    window = list(windows(window, W))[-1]
    current = window[-1]
    status = method_status(models,rho)
    active = {m for m,v in status.items() if v['status'] == 'ok'}
    scores = {m:None for m in METHODS}
    normal_logs = {m:None for m in METHODS}
    if not current.get('query_present', True) or current.get('newborn', False):
        return dict(scores={m:0. if m in active else None for m in METHODS}, current={}, window={},
                    opportunity_union=[], support_union=[], accept_eligible=False,
                    reject_eligible=False, finite=True, n_frames=0, method_status=status,
                    normal_loglik={m:0. if m in active and m not in ('Jind','G') else None for m in METHODS},
                    steps={'T':[], 'J':[], 'F':[]})
    preds = [predict_row(r, models) for r in window]
    U = np.asarray([p['u'] for p in preds])
    groups = [_groups(r['groups'], len(r['U'])) for r in window]
    false = false_window(U, s)
    steps = dict(F=false['steps'])
    for m,h in (('D',None),('B','hB'),('C','hC')):
        if m not in active:
            continue
        steps[m] = []
        for pred in preds:
            p = np.asarray(pred['D']) if h is None else (
                (1-np.asarray(pred[h]))*np.asarray(pred['emit'])[:,0] +
                np.asarray(pred[h])*np.asarray(pred['emit'])[:,1])
            logs = _bern_logs(pred['u'],p)
            steps[m].append(dict(loglik=float(logs.sum()), p=p.tolist(),
                                 marginal_loglik=logs.tolist(), delta=0.))
        normal_logs[m] = sum(a['loglik'] for a in steps[m])
        scores[m] = normal_logs[m]-false['loglik']
    for m in ('T','J'):
        if m not in active:
            continue
        result = normal_window(preds,groups,0. if m == 'T' else rho,m)
        steps[m] = result['steps']
        normal_logs[m] = result['loglik']
        scores[m] = result['loglik']-false['loglik']
    summaries = []
    if 'J' in active:
        for pred,tj,fj,group in zip(preds,steps['J'],false['steps'],groups):
            u = np.asarray(pred['u'])
            e = np.asarray(tj['marginal_loglik'])-np.asarray(fj['marginal_loglik'])
            group_e = sum(float(e[ix].mean()) for g in group
                          for ix in [[i for i in g if u[i] >= 0]] if ix)
            summaries.append(dict(e=e.tolist(), delta_T=tj['delta'], delta_F=fj['delta'],
                                  group_e=group_e, logL_T=tj['loglik'], logL_F=fj['loglik']))
        scores['Jind'] = sum(sum(a['e'])-a['delta_F'] for a in summaries)
        scores['G'] = sum(a['group_e']-a['delta_F'] for a in summaries)
    opportunity = np.flatnonzero(np.any(U >= 0, axis=0)).tolist()
    support = np.flatnonzero(np.any(U == 1, axis=0)).tolist()
    eligible = len(opportunity) >= 2
    accept = (eligible and len(support) >= 2 and current.get('query_present', True)
              and current.get('output_present', False) and current.get('identity_ok', False))
    summary = dict(e=None, delta_T=None, delta_F=None, normal_loglik=normal_logs['J'],
                   false_loglik=false['loglik'])
    if summaries:
        summary.update(e=np.sum([a['e'] for a in summaries],axis=0).tolist(),
                       delta_T=sum(a['delta_T'] for a in summaries),
                       delta_F=sum(a['delta_F'] for a in summaries))
    return dict(scores=scores, current=summaries[-1] if summaries else {}, window=summary,
                opportunity_union=opportunity, support_union=support,
                accept_eligible=bool(accept), reject_eligible=bool(eligible and np.any(U == 0)),
                finite=bool(np.isfinite([v for v in scores.values() if v is not None]).all()),
                n_frames=len(window), method_status=status, normal_loglik=normal_logs, steps=steps)


def score_window(window, models, rho, W=10, s=.9):
    """Score one record; numerical failure retains it with common unknown scores."""
    window = list(window)
    if not window:
        raise ValueError('cannot score empty window')
    try:
        result = _score_window(window,models,rho,W,s)
        if not result['finite']:
            raise FloatingPointError('nonfinite temporal score')
        return result
    except (ValueError, FloatingPointError, OverflowError) as error:
        from .fit import method_status
        status = method_status(models,rho)
        for method,value in status.items():
            if value['status'] == 'ok':
                status[method] = dict(status='numeric_failure', reason=str(error))
        return dict(scores={m:None for m in METHODS}, current={}, window={},
                    normal_loglik={m:None for m in METHODS}, steps={},
                    opportunity_union=[], support_union=[], accept_eligible=False,
                    reject_eligible=False, finite=False, n_frames=min(W,len(window)),
                    error=type(error).__name__+': '+str(error), method_status=status)
