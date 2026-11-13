"""Resumable frozen features/fit/score/report; legacy artifacts stay read-only."""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='1'

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import itertools
import json
from pathlib import Path
import traceback
import numpy as np
from scripts.rq1_temporal import data, fit as fitting, kernel, run as original
from . import heads, prepare

METHODS=heads.METHODS
# Local adapters use the old table's fixed-width columns, never its globals.
ALIASES=dict(D_head='D',T_head='T',I_Jmargin='Jind',J='J',G='G',Q='C',MATE_policy='MATE_policy')
METADATA=('key','job_id','id','epoch','parent','split','kind','family','attack_k','attack_role',
          'origin','index','frame','timestamp','query_truth','query_gt_id','output_truth',
          'query_present','newborn','output_present','identity_ok','native_mean','native_adopted','source_ids')


def _read(path):
    return json.loads(Path(path).read_text())


def _context(out):
    out=Path(out)
    if not (out/'prepare.complete.json').exists():
        raise RuntimeError('prepare is incomplete')
    manifest=_read(out/'manifest.json');config=manifest['config'];support=_read(out/'support.json')
    source_root=Path(config['source_manifest']['path']).parent.resolve();dest=out.resolve()
    if dest==source_root or source_root in dest.parents or dest in source_root.parents:
        raise ValueError('output must be isolated from the read-only source run')
    return manifest,config,support


def _provenance(out,config):
    paths=dict(run=__file__,heads=heads.__file__,prepare=prepare.__file__,
               temporal_fit=fitting.__file__,temporal_kernel=kernel.__file__,
               temporal_run=original.__file__,temporal_data=data.__file__)
    try:
        sources={name:data.source_record(path) for name,path in paths.items()}
    except OSError as error:
        raise ValueError('pipeline dependency source unavailable: '+str(error)) from error
    frozen={Path(r['path']).name:r['sha256'] for r in config['frozen_normal_code']}
    for name,filename in [('temporal_fit','fit.py'),('temporal_kernel','kernel.py')]:
        if sources[name]['sha256']!=frozen.get(filename):
            raise ValueError('frozen imported normal code changed: '+sources[name]['path'])
    record=dict(config=config,code=list(sources.values()))
    path=Path(out)/'pipeline.json'
    if path.exists():
        if _read(path)!=record:
            raise ValueError('pipeline code/config changed; use a new output directory')
    else:
        data.atomic_json(path,record)
    return record


def _finish(out,stage,support,**details):
    result=dict(status='complete' if support['any_regime_supported'] else 'not_tested_data_support',
                supported_regimes=[r for r,s in support['regimes'].items() if s['data_support_met']],**details)
    data.atomic_json(Path(out)/(stage+'.complete.json'),result)
    return result


def _require(out,stage):
    if not (Path(out)/(stage+'.complete.json')).exists():
        raise RuntimeError(stage+' is incomplete')


def _feature_rows(rows,models,rho):
    for window in kernel.windows(rows,10):
        result={k:window[-1].get(k) for k in METADATA}
        result.update(heads.window_features(window,models,rho))
        yield result


def _fold_name(parent):
    return hashlib.sha256(parent.encode()).hexdigest()[:16]


def _fold(arguments):
    out,parent,clean,held=arguments;out=Path(out)
    name=_fold_name(parent);dest=out/'folds'/name;marker=dest/'complete.json'
    if marker.exists():
        return _read(marker)
    train=[r for r in clean if r['parent']!=parent]
    model_path=dest/'normal.json'
    if model_path.exists():
        fitted=_read(model_path)
    else:
        normal=fitting.fit_models(train);rho_fit=fitting.fit_rho_oof(train,W=10)
        fitted=dict(models=normal,rho=rho_fit['rho'],rho_fit=rho_fit,
                    held_parent=parent,train_parents=sorted({r['parent'] for r in train}))
        data.atomic_json(model_path,fitted)
    if parent in fitted['train_parents']:
        raise ValueError('outer held parent leaked into normal model')
    path=out/'features/fit'/(name+'.jsonl.gz')
    if not path.exists():
        with data.atomic_rows(path) as write:
            for row in _feature_rows(held,fitted['models'],fitted['rho']):
                write(row)
    result=dict(parent=parent,train_parents=fitted['train_parents'],
                normal=str(model_path.relative_to(out)),features=str(path.relative_to(out)))
    data.atomic_json(marker,result)
    return result


def _feature_job(arguments):
    path,rows,models,rho=arguments;path=Path(path)
    if not path.exists():
        with data.atomic_rows(path) as write:
            for row in _feature_rows(rows,models,rho):
                write(row)


def _cal_eval_features(out,fitted,workers):
    tasks=[]
    # Group once in the parent; each worker receives just one complete job.
    for split in ('cal','eval'):
        for jid,group in itertools.groupby(prepare.iter_rows(out,split),key=lambda r:r['job_id']):
            path=Path(out)/'features'/split/(jid+'.jsonl.gz')
            if not path.exists():
                tasks.append((str(path),list(group),fitted['models'],fitted['rho']))
    if workers==1:
        for task in tasks:
            _feature_job(task)
    elif tasks:
        with ProcessPoolExecutor(max_workers=min(workers,len(tasks))) as pool:
            list(pool.map(_feature_job,tasks))


