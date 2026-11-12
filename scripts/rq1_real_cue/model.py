"""Frozen marginal, residual-dependence and global policy specification."""
from collections import Counter, defaultdict
import math
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logsumexp

CLIP = 1e-6
METHODS = ('B', 'C', 'J', 'G')
FALSE_MARGIN = .225


def primary(row):
    return (row.get('kind') == 'clean' and row.get('query_truth') == 1) or (row.get('kind') == 'attack' and row.get('query_truth') == 0)


def normal_rows(rows):
    return [r for r in rows if r.get('kind') == 'clean' and r.get('query_truth') == 1 and r.get('query_present')]


def query_weights(rows):
    parents = defaultdict(Counter)
    for r in rows:
        parents[r['parent']][r['job_id']] += 1
    return np.array([1 / (len(parents) * len(parents[r['parent']]) * parents[r['parent']][r['job_id']]) for r in rows], float)


def margin_features(row, use_cue):
    values, indices = [], []
    for i, u in enumerate(row['U']):
        if u not in (0, 1):
            continue
        x = row['X'][i]
        if x is None or len(x) < 5:
            continue
        x = np.asarray(x[:5], float)
        if not np.isfinite(x).all():
            continue
        if use_cue:
            x = np.r_[x, row['C'][i], row['C_missing'][i]]
        if not np.isfinite(x).all():
            raise ValueError('nonfinite cue')
        values.append(x)
        indices.append(i)
    return np.array(values, float).reshape(-1, 7 if use_cue else 5), indices


def fit_margin(rows, use_cue):
    rows = [r for r in normal_rows(rows) if r.get('split', 'fit') == 'fit' and len(margin_features(r, use_cue)[1])]
    if not rows:
        raise ValueError('no normal fit observations')
    X, y, w = [], [], []
    for r, weight in zip(rows, query_weights(rows)):
        x, ix = margin_features(r, use_cue)
        X.extend(x); y.extend(r['U'][i] for i in ix); w.extend([weight / len(ix)] * len(ix))
    X, y, w = np.asarray(X), np.asarray(y), np.asarray(w)
    if len(np.unique(y)) != 2:
        raise ValueError('margin is not estimable without both report outcomes')
    mean = w @ X
    std = np.sqrt(w @ ((X - mean) ** 2))
    scale = np.where(std <= 1e-6, 1., std)
    z = np.c_[np.ones(len(X)), (X - mean) / scale]

    def objective(beta):
        linear = z @ beta
        loss = w @ (np.logaddexp(0., linear) - y * linear) + .01 / 2 * (beta[1:] @ beta[1:])
        grad = z.T @ (w * (expit(linear) - y))
        grad[1:] += .01 * beta[1:]
        return float(loss), grad

    bounds = [(None, None)] * z.shape[1]
    if use_cue:
        bounds[6] = (None, 0.)
    result = minimize(objective, np.zeros(z.shape[1]), jac=True, method='L-BFGS-B', bounds=bounds,
                      options=dict(maxiter=500, ftol=1e-10, gtol=1e-6))
    if not result.success or not np.isfinite(result.x).all():
        raise RuntimeError('margin optimization failed: ' + str(result.message))
    return dict(use_cue=bool(use_cue), mean=mean.tolist(), scale=scale.tolist(), std=std.tolist(),
                intercept=float(result.x[0]), coef=result.x[1:].tolist(),
                train_parents=sorted({r['parent'] for r in rows}), n_queries=len(rows), n_sources=len(y),
                optimizer=dict(success=True, message=str(result.message), nit=int(result.nit), loss=float(result.fun)),
                feature_min=X.min(axis=0).tolist(), feature_max=X.max(axis=0).tolist(), clip=CLIP)


def predict_margin(fitted, X):
    X = np.asarray(X, float).reshape(-1, len(fitted['coef']))
    raw = expit(((X - fitted['mean']) / fitted['scale']) @ np.asarray(fitted['coef']) + fitted['intercept'])
    p = np.clip(raw, CLIP, 1 - CLIP)
    return p, dict(n=int(len(raw)), clipped=int(np.count_nonzero(p != raw)),
                   raw_min=float(raw.min()) if len(raw) else None, raw_max=float(raw.max()) if len(raw) else None)


def attach_probabilities(rows, fitted, field):
    """One batch matrix operation per model; no per-query standardization."""
    arrays, owners = [], []
    for r in rows:
        x, ix = margin_features(r, fitted['use_cue'])
        r[field] = [None] * len(r['U'])
        arrays.extend(x)
        owners.extend((r, i) for i in ix)
    p, summary = predict_margin(fitted, arrays)
    for (r, i), value in zip(owners, p):
        r[field][i] = float(value)
    return summary


