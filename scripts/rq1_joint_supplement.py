"""Frozen same-marginal Joint/Group comparison; no normal-model retraining."""
import argparse
from collections import Counter
import copy
import math
from pathlib import Path

import numpy as np
from scripts import rq1_independent_supplement as supplement
from scripts.rq1_temporal import data, fit as fitting, kernel, run as original
from scripts.rq1_score_revision import heads, prepare, run as legacy, no_miss_constant as zero
from scripts.rq1_report_freeze import run as freeze

BRANCHES=('Group','Joint')
METHODS=('Count','Cond')+BRANCHES
REGIMES=supplement.REGIMES
ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'docs/REALLY_MAYBE/rq1_joint_supplement_2026_11_17/config.json'
DEFAULT_OUT=Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_joint_supplement_2026_11_17/run_001')


def log_probability(u,p,groups,rho):
    u=np.asarray(u);p=np.asarray(p,float)
    if u.ndim!=1 or p.shape!=u.shape or not np.isin(u,[-1,0,1]).all():
        raise ValueError('invalid source events or probability shape')
    groups=kernel._groups(groups,len(u))
    if not supplement.finite(rho) or not 0<=rho<1 or not np.isfinite(p[u>=0]).all():
        raise ValueError('invalid rho or active probability')
    p=np.clip(p,1e-6,1-1e-6)
    return float(kernel._emission_log(u,p[None,:],groups,rho)[0])


def combination(u,p,groups,rho):
    """Only legal source events, fixed geometry groups and frozen marginals enter."""
    u=np.asarray(u);p=np.asarray(p,float)
    all_log=log_probability(u,p,groups,rho)
    plus=np.where(u==1,1,-1)
    plus_log=log_probability(plus,p,groups,rho)
    independent=log_probability(u,p,groups,0.)
    ind=float(-np.log1p(-np.clip(p[u==0],1e-6,1-1e-6)).sum())
    grouped=0.;patterns=Counter()
    for group in groups:
        ix=[i for i in group if u[i]>=0]
        if ix:
            grouped+=float(-np.log1p(-np.clip(p[[i for i in ix if u[i]==0]],1e-6,1-1e-6)).sum())/len(ix)
        if len(ix)>1:
            values=u[ix]
            patterns['common_00' if np.all(values==0) else 'common_11' if np.all(values==1) else 'common_mixed']+=1
    # Pure report frames are exact zero, including singleton and unknown groups.
    joint=0. if not np.any(u==0) else plus_log-all_log
    if joint < -1e-12 or not np.isfinite([ind,joint,grouped,all_log]).all():
        raise ValueError('invalid combination score')
    return dict(Ind=ind,Joint=max(0.,joint),Group=grouped,nll_ind=-independent,
                nll_joint=-all_log,patterns=dict(patterns))


def direct(row,model):
    if not np.isin(row['U'],[-1,0,1]).all():raise ValueError('invalid source events')
    groups=kernel._groups(row['groups'],len(row['U']))
    pred=fitting.predict_row(row,{'D':model})
    return dict(u=pred['u'].tolist(),p=pred['D'].tolist(),groups=groups)


def window_records(rows,model,rho):
    """Cache each frame's D once, then aggregate only causal W10 histories."""
    packed=[]
    for row in rows:
        item={k:row.get(k) for k in ('key','job_id','id','epoch','index','frame','timestamp','source_ids','query_present','newborn')}
        try:
            pred=direct(row,model);item['terms']=combination(**pred,rho=rho);item['error']=None
        except (ValueError,FloatingPointError,OverflowError) as exc:
            item.update(terms=None,error=str(exc))
        packed.append(item)
    result={}
    for window in kernel.windows(packed,10):
        current=window[-1];key=tuple(current['key'])
        if key in result:raise ValueError('duplicate raw row key')
        empty=not current.get('query_present') or current.get('newborn')
        errors=[r['error'] for r in window if r['error']]
        diagnostic=dict(n_frames=0 if empty else len(window),error='; '.join(errors) or None,
                        nll_ind=None if empty or current['terms'] is None else current['terms']['nll_ind'],
                        nll_joint=None if empty or current['terms'] is None else current['terms']['nll_joint'])
        diagnostic['metadata']={k:current[k] for k in ('job_id','id','epoch','index','frame','timestamp','source_ids','query_present','newborn')}
        for pattern in ('common_00','common_11','common_mixed'):
            diagnostic[pattern]=sum(bool(r['terms'] and r['terms']['patterns'].get(pattern)) for r in window) if not empty else 0
        diagnostic['scores']={m:None if errors else 0. if empty else sum(r['terms'][m] for r in window)
                              for m in ('Ind',)+BRANCHES}
        result[key]=diagnostic
    return result