def features(out,workers=1):
    out=Path(out)
    if not 1<=workers<=8:
        raise ValueError('workers must be between 1 and 8')
    with prepare._lock(out/'.features.lock'):
        manifest,config,support=_context(out);_provenance(out,config)
        if (out/'features.complete.json').exists():
            return _read(out/'features.complete.json')
        if not support['any_regime_supported']:
            return _finish(out,'features',support,folds=[],reason='all regimes fail the frozen support gate; no OOF performed')
        planned={j['job_id'] for j in config['planned_fit_attacks']}
        fit_rows=[r for r in prepare.iter_rows(out,'fit') if r['kind']=='clean' or r['job_id'] in planned]
        clean=[r for r in fit_rows if r['kind']=='clean']
        parents=sorted(p for p,s in config['parent_splits'].items() if s=='fit')
        if {r['parent'] for r in clean}!=set(parents):
            raise ValueError('missing clean fit parent')
        tasks=[(str(out),p,clean,[r for r in fit_rows if r['parent']==p]) for p in parents]
        if workers==1:
            folds=[_fold(task) for task in tasks]
        else:
            with ProcessPoolExecutor(max_workers=min(workers,len(tasks))) as pool:
                folds=list(pool.map(_fold,tasks))
        if data.source_record(config['source_models']['path'])['sha256']!=config['source_models']['sha256']:
            raise ValueError('frozen full-fit normal model changed')
        fitted=_read(config['source_models']['path'])
        _cal_eval_features(out,fitted,workers)
        return _finish(out,'features',support,folds=folds,normal_model_source=config['source_models'])


def supervision(rows,families):
    """Select source-family supervision before estimating scalers or weights."""
    return [r for r in rows if original.primary(r,1) or
            (original.primary(r,0) and r['family'] in families and r.get('origin')=='score_revision')]


def training_weights(rows):
    result=np.zeros(len(rows))
    for truth in (0,1):
        ix=[i for i,r in enumerate(rows) if r['query_truth']==truth]
        if not ix:
            raise ValueError('both supervision classes required')
        result[ix]=.5*original.weights([rows[i] for i in ix],truth)
        if abs(result[ix].sum()-.5)>1e-12:
            raise ValueError('class weight must sum to .5')
    return result


def fit_regime(rows,families):
    rows=supervision(rows,families);models={};statuses={};usable={}
    for method in heads.BASE_METHODS:
        selected=[r for r in rows if r['finite'] and r['features'].get(method) is not None]
        expected_parents=sorted({r['parent'] for r in rows});actual_parents=sorted({r['parent'] for r in selected})
        by_parent={}
        for parent in expected_parents:
            group=[r for r in rows if r['parent']==parent]
            by_parent[parent]=dict(n_supervision=len(group),n_usable=sum(r['finite'] and r['features'].get(method) is not None for r in group),
                normal_states=dict(Counter(r.get('method_status',{}).get(method,{}).get('status','not_recorded') for r in group)))
        missing=sorted(set(expected_parents)-set(actual_parents))
        unavailable=[r for r in rows if r.get('method_status',{}).get(method,{}).get('status')=='unestimable']
        coverage=dict(n_supervision=len(rows),n_usable=len(selected),n_excluded=len(rows)-len(selected),
                      expected_parents=expected_parents,usable_parents=actual_parents,missing_usable_parents=missing,by_parent=by_parent)
        try:
            if missing or unavailable:
                raise ValueError('normal OOF coverage incomplete; missing usable parents '+str(missing)+
                    '; component-unavailable parents '+str(sorted({r['parent'] for r in unavailable})))
            w=training_weights(selected)
            model=heads.fit_base([r['features'][method] for r in selected],[r['query_truth'] for r in selected],w)
            model.update(train_parents=sorted({r['parent'] for r in selected}),
                         false_cells=sorted({r['family']+'/'+str(r['attack_k']) for r in selected if r['query_truth']==0}),
                         fit_false=list(families))
            models[method]=model;usable[method]=selected
            statuses[method]=dict(status='ok',optimizer_ok=True,reason=None,coverage=coverage)
        except (ValueError,RuntimeError,FloatingPointError,OverflowError) as error:
            models[method]=None;statuses[method]=dict(status='unestimable',optimizer_ok=False if isinstance(error,RuntimeError) else None,reason=str(error),coverage=coverage)
    for method in ('J','Q'):
        base=models.get('I_Jmargin')
        if base is None:
            models[method]=None;statuses[method]=dict(status='unestimable',optimizer_ok=None,reason='I_Jmargin unavailable')
            continue
        selected=usable['I_Jmargin']
        if method=='J':
            selected=[r for r in selected if r.get('delta_T') is not None]
        try:
            w=training_weights(selected);offset=np.asarray([heads.base_score(base,r['features']['I_Jmargin']) for r in selected])
            x=np.asarray([r['delta_T'] for r in selected]) if method=='J' else offset**2
            model=heads.fit_increment(x,[r['query_truth'] for r in selected],w,offset,[r['parent'] for r in selected],joint=method=='J')
            models[method]=model;statuses[method]=dict(status='ok',optimizer_ok=model['optimizer_ok'],reason=None,
                increment_status=model['status'],delta_informative=model['delta_informative'],n_usable=len(selected))
        except (ValueError,RuntimeError,FloatingPointError,OverflowError) as error:
            models[method]=None;statuses[method]=dict(status='unestimable',optimizer_ok=False if isinstance(error,RuntimeError) else None,reason=str(error))
    statuses['MATE_policy']=dict(status='reference',reason='native mean minus .5; same regime calibration')
    return dict(models=models,method_status=statuses,fit_false=list(families),n_supervision=len(rows))


