"""Bounded gamma=0 comparison on frozen score-revision features only."""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[_name]='1'

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time
import traceback
import numpy as np
from . import heads, run as legacy
from scripts.rq1_temporal import data, run as original

CONFIG=Path(__file__).resolve().parents[2]/'docs/REALLY_MAYBE/rq1_no_miss_constant_2026_11_13/config.json'
ALIASES=dict(D_old='D',I_old='B',J_old='C',D_zero='T',I_zero='Jind',J_zero='J',I_cut='G',MATE_policy='MATE_policy')
METHODS=tuple(ALIASES)
BASELINES=dict(D_zero='D_old',I_zero='I_old',J_zero='J_old')
OLD=dict(D_old='D_head',I_old='I_Jmargin',J_old='J',MATE_policy='MATE_policy')
BASES=dict(D_zero='D_head',I_zero='I_Jmargin')


def read_config():
    return json.loads(CONFIG.read_text())


def _read(path):
    return json.loads(Path(path).read_text())


def _save(path,value):
    """An atomic orphan may be checked and adopted, never overwritten silently."""
    value=data.finite_json(value)
    if Path(path).exists():
        if _read(path)!=value:
            raise ValueError('existing artifact differs: '+str(path))
    else:
        data.atomic_json(path,value)


def fit_zero(rows,old_fitted,families):
    selected=legacy.supervision(rows,families)
    expected=sorted({p for m in BASES.values() for p in (old_fitted['models'].get(m) or {}).get('train_parents',[])})
    models={};statuses={};usable={}
    for name,base in BASES.items():
        available=[r for r in selected if r['finite'] and r['features'].get(base) is not None]
        actual=sorted({r['parent'] for r in available})
        coverage=dict(n_supervision=len(selected),n_usable=len(available),n_excluded=len(selected)-len(available),
            expected_parents=expected,usable_parents=actual,missing_usable_parents=sorted(set(expected)-set(actual)),
            by_parent={p:dict(n_supervision=sum(r['parent']==p for r in selected),
                n_usable=sum(r['parent']==p for r in available),
                normal_states=dict(Counter(r.get('method_status',{}).get(base,{}).get('status','not_recorded') for r in selected if r['parent']==p)))
                for p in sorted(set(expected)|{r['parent'] for r in selected})})
        try:
            if not old_fitted.get('data_support_met',True) or old_fitted['models'].get(base) is None:
                raise ValueError('original support or base model unavailable')
            if len(expected)!=6 or actual!=expected or sorted({r['parent'] for r in selected})!=expected:
                raise ValueError('all six original fit parents required; coverage incomplete')
            if len(available)!=len(selected):
                raise ValueError(base+': '+str(len(selected)-len(available))+' nonfinite or missing-feature records; supervision cannot be dropped')
            if any(r.get('method_status',{}).get(base,{}).get('status')=='unestimable' for r in selected):
                raise ValueError('normal OOF component unavailable')
            w=legacy.training_weights(available);X=np.array([r['features'][base] for r in available],float)
            mean=w@X;std=np.sqrt(w@((X-mean)**2));X[:,4]=0.
            model=heads.fit_base(X,[r['query_truth'] for r in available],w)
            model.update(structurally_fixed=['d'],original_d_mean=float(mean[4]),original_d_std=float(std[4]),original_d_variance=float(std[4]**2),
                free_parameters=1+sum(not c for c in model['constant']),
                train_parents=actual,fit_false=list(families),weight_sum=float(w.sum()),
                false_cells=sorted({r['family']+'/'+str(r['attack_k']) for r in available if r['query_truth']==0}),
                miss_condition_active=bool(heads.raw_parameters(model)['coef'][1]>0))
            models[name]=model;usable[name]=available
            statuses[name]=dict(status='ok',reason=None,optimizer_ok=True,coverage=coverage)
        except (ValueError,RuntimeError,FloatingPointError,OverflowError) as error:
            models[name]=None;statuses[name]=dict(status='unestimable',reason=str(error),
                optimizer_ok=False if isinstance(error,RuntimeError) else None,coverage=coverage)
    try:
        if models['I_zero'] is None:
            raise ValueError('I_zero unavailable')
        available=usable['I_zero']
        if any(r.get('delta_T') is None or not np.isfinite(r['delta_T']) for r in available):
            raise ValueError('Delta_T missing or nonfinite; supervision cannot be dropped')
        w=legacy.training_weights(available)
        offset=[heads.base_score(models['I_zero'],r['features']['I_Jmargin']) for r in available]
        model=heads.fit_increment([r['delta_T'] for r in available],[r['query_truth'] for r in available],w,
            offset,[r['parent'] for r in available],joint=True)
        models['J_zero']=model
        statuses['J_zero']=dict(status='ok',reason=None,optimizer_ok=model['optimizer_ok'],
            increment_status=model['status'],delta_informative=model['delta_informative'],n_usable=len(available))
    except (ValueError,RuntimeError,FloatingPointError,OverflowError) as error:
        models['J_zero']=None;statuses['J_zero']=dict(status='unestimable',reason=str(error),
            optimizer_ok=False if isinstance(error,RuntimeError) else None)
    return dict(status='fitted',models=models,method_status=statuses,fit_false=list(families),n_supervision=len(selected))


