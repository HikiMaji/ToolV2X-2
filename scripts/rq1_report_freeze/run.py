"""One frozen batch: prepare in native Python, then old-environment fit/evaluate."""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[_name]='1'

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
import json
from pathlib import Path
import subprocess
import sys
import traceback
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scripts.rq1_temporal import data, run as original
from scripts.rq1_score_revision import heads, run as legacy, no_miss_constant as zero

REPO=Path(__file__).resolve().parents[2]
CONFIG=REPO/'docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/config.json'
METHODS=('Count','CountQ','D_old','D_zero','I_zero','J_zero','G_zero','Q_zero','MATE_policy')
FROZEN=('D_old','D_zero','I_zero','J_zero','MATE_policy')
NEW=('Count','CountQ','G_zero','Q_zero')
OLD_ALIASES=dict(D_old='D_head',MATE_policy='MATE_policy')


def read(path): return json.loads(Path(path).read_text())


def save(path,value):
    value=data.finite_json(value);path=Path(path)
    if path.exists():
        if read(path)!=value: raise ValueError('existing artifact differs '+str(path))
    else: data.atomic_json(path,value)


def rows_once(path,rows):
    path=Path(path)
    if path.exists():
        if list(data.read_rows(path))!=rows: raise ValueError('resumed predictions differ '+str(path))
    else:
        with data.atomic_rows(path) as write:
            for row in rows: write(row)


def validate_config(config):
    if tuple(config['methods'])!=METHODS or config['window']!=10: raise ValueError('method/window mismatch')
    old=config['old_parent_splits'];parents=config['additional_eval_parents'];jobs=config['jobs']
    if Counter(old.values())!=Counter(fit=6,cal=5,eval=3) or len(set(parents))!=6 or set(parents)&set(old):
        raise ValueError('frozen parent isolation mismatch')
    for a,b in config['known_protected_overlap']:
        if a in set(old)|set(parents) and b in parents or b in set(old)|set(parents) and a in parents:
            raise ValueError('protected parent overlap')
    if len(jobs)!=30 or len({j['job_id'] for j in jobs})!=30: raise ValueError('30 distinct tasks required')
    expected={(p,f,k) for p in parents for f,k in [('clean',0),('F1',1),('F1',2),('F2',1),('F2',2)]}
    if {(j['parent'],j['family'],j['attack_k']) for j in jobs}!=expected: raise ValueError('frozen task inventory mismatch')
    for j in jobs:
        if (j['split']!='eval' or j['seed']!=0 or j['kind']!=('clean' if j['family']=='clean' else 'attack')): raise ValueError('task metadata mismatch')


def read_config(path=None):
    config=read(path or CONFIG);validate_config(config);return config


def bind(config,out):
    out=Path(out).resolve()
    for name in ('source_original_scores','source_zero_scores'):
        source=Path(config[name]).resolve()
        if out==source or out in source.parents or source in out.parents: raise ValueError('output overlaps source')
    sources=[config['source_manifest'],config['source_normal_models']]
    for regime in config['regimes']:
        sources += [str(Path(config[root])/folder/(regime+'.json')) for root in ('source_original_scores','source_zero_scores') for folder in ('models','calibration')]
    code=[Path(__file__),Path(__file__).with_name('prepare.py'),Path(heads.__file__),Path(legacy.__file__),Path(zero.__file__),Path(original.__file__),Path(data.__file__),Path(legacy.fitting.__file__),Path(legacy.kernel.__file__),Path(legacy.prepare.__file__),Path(data.__file__).with_name('native_adapter.py'),REPO/'scripts/rq1_real_cue/geometry.py']
    record=dict(config=config,sources=[data.source_record(p) for p in sources],code=[data.source_record(p) for p in code])
    save(out/'binding.json',record)
    return record


def count_inputs(row):
    context=row.get('context');x=row.get('features',{}).get('D_head');minus=row.get('n_minus')
    if (not row.get('finite',False) or context is None or len(context)!=3 or x is None or len(x)!=6 or minus is None or (context[0]>0 and not minus)):
        raise ValueError('Count requires actual valid-event counts')
    result=np.array([x[2],sum(minus),*context],float)
    if not np.isfinite(result).all() or np.any(result<0): raise ValueError('invalid Count inputs')
    return result.tolist()