def resample_parents(rows,draw):
    result=[]
    byparent=defaultdict(list)
    for row in rows:
        byparent[row['parent']].append(row)
    for i,parent in enumerate(draw):
        for row in byparent[parent]:
            result.append(dict(row,original_parent=parent,parent='draw_'+str(i),draw_cluster_id=i))
    return result


def bootstrap_precheck(rows,config):
    spec=config['coefficient_interval'];n=spec['draw_n_parents'];cells=defaultdict(set)
    for r in rows:
        if original.primary(r,0):
            cells[r['family']+'/'+str(r['attack_k'])].add(r['parent'])
    result={key:dict(n_parents=len(parents),parent_ids=sorted(parents),
                   missing_probability_lower_bound=(1-len(parents)/n)**n) for key,parents in sorted(cells.items())}
    unsupported=[key for key,c in result.items() if c['missing_probability_lower_bound']>spec['coverage_precheck']['skip_bootstrap_if_any_bound_exceeds']]
    return dict(status='interval_support_insufficient' if unsupported or not cells else 'ok',
                cells=result,unsupported_cells=unsupported,draw_n_parents=n,
                reason='original cell parent coverage precheck' if unsupported else 'no false cells' if not cells else None)


def coefficient_interval(rows,config,fitted):
    rows=[r for r in supervision(rows,config['regimes']['mixed']['fit_false'])
          if r['finite'] and r['features'].get('I_Jmargin') is not None and r.get('delta_T') is not None]
    precheck=bootstrap_precheck(rows,config);spec=config['coefficient_interval']
    result=dict(precheck=precheck,requested_repetitions=spec['repetitions'],seed=spec['seed'],
                interpretation=spec['interpretation'],interval=None,interval_excludes_zero=None)
    if precheck['status']!='ok':
        return dict(result,status=precheck['status'],performed_repetitions=0)
    model=fitted['models'].get('J')
    if model is None or not model['delta_informative']:
        return dict(result,status='joint_unestimable_or_uninformative',performed_repetitions=0)
    parents=sorted(p for p,s in config['parent_splits'].items() if s=='fit')
    if len(parents)!=spec['draw_n_parents']:
        raise ValueError('coefficient bootstrap requires the frozen six fit parents')
    rng=np.random.RandomState(spec['seed']);values=[];failures=Counter();draws=[]
    original_cells=set(precheck['cells'])
    for b in range(spec['repetitions']):
        draw=[parents[i] for i in rng.randint(len(parents),size=spec['draw_n_parents'])]
        sampled=resample_parents(rows,draw);reason=None;c=None
        cells={r['family']+'/'+str(r['attack_k']) for r in sampled if original.primary(r,0)}
        if cells!=original_cells:
            reason='original_cell_absent'
        elif {r['query_truth'] for r in sampled}!={0,1}:
            reason='class_absent'
        else:
            try:
                w=training_weights(sampled);y=[r['query_truth'] for r in sampled]
                base=heads.fit_base([r['features']['I_Jmargin'] for r in sampled],y,w)
                offset=[heads.base_score(base,r['features']['I_Jmargin']) for r in sampled]
                joint=heads.fit_increment([r['delta_T'] for r in sampled],y,w,offset,[r['parent'] for r in sampled],joint=True)
                if not joint['delta_informative']:
                    reason='delta_uninformative'
                else:
                    c=joint['coefficient'];values.append(c)
            except (ValueError,RuntimeError,FloatingPointError,OverflowError):
                reason='optimizer_or_base_failure'
        if reason:
            failures[reason]+=1
        draws.append(dict(repetition=b,parents=draw,coefficient=c,invalid_reason=reason))
    invalid=sum(failures.values());valid=invalid/spec['repetitions']<=spec['max_invalid_fraction'] and bool(values)
    interval=np.quantile(values,spec['quantiles']).tolist() if valid else None
    return dict(result,status='ok' if valid else 'invalid_fraction_exceeded',performed_repetitions=spec['repetitions'],
                n_valid=len(values),n_invalid=invalid,invalid_fraction=invalid/spec['repetitions'],failures=dict(failures),
                interval=interval,interval_excludes_zero=bool(interval[0]>0 or interval[1]<0) if interval else None,draws=draws)


def _all_features(out,split):
    for path in sorted((Path(out)/'features'/split).glob('*.jsonl.gz')):
        yield from data.read_rows(path)