def fit_records(records,grid):
    if not records:return dict(status='unestimable',rho=None,reason='no_usable_normal_supervision',objectives={},by_parent={},coverage={})
    rows=[r for r,pred in records];weights=original.weights(rows,1)
    if not math.isclose(float(weights.sum()),1.,abs_tol=1e-12):raise ValueError('rho weights do not sum to one')
    objectives={str(float(rho)):0. for rho in grid};by_parent={};coverage=Counter();informative=set();epochs=set();informative_frames=0
    for (row,pred),weight in zip(records,weights):
        parent=row['parent'];entry=by_parent.setdefault(parent,dict(weight=0.,rows=0,informative_frames=0,patterns=Counter(),objectives={k:0. for k in objectives}))
        entry['weight']+=float(weight);entry['rows']+=1
        for rho in grid:
            terms=combination(**pred,rho=rho);key=str(float(rho));loss=float(weight)*terms['nll_joint']
            objectives[key]+=loss;entry['objectives'][key]+=loss
        patterns=terms['patterns'];coverage.update(patterns);entry['patterns'].update(patterns)
        if patterns:
            informative.add(parent);epochs.add((parent,)+original.epoch(row));informative_frames+=1;entry['informative_frames']+=1
    for entry in by_parent.values():
        entry['objectives']={k:v/entry['weight'] for k,v in entry['objectives'].items()}
    minimum=min(objectives.values());rho=min(float(k) for k,v in objectives.items() if v<=minimum+1e-12)
    status='no_identifying_groups' if not informative else 'structural_degeneracy' if rho==0 else 'selected'
    if not informative:rho=0.
    return dict(status=status,rho=rho,objectives=objectives,by_parent=by_parent,
                weight_sum=float(weights.sum()),n_rows=len(rows),
                coverage=dict(patterns=coverage,informative_parents=sorted(informative),informative_epochs=len(epochs),informative_frames=informative_frames),
                objective_meaning='training_selection_with_held_parent_D_not_independent_rho_validation')


def bind(config_path,out):
    config_path=Path(config_path);config=freeze.read(config_path);out=Path(out).resolve()
    if config['window']!=10 or config['rho_grid']!=[0,.25,.5,.75,.9]:raise ValueError('frozen window/grid mismatch')
    sources=[config_path,config_path.with_name('SDS.md'),Path(config['source_scores'])/'features.complete.json',
             Path(config['source_scores'])/'manifest.json',Path(config['source_report'])/'manifest.json',config['source_normal_models']]
    for name in ('source_scores','source_report','source_independent'):
        source=Path(config[name]).resolve()
        if out==source or out in source.parents or source in out.parents:raise ValueError('output overlaps source')
    for regime in REGIMES:
        sources += [Path(config['source_independent'])/'calibration'/(regime+'.json'),
                    Path(config['source_report'])/'models'/(regime+'.json'),Path(config['source_report'])/'calibration'/(regime+'.json')]
    code=[Path(__file__),Path(supplement.__file__),Path(fitting.__file__),Path(kernel.__file__),Path(heads.__file__),
          Path(original.__file__),Path(legacy.__file__),Path(zero.__file__),Path(freeze.__file__),Path(data.__file__)]
    freeze.save(out/'binding.json',dict(config=config,sources=[data.source_record(p) for p in sources],code=[data.source_record(p) for p in code]))
    legacy._text_once(out/'frozen_spec.md',config_path.with_name('SDS.md').read_text())
    return config