def fit_count(X,y,w):
    X,y,w=heads._samples(X,y,w)
    if X.shape!=(len(y),5): raise ValueError('five Count features required')
    mean=w@X;std=np.sqrt(w@((X-mean)**2));constant=std<=1e-6;scale=np.where(constant,1.,std)
    design=np.column_stack([np.ones(len(y)),(X-mean)/scale])
    def objective(beta):
        s=design@beta;loss=w@(np.logaddexp(0.,s)-y*s)+.005*(beta[1:]@beta[1:])
        grad=design.T@(w*(expit(s)-y));grad[1:]+=.01*beta[1:]
        return float(loss),grad
    fitted=minimize(objective,np.zeros(6),jac=True,method='L-BFGS-B',bounds=[(None,None)]+[(0.,0.) if c else (None,None) for c in constant],options=dict(maxiter=500,ftol=1e-10,gtol=1e-6))
    if not fitted.success or not np.isfinite(fitted.x).all(): raise RuntimeError('Count optimizer failed '+str(fitted.message))
    return dict(status='ok',optimizer_ok=True,features=['n_plus','n_minus','w','d','m'],mean=mean.tolist(),std=std.tolist(),scale=scale.tolist(),constant=constant.tolist(),coef=fitted.x[1:].tolist(),intercept=float(fitted.x[0]),n_samples=len(y),class_weight=[float(w[y==v].sum()) for v in (0,1)],optimizer=dict(success=True,nit=int(fitted.nit),loss=float(fitted.fun),message=str(fitted.message)))


def fit_controls(rows,zero_fitted,families):
    selected=legacy.supervision(rows,families);models={};states={}
    def attempt(name,operation):
        try:
            model=operation();models[name]=model;states[name]=dict(status='ok',reason=None,optimizer_ok=model.get('optimizer_ok'))
        except (ValueError,RuntimeError,FloatingPointError,OverflowError) as exc:
            models[name]=None;states[name]=dict(status='unestimable',reason=str(exc))
    def base(name):
        if name=='Count': X=np.asarray([count_inputs(r) for r in selected],float)
        else:
            if not selected: raise ValueError('G supervision is empty')
            if any(not r['finite'] or r['features'].get('G') is None for r in selected): raise ValueError('G supervision unavailable; cannot drop records')
            X=np.asarray([r['features']['G'] for r in selected],float);X[:,4]=0.
        w=legacy.training_weights(selected);y=[r['query_truth'] for r in selected]
        result=fit_count(X,y,w) if name=='Count' else heads.fit_base(X,y,w)
        result.update(train_parents=sorted({r['parent'] for r in selected}),fit_false=list(families),false_cells=sorted({r['family']+'/'+str(r['attack_k']) for r in selected if original.primary(r,0)}))
        if name=='G_zero':
            if result['coef'][4]!=0.: raise ValueError('G d coefficient not fixed')
            result['structurally_fixed']=['d']
        return result
    attempt('Count',lambda:base('Count'));attempt('G_zero',lambda:base('G_zero'))
    def increment(name):
        count=name=='CountQ';model=models['Count'] if count else zero_fitted['models'].get('I_zero')
        if model is None: raise ValueError('fixed base unavailable')
        offset=[]
        for r in selected:
            if not r['finite']: raise ValueError('nonfinite increment supervision')
            x=count_inputs(r) if count else r['features'].get('I_Jmargin')
            if x is None: raise ValueError('fixed base feature missing')
            offset.append(heads.base_score(model,x))
        return heads.fit_increment(np.square(offset),[r['query_truth'] for r in selected],legacy.training_weights(selected),offset,[r['parent'] for r in selected],joint=False)
    attempt('CountQ',lambda:increment('CountQ'));attempt('Q_zero',lambda:increment('Q_zero'))
    return dict(models=models,method_status=states,n_supervision=len(selected),fit_false=list(families))


