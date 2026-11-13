"""Normal-side causal summaries and the frozen seven-coefficient score heads."""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ[_name]='1'

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scripts.rq1_temporal.fit import predict_row, method_status
from scripts.rq1_temporal.kernel import normal_window, windows, _groups

BASE_METHODS=('D_head','T_head','I_Jmargin','G')
METHODS=('D_head','T_head','I_Jmargin','J','G','Q','MATE_policy')
FEATURES=('L_plus','L_minus','n_plus','w','d','m')
DEPENDENCIES=dict(D_head='D',T_head='T',I_Jmargin='J',G='J')


def window_features(window, models, rho, W=10):
    """Read only online fields; each normal step predicts before observing U."""
    window=list(window)
    if not window:
        raise ValueError('empty window')
    window=list(windows(window,W))[-1]
    current=window[-1];normal_status=method_status(models,rho)
    status={m:dict(normal_status[DEPENDENCIES[m]]) for m in BASE_METHODS}
    result=dict(features={m:None for m in BASE_METHODS},sources={m:None for m in BASE_METHODS},
                method_status=status,delta_T=None,n_minus=[],context=[0,0,0],
                accept_eligible=False,reject_eligible=False,finite=True,n_frames=0,error=None)
    if not current.get('query_present',True) or current.get('newborn',False):
        for m in BASE_METHODS:
            if status[m]['status']=='ok':
                result['features'][m]=[0.]*6
                result['sources'][m]=np.zeros((len(current['U']),3)).tolist()
        return result
    try:
        # Invalid events are numerical/input failures, never silently missing.
        if any(np.any(~np.isin(r['U'],[-1,0,1])) for r in window):
            raise ValueError('invalid source events')
        preds=[predict_row(r,models) for r in window]
        U=np.asarray([p['u'] for p in preds]);n=U.shape[1]
        groups=[_groups(r['groups'],n) for r in window]
        opportunity=np.any(U>=0,axis=0);support=np.any(U==1,axis=0)
        context=[len(window),int(opportunity.sum()),int(support.sum())]
        result.update(context=context,n_frames=len(window),n_minus=(U==0).sum(0).tolist(),
                      accept_eligible=bool(opportunity.sum()>=2 and support.sum()>=2
                          and current.get('output_present',False) and current.get('identity_ok',False)),
                      reject_eligible=bool(opportunity.sum()>=2 and np.any(U==0)))
        probabilities={}
        if status['D_head']['status']=='ok':
            probabilities['D_head']=[p['D'] for p in preds]
        if status['T_head']['status']=='ok':
            probabilities['T_head']=[s['p'] for s in normal_window(preds,groups,0.,'T')['steps']]
        if status['I_Jmargin']['status']=='ok':
            joint=normal_window(preds,groups,rho,'J')
            probabilities['I_Jmargin']=[s['p'] for s in joint['steps']]
            result['delta_T']=float(sum(s['delta'] for s in joint['steps']))
        for method,ps in probabilities.items():
            per_source=np.zeros((n,3));grouped=np.zeros((n,3))
            for u,p,partition in zip(U,ps,groups):
                valid=u>=0;p=np.asarray(p,float)
                if np.any(~np.isfinite(p[valid])):
                    raise ValueError('nonfinite normal probability')
                p=np.clip(p,1e-6,1-1e-6)
                values=np.zeros((n,3));plus=u==1;minus=u==0
                values[plus,0]=np.log(p[plus]);values[minus,1]=np.log1p(-p[minus]);values[plus,2]=1.
                per_source+=values
                if method=='I_Jmargin':
                    for group in partition:
                        ix=[i for i in group if valid[i]]
                        if ix:
                            grouped[ix]+=values[ix]/len(ix)
            result['sources'][method]=per_source.tolist()
            result['features'][method]=np.r_[per_source.sum(0),context].tolist()
            if method=='I_Jmargin':
                result['sources']['G']=grouped.tolist()
                result['features']['G']=np.r_[grouped.sum(0),context].tolist()
        numbers=[v for x in result['features'].values() if x is not None for v in x]
        if result['delta_T'] is not None:
            numbers.append(result['delta_T'])
        if not np.isfinite(numbers).all():
            raise ValueError('nonfinite summary')
    except (ValueError,FloatingPointError,OverflowError) as error:
        result.update(features={m:None for m in BASE_METHODS},sources={m:None for m in BASE_METHODS},
                      delta_T=None,finite=False,accept_eligible=False,reject_eligible=False,
                      error=type(error).__name__+': '+str(error))
        for value in status.values():
            if value['status']=='ok':
                value.update(status='numeric_failure',reason=result['error'])
    return result