def fit(out,workers=1):
    out=Path(out)
    with prepare._lock(out/'.fit.lock'):
        _,config,support=_context(out);_provenance(out,config);_require(out,'features')
        if (out/'fit.complete.json').exists():
            return _read(out/'fit.complete.json')
        if not support['any_regime_supported']:
            return _finish(out,'fit',support,reason='no supported regime; heads and bootstrap not run')
        rows=list(_all_features(out,'fit'));states={}
        for regime,spec in config['regimes'].items():
            dest=out/'models'/(regime+'.json')
            if dest.exists():
                states[regime]=_read(dest)['status'];continue
            if not support['regimes'][regime]['data_support_met']:
                fitted=dict(status='not_tested_data_support',data_support_met=False,models={m:None for m in METHODS},
                            method_status={m:dict(status='not_tested',reason='data support gate') for m in METHODS})
            else:
                fitted=fit_regime(rows,spec['fit_false']);fitted.update(status='fitted',data_support_met=True)
                if regime=='mixed':
                    fitted['coefficient_interval']=coefficient_interval(rows,config,fitted)
            data.atomic_json(dest,fitted);states[regime]=fitted['status']
        return _finish(out,'fit',support,regimes=states)


def score_row(row,fitted):
    result={k:v for k,v in row.items() if k not in ('sources','features','method_status')}
    scores={m:None for m in METHODS};status={m:dict(v) for m,v in fitted['method_status'].items()};contributions={}
    numeric_error=None
    try:
        for method in heads.BASE_METHODS:
            model=fitted['models'].get(method);x=row['features'].get(method)
            if not row['finite'] or model is None or x is None:
                continue
            scores[method]=heads.base_score(model,x)
            contributions[method]=heads.decompose(model,row['sources'][method],row['context'])
        for method in ('J','Q'):
            model=fitted['models'].get(method);base=scores['I_Jmargin']
            x=row.get('delta_T') if method=='J' else None if base is None else base**2
            if model is not None and base is not None and x is not None:
                scores[method]=heads.increment_score(model,base,x)
                contributions[method]=dict(contributions['I_Jmargin'],increment=float(model['coefficient']*x),score=scores[method])
        mean=row.get('native_mean')
        if row['finite'] and mean is not None and np.isfinite(mean):
            scores['MATE_policy']=float(mean-.5)
        if not np.isfinite([v for v in scores.values() if v is not None]).all():
            raise ValueError('nonfinite score')
    except (ValueError,FloatingPointError,OverflowError) as error:
        numeric_error=str(error);scores={m:None for m in METHODS};contributions={}
        result.update(finite=False,accept_eligible=False,reject_eligible=False,error=numeric_error)
    for method in METHODS:
        if scores[method] is None and status.get(method,{}).get('status') in ('ok','reference'):
            base='I_Jmargin' if method in ('J','Q') else method
            reason=numeric_error or row.get('error') or row.get('method_status',{}).get(base,{}).get('reason') or 'score unavailable on this record'
            status[method]=dict(status='numeric_failure' if not result['finite'] else 'unavailable',reason=reason)
    result.update(scores=scores,method_status=status,contributions=contributions,
                  w=row['context'][0],d=row['context'][1],m=row['context'][2])
    return data.finite_json(result)


def score(out,workers=1):
    out=Path(out)
    with prepare._lock(out/'.score.lock'):
        manifest,config,support=_context(out);_provenance(out,config);_require(out,'fit')
        if (out/'score.complete.json').exists():
            return _read(out/'score.complete.json')
        if not support['any_regime_supported']:
            return _finish(out,'score',support,reason='no supported regime; scoring not run')
        jobs={j['job_id']:j for j in manifest['jobs']}
        for regime in config['regimes']:
            if not support['regimes'][regime]['data_support_met']:
                continue
            fitted=_read(out/'models'/(regime+'.json'))
            for split in ('cal','eval'):
                for path in sorted((out/'features'/split).glob('*.jsonl.gz')):
                    job=jobs[path.name[:-len('.jsonl.gz')]]
                    if job['kind']!='clean' and job['family'] not in config['regimes'][regime][split+'_false']:
                        continue
                    dest=out/'scores'/regime/split/path.name
                    if dest.exists():
                        continue
                    with data.atomic_rows(dest) as write:
                        for row in data.read_rows(path):
                            write(score_row(row,fitted))
        return _finish(out,'score',support)


def _alias_rows(rows):
    adapted=[]
    for row in rows:
        adapted.append(dict(row,scores={ALIASES[m]:v for m,v in row.get('scores',{}).items()},
                            decisions={ALIASES[m]:v for m,v in row.get('decisions',{}).items()},
                            m=row.get('d',0),supports=row.get('m',0),n_frames=row.get('w',0)))
    return original.ReportRows.from_rows(adapted)


def calibrate(rows,expected_layers):
    adapted=_alias_rows(rows)
    return {m:original.calibrate(adapted,ALIASES[m],expected_layers=expected_layers,alpha=.05) for m in METHODS}


def six_cells(rows):
    metrics=original.six_cells_many(_alias_rows(rows),methods=tuple(ALIASES.values()))
    return {m:metrics[ALIASES[m]] for m in METHODS}