def model_bundle(old_fitted,zero_fitted,controls):
    models={m:copy.deepcopy(old_fitted['models'].get(OLD_ALIASES[m]) if m in OLD_ALIASES else zero_fitted['models'].get(m)) for m in FROZEN}
    states={m:copy.deepcopy(old_fitted['method_status'][OLD_ALIASES[m]] if m in OLD_ALIASES else zero_fitted['method_status'][m]) for m in FROZEN}
    models.update(controls['models']);states.update(controls['method_status'])
    return dict(status='fitted',models={m:models[m] for m in METHODS},method_status={m:states[m] for m in METHODS},old_fitted=old_fitted,zero_fitted=zero_fitted,fit_false=controls['fit_false'])


def score_feature(row,bundle):
    frozen=zero.score_feature(row,bundle['old_fitted'],bundle['zero_fitted'])
    result={k:v for k,v in frozen.items() if k not in ('scores','method_status','contributions')}
    scores={m:frozen['scores'][m] for m in FROZEN};states={m:copy.deepcopy(frozen['method_status'][m]) for m in FROZEN}
    contributions={m:frozen['contributions'][m] for m in FROZEN if m in frozen['contributions']}
    result['Count_inputs']=None
    for m in NEW:
        scores[m]=None;states[m]=copy.deepcopy(bundle['method_status'][m]);model=bundle['models'][m]
        try:
            if model is None: continue
            if not row['finite']: raise ValueError('normal feature failure')
            if m=='Count':
                x=count_inputs(row);result['Count_inputs']=x;scores[m]=heads.base_score(model,x)
            elif m=='G_zero':
                x=row['features'].get('G')
                if x is None: raise ValueError('G feature missing')
                scores[m]=heads.base_score(model,x)
                contributions[m]=heads.decompose(model,row['sources']['G'],row['context'])
            else:
                base=scores['Count' if m=='CountQ' else 'I_zero']
                if base is None: raise ValueError('fixed base unavailable')
                scores[m]=heads.increment_score(model,base,base**2)
                contributions[m]=dict(offset=base,increment=model['coefficient']*base**2,score=scores[m])
        except (ValueError,FloatingPointError,OverflowError) as exc: states[m]=dict(status='numeric_failure',reason=str(exc))
    result.update(scores={m:scores[m] for m in METHODS},method_status={m:states[m] for m in METHODS},contributions=contributions)
    return data.finite_json(result)


def table(rows,method):
    return original.ReportRows.from_rows([dict(r,scores={'D':r['scores'].get(method)},decisions={'D':r.get('decisions',{}).get(method,'unknown')},m=r['d'],supports=r['m'],n_frames=r['w']) for r in rows])


def apply_decisions(rows,policies):
    for row in rows: row['decisions']={m:original.decide(row,m,policies[m]) for m in METHODS}


def six_cells(rows):
    return {m:original.six_cells(table(rows,m),'D') for m in METHODS}


def old_inputs(config):
    source=Path(config['source_original_scores']);manifest=read(config['source_manifest'])
    if manifest['config']['parent_splits']!=config['old_parent_splits']: raise ValueError('old splits changed')
    for stage in ('prepare','features','fit','score','report'):
        if read(source/(stage+'.complete.json'))['status'] not in ('COMPLETE','complete'): raise ValueError('source stage incomplete '+stage)
    folds=read(source/'features.complete.json')['folds'];expected=sorted(p for p,s in config['old_parent_splits'].items() if s=='fit')
    if sorted(f['parent'] for f in folds)!=expected: raise ValueError('six source folds required')
    paths={'fit':[source/f['features'] for f in folds],'cal':[]};statuses=read(source/'prepare.complete.json')['jobs']
    for j in manifest['jobs']:
        if j['split']!='cal': continue
        status=statuses[j['job_id']]['status']
        if status not in ('COMPLETE','UNREALIZABLE'): raise ValueError('old cal task incomplete')
        if status=='COMPLETE' and statuses[j['job_id']].get('rows',0)>0: paths['cal'].append(Path(config['source_features'])/'cal'/(j['job_id']+'.jsonl.gz'))
    for files in paths.values():
        for p in files:
            if not p.is_file(): raise FileNotFoundError(str(p))
    fitrows=[r for p in paths['fit'] for r in data.read_rows(p)];calrows=[r for p in paths['cal'] for r in data.read_rows(p)]
    if {r['parent'] for r in fitrows}!=set(expected) or {r['parent'] for r in calrows}!={p for p,s in config['old_parent_splits'].items() if s=='cal'}: raise ValueError('fit/cal parent coverage incomplete')
    return manifest,fitrows,calrows