def score_feature(row,old_fitted,fitted):
    old=legacy.score_row(row,old_fitted)
    result={k:v for k,v in old.items() if k not in ('scores','method_status','contributions')}
    scores={m:old['scores'].get(base) for m,base in OLD.items()}
    contributions={m:old['contributions'][base] for m,base in OLD.items() if base in old['contributions']}
    states={m:{k:old['method_status'].get(base,{}).get(k) for k in ('status','reason')} for m,base in OLD.items()}
    for name,base in BASES.items():
        model=fitted['models'].get(name);x=row['features'].get(base);scores[name]=None
        states[name]={k:fitted['method_status'].get(name,{}).get(k) for k in ('status','reason')}
        try:
            if old['finite'] and model is not None and x is not None:
                scores[name]=heads.base_score(model,x)
                contributions[name]=heads.decompose(model,row['sources'][base],row['context'])
        except (ValueError,FloatingPointError,OverflowError) as error:
            states[name]=dict(status='numeric_failure',reason=str(error))
        if scores[name] is None and states[name]['status']=='ok':
            states[name]=dict(status='unavailable',reason=row.get('error') or 'feature unavailable on this record')
    name='J_zero';model=fitted['models'].get(name);scores[name]=None
    states[name]={k:fitted['method_status'].get(name,{}).get(k) for k in ('status','reason')}
    try:
        if model is not None and scores['I_zero'] is not None and row.get('delta_T') is not None:
            scores[name]=heads.increment_score(model,scores['I_zero'],row['delta_T'])
            contributions[name]=dict(contributions['I_zero'],increment=float(model['coefficient']*row['delta_T']),score=scores[name])
    except (ValueError,FloatingPointError,OverflowError) as error:
        states[name]=dict(status='numeric_failure',reason=str(error))
    if scores[name] is None and states[name]['status']=='ok':
        states[name]=dict(status='unavailable',reason='I_zero or Delta_T unavailable on this record')
    removed=None;scores['I_cut']=None;states['I_cut']=dict(states['I_old'])
    if scores['I_old'] is not None:
        gamma=heads.raw_parameters(old_fitted['models']['I_Jmargin'])['coef'][4]
        removed=float(gamma*(result['d']-result['m']))
        scores['I_cut']=float(scores['I_old']-removed)
        contributions['I_cut']=dict(removed_gamma_n0=removed,score=scores['I_cut'])
    result.update(scores={m:scores[m] for m in METHODS},method_status={m:states[m] for m in METHODS},
        contributions=contributions,I_cut_removed=removed,n0=result['d']-result['m'])
    return data.finite_json(result)


def _table(rows):
    return original.ReportRows.from_rows([dict(r,scores={ALIASES[m]:r['scores'].get(m) for m in METHODS},
        decisions={ALIASES[m]:r.get('decisions',{}).get(m,'unknown') for m in METHODS},
        m=r['d'],supports=r['m'],n_frames=r['w']) for r in rows])


def _six(table):
    result=original.six_cells_many(table,methods=tuple(ALIASES.values()))
    return {m:result[alias] for m,alias in ALIASES.items()}


def _apply(rows,table,policies):
    original.apply_policies(table,{ALIASES[m]:policies[m] for m in METHODS})
    for i,r in enumerate(rows):
        r['decisions']={m:original.DECISIONS[table.values['d_'+alias][i]] for m,alias in ALIASES.items()}


