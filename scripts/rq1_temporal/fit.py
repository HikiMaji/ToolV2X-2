"""Supervised proxy models and parent-held-out window likelihood estimation."""
from collections import Counter, defaultdict
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

CLIP = 1e-6
RHO_GRID = (0., .25, .5, .75, .9)


def fit_logistic(X, y, w, signs):
    X, y, w = np.asarray(X, float), np.asarray(y, float), np.asarray(w, float)
    if (X.ndim != 2 or len(X) == 0 or y.shape != (len(X),) or
            w.shape != y.shape or not np.isfinite(X).all() or
            not np.isfinite(w).all() or np.any(w <= 0) or
            set(np.unique(y)) != {0.,1.}):
        raise ValueError('logistic not estimable: finite samples and both classes required')
    if len(signs) != X.shape[1] or any(s not in (-1,0,1) for s in signs):
        raise ValueError('one coefficient sign in {-1,0,1} required per feature')
    w = w/w.sum()
    mean = w @ X
    std = np.sqrt(w @ ((X-mean)**2))
    scale = np.where(std <= 1e-6, 1., std)
    design = np.column_stack([np.ones(len(X)), (X-mean)/scale])
    def objective(beta):
        linear = design @ beta
        loss = w @ (np.logaddexp(0., linear)-y*linear) + .005*(beta[1:]@beta[1:])
        grad = design.T @ (w*(expit(linear)-y))
        grad[1:] += .01*beta[1:]
        return float(loss), grad
    bounds = [(None,None)] + [(0.,None) if s == 1 else (None,0.) if s == -1 else (None,None) for s in signs]
    result = minimize(objective, np.zeros(design.shape[1]), jac=True,
                      method='L-BFGS-B', bounds=bounds,
                      options=dict(maxiter=500, ftol=1e-10, gtol=1e-6))
    if not result.success or not np.isfinite(result.x).all():
        raise RuntimeError('logistic optimization failed: '+str(result.message))
    return dict(mean=mean.tolist(), scale=scale.tolist(), std=std.tolist(),
                intercept=float(result.x[0]), coef=result.x[1:].tolist(), clip=CLIP,
                feature_min=X.min(axis=0).tolist(), feature_max=X.max(axis=0).tolist(),
                n_samples=len(X), class_weight=[float(w[y==v].sum()) for v in (0,1)],
                optimizer=dict(success=bool(result.success), message=str(result.message),
                               nit=int(result.nit), loss=float(result.fun)))


def _predict(model, x):
    raw = expit((np.asarray(x)-model['mean'])/model['scale'] @ np.asarray(model['coef'])+model['intercept'])
    if not np.isfinite(raw):
        raise ValueError('nonfinite logistic prediction')
    return float(np.clip(raw, CLIP, 1-CLIP))


def _x(row, i):
    x = row['X'][i]
    if x is None:
        return None
    x = np.asarray(x, float)
    return x if x.shape == (5,) and np.isfinite(x).all() else None


def _cue(row, i):
    c = row['C'][i]
    return None if row['C_missing'][i] or c is None or not np.isfinite(c) else float(c)


def _epoch(row):
    return (row['job_id'], row['id'], row.get('epoch',0))


def sample_weights(records):
    """Normalize parent/epoch/frame/source weights on this task's usable set."""
    parents = defaultdict(lambda: defaultdict(Counter))
    for r, _ in records:
        parents[r['parent']][_epoch(r)][r['index']] += 1
    if not parents:
        raise ValueError('no usable supervision')
    return np.asarray([1/(len(parents)*len(parents[r['parent']])*
                          len(parents[r['parent']][_epoch(r)])*
                          parents[r['parent']][_epoch(r)][r['index']]) for r,_ in records])