def verify_frozen(rows,reference,policies,expected_policies):
    if any(policies[m]!=expected_policies[m] for m in FROZEN): raise ValueError('frozen policies changed')
    expected={tuple(r['key']):r for r in reference}
    if len(expected)!=len(reference) or len({tuple(r['key']) for r in rows})!=len(rows) or set(expected)!={tuple(r['key']) for r in rows}: raise ValueError('old cal key/denominator mismatch')
    for row in rows:
        old=expected[tuple(row['key'])]
        for m in FROZEN:
            if row['scores'][m]!=old['scores'][m] or row['decisions'][m]!=old['decisions'][m]: raise ValueError('old cal score/decision mismatch '+m)
        for k in ('finite','accept_eligible','reject_eligible','w','d','m','query_truth','query_present','newborn'):
            if row[k]!=old[k]: raise ValueError('old cal metadata changed '+k)


def fit(config,out):
    out=Path(out);bind(config,out)
    with legacy.prepare._lock(out/'.fit.lock'):
        marker=out/'fit.complete.json'
        if marker.exists():
            for p in read(marker)['artifacts']:
                if not (out/p).is_file(): raise RuntimeError('fit artifact missing '+p)
            return read(marker)
        manifest,fitrows,calrows=old_inputs(config);artifacts=[]
        source=Path(config['source_original_scores']);zsource=Path(config['source_zero_scores'])
        for regime,spec in config['regimes'].items():
            modelpath=out/'models'/(regime+'.json')
            if modelpath.exists(): bundle=read(modelpath)
            else:
                old=read(source/'models'/(regime+'.json'));zf=read(zsource/'models'/(regime+'.json'))
                bundle=model_bundle(old,zf,fit_controls(fitrows,zf,spec['fit_false']));save(modelpath,bundle)
            families=['F0','F1','F2'] if regime=='mixed' else spec['fit_false']
            rows=[score_feature(r,bundle) for r in legacy._domain(calrows,families)]
            expected={(j['family'],j['attack_k']) for j in manifest['jobs'] if j['split']=='cal' and j['kind']=='attack' and j['family'] in families}
            frozen=read(zsource/'calibration'/(regime+'.json'))['policies']
            policy={m:copy.deepcopy(frozen[m]) for m in FROZEN}
            for m in NEW: policy[m]=original.calibrate(table(rows,m),'D',expected_layers=expected,alpha=config['gates']['false_accept_max'])
            apply_decisions(rows,policy)
            verify_frozen(rows,list(data.read_rows(zsource/'predictions'/regime/'cal.jsonl.gz')),policy,frozen)
            observed={(r['family'],r['attack_k']) for r in rows if original.primary(r,0)}
            calibration=dict(policies={m:policy[m] for m in METHODS},calibration_sufficient=all(any(original.primary(r,t) for r in rows) for t in (0,1)),expected_layers=sorted(expected),observed_layers=sorted(observed),missing_layers=sorted(expected-observed),cal_false=families,cal_parents=sorted({r['parent'] for r in rows}),old_reproduction=dict(status='pass',methods=list(FROZEN)))
            save(out/'calibration'/(regime+'.json'),calibration);rows_once(out/'predictions'/regime/'cal.jsonl.gz',rows)
            artifacts += ['models/'+regime+'.json','calibration/'+regime+'.json','predictions/'+regime+'/cal.jsonl.gz']
        result=dict(status='complete',artifacts=artifacts);save(marker,result);return result


def score_coverage(rows,method):
    primary=[r for r in rows if original.primary(r,0) or original.primary(r,1)]
    def missing(row):
        score=row['scores'].get(method)
        return score is None or not np.isfinite(score)
    return dict(n_total=len(rows),n_finite=sum(not missing(r) for r in rows),
                states=dict(Counter(r['method_status'].get(method,{}).get('status','unavailable') for r in rows)),
                numeric_failures=sum(r['method_status'].get(method,{}).get('status')=='numeric_failure' for r in rows),
                primary=dict(n_total=len(primary),n_missing_score=sum(missing(r) for r in primary),
                    n_failed=sum(not r.get('finite',False) or r['method_status'].get(method,{}).get('status','unavailable') not in ('ok','reference') for r in primary),
                    states=dict(Counter(r['method_status'].get(method,{}).get('status','unavailable') for r in primary))))