def _paired(rows,candidate,baseline):
    groups=defaultdict(list)
    for r in rows:
        if original.primary(r,1):groups[(r['parent'],)+original.epoch(r)].append(r)
    epochs=[];parents=Counter(key[0] for key in groups)
    for key,group in sorted(groups.items()):
        first={m:min((r['timestamp'] for r in group if r['decisions'][m]=='accept'),default=None) for m in (candidate,baseline)}
        epochs.append(dict(parent=key[0],epoch=list(key[1:]),origin=min(r['timestamp'] for r in group),first_accept=first))
    never={m:sum(1/(len(parents)*parents[e['parent']]) for e in epochs if e['first_accept'][m] is None)
        if parents else None for m in (candidate,baseline)}
    shared=[e for e in epochs if all(e['first_accept'][m] is not None for m in (candidate,baseline))]
    shared_parents=Counter(e['parent'] for e in shared);values=[]
    for e in shared:
        diff=e['first_accept'][candidate]-e['first_accept'][baseline]
        weight=1/(len(shared_parents)*shared_parents[e['parent']]);values.append((diff,weight))
        e.update(delay_difference_seconds=diff,paired_weight=weight)
    median=None;mass=0.
    for value,weight in sorted(values):
        mass+=weight
        if mass>=.5:median=float(value);break
    return dict(status='ok' if shared else 'insufficient_no_common_ever_adopted_epoch',candidate=candidate,baseline=baseline,
        n_primary_true_epochs=len(epochs),n_parents=len(parents),candidate_never=never[candidate],baseline_never=never[baseline],
        never_difference=None if not epochs else never[candidate]-never[baseline],shared_ever_epochs=len(shared),
        weighted_median_delay_difference_seconds=median,epochs=epochs)


def _transitions(rows,candidate,baseline):
    result={}
    for truth in (0,1):
        subset=[r for r in rows if original.primary(r,truth)];w=original.weights(subset,truth)
        cells={a+'/'+b:dict(n=0,weighted=0.) for a in original.DECISIONS for b in original.DECISIONS}
        for r,weight in zip(subset,w):
            cell=cells[r['decisions'][baseline]+'/'+r['decisions'][candidate]];cell['n']+=1;cell['weighted']+=float(weight)
        result[str(truth)]=dict(n=len(subset),from_method=baseline,to_method=candidate,cells=cells)
    return result


def evaluate(rows,policies,cal_layers,_report_table=None):
    table=_report_table if _report_table is not None else _table(rows)
    if _report_table is None:_apply(rows,table,policies)
    a=table.values
    strata=lambda mask:_six(table.subset(mask))
    metrics=dict(system_query=_six(table),coverage=legacy._coverage(rows),
        first_windows={name:strata(mask) for name,mask in [('length_1',a['n_frames']==1),
            ('length_2_to_9',(a['n_frames']>=2)&(a['n_frames']<=9)),('length_10',a['n_frames']==10)]},
        by_parent={p:strata(a['parent']==i) for i,p in enumerate(table.codes['parent'])},
        by_w={str(int(w)):strata(a['n_frames']==w) for w in np.unique(a['n_frames'])},
        by_m={str(int(m)):strata(a['supports']==m) for m in np.unique(a['supports'])},
        by_n0={str(int(n0)):strata(a['m']-a['supports']==n0) for n0 in np.unique(a['m']-a['supports'])},
        context_counts=[dict(w=int(w),d=int(d),m=int(m),n0=int(d-m),n=count)
            for (w,d,m),count in sorted(Counter((r['w'],r['d'],r['m']) for r in rows).items())],
        method_score_coverage={m:dict(n_finite=int(np.isfinite(a['s_'+alias]).sum()),n_total=len(rows),
            states=dict(Counter(r['method_status'].get(m,{}).get('status','unavailable') for r in rows))) for m,alias in ALIASES.items()},
        family_k={},paired_timeliness={m:_paired(rows,m,old) for m,old in BASELINES.items()},
        transitions={m:_transitions(rows,m,old) for m,old in dict(BASELINES,I_cut='I_old').items()})
    for family in ('F0','F1','F2','F3'):
        for k in (1,2,3):
            code=table.codes['family'].index(family) if family in table.codes['family'] else -1
            subset=table.subset((a['family']==code)&(a['attack_k']==k));n=int(original.primary_mask(subset,0).sum())
            metrics['family_k'][family+'/'+str(k)]=dict(family=family,k=k,n_primary_false=n,
                status='observed' if n else 'not_tested',cal_status='observed' if (family,k) in cal_layers else 'not_calibrated',metrics=_six(subset))
    fixed=table.values.copy();alias=ALIASES['I_cut'];p=policies['I_old'];score=fixed['s_'+alias];decision=fixed['d_'+alias];decision[:]=1
    if p['A'] is not None:decision[fixed['finite']&fixed['accept_eligible']&(score>0)&(score>=p['A'])]=0
    if p['R'] is not None:decision[fixed['finite']&fixed['reject_eligible']&(score<0)&(score<=p['R'])]=2
    metrics['I_cut_old_policy']=_six(original.ReportRows(fixed,table.codes))['I_cut']
    metrics['predeclared_records']=[{k:r[k] for k in ('key','w','d','m','scores','decisions','contributions','I_cut_removed')}
        for r in rows if (r['job_id']=='605ff9c3ca7bf3a5' and r['id']==212 and r['index']==23) or
            (r['job_id']=='cf2ad1a17529d018' and r['id']==185 and r['epoch']==1 and 23<=r['index']<=28)]
    return metrics