def fit_models(rows):
    from .kernel import windows
    rows = [r for r in rows if r.get('split') == 'fit' and r.get('kind') == 'clean'
            and r.get('query_present') and r.get('query_truth') == 1]
    tasks = {name: [] for name in ('D','h_B','h_C','emission','transition','pi','T_base')}
    for r in rows:
        for i,u in enumerate(r['U']):
            x = _x(r,i)
            if u not in (0,1) or x is None:
                continue
            c, z = _cue(r,i), r['Z'][i]
            tasks['D'].append((r,i,np.r_[x,0. if c is None else c, float(c is None)],u))
            if z not in (0,1):
                continue
            tasks['h_B'].append((r,i,x,z))
            tasks['pi'].append((r,i,None,z))
            tasks['emission'].append((r,i,np.r_[x,z],u))
            if c is not None:
                tasks['h_C'].append((r,i,np.r_[x,c],z))
    # Derive legal adjacency on unfiltered rows so unknown labels cannot bridge a gap.
    all_rows = sorted(rows, key=lambda r: (str(r['job_id']),str(r['id']),r['index']))
    for window in windows(all_rows, W=2):
        if len(window) != 2:
            continue
        prev, r = window
        if r.get('query_gt_id') is None or r.get('query_gt_id') != prev.get('query_gt_id'):
            continue
        for i,u in enumerate(r['U']):
            x, c = _x(r,i), _cue(r,i)
            z, zp = r['Z'][i], prev['Z'][i]
            if (u not in (0,1) or prev['U'][i] not in (0,1) or x is None or
                    _x(prev,i) is None or z not in (0,1) or zp not in (0,1)):
                continue
            tasks['T_base'].append((r,i,np.array([zp]),z))
            if c is not None:
                tasks['transition'].append((r,i,np.r_[x,c,zp],z))
    signs = dict(D=[0]*5+[-1,0], h_B=[0]*5, h_C=[0]*5+[-1],
                 emission=[0]*5+[1], transition=[0]*5+[-1,1])
    out, supports, statuses = {}, {}, {}
    for name, sign in signs.items():
        samples = tasks[name]
        supports[name] = dict(n_sources=len(samples), n_rows=len({(r['parent'],_epoch(r),r['index']) for r,_,_,_ in samples}))
        try:
            if not samples:
                raise ValueError('no usable supervision')
            w = sample_weights([(r,i) for r,i,_,_ in samples])
            fitted = fit_logistic([a[2] for a in samples], [a[3] for a in samples], w, sign)
        except (ValueError, RuntimeError) as error:
            statuses[name] = dict(status='unestimable', reason=name+': '+str(error))
            continue
        fitted['train_parents'] = sorted({r['parent'] for r,_,_,_ in samples})
        out[name] = fitted
        statuses[name] = dict(status='ok', reason=None)
    pi_samples = tasks['pi']
    pi_raw = None
    if pi_samples:
        w = sample_weights([(r,i) for r,i,_,_ in pi_samples])
        pi_raw = float(w @ np.array([a[3] for a in pi_samples]))
        out['pi'] = float(np.clip(pi_raw,CLIP,1-CLIP))
        statuses['pi'] = dict(status='ok', reason=None)
    else:
        statuses['pi'] = dict(status='unestimable', reason='pi: no usable supervision')
    samples = tasks['T_base']
    counts = np.zeros((2,2),int)
    mass = np.zeros((2,2))
    if samples:
        w = sample_weights([(r,i) for r,i,_,_ in samples])
        for (_,_,x,z),weight in zip(samples,w):
            counts[int(x[0]),z] += 1
            mass[int(x[0]),z] += weight
    raw = None
    if np.any(mass.sum(axis=1) == 0):
        statuses['T_base'] = dict(status='unestimable', reason='T_base: a previous-state row has no supervision')
    else:
        raw = mass/mass.sum(axis=1,keepdims=True)
        p = np.clip(raw[:,1],CLIP,1-CLIP)
        out['T_base'] = np.column_stack([1-p,p]).tolist()
        statuses['T_base'] = dict(status='ok', reason=None)
    out['component_status'] = statuses
    out['diagnostics'] = dict(train_parents=sorted({r['parent'] for r in rows}), supports=supports,
                              pi_raw=pi_raw, pi_n=len(pi_samples), T_base_counts=counts.tolist(),
                              T_base_weighted_mass=mass.tolist(), T_base_raw=None if raw is None else raw.tolist(),
                              T_base_boundary=None if raw is None else ((raw==0)|(raw==1)).tolist(), clip=CLIP)
    return out


def method_status(models, rho):
    """Fixed dependencies distinguish unavailable parameters from numeric failures."""
    dependencies = dict(D=('D',), B=('h_B','emission'), C=('h_B','h_C','emission'),
                        T=('h_B','h_C','emission','transition','pi','T_base'))
    statuses = {}
    components = models.get('component_status',{})
    for name, needed in dependencies.items():
        missing = [c for c in needed if c not in models or components.get(c,{}).get('status','ok') != 'ok']
        reasons = [components.get(c,{}).get('reason') or c+' unavailable' for c in missing]
        statuses[name] = dict(status='unestimable' if missing else 'ok', reason='; '.join(reasons) or None)
    valid_rho = isinstance(rho,(int,float,np.number)) and np.isfinite(rho) and 0 <= rho <= 1
    joint_reason = statuses['T']['reason'] or (None if valid_rho else 'rho estimation unavailable')
    for name in ('J','Jind','G'):
        statuses[name] = dict(status='unestimable' if joint_reason else 'ok', reason=joint_reason)
    return statuses