def fit(config_path,out):
    out=Path(out);config=bind(config_path,out);source=Path(config['source_scores'])
    if (out/'rho.json').exists():return freeze.read(out/'rho.json')
    folds=freeze.read(source/'features.complete.json')['folds'];manifest=freeze.read(source/'manifest.json')
    parents={p for p,split in config['old_parent_splits'].items() if split=='fit'}
    if len(folds)!=6 or {f['parent'] for f in folds}!=parents:raise ValueError('six frozen folds required')
    records=[];sources=[]
    for fold in folds:
        parent=fold['parent'];normal=source/fold['normal'];fitted=freeze.read(normal)
        if set(fold['train_parents'])!=parents-{parent} or set(fitted['train_parents'])!=parents-{parent} or fitted['held_parent']!=parent:
            raise ValueError('held parent leaked or fold training inventory differs')
        model=fitted['models']['D']
        if set(model.get('train_parents',[]))!=parents-{parent}:raise ValueError('D model training parents differ')
        jobs=[j for j in manifest['jobs'] if j['parent']==parent and j['split']=='fit' and j['kind']=='clean']
        if len(jobs)!=1:raise ValueError('one clean job per fit parent required')
        path=Path(jobs[0]['rows_path']);sources.append(dict(parent=parent,normal=data.source_record(normal),rows_path=data.source_record(path)))
        for row in data.read_rows(path):
            if row['parent']!=parent or row['job_id']!=jobs[0]['job_id']:raise ValueError('fit row identity differs')
            if row['kind']!='clean' or row['split']!='fit' or not original.primary(row,1):continue
            pred=direct(row,model)
            if any(u>=0 for u in pred['u']):records.append((row,pred))
    result=fit_records(records,config['rho_grid']);result['source_folds']=sources
    freeze.save(out/'rho.json',result);return result


def attach(rows,records,rho):
    if len({tuple(r['key']) for r in rows})!=len(rows) or not {tuple(r['key']) for r in rows}<=set(records):
        raise ValueError('prediction/raw window key coverage differs')
    for row in rows:
        diagnostic=records[tuple(row['key'])]
        for field,value in diagnostic['metadata'].items():
            if row.get(field)!=value:raise ValueError('prediction/raw metadata differs '+field)
        if diagnostic['n_frames']!=row['n_frames']:raise ValueError('causal window length differs')
        cached=row['scores'].get('Cond');rebuilt=diagnostic['scores']['Ind']
        if supplement.finite(cached) and supplement.finite(rebuilt) and not math.isclose(cached,rebuilt,abs_tol=1e-10,rel_tol=1e-12):
            raise ValueError('independent source-event/window alignment differs')
        row['joint_diagnostics']={k:v for k,v in diagnostic.items() if k!='scores'}
        row.setdefault('supplement_scores',{}).update({m:cached if m=='Joint' and rho==0 else diagnostic['scores'][m] for m in BRANCHES})
    return rows


def apply(rows,policies,rho):
    for row in rows:
        for method in BRANCHES:
            score=row['supplement_scores'][method]
            result=supplement.decide(row['decisions']['Count'],supplement.readable(row),bool(row.get('query_present')),
                                     bool(row.get('newborn')),bool(row.get('reject_eligible')),score,policies[method])
            if method=='Joint' and rho==0:
                score=row['scores']['Cond'];result=dict(decision=row['decisions']['Cond'],status='exact_Cond_degeneracy')
            row['scores'][method]=score;row['decisions'][method]=result['decision']
            row.setdefault('supplement_status',{})[method]=result['status']
            row['method_status'][method]=dict(status='ok' if supplement.finite(score) else 'numeric_failure',decision_status=result['status'])
    return rows