def paired_timeliness(rows):
    groups=defaultdict(list)
    for row in rows:
        if original.primary(row,1):
            groups[(row['parent'],)+original.epoch(row)].append(row)
    epochs=[];parents=Counter()
    for key,group in sorted(groups.items()):
        parent=key[0];parents[parent]+=1;origin=min(r['timestamp'] for r in group)
        first={m:min((r['timestamp'] for r in group if r['decisions'].get(m)=='accept'),default=None) for m in ('J','MATE_policy')}
        epochs.append(dict(parent=parent,epoch=list(key[1:]),origin=origin,first_accept=first))
    never={m:sum(1/(len(parents)*parents[e['parent']]) for e in epochs if e['first_accept'][m] is None) if parents else None for m in ('J','MATE_policy')}
    shared=[e for e in epochs if all(e['first_accept'][m] is not None for m in ('J','MATE_policy'))]
    shared_parents=Counter(e['parent'] for e in shared);values=[]
    for e in shared:
        # Same origin cancels; first adoption is restricted to primary-true rows.
        diff=e['first_accept']['J']-e['first_accept']['MATE_policy'];weight=1/(len(shared_parents)*shared_parents[e['parent']])
        e['delay_difference_seconds']=diff;e['paired_weight']=weight;values.append((diff,weight))
    median=None;mass=0.
    for value,weight in sorted(values):
        mass+=weight
        if mass>=.5:
            median=float(value);break
    return dict(status='ok' if shared else 'not_tested_no_common_ever_adopted_epoch',n_primary_true_epochs=len(epochs),
                n_parents=len(parents),J_never=never['J'],MATE_policy_never=never['MATE_policy'],
                never_difference=None if not epochs else never['J']-never['MATE_policy'],shared_ever_epochs=len(shared),
                weighted_median_delay_difference_seconds=median,epochs=epochs)


def _domain(rows,families):
    return [r for r in rows if r['kind']=='clean' or r['family'] in families]


def transitions(rows,baseline):
    result={}
    for truth in (0,1):
        subset=[r for r in rows if original.primary(r,truth)];w=original.weights(subset,truth)
        cells={a+'/'+b:dict(n=0,weighted=0.) for a in original.DECISIONS for b in original.DECISIONS}
        for r,weight in zip(subset,w):
            key=r['decisions'][baseline]+'/'+r['decisions']['J'];cells[key]['n']+=1;cells[key]['weighted']+=float(weight)
        result[str(truth)]=dict(n=len(subset),from_method=baseline,to_method='J',cells=cells,
            newly_false_accepted_weight=sum(float(weight) for r,weight in zip(subset,w) if not truth and r['decisions']['J']=='accept' and r['decisions'][baseline]!='accept'),
            repaired_false_accept_weight=sum(float(weight) for r,weight in zip(subset,w) if not truth and r['decisions'][baseline]=='accept' and r['decisions']['J']!='accept'))
    return result


def _coverage(rows):
    result=dict(n_rows=len(rows),primary_true=0,primary_false=0,unknown_labels=0,
                attack_true_background=0,auxiliary_occluder=0,no_query=0,newborn=0,numeric_failure=0)
    for r in rows:
        result['primary_true']+=original.primary(r,1);result['primary_false']+=original.primary(r,0)
        result['unknown_labels']+=r.get('query_truth') not in (0,1)
        result['attack_true_background']+=r['kind']=='attack' and r.get('query_truth')==1
        result['auxiliary_occluder']+=r.get('attack_role')=='occluder'
        result['no_query']+=not r.get('query_present');result['newborn']+=bool(r.get('newborn'))
        result['numeric_failure']+=not r.get('finite',True)
    result['parents']=len({r['parent'] for r in rows})
    result['jobs']=len({r['job_id'] for r in rows})
    result['query_epochs']=len({(r['parent'],)+original.epoch(r) for r in rows})
    result['primary_false_injected_entities']=len({r['job_id'] for r in rows if original.primary(r,0)})
    result['primary_true_entities']=len({(r['parent'],r.get('query_gt_id')) for r in rows if original.primary(r,1) and r.get('query_gt_id') is not None})
    return result


def evaluate(rows,cal_layers):
    metrics=dict(system_query=six_cells(rows),coverage=_coverage(rows),family_k={},
                 first_windows={name:six_cells([r for r in rows if condition(r)]) for name,condition in
                                [('length_1',lambda r:r['w']==1),('length_under_10',lambda r:0<r['w']<10),('length_10',lambda r:r['w']==10)]},
                 method_score_coverage={m:dict(n_finite=sum(r['scores'].get(m) is not None for r in rows),n_total=len(rows),
                     states=dict(Counter(r['method_status'].get(m,{}).get('status','unavailable') for r in rows))) for m in METHODS},
                 paired_timeliness=paired_timeliness(rows),
                 transitions={m:transitions(rows,m) for m in ('T_head','MATE_policy')})
    for family in ('F0','F1','F2','F3'):
        for k in (1,2,3):
            subset=[r for r in rows if r['family']==family and r['attack_k']==k]
            primary=[r for r in subset if original.primary(r,0)]
            metrics['family_k'][family+'/'+str(k)]=dict(family=family,k=k,n_primary_false=len(primary),
                status='observed' if primary else 'not_tested',cal_status='observed' if (family,k) in cal_layers else 'not_calibrated',
                metrics=six_cells(subset),coverage=_coverage(subset),
                transitions={m:transitions(subset,m)['0'] for m in ('T_head','MATE_policy')})
    metrics['by_parent']={p:six_cells([r for r in rows if r['parent']==p]) for p in sorted({r['parent'] for r in rows})}
    return metrics