def retention(reports,config):
    limits=config['thresholds'];result={}
    for candidate,baseline in BASELINES.items():
        checks={}
        for regime in config['regimes']:
            report=reports.get(regime)
            if report is None or report.get('status')=='not_tested_data_support':
                checks[regime+'_available']=legacy._check(None,1);continue
            metrics=report['metrics']['eval'];main=metrics['system_query'];pair=metrics['paired_timeliness'][candidate]
            available=report['calibration_sufficient'] and report['method_status'][candidate]['status']=='ok' and all(metrics['method_score_coverage'][m]['n_finite']>0 for m in (candidate,baseline))
            both=available and main[candidate]['true']['n']>0 and main[candidate]['false']['n']>0
            # An all-Unknown method has no empirical support for retention.
            both=both and any(main[candidate][t]['counts'][d]>0 for t in ('true','false') for d in ('accept','reject'))
            check=lambda value,limit:legacy._check(value,limit,available=both)
            prefix=regime+'/'
            checks[prefix+'true_reject']=check(main[candidate]['true']['weighted']['reject'],limits['risk'])
            checks[prefix+'false_accept']=check(main[candidate]['false']['weighted']['accept'],limits['risk'])
            for key,layer in metrics['family_k'].items():
                if layer['n_primary_false']:
                    checks[prefix+key+'/false_accept']=check(layer['metrics'][candidate]['false']['weighted']['accept'],limits['risk'])
            checks[prefix+'TA_drop']=check(legacy._difference(main[baseline]['true']['weighted']['accept'],main[candidate]['true']['weighted']['accept']),limits['max_TA_drop'])
            checks[prefix+'CD_drop']=check(legacy._difference(main[baseline]['correct_definite'],main[candidate]['correct_definite']),limits['max_CD_drop'])
            checks[prefix+'never_increase']=check(pair['never_difference'],limits['max_never_adopted_increase'])
            checks[prefix+'paired_delay']=check(pair['weighted_median_delay_difference_seconds'],limits['max_paired_delay_seconds'])
            if regime=='mixed':
                checks['mixed/MATE_TA_deficit']=check(legacy._difference(main['MATE_policy']['true']['weighted']['accept'],main[candidate]['true']['weighted']['accept']),limits['max_mixed_MATE_TA_deficit'])
        mixed=reports.get('mixed',{});reverse=reports.get('F2_only',{});improvements={}
        if 'metrics' in mixed:
            main=mixed['metrics']['eval']['system_query'];gain=legacy._difference(main[candidate]['correct_definite'],main[baseline]['correct_definite'])
            improvements['mixed_CD_gain']=legacy._check(gain,limits['min_mixed_CD_gain'],'min',available=mixed['calibration_sufficient'] and mixed['method_status'][candidate]['status']=='ok')
        else:improvements['mixed_CD_gain']=legacy._check(None,limits['min_mixed_CD_gain'],'min')
        if 'metrics' in reverse:
            layer=reverse['metrics']['eval']['family_k']['F1/3'];v=layer['metrics']
            valid=bool(layer['n_primary_false']) and reverse['calibration_sufficient'] and reverse['method_status'][candidate]['status']=='ok'
            reduction=legacy._check(legacy._difference(v[baseline]['false']['weighted']['accept'],v[candidate]['false']['weighted']['accept']),limits['min_reverse_F1_k3_FA_reduction'],'min',available=valid)
            risk=legacy._check(v[candidate]['false']['weighted']['accept'],limits['risk'],available=valid)
            improvements['reverse_F1_k3']=dict(status='pass' if reduction['status']==risk['status']=='pass' else 'fail' if 'fail' in (reduction['status'],risk['status']) else 'insufficient',checks=dict(reduction=reduction,final_risk=risk))
        else:improvements['reverse_F1_k3']=dict(status='insufficient')
        states={v['status'] for v in improvements.values()}
        checks['actual_improvement']=dict(status='pass' if 'pass' in states else 'insufficient' if 'insufficient' in states else 'fail',alternatives=improvements)
        result[candidate]=dict(status=legacy._verdict(checks),role='primary' if candidate=='D_zero' else 'secondary',baseline=baseline,checks=checks)
    return result