def normal_nll(rows):
    clean=[r for r in rows if original.primary(r,1)];weights=original.weights(clean,1)
    if not clean:return dict(status='insufficient',n_rows=0)
    if any(not supplement.finite(r['joint_diagnostics'][k]) for r in clean for k in ('nll_ind','nll_joint')):
        return dict(status='failure',n_rows=len(clean))
    return dict(status='ok',n_rows=len(clean),weight_sum=float(weights.sum()),
                independent=sum(float(w)*r['joint_diagnostics']['nll_ind'] for r,w in zip(clean,weights)),
                joint=sum(float(w)*r['joint_diagnostics']['nll_joint'] for r,w in zip(clean,weights)))


def metrics(rows,layers,cal_layers):
    tables={m:freeze.table(rows,m) for m in METHODS}
    def cells(mask=None):return {m:original.six_cells(t if mask is None else t.subset(mask),'D') for m,t in tables.items()}
    windows=np.asarray([r['w'] for r in rows]);parents=np.asarray([r['parent'] for r in rows],dtype=object)
    families=np.asarray([r['family'] for r in rows],dtype=object);ks=np.asarray([r['attack_k'] for r in rows])
    result=dict(system_query=cells(),coverage=legacy._coverage(rows),normal_frame_nll=normal_nll(rows),family_k={},
        first_windows={name:cells(mask) for name,mask in [('length_1',windows==1),('length_2_to_9',(windows>=2)&(windows<10)),('length_10',windows==10)]},
        by_parent={p:cells(parents==p) for p in sorted(set(parents))},
        paired_timeliness={m:zero._paired(rows,m,'Cond') for m in BRANCHES},
        transitions={m:zero._transitions(rows,m,'Cond') for m in BRANCHES},
        method_score_coverage={m:freeze.score_coverage(rows,m) for m in METHODS},group_patterns={})
    for pattern in ('common_00','common_11','common_mixed'):
        mask=np.asarray([bool(r['joint_diagnostics'][pattern]) for r in rows],bool)
        result['group_patterns'][pattern]=dict(n_windows=int(mask.sum()),metrics=cells(mask),
            transitions={m:zero._transitions([r for r,keep in zip(rows,mask) if keep],m,'Cond') for m in BRANCHES})
    for family,k in sorted(layers):
        mask=(families==family)&(ks==k);selected=[r for r,keep in zip(rows,mask) if keep and original.primary(r,0)]
        result['family_k'][family+'/'+str(k)]=dict(family=family,k=k,status='observed' if selected else 'not_tested',
            cal_status='observed' if (family,k) in cal_layers else 'not_calibrated',
            support=dict(rows=len(selected),parents=len({r['parent'] for r in selected}),entities=len({r['job_id'] for r in selected}),epochs=len({original.epoch(r) for r in selected})),metrics=cells(mask))
    return result


def judge(measurement,policies,rho,required_layers):
    main=measurement['system_query'];joint=main['Joint'];cond=main['Cond'];pair=measurement['paired_timeliness']['Joint']
    check=legacy._check
    risk={m:dict(true_reject=check(main[m]['true']['weighted']['reject'],.05),false_accept=check(main[m]['false']['weighted']['accept'],.05)) for m in ('Cond',)+BRANCHES}
    for layer,group in measurement['family_k'].items():
        if group['status']=='observed':
            for method in risk:risk[method]['false_accept_'+layer]=check(group['metrics'][method]['false']['weighted']['accept'],.05)
    changes=sum(cell['n'] for truth in measurement['transitions']['Joint'].values() for key,cell in truth['cells'].items() if key.split('/')[0]!=key.split('/')[1])
    checks=dict(risk['Joint'],cd_gain_Cond=check(legacy._difference(joint['correct_definite'],cond['correct_definite']),.01,'min'),
        cd_gain_Group=check(legacy._difference(joint['correct_definite'],main['Group']['correct_definite']),.01,'min'),
        true_accept_loss=check(legacy._difference(cond['true']['weighted']['accept'],joint['true']['weighted']['accept']),.02),
        never_accept_increase=check(pair['never_difference'],.02),paired_delay=check(pair['weighted_median_delay_difference_seconds'],.5),
        active=check(int(policies['Joint']['status']=='active' and rho>0),1,'min'),changed_primary=check(changes,1,'min'))
    for method in ('Cond','Group'):
        status=legacy._verdict(risk[method])
        checks['control_risk_'+method]=check(None if status=='evidence_insufficient' else int(status=='retained'),1,'min')
    for layer in required_layers:
        group=measurement['family_k'].get(layer);support=group['support'] if group else {}
        enough=bool(support and min(support['parents'],support['entities'])>=3)
        checks['coverage_'+layer]=check(None if not support else min(support['parents'],support['entities']),3,'min',available=enough)
    return dict(status=legacy._verdict(checks),checks=checks,n_changed_primary=changes,
                risk_status={m:legacy._verdict(v) for m,v in risk.items()},risk_checks=risk,
                same_risk_comparison='supported' if all(legacy._verdict(v)=='retained' for v in risk.values()) else 'limited_by_control_risk')