def crossfit_cue_margin(fit_rows):
    rows = normal_rows(fit_rows)
    parents = sorted({r['parent'] for r in rows})
    if len(parents) != 5:
        raise ValueError('crossfit requires five fit parents')
    oof, folds = [], {}
    for parent in parents:
        train = [r for r in rows if r['parent'] != parent]
        held = [dict(r) for r in rows if r['parent'] == parent]
        fitted = fit_margin(train, True)
        clipping = attach_probabilities(held, fitted, 'p_C')
        folds[parent] = dict(train_parents=fitted['train_parents'], model=fitted, clipping=clipping, n_held=len(held))
        oof.extend(held)
    return oof, folds


def _group_parts(p, u):
    p, u = np.asarray(p, float), np.asarray(u)
    observed = (u == 0) | (u == 1)
    p, u = p[observed], u[observed]
    if not len(p):
        return 0., 0., 0
    if not np.isfinite(p).all() or (p < CLIP).any() or (p > 1 - CLIP).any():
        raise ValueError('invalid probability')
    ind = float(np.where(u == 1, np.log(p), np.log1p(-p)).sum())
    upper = float(p[u == 1].min()) if (u == 1).any() else 1.
    lower = float(p[u == 0].max()) if (u == 0).any() else 0.
    mass = max(0., upper - lower)
    return ind, math.log(mass) if mass > 0 else -np.inf, len(p)


def _mixed_log(ind, comono, rho):
    if rho == 0:
        return ind
    return float(np.logaddexp(math.log1p(-rho) + ind, math.log(rho) + comono))


def normal_logprob(p, u, groups, rho):
    if not 0 <= rho <= .95:
        raise ValueError('rho outside fixed range')
    p, u = np.asarray(p, float), np.asarray(u)
    if sorted(i for g in groups for i in g) != list(range(len(u))):
        raise ValueError('groups must partition registered dimensions')
    return sum(_mixed_log(*_group_parts(p[g], u[g])[:2], rho) for g in groups)


def false_logprob(u):
    u = np.asarray(u)
    u = u[(u == 0) | (u == 1)]
    m, k = len(u), int(u.sum())
    if not m:
        return 0.
    logs = [k * math.log(r) + (m - k) * math.log1p(-r) for r in (.1, .2, .4)]
    logs.append(math.log(.8) if k == 0 else math.log(.2) if k == m else -np.inf)
    return float(logsumexp(logs) - math.log(4))


def fit_rho(oof_rows):
    rows = normal_rows(oof_rows)
    w = query_weights(rows)
    ind, comono, weights = [], [], []
    informative_queries, informative_parents = set(), set()
    constant_nll = 0.
    for qi, (row, weight) in enumerate(zip(rows, w)):
        p = np.array([np.nan if x is None else x for x in row['p_C']])
        u = np.array(row['U'])
        u[~np.isfinite(p)] = -1
        for g in row['groups']:
            a, b, m = _group_parts(p[g], u[g])
            if m < 2 or (np.isfinite(b) and abs(a - b) <= 1e-12):
                constant_nll -= weight * a
                continue
            ind.append(a);comono.append(b);weights.append(weight)
            informative_queries.add(qi);informative_parents.add(row['parent'])
    diagnostics = dict(nontrivial_queries=len(informative_queries), nontrivial_groups=len(ind),
                       nontrivial_parents=len(informative_parents))
    if not ind:
        return dict(rho=0., status='structurally_unidentified', nll_gain=0., objective_at_zero=constant_nll, objective_at_best=constant_nll, **diagnostics)
    a, b, w = np.asarray(ind), np.asarray(comono), np.asarray(weights)

    def nll(rho):
        if rho == 0:
            return float(constant_nll - w @ a)
        return float(constant_nll - w @ np.logaddexp(np.log1p(-rho) + a, np.log(rho) + b))

    opt = minimize_scalar(nll, bounds=(0., .95), method='bounded', options={'xatol': 1e-10})
    if not opt.success:
        raise RuntimeError('rho optimization failed')
    best = min([0., .95, float(opt.x)], key=lambda r: (nll(r), r))
    gain = nll(0.) - nll(best)
    status = 'estimated'
    if gain <= 1e-8:
        best, status = 0., 'negligible_gain'
    return dict(rho=best, status=status, nll_gain=gain, objective_at_zero=nll(0.), objective_at_best=nll(best), **diagnostics)