def _equal_number(a,b,tolerance):
    return a is None and b is None or a is not None and b is not None and np.isfinite(a) and np.isfinite(b) and abs(a-b)<=tolerance


def _verify_old(rows,saved,policies,old_policies,config):
    for method,old in OLD.items():
        for branch in ('A','R'):
            if not _equal_number(policies[method][branch],old_policies[old][branch],config['comparison_tolerances']['old_policy']):
                raise ValueError('old policy mismatch: '+method+'/'+branch)
    expected={tuple(r['key']):r for r in saved};keys=[tuple(r['key']) for r in rows]
    if len(expected)!=len(saved) or len(set(keys))!=len(keys) or set(keys)!=set(expected):
        raise ValueError('old prediction key/denominator mismatch')
    for r in rows:
        old=expected[tuple(r['key'])]
        for key in ('job_id','id','epoch','parent','split','kind','family','attack_k','attack_role','index','timestamp','query_truth','query_gt_id','output_truth','output_present','identity_ok','query_present','newborn','finite','accept_eligible','reject_eligible','w','d','m'):
            if r.get(key)!=old.get(key):raise ValueError('old prediction metadata mismatch: '+key+' '+str(r['key']))
        for method,base in OLD.items():
            if not _equal_number(r['scores'][method],old['scores'][base],config['comparison_tolerances']['old_score']):
                raise ValueError('old score mismatch: '+method+' '+str(r['key']))
            if r['decisions'][method]!=old['decisions'][base]:
                raise ValueError('old decision mismatch: '+method+' '+str(r['key']))


def _inputs(source,config):
    small=['manifest.json','support.json']+[s+'.complete.json' for s in ('prepare','features','fit','score','report')]
    objects={name:_read(source/name) for name in small}
    supported={r for r in config['regimes'] if objects['support.json']['regimes'][r]['data_support_met']}
    for regime in config['regimes']:
        for folder in ('models','calibration'):
            name=folder+'/'+regime+'.json'
            if regime in supported or (source/name).exists():
                small.append(name);objects[name]=_read(source/name)
    for stage in ('prepare','features','fit','score','report'):
        completed=('COMPLETE',) if stage=='prepare' else ('complete','not_tested_data_support')
        if objects[stage+'.complete.json']['status'] not in completed:raise ValueError('source stage incomplete: '+stage)
    manifest=objects['manifest.json'];splits=manifest['config']['parent_splits']
    expected=sorted(p for p,s in splits.items() if s=='fit');folds=objects['features.complete.json'].get('folds',[])
    if supported and (len(expected)!=6 or sorted(f['parent'] for f in folds)!=expected):raise ValueError('six completed source folds required')
    paths={'fit':[source/f['features'] for f in folds]}
    for split in ('cal','eval'):
        expected_jobs=[j for j in manifest['jobs'] if j['split']==split and objects['prepare.complete.json']['jobs'][j['job_id']]['status']=='COMPLETE'
            and objects['prepare.complete.json']['jobs'][j['job_id']].get('rows',0)>0]
        paths[split]=[source/'features'/split/(j['job_id']+'.jsonl.gz') for j in expected_jobs] if supported else sorted((source/'features'/split).glob('*.jsonl.gz'))
    for split,files in paths.items():
        if set(files)!=set((source/'features'/split).glob('*.jsonl.gz')):
            raise ValueError('completed source feature inventory mismatch: '+split)
        if supported and not files:raise ValueError('source features missing: '+split)
    for regime in supported:
        for split in ('cal','eval'):
            if not (source/'report/predictions'/regime/(split+'.jsonl.gz')).is_file():raise ValueError('source predictions missing')
    modules=[__file__,heads.__file__,legacy.__file__,original.__file__,data.__file__,legacy.prepare.__file__,legacy.fitting.__file__,legacy.kernel.__file__]
    binding=dict(config=config,source=str(source),source_files=[data.source_record(source/name) for name in small],
        code=[data.source_record(path) for path in modules],
        features={s:[dict(path=str(p.relative_to(source)),bytes=p.stat().st_size) for p in sorted(files)] for s,files in paths.items()})
    return objects,paths,binding