def raw_jobs(config,split):
    source=Path(config['source_scores'] if split=='cal' else config['source_report']);manifest=freeze.read(source/'manifest.json')
    for job in manifest['jobs']:
        if job['split']!=split:continue
        path=Path(job.get('rows_path',source/'jobs'/job['job_id']/'rows.jsonl.gz'))
        if not path.exists():
            status=freeze.read(Path(job.get('status_path',source/'jobs'/job['job_id']/'complete.json')))
            if status['status']=='UNREALIZABLE':continue
        yield job,path


def source_records(config,split,model,rho):
    result={};sources=[]
    for job,path in raw_jobs(config,split):
        rows=list(data.read_rows(path));mapping=window_records(rows,model,rho)
        if set(result)&set(mapping):raise ValueError('duplicate job rows')
        result.update(mapping);sources.append(data.source_record(path))
    return result,sources


def compatibility(config,model,out):
    """Check a bounded old prefix before generating the D-only confirmation path."""
    path=Path(out)/'compatibility.json'
    if path.exists():return freeze.read(path)
    result={}
    for split in ('cal','eval'):
        job,raw_path=next((j,p) for j,p in raw_jobs(config,split) if j['kind']=='clean')
        sample=[]
        for window in kernel.windows(data.read_rows(raw_path),10):
            feature={k:window[-1].get(k) for k in legacy.METADATA};feature.update(heads.window_features(window,{'D':model},0.));sample.append(feature)
            if len(sample)==32:break
        keys={tuple(r['key']) for r in sample}
        root=Path(config['source_scores']) if split=='cal' else Path(config['source_report'])
        cached={tuple(r['key']):r for r in data.read_rows(root/'features'/split/(job['job_id']+'.jsonl.gz')) if tuple(r['key']) in keys}
        for feature in sample:
            old=cached[tuple(feature['key'])]
            for field in ('context','n_minus','accept_eligible','reject_eligible','finite','n_frames'):
                if feature[field]!=old[field]:raise ValueError('D-only compatibility differs '+field)
            if feature['features']['D_head']!=old['features']['D_head']:
                if not np.allclose(feature['features']['D_head'],old['features']['D_head'],rtol=1e-12,atol=1e-10):raise ValueError('D features differ')
        for regime in REGIMES:
            report=Path(config['source_report']);ind=Path(config['source_independent'])
            bundle=freeze.read(report/'models'/(regime+'.json'));policy=freeze.read(report/'calibration'/(regime+'.json'))['policies']['Count']
            cond=freeze.read(ind/'calibration'/(regime+'.json'))['branches']['Cond']
            expected={tuple(r['key']):r for r in data.read_rows(ind/'predictions'/regime/(split+'.jsonl.gz')) if tuple(r['key']) in keys}
            for row in new_predictions(sample,bundle,policy,cond):
                old=expected[tuple(row['key'])]
                if row['Count_inputs']!=old['Count_inputs'] or row['decisions']!={m:old['decisions'][m] for m in ('Count','Cond')}:
                    raise ValueError('Count/Cond compatibility differs')
                for method in ('Count','Cond'):
                    if row['scores'][method]!=old['scores'][method] and not math.isclose(row['scores'][method],old['scores'][method],abs_tol=1e-10,rel_tol=1e-12):raise ValueError('Count/Cond score differs')
        result[split]=dict(status='pass',job_id=job['job_id'],n_rows=len(sample),regimes=list(REGIMES))
    freeze.save(path,result);return result