def _samples(X,y,w):
    X,y,w=np.asarray(X,float),np.asarray(y,float),np.asarray(w,float)
    if (not len(y) or y.shape!=w.shape or not np.isfinite(X).all()
            or not np.isfinite(y).all() or not np.isfinite(w).all() or np.any(w<=0)
            or set(np.unique(y))!={0.,1.}):
        raise ValueError('finite supervision and both classes required')
    return X,y,w/w.sum()


def fit_base(X,y,w):
    X,y,w=_samples(X,y,w)
    if X.shape!=(len(y),6):
        raise ValueError('six features required')
    mean=w@X;std=np.sqrt(w@((X-mean)**2));constant=std<=1e-6
    scale=np.where(constant,1.,std);design=np.column_stack([np.ones(len(y)),(X-mean)/scale])
    bounds=[(None,None)]+[(0.,0.) if fixed else (0.,None) if i<2 else (None,None) for i,fixed in enumerate(constant)]
    def objective(beta):
        s=design@beta;loss=w@(np.logaddexp(0.,s)-y*s)+.005*(beta[1:]@beta[1:])
        grad=design.T@(w*(expit(s)-y));grad[1:]+=.01*beta[1:]
        return float(loss),grad
    fitted=minimize(objective,np.zeros(7),jac=True,method='L-BFGS-B',bounds=bounds,
                    options=dict(maxiter=500,ftol=1e-10,gtol=1e-6))
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise RuntimeError('head optimizer failed: '+str(fitted.message))
    return dict(status='ok',optimizer_ok=True,features=list(FEATURES),mean=mean.tolist(),std=std.tolist(),
                scale=scale.tolist(),constant=constant.tolist(),coef=fitted.x[1:].tolist(),
                intercept=float(fitted.x[0]),n_samples=len(y),class_weight=[float(w[y==v].sum()) for v in (0,1)],
                feature_min=X.min(0).tolist(),feature_max=X.max(0).tolist(),
                optimizer=dict(success=True,nit=int(fitted.nit),loss=float(fitted.fun),message=str(fitted.message)))


def raw_parameters(model):
    coef=np.asarray(model['coef'])/model['scale']
    return dict(coef=coef.tolist(),intercept=float(model['intercept']-coef@model['mean']))


def base_score(model,x):
    score=float(((np.asarray(x)-model['mean'])/model['scale'])@model['coef']+model['intercept'])
    if not np.isfinite(score):
        raise ValueError('nonfinite head score')
    return score


def decompose(model,source_features,context):
    raw=raw_parameters(model);coef=np.asarray(raw['coef'])
    source=np.asarray(source_features)@coef[:3]
    global_score=float(raw['intercept']+np.asarray(context)@coef[3:])
    return dict(source_scores=source.tolist(),global_score=global_score,score=float(source.sum()+global_score))


def fit_increment(x,y,w,offset,parents,joint=False):
    x,y,w=_samples(x,y,w);offset=np.asarray(offset,float);parents=np.asarray(parents)
    if x.shape!=y.shape or offset.shape!=y.shape or parents.shape!=y.shape or not np.isfinite(offset).all():
        raise ValueError('increment input shape or offset invalid')
    rms=float(np.sqrt(w@(x*x)));std=float(np.sqrt(w@((x-w@x)**2)))
    varying=[]
    for parent in sorted(set(parents)):
        mask=parents==parent;pw=w[mask]/w[mask].sum();px=x[mask]
        if np.sqrt(pw@((px-pw@px)**2))>1e-6:
            varying.append(str(parent))
    informative=rms>1e-6 and (not joint or (std>1e-6 and len(varying)>=3))
    info=dict(rms=rms,std=std,varying_parents=varying,delta_informative=bool(informative) if joint else None,
              scaling='weighted_RMS_no_centering',n_samples=len(y))
    if not informative:
        return dict(info,status='delta_uninformative' if joint else 'increment_uninformative',
                    optimizer_ok=None,coef_std=0.,coefficient=0.)
    z=x/rms
    def objective(beta):
        s=offset+beta[0]*z
        return float(w@(np.logaddexp(0.,s)-y*s)+.005*beta[0]**2),np.array([w@((expit(s)-y)*z)+.01*beta[0]])
    fitted=minimize(objective,np.zeros(1),jac=True,method='L-BFGS-B',
                    options=dict(maxiter=500,ftol=1e-10,gtol=1e-6))
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise RuntimeError('increment optimizer failed: '+str(fitted.message))
    return dict(info,status='ok',optimizer_ok=True,coef_std=float(fitted.x[0]),coefficient=float(fitted.x[0]/rms),
                optimizer=dict(success=True,nit=int(fitted.nit),loss=float(fitted.fun),message=str(fitted.message)))


def increment_score(model,offset,x):
    score=float(offset+model['coefficient']*x)
    if not np.isfinite(score):
        raise ValueError('nonfinite increment score')
    return score