def _rows_once(path,rows):
    if path.exists():
        if list(data.read_rows(path))!=rows:raise ValueError('existing predictions differ: '+str(path))
    else:
        with data.atomic_rows(path) as write:
            for r in rows:write(r)


def _summary(metrics):
    lines=['# 只未报来源常数约束开发比较','','本批只使用已查看的开发资料，不支持部署风险或联合创新主张。','']
    for regime,report in metrics['regimes'].items():
        lines += ['## '+regime,'','状态 '+report['status'],'']
        if 'metrics' not in report:continue
        lines += ['| 方法 | 真采纳 | 真未知 | 真拒绝 | 假采纳 | 假未知 | 假拒绝 | CD |','|---|---:|---:|---:|---:|---:|---:|---:|']
        for method,v in report['metrics']['eval']['system_query'].items():
            values=[v[t]['weighted'][d] for t in ('true','false') for d in original.DECISIONS]+[v['correct_definite']]
            lines += ['| '+method+' | '+' | '.join('NA' if x is None else '%.5f'%x for x in values)+' |']
        lines += ['']
    for method,verdict in metrics['retention'].items():lines += [method+' '+verdict['role']+' '+verdict['status']]
    lines += ['','逐项判据、分母、空层、转移及配对时效见metrics.json。',
        'I_cut仅为诊断。a_minus为0时条件未报项失活，模型中明确记录。',
        '未计算c区间。多控单父及F3缺失仍限制外推；经验通过不是统计显著性。']
    return '\n'.join(lines)+'\n'