def predict_row(row, models):
    """Predict only usable dependencies from online fields, without default models."""
    n = len(row['U'])
    status = method_status(models,0.)
    active = {m for m,v in status.items() if v['status'] == 'ok'}
    out = dict(u=np.full(n,-1,dtype=int))
    if 'D' in active:
        out['D'] = np.full(n,np.nan)
    if active.intersection(('B','C','T')):
        out['hB'] = np.full(n,models.get('pi',np.nan))
        out['emit'] = np.full((n,2),.5)
    if active.intersection(('C','T')):
        out['hC'] = np.full(n,models.get('pi',np.nan))
    if 'T' in active:
        out['trans'] = np.tile(np.asarray(models['T_base'],float),(n,1,1))
    for i,u in enumerate(row['U']):
        x = _x(row,i)
        if x is None:
            continue
        if u in (0,1):
            out['u'][i] = u
        c = _cue(row,i)
        if 'D' in out:
            out['D'][i] = _predict(models['D'],np.r_[x,0. if c is None else c,float(c is None)])
        if 'hB' in out:
            out['hB'][i] = _predict(models['h_B'],x)
            for z in (0,1):
                out['emit'][i,z] = _predict(models['emission'],np.r_[x,z])
        if 'hC' in out:
            out['hC'][i] = out['hB'][i] if c is None else _predict(models['h_C'],np.r_[x,c])
        if 'trans' in out and c is not None:
            for z in (0,1):
                p = _predict(models['transition'],np.r_[x,c,z])
                out['trans'][i,z] = [1-p,p]
    return out


def _fit_rho_oof(fit_rows, W=10):
    """Refit every parent fold and rerun complete windows for each fixed rho."""
    from .kernel import normal_window, windows
    rows = [r for r in fit_rows if r.get('split') == 'fit' and r.get('kind') == 'clean']
    parents = sorted({r['parent'] for r in rows})
    if len(parents) < 2:
        raise ValueError('rho OOF not estimable: at least two fit parents required')
    objectives = {str(rho): 0. for rho in RHO_GRID}
    folds, common_groups = [], 0
    for parent in parents:
        models = fit_models([r for r in rows if r['parent'] != parent])
        temporal = method_status(models,0.)['T']
        if temporal['status'] != 'ok':
            raise ValueError('rho OOF fold '+str(parent)+': '+temporal['reason'])
        # OOF does not consume D, so its prediction cannot disable state fitting.
        models = {k:v for k,v in models.items() if k != 'D'}
        held = sorted([r for r in rows if r['parent'] == parent],
                      key=lambda r:(str(r['job_id']),str(r['id']),r['index']))
        targets = []
        for window in windows(held,W):
            current = window[-1]
            if not current.get('query_present') or current.get('newborn') or current.get('query_truth') != 1:
                continue
            preds = [predict_row(r,models) for r in window]
            if not any(np.any(p['u'] >= 0) for p in preds):
                continue
            groups = [r['groups'] for r in window]
            common_groups += sum(sum(sum(p['u'][i] >= 0 for i in g) >= 2 for g in group) for p,group in zip(preds,groups))
            losses = [ -normal_window(preds,groups,rho)['loglik'] for rho in RHO_GRID]
            targets.append((current,losses))
        if not targets:
            raise ValueError('rho OOF not estimable: held parent has no valid target windows: '+parent)
        weights = sample_weights([(r,0) for r,_ in targets])
        loss = weights @ np.asarray([v for _,v in targets])
        for rho,value in zip(RHO_GRID,loss):
            objectives[str(rho)] += float(value)/len(parents)
        folds.append(dict(parent=parent, train_parents=sorted(set(parents)-{parent}),
                          n_windows=len(targets), objectives={str(r):float(v) for r,v in zip(RHO_GRID,loss)}))
    best = min(objectives.values())
    rho = min(r for r in RHO_GRID if objectives[str(r)] <= best+1e-8)
    reason = 'minimum_parent_epoch_frame_weighted_window_nll'
    if not common_groups:
        rho,reason = 0.,'no_common_group_information'
    elif objectives['0.0']-best <= 1e-8:
        rho,reason = 0.,'no_increment_over_rho_zero'
    return dict(status='ok', rho=rho, objectives=objectives, folds=folds,
                common_valid_groups=common_groups, reason=reason, W=W)


def fit_rho_oof(fit_rows, W=10):
    """A failed OOF fit has no rho estimate; it never silently becomes rho zero."""
    try:
        return _fit_rho_oof(fit_rows,W)
    except (ValueError, RuntimeError, FloatingPointError, OverflowError) as error:
        return dict(status='unestimable', rho=None, reason=type(error).__name__+': '+str(error),
                    objectives={str(r):None for r in RHO_GRID}, folds=[], common_valid_groups=0, W=W)