def confirmation_features(config,out,model,rho):
    root=Path(out)/'confirmation';manifest=freeze.read(root/'manifest.json');complete=freeze.read(root/'prepare.complete.json')
    if manifest['jobs']!=config['jobs'] or set(complete['jobs'])!={j['job_id'] for j in config['jobs']}:
        raise ValueError('confirmation task set differs')
    features=[];records={}
    for job in manifest['jobs']:
        status=freeze.read(root/'jobs'/job['job_id']/'complete.json')
        if status!=complete['jobs'][job['job_id']] or status['status'] not in ('COMPLETE','UNREALIZABLE'):raise ValueError('confirmation incomplete')
        if status['status']=='UNREALIZABLE':continue
        raw=list(data.read_rows(root/'jobs'/job['job_id']/'rows.jsonl.gz'))
        for row in raw:
            if any(row.get(k)!=job[k] for k in ('job_id','parent','split','kind','family','attack_k')):raise ValueError('confirmation row identity differs')
        records.update(window_records(raw,model,rho));job_features=[]
        for window in kernel.windows(raw,10):
            row={k:window[-1].get(k) for k in legacy.METADATA};row.update(heads.window_features(window,{'D':model},0.))
            job_features.append(row)
        freeze.rows_once(Path(out)/'features/additional'/(job['job_id']+'.jsonl.gz'),job_features);features.extend(job_features)
    return features,records,complete


def new_predictions(features,bundle,count_policy,cond_policy):
    rows=[]
    for feature in features:
        row={k:v for k,v in feature.items() if k not in ('features','sources','method_status')}
        row.update(scores={'Count':None},decisions={},supplement_scores={},method_status={'Count':copy.deepcopy(bundle['method_status']['Count'])},
                   Count_inputs=None,w=feature['context'][0],d=feature['context'][1],m=feature['context'][2])
        try:
            if bundle['models']['Count'] is not None:
                row['Count_inputs']=freeze.count_inputs(feature);row['scores']['Count']=heads.base_score(bundle['models']['Count'],row['Count_inputs'])
        except (ValueError,FloatingPointError,OverflowError) as exc:row['method_status']['Count']=dict(status='numeric_failure',reason=str(exc))
        row['decisions']['Count']=original.decide(row,'Count',count_policy)
        x=feature['features'].get('D_head');score=-float(x[1]) if x is not None else None
        result=supplement.decide(row['decisions']['Count'],supplement.readable(row),bool(row['query_present']),bool(row['newborn']),bool(row['reject_eligible']),score,cond_policy)
        row['scores']['Cond']=score;row['supplement_scores']['Cond']=score;row['decisions']['Cond']=result['decision']
        row['method_status']['Cond']=dict(status='ok' if supplement.finite(score) else 'numeric_failure');row['supplement_status']={'Cond':result['status']}
        rows.append(data.finite_json(row))
    return rows