def metrics(rows,cal_layers,families):
    tables={m:table(rows,m) for m in METHODS}
    def cells(subset):
        return {m:original.six_cells(tables[m].subset(subset),'D') for m in METHODS}
    windows=np.asarray([r['w'] for r in rows]);parents=np.asarray([r['parent'] for r in rows],dtype=object);family=np.asarray([r['family'] for r in rows],dtype=object);ks=np.asarray([r['attack_k'] for r in rows],dtype=int)
    result=dict(system_query={m:original.six_cells(t,'D') for m,t in tables.items()},coverage=legacy._coverage(rows),
                first_windows={name:cells(mask) for name,mask in [('length_1',windows==1),('length_2_to_9',(windows>=2)&(windows<=9)),('length_10',windows==10)]},
                by_parent={p:cells(parents==p) for p in sorted(set(parents))},family_k={},
                method_score_coverage={m:score_coverage(rows,m) for m in METHODS},
                paired_timeliness={'D_zero':zero._paired(rows,'D_zero','D_old'),'J_zero':zero._paired(rows,'J_zero','I_zero')},
                transitions={'D_zero':zero._transitions(rows,'D_zero','D_old'),'J_zero':zero._transitions(rows,'J_zero','I_zero')})
    for f in families:
        for k in (1,2):
            subset=[r for r in rows if r['family']==f and r['attack_k']==k];primary=[r for r in subset if original.primary(r,0)]
            support=dict(parents=len({r['parent'] for r in primary}),entities=len({(r['job_id'],'target') for r in primary}),query_epochs=len({original.epoch(r) for r in primary}),rows=len(primary))
            result['family_k'][f+'/'+str(k)]=dict(status='observed' if primary else 'not_tested',n_primary_false=len(primary),support=support,cal_status='observed' if (f,k) in cal_layers else 'not_calibrated',metrics=cells((family==f)&(ks==k)))
    return result