def attack_coverage(out,manifest):
    jobs=[];counts=Counter()
    for job in manifest['jobs']:
        if job['kind']!='attack':
            continue
        status=_read(job.get('status_path',Path(out)/'jobs'/job['job_id']/'complete.json'))
        counts[status['status']]+=1
        jobs.append(dict(job_id=job['job_id'],parent=job['parent'],split=job['split'],family=job['family'],
                         attack_k=job['attack_k'],origin=job['origin'],completion=status))
    return dict(counts=dict(counts),jobs=jobs,F3='construction missing; no effectiveness claim')


def _value(metrics,method,truth,decision):
    return metrics['system_query'][method][truth]['weighted'][decision]


def _difference(a,b):
    return None if a is None or b is None else a-b


def _check(value,limit,direction='max',tol=1e-12,available=True):
    if value is None or not available:
        return dict(status='insufficient',value=value,limit=limit,direction=direction)
    ok=(value<=limit+tol) if direction=='max' else (value>=limit-tol) if direction=='min' else value>limit+tol
    return dict(status='pass' if ok else 'fail',value=value,limit=limit,direction=direction)


def _verdict(checks):
    statuses={v['status'] for v in checks.values()}
    return 'not_retained' if 'fail' in statuses else 'evidence_insufficient' if 'insufficient' in statuses else 'retained'


def scoring_comparisons(metrics):
    main=metrics['system_query'];result={}
    for method in METHODS:
        if method=='MATE_policy':
            continue
        result[method]=dict(CD_minus_MATE=_difference(main[method]['correct_definite'],main['MATE_policy']['correct_definite']),
            TA_minus_MATE=_difference(_value(metrics,method,'true','accept'),_value(metrics,'MATE_policy','true','accept')),
            true_reject_minus_MATE=_difference(_value(metrics,method,'true','reject'),_value(metrics,'MATE_policy','true','reject')),
            false_accept_minus_MATE=_difference(_value(metrics,method,'false','accept'),_value(metrics,'MATE_policy','false','accept')),
            score_available=metrics['method_score_coverage'][method]['n_finite']>0)
    return dict(status='descriptive_development_comparison',comparisons=result,
                interpretation='reports empirical scoring effects separately; does not establish joint or general-authenticity contribution')


def main_retention(metrics,fitted,config):
    spec=config['main_retention'];tol=spec['numeric_tolerance'];checks={};main=metrics['system_query']
    available={m:metrics['method_score_coverage'][m]['n_finite']>0 and
               (m=='MATE_policy' or fitted['method_status'].get(m,{}).get('status')=='ok') for m in METHODS}
    joint=available['J'];interval=fitted.get('coefficient_interval',{})
    interval_available=interval.get('status')=='ok' and interval.get('interval_excludes_zero') is not None
    checks['coefficient_interval_excludes_zero']=_check(float(bool(interval.get('interval_excludes_zero'))),1.,'min',tol,interval_available)
    for baseline in ('I_Jmargin','G','Q','D_head','T_head'):
        limit=spec['CD_gain_min_each_I_G_Q'] if baseline in ('I_Jmargin','G','Q') else spec['CD_gain_min_each_D_T']
        checks['CD_J_minus_'+baseline]=_check(_difference(main['J']['correct_definite'],main[baseline]['correct_definite']),limit,'min',tol,joint and available[baseline])
    checks['TA_MATE_minus_TA_J']=_check(_difference(_value(metrics,'MATE_policy','true','accept'),_value(metrics,'J','true','accept')),spec['TA_MATE_minus_TA_J_max'],tol=tol,available=joint and available['MATE_policy'])
    checks['true_reject_rate']=_check(_value(metrics,'J','true','reject'),spec['true_reject_rate_max'],tol=tol,available=joint)
    checks['false_accept_rate']=_check(_value(metrics,'J','false','accept'),spec['false_accept_rate_max'],tol=tol,available=joint)
    nonempty=[(key,layer) for key,layer in metrics['family_k'].items() if layer['n_primary_false']]
    checks['eval_false_coverage']=_check(len(nonempty),1,'min',available=joint and bool(nonempty))
    for key,layer in nonempty:
        rates={m:layer['metrics'][m]['false']['weighted']['accept'] for m in METHODS}
        checks[key+'_FA_J']=_check(rates['J'],spec['each_nonempty_eval_family_k_false_accept_max'],tol=tol,available=joint)
        for baseline,field in [('T_head','FA_J_minus_FA_T_max_per_cell'),('MATE_policy','FA_J_minus_FA_MATE_max_per_cell')]:
            checks[key+'_FA_J_minus_'+baseline]=_check(_difference(rates['J'],rates[baseline]),spec[field],tol=tol,available=joint and available[baseline])
    time=metrics['paired_timeliness']
    checks['never_adopted_J_minus_MATE']=_check(time['never_difference'],spec['never_adopted_J_minus_MATE_max'],tol=tol,available=joint and available['MATE_policy'])
    checks['paired_first_adoption_delay']=_check(time['weighted_median_delay_difference_seconds'],spec['paired_first_adoption_delay_weighted_median_max_seconds'],tol=tol,available=joint and available['MATE_policy'])
    return dict(status=_verdict(checks),checks=checks,coefficient_interval_status=interval.get('status','unavailable'),method_estimable=available,
                interpretation='development retention only; no unseen-test or deployment risk guarantee')