def run(source,out):
    source=Path(source).resolve();out=Path(out).resolve();config=read_config()
    if source==out or source in out.parents or out in source.parents:
        raise ValueError('output must be isolated from the read-only source run')
    with legacy.prepare._lock(out/'.run.lock'):
        started=time.monotonic();times={}
        try:
            objects,paths,binding=_inputs(source,config)
            bind=out/'binding.json'
            if bind.exists() and _read(bind)!=binding:raise ValueError('binding code/config/source changed; use a new output directory')
            _save(bind,binding)
            if (out/'run.complete.json').exists():
                marker=_read(out/'run.complete.json')
                for relative in marker['artifacts']:
                    if not (out/relative).is_file():raise ValueError('completed artifact missing: '+relative)
                return marker
            manifest=objects['manifest.json'];reports={};cache={}
            for regime,spec in config['regimes'].items():
                marker=out/'regimes'/(regime+'.complete.json');report_path=out/'report'/(regime+'.json')
                if marker.exists():
                    complete=_read(marker)
                    for relative in complete['artifacts']:
                        if not (out/relative).is_file():raise ValueError('completed regime artifact missing: '+relative)
                    reports[regime]=_read(report_path);times[regime]=complete['times'];continue
                tick=time.monotonic();old_fitted=objects.get('models/'+regime+'.json')
                if not objects['support.json']['regimes'][regime]['data_support_met']:
                    report=dict(status='not_tested_data_support',reason='original frozen support gate')
                else:
                    model_path=out/'models'/(regime+'.json');model_marker=out/'models'/(regime+'.complete.json')
                    if model_path.exists():
                        fitted=_read(model_path)
                        if fitted.get('status')!='fitted':raise ValueError('model lacks completion state: '+str(model_path))
                        _save(model_marker,dict(status='complete'))
                    else:
                        if 'fit' not in cache:cache['fit']=[r for p in paths['fit'] for r in data.read_rows(p)]
                        fitted=fit_zero(cache['fit'],old_fitted,spec['fit_false'])
                        _save(model_path,fitted);_save(model_marker,dict(status='complete'))
                    fit_elapsed=time.monotonic()-tick;calibrated=None;metrics={}
                    expected={(j['family'],j['attack_k']) for j in manifest['jobs'] if j['split']=='cal' and j['kind']=='attack' and j['family'] in spec['cal_false']}
                    for split in ('cal','eval'):
                        if split not in cache:cache[split]=[r for p in paths[split] for r in data.read_rows(p)]
                        rows=[score_feature(r,old_fitted,fitted) for r in legacy._domain(cache[split],spec[split+'_false'])]
                        table=_table(rows)
                        if split=='cal':
                            calibrated={m:original.calibrate(table,alias,expected_layers=expected,alpha=.05) for m,alias in ALIASES.items()}
                            observed={(r['family'],r['attack_k']) for r in rows if original.primary(r,0)}
                            sufficient=all(any(original.primary(r,t) for r in rows) for t in (0,1))
                            _save(out/'calibration'/(regime+'.json'),dict(policies=calibrated,cal_false=spec['cal_false'],
                                cal_parents=sorted({r['parent'] for r in rows}),cal_job_ids=sorted({r['job_id'] for r in rows}),expected_layers=sorted(expected)))
                        _apply(rows,table,calibrated)
                        _verify_old(rows,list(data.read_rows(source/'report/predictions'/regime/(split+'.jsonl.gz'))),
                            calibrated,objects['calibration/'+regime+'.json']['policies'],config)
                        metrics[split]=evaluate(rows,calibrated,observed,_report_table=table)
                        _rows_once(out/'predictions'/regime/(split+'.jsonl.gz'),rows)
                    report=dict(status='evaluated' if sufficient else 'insufficient_calibration',metrics=metrics,
                        method_status=dict({m:old_fitted['method_status'][old] for m,old in OLD.items()},I_cut=old_fitted['method_status']['I_Jmargin'],**fitted['method_status']),calibration_sufficient=sufficient,policies=calibrated,
                        fit_false=spec['fit_false'],cal_false=spec['cal_false'],eval_false=spec['eval_false'],
                        old_reproduction=dict(status='pass',methods=list(OLD),policy_tolerance=config['comparison_tolerances']['old_policy'],score_tolerance=config['comparison_tolerances']['old_score']))
                    times[regime]=dict(fit_or_resume_seconds=fit_elapsed,total_seconds=time.monotonic()-tick)
                reports[regime]=report;_save(report_path,report)
                artifacts=[str(report_path.relative_to(out))]
                if 'metrics' in report:
                    artifacts += ['models/'+regime+'.json','models/'+regime+'.complete.json','calibration/'+regime+'.json']
                    artifacts += ['predictions/'+regime+'/'+s+'.jsonl.gz' for s in ('cal','eval')]
                _save(marker,dict(status='complete',artifacts=artifacts,times=times.get(regime,{})))
            metrics=dict(status='complete',regimes=reports,retention=retention(reports,config),
                primary_candidate='D_zero',coefficient_interval=dict(status='not_tested_known_support_insufficient'),
                scope=config['scope'],attack_coverage={jid:s for jid,s in objects['prepare.complete.json']['jobs'].items()},
                boundaries=['F3 absent','multi-control cells may have single-parent coverage','seen development only'])
            _save(out/'report/metrics.json',metrics)
            summary=out/'report/summary.md'
            if not summary.exists():legacy._text_once(summary,_summary(metrics))
            if not (out/'stage_times.json').exists():
                _save(out/'stage_times.json',dict(regimes=times,invocation_seconds=time.monotonic()-started))
            artifacts=['binding.json','report/metrics.json','report/summary.md','stage_times.json']
            for regime in reports:
                complete=_read(out/'regimes'/(regime+'.complete.json'))
                artifacts+=['regimes/'+regime+'.complete.json']+complete['artifacts']
            marker=dict(status='complete',artifacts=artifacts,primary_candidate='D_zero',retention={m:r['status'] for m,r in metrics['retention'].items()})
            _save(out/'run.complete.json',marker)
            return marker
        except Exception as error:
            if not (out/'error.json').exists():
                data.atomic_json(out/'error.json',dict(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc(),elapsed_seconds=time.monotonic()-started))
            raise


def main(argv=None):
    parser=argparse.ArgumentParser();config=read_config()
    parser.add_argument('--source',type=Path,default=Path(config['source']))
    parser.add_argument('--out',type=Path,default=Path(config['output']))
    args=parser.parse_args(argv);run(args.source,args.out)


if __name__=='__main__':main()