def judge(regime,measurement,states,calibration_sufficient,config,tasks_complete):
    gates=config['gates'];main=measurement['system_query'];result={}
    def difference(a,b): return legacy._difference(a,b)
    def rate(m,t,d): return main[m][t]['weighted'][d]
    for label,candidate in [('main','D_zero'),('joint','J_zero')]:
        checks={};coverage=measurement['method_score_coverage'][candidate]
        both=all(main[candidate][t]['n']>0 for t in ('true','false'))
        available=states[candidate]['status'] in ('ok','reference') and coverage['n_finite']>0 and calibration_sufficient and both and tasks_complete
        denominator=dict(true=main[candidate]['true']['n'],false=main[candidate]['false']['n'],true_parents=main[candidate]['true']['parents'],false_parents=main[candidate]['false']['parents'])
        def check(name,value,limit,direction='max',usable=available,denom=denominator):
            checks[name]=dict(legacy._check(value,limit,direction,available=usable),denominator=denom)
        check('estimable',float(available),1.,'min',usable=both and calibration_sufficient and tasks_complete)
        check('numeric_failures',coverage['numeric_failures'],0.,usable=True)
        check('both_classes',float(both),1.,'min',usable=both)
        check('calibration_classes',float(calibration_sufficient),1.,'min',usable=calibration_sufficient)
        check('tasks_complete',float(tasks_complete),1.,'min',usable=tasks_complete)
        check('false_accept',rate(candidate,'false','accept'),gates['false_accept_max'])
        check('true_reject',rate(candidate,'true','reject'),gates['true_reject_max'])
        for cell,layer in measurement['family_k'].items():
            s=layer['support'];covered=s['parents']>=gates['false_cell_min_parents'] and s['entities']>=gates['false_cell_min_entities']
            check(cell+'/coverage',float(covered),1.,'min',usable=covered,denom=s)
            if layer['n_primary_false']:
                check(cell+'/false_accept',layer['metrics'][candidate]['false']['weighted']['accept'],gates['family_k_false_accept_max'],denom=s)
        if label=='main':
            check('TA_drop_vs_D_old',difference(rate('D_old','true','accept'),rate(candidate,'true','accept')),gates['main_true_accept_drop_vs_D_old_max'])
            check('CD_drop_vs_D_old',difference(main['D_old']['correct_definite'],main[candidate]['correct_definite']),gates['main_CD_drop_vs_D_old_max'])
            pair=measurement['paired_timeliness'][candidate]
            check('never_adopted_increase',pair['never_difference'],gates['never_adopted_increase_max'],denom=dict(epochs=pair['n_primary_true_epochs'],parents=pair['n_parents']))
            check('paired_median_delay_increase',pair['weighted_median_delay_difference_seconds'],gates['paired_median_delay_increase_seconds_max'],denom=dict(epochs=pair['shared_ever_epochs']))
        else:
            check('TA_drop_vs_I_zero',difference(rate('I_zero','true','accept'),rate(candidate,'true','accept')),gates['joint_true_accept_drop_vs_I_zero_max'])
        if regime=='mixed': check('TA_gap_to_MATE',difference(rate('MATE_policy','true','accept'),rate(candidate,'true','accept')),gates['mixed_true_accept_gap_to_MATE_max'])
        required=[candidate,'D_old'] if label=='main' else [candidate,'I_zero','G_zero','Q_zero']
        if regime=='mixed':
            required.append('MATE_policy')
            if label=='main': required.extend(('Count','CountQ'))
        for method in required:
            primary=measurement['method_score_coverage'][method]['primary']
            complete_classes=both and calibration_sufficient and tasks_complete
            check('primary_missing_score/'+method,primary['n_missing_score'],0.,usable=complete_classes,denom=primary)
            check('primary_failed/'+method,primary['n_failed'],0.,usable=complete_classes,denom=primary)
            check('required_model/'+method,float(states[method]['status'] in ('ok','reference')),1.,'min',usable=complete_classes,denom=primary)
        utility=copy.deepcopy(checks)
        baselines=('Count','CountQ') if label=='main' else ('I_zero','G_zero','Q_zero')
        if label=='joint' or regime=='mixed':
            for baseline in baselines:
                bcoverage=measurement['method_score_coverage'][baseline]
                usable=available and states[baseline]['status'] in ('ok','reference') and bcoverage['n_finite']>0 and not bcoverage['numeric_failures']
                check('CD_gain_over_'+baseline,difference(main[candidate]['correct_definite'],main[baseline]['correct_definite']),gates['mixed_condition_CD_gain_over_each_Count_Control_min'] if label=='main' else gates['joint_CD_gain_over_each_I_G_Q_zero_min'],'min',usable)
        result[label]=dict(status=legacy._verdict(checks),candidate=candidate,checks=checks,risk_utility_status=legacy._verdict(utility),
                           interpretation='frozen development gate; no significance or deployment guarantee')
    return result


def evaluation_tasks(config,out):
    marker=out/'prepare.complete.json'
    if not marker.is_file(): raise RuntimeError('prepare incomplete')
    manifest=read(out/'manifest.json');completed=read(marker)
    if manifest['jobs']!=config['jobs'] or set(completed['jobs'])!={j['job_id'] for j in config['jobs']}: raise ValueError('new task inventory changed')
    for j in manifest['jobs']:
        dest=out/'jobs'/j['job_id'];status=read(dest/'complete.json')
        if status!=completed['jobs'][j['job_id']] or status['status'] not in ('COMPLETE','UNREALIZABLE'): raise RuntimeError('new task incomplete')
        if status['status']=='COMPLETE' and any(not (dest/name).is_file() for name in ('rows.jsonl.gz','entity_coverage.jsonl.gz','online.jsonl.gz','attack.json')): raise RuntimeError('new task artifact missing')
    return manifest,completed


def feature_worker(args):
    path,rows,models,rho=args
    legacy._feature_job((path,rows,models,rho))