def transfer_retention(regime,report,mixed,config):
    spec=config['transfer_retention_per_direction'];checks={};metrics=report['metrics']['eval'];main=metrics['system_query']
    reasons=[]
    if not report['calibration_sufficient']:
        reasons.append('source calibration lacks a primary class')
    if not metrics['coverage']['primary_false']:
        reasons.append('target family has no labelled primary false queries')
    status=report['method_status'];joint=status.get('J',{}).get('status')=='ok' and metrics['method_score_coverage']['J']['n_finite']>0
    if not joint:
        reasons.append('joint head unavailable')
    if reasons:
        return dict(status='not_tested',reasons=reasons,checks={})
    checks['false_accept_global']=_check(_value(metrics,'J','false','accept'),spec['false_accept_max_global_and_each_nonempty_k'])
    for key,layer in metrics['family_k'].items():
        if layer['n_primary_false']:
            checks[key+'_false_accept']=_check(layer['metrics']['J']['false']['weighted']['accept'],spec['false_accept_max_global_and_each_nonempty_k'])
    checks['true_reject']=_check(_value(metrics,'J','true','reject'),spec['true_reject_max'])
    checks['CD_J_minus_I']=_check(_difference(main['J']['correct_definite'],main['I_Jmargin']['correct_definite']),spec['CD_J_minus_CD_I_min'],'min',available=status.get('I_Jmargin',{}).get('status')=='ok')
    checks['CD_J_strictly_positive']=_check(main['J']['correct_definite'],0.,'strict_min',tol=0.)
    target=config['regimes'][regime]['eval_false'][0]
    reference=None if mixed is None else mixed.get('target_family_metrics',{}).get(target)
    ref_valid=mixed is not None and mixed.get('method_status',{}).get('J',{}).get('status')=='ok'
    checks['CD_mixed_minus_transfer']=_check(None if reference is None else _difference(reference['J']['correct_definite'],main['J']['correct_definite']),spec['CD_mixed_minus_CD_transfer_max_same_target_family'],available=ref_valid)
    checks['TA_mixed_minus_transfer']=_check(None if reference is None else _difference(reference['J']['true']['weighted']['accept'],main['J']['true']['weighted']['accept']),spec['TA_mixed_minus_TA_transfer_max'],available=ref_valid)
    return dict(status=_verdict(checks),checks=checks,source_calibration_only=True,target_family=target,
                interpretation='direction-specific development transfer; common injection shortcuts remain possible')


def _score_rows(out,regime,split):
    for path in sorted((Path(out)/'scores'/regime/split).glob('*.jsonl.gz')):
        yield from data.read_rows(path)


def _summary(metrics):
    lines=['# 评分修订开发结果','','本批为已查看14父资料上的冻结开发比较，不是独立未见终测，也不提供部署风险保证。',
           '实现验收与方法有效性分开。区间不足、覆盖缺失和不可估均不能当作通过。','']
    for regime,report in metrics['regimes'].items():
        lines+=['## '+regime,'','状态 '+report['status'],'']
        if report['status']=='not_tested_data_support':
            lines+=['未达到冻结数据支持门槛，未拟合或比较本方案。',''];continue
        lines+=['| 方法 | 真采纳 | 真未知 | 真拒绝 | 假采纳 | 假未知 | 假拒绝 | CD |',
                '|---|---:|---:|---:|---:|---:|---:|---:|']
        for method,values in report['metrics']['eval']['system_query'].items():
            numbers=[values[truth]['weighted'][d] for truth in ('true','false') for d in original.DECISIONS]+[values['correct_definite']]
            lines.append('| '+method+' | '+' | '.join('NA' if x is None else '%.5f'%x for x in numbers)+' |')
        lines+=['','裁决 '+report.get('retention',{}).get('status','not_tested'),
                '详细分母、F0/F1/F2×k1/2/3缺层、初窗、配对时效、错误转移、校准和逐项判据见metrics.json。','']
    lines+=['c区间状态 '+metrics.get('parameter_stability',{}).get('status','not_tested'),
            '双向族迁移整体主张 '+metrics.get('cross_family_claim',{}).get('status','not_tested'),
            'F3保持构造缺失。单父层经验结果不构成总体风险上界。']
    return '\n'.join(lines)+'\n'


def _text_once(path,text):
    path=Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.partial')
    temp.write_text(text);temp.replace(path)