def score_query(row, models):
    _, indices = margin_features(row, False)
    u = np.array([row['U'][i] for i in indices])
    groups = [[indices.index(i) for i in g if i in indices] for g in row['groups']]
    groups = [g for g in groups if g]
    m, k = len(u), int(u.sum())
    eligible = bool(row.get('query_present') and m >= 2)
    result = dict(m=m, k=k, eligible=eligible, valid_indices=indices,
                  scores={name: None for name in METHODS}, raw_scores={name: None for name in METHODS},
                  supported=True, failure=None, p_B=[], p_C=[], e_B=[], e=[], delta=[], gamma=0.,
                  common_effective_group=any(len(g) > 1 for g in groups), effective_groups=groups)
    if not row.get('query_present'):
        return result
    try:
        pb = np.array([row['p_B'][i] for i in indices], float)
        pc = np.array([row['p_C'][i] for i in indices], float)
        eb = np.where(u == 1, np.log(pb / FALSE_MARGIN), np.log((1 - pb) / (1 - FALSE_MARGIN)))
        ec = np.where(u == 1, np.log(pc / FALSE_MARGIN), np.log((1 - pc) / (1 - FALSE_MARGIN)))
        q = false_logprob(u)
        gamma = float(k * math.log(FALSE_MARGIN) + (m - k) * math.log1p(-FALSE_MARGIN) - q)
        ni = normal_logprob(pc, u, groups, 0.)
        nj = normal_logprob(pc, u, groups, models['rho'])
        raw = dict(B=normal_logprob(pb, u, groups, 0.) - q, C=ni - q, J=nj - q,
                   G=sum(float(ec[g].mean()) for g in groups) + gamma)
        if not all(np.isfinite(v) for v in raw.values()):
            raise ValueError('nonfinite scores')
        delta = [_mixed_log(*_group_parts(pc[g], u[g])[:2], models['rho']) - _group_parts(pc[g], u[g])[0] for g in groups]
        result.update(raw_scores=raw, scores={name: round(v, 12) for name, v in raw.items()},
                      p_B=pb.tolist(), p_C=pc.tolist(), e_B=eb.tolist(), e=ec.tolist(), delta=delta, gamma=gamma)
    except (KeyError, ValueError, FloatingPointError, TypeError) as exc:
        result.update(supported=False, failure=str(exc))
    return result


def calibrate(rows, method, alpha=.05):
    rows = [r for r in rows if primary(r) and r['eligible']]
    weights = np.zeros(len(rows))
    for truth in (0, 1):
        ix = [i for i, r in enumerate(rows) if r['query_truth'] == truth]
        weights[ix] = query_weights([rows[i] for i in ix])
    has_both = {r['query_truth'] for r in rows} == {0, 1}
    policy = dict(alpha=alpha, status='estimated' if has_both else 'not_estimable',
                  reason=None if has_both else 'missing primary calibration class', accept=dict(enabled=False, threshold=None, benefit=0., error=0.),
                  reject=dict(enabled=False, threshold=None, benefit=0., error=0.))
    if not has_both:
        for branch in ['accept', 'reject']:
            policy[branch].update(benefit=None, error=None)
        return policy
    for branch, sign, benefit_truth in [('accept', 1, 1), ('reject', -1, 0)]:
        entries = [(r['scores'][method], r['query_truth'], w) for r, w in zip(rows, weights)
                   if r['scores'][method] is not None and r['scores'][method] * sign > 0]
        entries.sort(key=lambda x: -sign * x[0])
        good = bad = 0.
        best = None
        j = 0
        while j < len(entries):
            score = entries[j][0]
            while j < len(entries) and entries[j][0] == score:
                _, truth, weight = entries[j]
                if truth == benefit_truth:good += weight
                else:bad += weight
                j += 1
            if bad <= alpha + 1e-12 and good > 0:
                rank = (-good, bad, -sign * score)
                if best is None or rank < best[0]:
                    best = (rank, dict(enabled=True, threshold=score, benefit=good, error=bad))
        if best:
            policy[branch] = best[1]
    return policy


def decide(score, eligible, policy):
    if not eligible or score is None or not np.isfinite(score):
        return 'unknown'
    if score > 0 and policy['accept']['enabled'] and score >= policy['accept']['threshold']:
        return 'accept'
    if score < 0 and policy['reject']['enabled'] and score <= policy['reject']['threshold']:
        return 'reject'
    return 'unknown'