def evaluate(config_path,out):
    out=Path(out);config=bind(config_path,out);rho_fit=freeze.read(out/'rho.json');rho=rho_fit['rho']
    if rho is None:raise ValueError('Joint is unestimable; rho is not zero')
    model=freeze.read(config['source_normal_models'])['models']['D'];source=Path(config['source_independent']);report_source=Path(config['source_report'])
    regime_specs=freeze.read(report_source/'manifest.json')['config']['regimes']
    compatibility(config,model,out)
    records={};raw_sources={}
    for split in ('cal','eval'):records[split],raw_sources[split]=source_records(config,split,model,rho)
    additional=None
    if rho>0:additional=confirmation_features(config,out,model,rho)
    reports={};policies_by_regime={}
    for regime in REGIMES:
        saved_cal=freeze.read(source/'calibration'/(regime+'.json'));old_cal=freeze.read(report_source/'calibration'/(regime+'.json'))
        all_rows={s:attach(list(data.read_rows(source/'predictions'/regime/(s+'.jsonl.gz'))),records[s],rho) for s in ('cal','eval')}
        policies={m:supplement.calibrate(all_rows['cal'],m) for m in BRANCHES}
        if rho==0:policies['Joint']=copy.deepcopy(saved_cal['branches']['Cond'])
        calibration=dict(branches=policies,Cond=saved_cal['branches']['Cond'],source_calibration_sufficient=saved_cal['source_calibration_sufficient'],
                         observed_layers=saved_cal['observed_layers'],missing_layers=saved_cal['missing_layers'])
        freeze.save(out/'calibration'/(regime+'.json'),calibration);policies_by_regime[regime]=calibration
        observed={tuple(x) for x in saved_cal['observed_layers']};layers=observed|{tuple(x) for x in old_cal['expected_layers']}|{('F1',1),('F1',2),('F2',1),('F2',2)}
        domains={'existing':all_rows}
        if additional is not None:
            features,new_records,complete=additional;bundle=freeze.read(report_source/'models'/(regime+'.json'))
            rows=new_predictions(legacy._domain(features,regime_specs[regime]['eval_false']),bundle,old_cal['policies']['Count'],saved_cal['branches']['Cond'])
            domains['additional']={'eval':attach(rows,new_records,rho)}
        for domain,splits in domains.items():
            measurements={};reproduced={}
            for split,rows in splits.items():
                old=copy.deepcopy(rows) if domain=='existing' else None
                apply(rows,policies,rho);measurements[split]=metrics(rows,layers,observed)
                if old is not None:
                    for before,after in zip(old,rows):
                        for field in ('scores','decisions','method_status','supplement_scores','supplement_status'):
                            if any(after[field].get(k)!=v for k,v in before[field].items() if k not in BRANCHES):raise ValueError('old output changed '+field)
                    reproduced[split]=dict(status='pass',n_rows=len(rows),methods=sorted(old[0]['decisions']) if old else [])
                if split=='cal':
                    for method,policy in policies.items():
                        added=measurements[split]['system_query'][method]['true']['weighted']['reject']-policy['base_true_reject']
                        if abs(added-policy['added_true_reject_weight'])>1e-12 or added>policy['delta']+1e-12:raise ValueError('calibration full-weight replay differs')
                freeze.rows_once(out/'predictions'/domain/regime/(split+'.jsonl.gz'),rows)
            required=[f+'/'+str(k) for f in ('F1','F2') if regime=='mixed' or f!=regime[:2] for k in (1,2)]
            report=dict(metrics=measurements,calibration=calibration,baseline_reproduction=reproduced,
                        retention=judge(measurements['eval'],policies,rho,required))
            freeze.save(out/'report'/domain/(regime+'.json'),report);reports[domain+'/'+regime]=report
        print('completed',regime,flush=True)
    freeze.save(out/'raw_sources.json',raw_sources)
    summary=dict(status='complete',meaning='development_confirmation_not_blind_test',rho=rho_fit,
        additional_status='skipped_structural_zero' if rho==0 else 'complete',
        additional_task_statuses=None if additional is None else additional[2]['jobs'],
        retention={name:r['retention'] for name,r in reports.items()},
        overall_retention='retained' if rho>0 and all(r['retention']['status']=='retained' for r in reports.values()) else
                          'not_retained' if rho==0 or any(r['retention']['status']=='not_retained' for r in reports.values()) else 'insufficient')
    freeze.save(out/'summary.json',summary);freeze.save(out/'run.complete.json',dict(status='complete',overall_retention=summary['overall_retention']))
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('fit','evaluate'))
    parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    args=parser.parse_args(argv);(fit if args.stage=='fit' else evaluate)(args.config,args.out)


if __name__=='__main__':main()