def report(out,workers=1):
    out=Path(out)
    with prepare._lock(out/'.report.lock'):
        manifest,config,support=_context(out);_provenance(out,config)
        if (out/'report.complete.json').exists():
            return _read(out/'report.complete.json')
        path=out/'report/metrics.json'
        if path.exists():
            metrics=_read(path)
        else:
            metrics=dict(status='complete' if support['any_regime_supported'] else 'not_tested_data_support',support=support,
                         regimes={},attack_coverage=attack_coverage(out,manifest),parameter_stability=dict(status='not_tested'),
                         provenance=_read(out/'pipeline.json'))
            if support['any_regime_supported']:
                _require(out,'score')
            else:
                # Coverage is still recorded; no normal fit or invented six-cell comparison.
                metrics['unscored_coverage']={s:_coverage(list(prepare.iter_rows(out,s))) for s in ('fit','cal','eval')}
            for regime,spec in config['regimes'].items():
                if not support['regimes'][regime]['data_support_met']:
                    metrics['regimes'][regime]=dict(status='not_tested_data_support',support=support['regimes'][regime],
                        method_status={m:dict(status='not_tested',reason='data support gate') for m in METHODS},retention=dict(status='not_tested'))
                    continue
                fitted=_read(out/'models'/(regime+'.json'));cal=_domain(list(_score_rows(out,regime,'cal')),spec['cal_false'])
                expected={(j['family'],j['attack_k']) for j in manifest['jobs'] if j['split']=='cal' and j['kind']=='attack' and j['family'] in spec['cal_false']}
                cal_path=out/'calibration'/(regime+'.json')
                if cal_path.exists():
                    saved=_read(cal_path);policies=saved['policies']
                else:
                    policies=calibrate(cal,expected)
                    saved=dict(policies=policies,cal_false=spec['cal_false'],cal_parents=sorted({r['parent'] for r in cal}),
                        cal_job_ids=sorted({r['job_id'] for r in cal}),expected_layers=sorted(expected))
                    data.atomic_json(cal_path,saved)
                observed={(r['family'],r['attack_k']) for r in cal if original.primary(r,0)}
                calibration_sufficient=any(original.primary(r,0) for r in cal) and any(original.primary(r,1) for r in cal)
                evaluation=_domain(list(_score_rows(out,regime,'eval')),spec['eval_false'])
                reports={}
                for split,rows in [('cal',cal),('eval',evaluation)]:
                    predictions=out/'report/predictions'/regime/(split+'.jsonl.gz')
                    for row in rows:
                        row['decisions']={m:original.decide(row,m,policies[m]) for m in METHODS}
                    if not predictions.exists():
                        with data.atomic_rows(predictions) as write:
                            for row in rows:
                                write(row)
                    reports[split]=evaluate(rows,observed)
                current=dict(status='evaluated' if calibration_sufficient else 'insufficient_calibration',
                    data_support_met=True,method_status=fitted['method_status'],policies=policies,
                    calibration_sufficient=calibration_sufficient,metrics=reports,fit_false=spec['fit_false'],
                    cal_false=spec['cal_false'],eval_false=spec['eval_false'],
                    scoring_layer_effect=scoring_comparisons(reports['eval']),
                    target_family_metrics={f:six_cells(_domain(evaluation,[f])) for f in ('F0','F1','F2')})
                if regime=='mixed':
                    metrics['parameter_stability']=fitted.get('coefficient_interval',dict(status='not_available'))
                    current['retention']=main_retention(reports['eval'],fitted,config)
                    joint_checks={name:value for name,value in current['retention']['checks'].items()
                                  if name in ('coefficient_interval_excludes_zero','CD_J_minus_I_Jmargin','CD_J_minus_G','CD_J_minus_Q')}
                    current['joint_increment']=dict(status=_verdict(joint_checks),checks=joint_checks,
                        overall_candidate_retention=current['retention']['status'])
                    if not calibration_sufficient:
                        current['retention']=dict(status='not_tested',reason='mixed calibration lacks a primary class',numerical_checks=current['retention'])
                metrics['regimes'][regime]=current
            mixed=metrics['regimes'].get('mixed')
            if mixed is not None and mixed.get('status')=='not_tested_data_support':
                mixed=None
            for regime in ('F1_only','F2_only'):
                current=metrics['regimes'][regime]
                if current['status']!='not_tested_data_support':
                    current['retention']=transfer_retention(regime,current,mixed,config)
            claim_checks={r:dict(status='pass' if metrics['regimes'][r]['retention']['status']=='retained' else
                                  'fail' if metrics['regimes'][r]['retention']['status']=='not_retained' else 'insufficient') for r in config['regimes']}
            metrics['cross_family_claim']=dict(status=_verdict(claim_checks),components=claim_checks,
                                               interpretation='requires mixed retention and both separate transfer directions')
            data.atomic_json(path,metrics)
        _text_once(out/'report/summary.md',_summary(metrics))
        return _finish(out,'report',support,metrics=str(path),report=str(out/'report/summary.md'))


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--stage',required=True,choices=('features','fit','score','report'))
    parser.add_argument('--out',type=Path,default=Path(prepare.read_config()['new_output_root']))
    parser.add_argument('--workers',type=int,default=1);args=parser.parse_args(argv)
    if not 1<=args.workers<=8:
        parser.error('--workers must be between 1 and 8')
    try:
        globals()[args.stage](args.out,args.workers)
    except Exception as error:
        path=args.out/(args.stage+'.error.json')
        if not path.exists():
            data.atomic_json(path,dict(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc()))
        raise


if __name__=='__main__':
    main()