def generate_features(config,out,manifest,completed,workers):
    normal=read(config['source_normal_models']);tasks=[]
    for job in manifest['jobs']:
        if completed['jobs'][job['job_id']]['status']!='COMPLETE': continue
        path=out/'features/eval'/(job['job_id']+'.jsonl.gz')
        if path.exists(): continue
        rows=list(data.read_rows(out/'jobs'/job['job_id']/'rows.jsonl.gz'))
        if len(rows)!=completed['jobs'][job['job_id']]['rows']: raise ValueError('prepared row count mismatch')
        for row in rows:
            if any(row[k]!=job[k] for k in ('job_id','parent','split','kind','family','attack_k')): raise ValueError('new row/task mismatch')
        tasks.append((str(path),rows,normal['models'],normal['rho']))
    if workers==1:
        for task in tasks: feature_worker(task)
    elif tasks:
        with ProcessPoolExecutor(max_workers=workers) as pool: list(pool.map(feature_worker,tasks))


def construction_coverage(manifest,completed,rows):
    entities={}
    for job in manifest['jobs']:
        if job['kind']!='attack': continue
        status=completed['jobs'][job['job_id']]
        primary=[r for r in rows if r['job_id']==job['job_id'] and original.primary(r,0)]
        entities[job['job_id']+'/target']=dict(parent=job['parent'],family=job['family'],attack_k=job['attack_k'],status=status['status'],constructed=status['status']=='COMPLETE',definite_false_query=bool(primary),query_epochs=len({original.epoch(r) for r in primary}),rows=len(primary),no_definite_query=status['status']=='COMPLETE' and not primary,completion=status)
    return dict(entities=entities,attempts=len(entities),constructed=sum(e['constructed'] for e in entities.values()),definite_false_entities=sum(e['definite_false_query'] for e in entities.values()),constructed_without_definite_query=sum(e['no_definite_query'] for e in entities.values()),unrealizable=sum(e['status']=='UNREALIZABLE' for e in entities.values()))


def summary(metrics):
    lines=['# 冻结扩大开发评价','','六父30任务为已处理资料上的扩大开发评价，不是盲终测。旧k3失败与原迁移失败仍保留。','run.complete仅表示任务执行结束。缺校准层不提供风险保证，覆盖不足与失败均不能写为通过。','']
    def values_table(cells):
        output=['| 方法 | 真采纳 | 真未知 | 真拒绝 | 假采纳 | 假未知 | 假拒绝 | CD |','|---|---:|---:|---:|---:|---:|---:|---:|']
        for m,c in cells.items():
            values=[c[t]['weighted'][d] for t in ('true','false') for d in original.DECISIONS]+[c['correct_definite']]
            output.append('| '+m+' | '+' | '.join('NA' if v is None else '%.5f'%v for v in values)+' |')
        return output+['']
    for regime,report in metrics['regimes'].items():
        evaluation=report['metrics']['eval'];lines+=['## '+regime,'','新增评价总体','']+values_table(evaluation['system_query'])
        lines+=['首窗 w=1，必须与总体一起解释','']+values_table(evaluation['first_windows']['length_1'])
        lines+=['旧开发评价，独立列示，不合并平均','']+values_table(report['old_development_system_query'])
        lines+=['| 父录制 | D_zero真采纳 | D_zero CD | 相对D_old真采纳差 | 相对D_old CD差 |','|---|---:|---:|---:|---:|']
        def number(v): return 'NA' if v is None else '%.5f'%v
        for parent,cells in evaluation['by_parent'].items():
            d=cells['D_zero'];old=cells['D_old'];ta=d['true']['weighted']['accept'];cd=d['correct_definite']
            lines+=['| '+parent+' | '+' | '.join(map(number,[ta,cd,legacy._difference(ta,old['true']['weighted']['accept']),legacy._difference(cd,old['correct_definite'])]))+' |']
        lines+=['','主候选 '+report['retention']['main']['status'],'联合增量 '+report['retention']['joint']['status'],
                'cal缺层 '+str(report['calibration']['missing_layers']),
                '短窗、满窗、各父九方法六格、真假原始分母、来源支持和逐项裁决见对应report JSON。','']
    return '\n'.join(lines)+'\n'


def evaluate(config,out,workers=4):
    out=Path(out);bind(config,out)
    if not 1<=workers<=6: raise ValueError('workers must be 1..6')
    with legacy.prepare._lock(out/'.evaluate.lock'):
        if not (out/'fit.complete.json').is_file(): raise RuntimeError('fit incomplete')
        for p in read(out/'fit.complete.json')['artifacts']:
            if not (out/p).is_file(): raise RuntimeError('fit artifact missing '+p)
        manifest,completed=evaluation_tasks(config,out)
        marker=out/'run.complete.json'
        if marker.exists():
            for p in read(marker)['artifacts']:
                if not (out/p).is_file(): raise RuntimeError('completed artifact missing '+p)
            return read(marker)
        # All three models and policies are saved before any new score is generated.
        bundles={r:read(out/'models'/(r+'.json')) for r in config['regimes']}
        calibrations={r:read(out/'calibration'/(r+'.json')) for r in config['regimes']}
        generate_features(config,out,manifest,completed,workers)
        features=[r for j in manifest['jobs'] if completed['jobs'][j['job_id']]['status']=='COMPLETE' for r in data.read_rows(out/'features/eval'/(j['job_id']+'.jsonl.gz'))]
        reports={};artifacts=['binding.json','manifest.json','prepare.complete.json','fit.complete.json']+read(out/'fit.complete.json')['artifacts']
        for regime,spec in config['regimes'].items():
            path=out/'report'/(regime+'.json');prediction=out/'predictions'/regime/'eval.jsonl.gz'
            if path.exists() and prediction.exists(): reports[regime]=read(path)
            else:
                bundle=bundles[regime];cal=calibrations[regime]
                rows=[score_feature(r,bundle) for r in legacy._domain(features,spec['eval_false'])]
                apply_decisions(rows,cal['policies']);rows_once(prediction,rows)
                observed={tuple(x) for x in cal['observed_layers']};measurement=metrics(rows,observed,spec['eval_false'])
                # Evaluate the preserved old cal predictions without refitting or selecting thresholds.
                old_cal=list(data.read_rows(out/'predictions'/regime/'cal.jsonl.gz'))
                old_report=read(Path(config['source_zero_scores'])/'report'/(regime+'.json'))
                report=dict(status='evaluated' if cal['calibration_sufficient'] else 'insufficient_calibration',method_status=bundle['method_status'],calibration_sufficient=cal['calibration_sufficient'],calibration=cal,policies=cal['policies'],fit_false=spec['fit_false'],eval_false=spec['eval_false'],
                            metrics=dict(eval=measurement,cal=metrics(old_cal,observed,cal['cal_false'])),retention=judge(regime,measurement,bundle['method_status'],cal['calibration_sufficient'],config,True),
                            old_development_system_query={m:old_report['metrics']['eval']['system_query'][m] for m in FROZEN})
                save(path,report);reports[regime]=report
            artifacts += [str(path.relative_to(out)),str(prediction.relative_to(out))]
        result=dict(status='complete',scope=config['scope'],primary='D_zero',regimes=reports,construction_coverage=construction_coverage(manifest,completed,features),task_statuses=completed['jobs'],old_k3_and_transfer_failures_retained=True)
        save(out/'report/metrics.json',result)
        legacy._text_once(out/'report/summary.md',summary(result))
        artifacts += ['report/metrics.json','report/summary.md']
        save(out/'evaluate.complete.json',dict(status='complete',artifacts=artifacts))
        complete=dict(status='complete',meaning='execution_complete_not_scientific_pass',artifacts=artifacts+['evaluate.complete.json'],retention={r:{k:v['status'] for k,v in report['retention'].items()} for r,report in reports.items()})
        save(marker,complete);return complete


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',required=True,choices=('prepare','fit','evaluate','all'))
    parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--out',type=Path)
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args(argv)
    if not 1<=args.workers<=6: parser.error('workers must be 1..6')
    config=read_config(args.config);out=(args.out or Path(config['new_output'])).resolve()
    try:
        if args.stage=='prepare':
            from .prepare import prepare
            prepare(config,out,args.workers)
        elif args.stage=='fit': fit(config,out)
        elif args.stage=='evaluate': evaluate(config,out,args.workers)
        else:
            subprocess.run([str(data.RUNTIME),'-m','scripts.rq1_report_freeze.run','--stage','prepare','--config',str(args.config.resolve()),'--out',str(out),'--workers',str(args.workers)],cwd=str(REPO),env=os.environ.copy(),check=True)
            fit(config,out);evaluate(config,out,args.workers)
    except Exception as exc:
        path=out/(args.stage+'.error.json')
        if not path.exists(): data.atomic_json(path,dict(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc()))
        raise


if __name__=='__main__': main()
