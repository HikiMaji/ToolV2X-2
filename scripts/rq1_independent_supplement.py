"""One frozen, label-free online supplement to saved Count decisions."""
import argparse
from collections import Counter
import math
from pathlib import Path

import numpy as np
from scripts.rq1_temporal import data, run as original
from scripts.rq1_score_revision import run as legacy, no_miss_constant as zero
from scripts.rq1_report_freeze import run as freeze

BRANCHES=('Cond','MissCount','BaseTail')
METHODS=('Count','D_zero')+BRANCHES
REGIMES=('mixed','F1_only','F2_only')
ROOT=Path('/root/autodl-tmp/ToolV2X')
DEFAULT_SOURCE=ROOT/'docs/evidence/rq1_report_freeze_2026_11_13/run_001'
DEFAULT_SPEC=Path(__file__).resolve().parents[1]/'docs/REALLY_MAYBE/rq1_independent_supplement_2026_11_16/SDS.md'
DEFAULT_OUT=ROOT/'docs/evidence/rq1_independent_supplement_2026_11_16/run_001'


def finite(value):
    return isinstance(value,(int,float,np.number)) and math.isfinite(value)


def readable(row):
    return (bool(row.get('finite')) and row.get('error') is None and finite(row['scores'].get('Count')) and
            row.get('method_status',{}).get('Count',{}).get('status') in ('ok','reference'))


def eligible(row):
    return (readable(row) and row['decisions']['Count']!='reject' and
            bool(row.get('query_present')) and not row.get('newborn') and bool(row.get('reject_eligible')))


def decide(base,base_readable,query_present,newborn,reject_eligible,score,policy):
    """Inputs deliberately exclude labels, parent, attack identity and family."""
    if base=='reject':
        return dict(decision=base,status='base_reject')
    if not base_readable:
        return dict(decision=base,status='base_failure')
    if policy['status']!='active':
        return dict(decision=base,status='disabled')
    if not finite(score):
        return dict(decision=base,status='degraded')
    changed=query_present and not newborn and reject_eligible and score>policy['tau']
    return dict(decision='reject' if changed else base,status='added_reject' if changed else 'base_preserved')


def join_features(rows,features):
    """Validate structural identity once; numerical score failures remain explicit."""
    by_key={tuple(r['key']):r for r in features}
    if len(by_key)!=len(features) or len({tuple(r['key']) for r in rows})!=len(rows):
        raise ValueError('duplicate prediction/feature key')
    if set(by_key)!={tuple(r['key']) for r in rows}:
        raise ValueError('prediction/feature key coverage mismatch')
    fields=('job_id','frame','id','epoch','parent','split','kind','family','attack_k',
            'attack_role','index','timestamp','query_truth','query_present','newborn',
            'source_ids','finite','accept_eligible','reject_eligible','n_frames','context','n_minus')
    for row in rows:
        key=tuple(row['key']);feature=by_key[key]
        if key!=(row['job_id'],row['frame'],row['id']):
            raise ValueError('malformed prediction key')
        for field in fields:
            if row.get(field)!=feature.get(field):
                raise ValueError('prediction/feature metadata mismatch '+str(key)+' '+field)
        if list(row['context'])!=[row['w'],row['d'],row['m']]:
            raise ValueError('saved window counts differ')
        try:
            counts=freeze.count_inputs(feature)
        except ValueError:
            if row.get('Count_inputs') is not None:
                raise ValueError('Count inputs unavailable in features')
        else:
            if row.get('Count_inputs')!=counts:
                raise ValueError('Count inputs mismatch '+str(key))
        x=feature.get('features',{}).get('D_head')
        cond=-float(x[1]) if x is not None and len(x)==6 and finite(x[1]) else None
        if cond is not None and cond<0:
            cond=None
        minus=feature.get('n_minus')
        miss=float(sum(minus)) if minus is not None and all(finite(v) and v>=0 for v in minus) else None
        if miss==0 and cond not in (None,0.):
            raise ValueError('nonzero conditional evidence without misses')
        base=row['scores'].get('Count')
        row['supplement_scores']=dict(Cond=cond,MissCount=miss,BaseTail=-float(base) if finite(base) else None)
    return rows


def calibrate(rows,method):
    clean=[r for r in rows if original.primary(r,1)]
    w=original.weights(clean,1)
    if clean and not math.isclose(float(w.sum()),1.,abs_tol=1e-12):
        raise ValueError('clean class weights do not sum to one')
    error=sum(float(v) for r,v in zip(clean,w) if r['decisions']['Count']=='reject')
    delta=min(.02,max(0.,.05-error))
    policy=dict(status='disabled',reason=None,tau=None,base_true_reject=error,delta=delta,
                n_clean_primary=len(clean),clean_weight_sum=float(w.sum()),n_eligible=0,
                n_candidates=0,added_true_reject_weight=0.)
    if not clean:
        policy['reason']='no_clean_primary';return policy
    if delta==0:
        policy['reason']='no_remaining_budget';return policy
    candidates=[]
    for r,weight in zip(clean,w):
        if not eligible(r):
            continue
        policy['n_eligible']+=1
        score=r['supplement_scores'][method]
        if not finite(score):
            policy['reason']='candidate_score_failure';return policy
        if method=='BaseTail' or score>0:
            candidates.append((float(score),float(weight)))
    policy['n_candidates']=len(candidates)
    if not candidates:
        policy['reason']='no_candidates';return policy
    masses=Counter()
    for score,weight in candidates:
        masses[score]+=weight
    remaining=sum(masses.values())
    for tau,mass in sorted(masses.items()):
        remaining=max(0.,remaining-mass)
        if remaining<=delta+1e-12:
            policy.update(status='active',reason=None,tau=tau,added_true_reject_weight=remaining)
            break
    return policy


def apply(rows,policies):
    for row in rows:
        row['supplement_status']={}
        for method in BRANCHES:
            score=row['supplement_scores'][method]
            result=decide(row['decisions']['Count'],readable(row),bool(row.get('query_present')),
                          bool(row.get('newborn')),bool(row.get('reject_eligible')),score,policies[method])
            row['scores'][method]=score
            row['decisions'][method]=result['decision']
            row['supplement_status'][method]=result['status']
            row['method_status'][method]=dict(status='ok' if finite(score) else 'numeric_failure',
                                              decision_status=result['status'])
            if result['decision']=='accept' and row['decisions']['Count']!='accept':
                raise AssertionError('supplement expanded acceptance')
            if row['decisions']['Count']=='reject' and result['decision']!='reject':
                raise AssertionError('supplement removed rejection')
    return rows


def metrics(rows,layers,cal_layers):
    tables={m:freeze.table(rows,m) for m in METHODS}
    def cells(mask=None):
        return {m:original.six_cells(t if mask is None else t.subset(mask),'D') for m,t in tables.items()}
    windows=np.asarray([r['w'] for r in rows]);parents=np.asarray([r['parent'] for r in rows],dtype=object)
    families=np.asarray([r['family'] for r in rows],dtype=object);ks=np.asarray([r['attack_k'] for r in rows])
    result=dict(system_query=cells(),coverage=legacy._coverage(rows),family_k={},
                first_windows={name:cells(mask) for name,mask in (
                    ('length_1',windows==1),('length_2_to_9',(windows>=2)&(windows<10)),('length_10',windows==10))},
                by_parent={p:cells(parents==p) for p in sorted(set(parents))},
                paired_timeliness={m:zero._paired(rows,m,'Count') for m in BRANCHES},
                transitions={m:zero._transitions(rows,m,'Count') for m in BRANCHES},
                method_score_coverage={m:freeze.score_coverage(rows,m) for m in METHODS},
                supplement_status={m:dict(Counter(r['supplement_status'][m] for r in rows)) for m in BRANCHES})
    for family,k in sorted(layers):
        mask=(families==family)&(ks==k)
        selected=[r for r,keep in zip(rows,mask) if keep and original.primary(r,0)]
        result['family_k'][family+'/'+str(k)]=dict(family=family,k=k,
            status='observed' if selected else 'not_tested',cal_status='observed' if (family,k) in cal_layers else 'not_calibrated',
            support=dict(rows=len(selected),parents=len({r['parent'] for r in selected}),
                         entities=len({r['job_id'] for r in selected}),epochs=len({original.epoch(r) for r in selected})),
            metrics=cells(mask))
    for truth in (0,1):
        selected=[r for r in rows if original.primary(r,truth)]
        if selected and not math.isclose(float(original.weights(selected,truth).sum()),1.,abs_tol=1e-12):
            raise ValueError('class weight conservation failed')
    return result


def reproduction(actual,expected):
    def same(a,b):
        if isinstance(a,dict):
            return isinstance(b,dict) and set(a)==set(b) and all(same(a[k],b[k]) for k in a)
        if isinstance(a,(float,int)) and isinstance(b,(float,int)):
            return math.isclose(a,b,rel_tol=0.,abs_tol=1e-12)
        return a==b
    result={m:dict(status='pass' if same(actual[m],expected[m]) else 'fail') for m in ('Count','D_zero')}
    if any(v['status']!='pass' for v in result.values()):
        raise ValueError('saved baseline six-cell reproduction failed '+str(result))
    return result


def judge(measurement,policies):
    main=measurement['system_query'];base=main['Count'];verdicts={}
    for method in BRANCHES:
        current=main[method];pair=measurement['paired_timeliness'][method]
        risk=dict(true_reject=legacy._check(current['true']['weighted']['reject'],.05),
                  false_accept=legacy._check(current['false']['weighted']['accept'],.05),
                  true_accept_loss=legacy._check(legacy._difference(base['true']['weighted']['accept'],current['true']['weighted']['accept']),.02),
                  never_accept_increase=legacy._check(pair['never_difference'],.02),
                  paired_delay=legacy._check(pair['weighted_median_delay_difference_seconds'],.5))
        for layer,group in measurement['family_k'].items():
            if group['status']=='observed':
                risk['false_accept_'+layer]=legacy._check(group['metrics'][method]['false']['weighted']['accept'],.05)
        gain=legacy._difference(current['correct_definite'],base['correct_definite'])
        changes=sum(r['n'] for truth in measurement['transitions'][method].values()
                    for key,r in truth['cells'].items() if key.split('/')[0]!=key.split('/')[1])
        checks=dict(risk,cd_gain=legacy._check(gain,.01,'min'),
                    active=legacy._check(int(policies[method]['status']=='active'),1,'min'),
                    changed_primary=legacy._check(changes,1,'min'))
        verdicts[method]=dict(status=legacy._verdict(checks),checks=checks,risk_checks=risk,
                              risk_status=legacy._verdict(risk),cd_gain=gain,n_changed_primary=changes)
    attribution={}
    for control in ('MissCount','BaseTail'):
        difference=legacy._difference(main['Cond']['correct_definite'],main[control]['correct_definite'])
        attribution[control]=dict(cd_difference=difference,control_risk_status=verdicts[control]['risk_status'],
            status='established' if verdicts['Cond']['status']=='retained' and verdicts[control]['risk_status']=='retained'
                   and difference is not None and difference>=.01-1e-12 else 'not_established')
    return dict(branches=verdicts,conditional_increment=dict(status='established' if all(
        v['status']=='established' for v in attribution.values()) else 'not_established',comparisons=attribution))


def run(source,out,spec=DEFAULT_SPEC,resume=False):
    source=Path(source).resolve();out=Path(out).resolve();spec=Path(spec).resolve()
    if source==out or source in out.parents or out in source.parents:
        raise ValueError('source and output overlap')
    if out.exists() and not resume:
        raise FileExistsError('output exists; use --resume only for same frozen rules')
    manifest=freeze.read(source/'manifest.json');config=manifest['config']
    prediction_paths=[source/'predictions'/regime/(split+'.jsonl.gz') for regime in REGIMES for split in ('cal','eval')]
    source_paths=[source/'manifest.json',spec]+prediction_paths+[
        source/folder/(regime+'.json') for regime in REGIMES for folder in ('calibration','report_corrected')]
    binding=dict(schema='rq1_independent_supplement_v1',methods=list(METHODS),regimes=list(REGIMES),
                 sources=[data.source_record(p) for p in source_paths],code=[data.source_record(p) for p in
                 (Path(__file__),Path(original.__file__),Path(legacy.__file__),Path(zero.__file__),Path(freeze.__file__),Path(data.__file__))])
    freeze.save(out/'binding.json',binding)
    frozen=out/'frozen_spec.md'
    if frozen.exists():
        if frozen.read_text()!=spec.read_text():raise ValueError('frozen spec differs')
    else:frozen.write_text(spec.read_text())
    reports={};feature_sources={}
    for regime in REGIMES:
        calibration=freeze.read(source/'calibration'/(regime+'.json'))
        source_report=freeze.read(source/'report_corrected'/(regime+'.json'))
        all_rows={}
        for split in ('cal','eval'):
            rows=list(data.read_rows(source/'predictions'/regime/(split+'.jsonl.gz')))
            feature_root=Path(config['source_features'])/'cal' if split=='cal' else source/'features/eval'
            paths=[feature_root/(jid+'.jsonl.gz') for jid in sorted({r['job_id'] for r in rows})]
            features=[r for p in paths for r in data.read_rows(p)]
            for p in paths:
                if str(p) not in feature_sources:feature_sources[str(p)]=data.source_record(p)
            all_rows[split]=join_features(rows,features)
        policies={m:calibrate(all_rows['cal'],m) for m in BRANCHES}
        freeze.save(out/'calibration'/(regime+'.json'),dict(branches=policies,
            source_calibration_sufficient=calibration['calibration_sufficient'],
            observed_layers=calibration['observed_layers'],missing_layers=calibration['missing_layers']))
        observed={tuple(x) for x in calibration['observed_layers']}
        layers=observed|{tuple(x) for x in calibration['expected_layers']}|{
            (r['family'],r['attack_k']) for rows in all_rows.values() for r in rows if r['kind']=='attack'}
        measurements={};baseline={}
        for split,rows in all_rows.items():
            apply(rows,policies)
            measurements[split]=metrics(rows,layers,observed)
            baseline[split]=reproduction(measurements[split]['system_query'],source_report['metrics'][split]['system_query'])
            if split=='cal':
                for m,p in policies.items():
                    delta=measurements[split]['system_query'][m]['true']['weighted']['reject']-p['base_true_reject']
                    if abs(delta-p['added_true_reject_weight'])>1e-12 or delta>p['delta']+1e-12:
                        raise ValueError('calibration global budget replay mismatch '+m)
            freeze.rows_once(out/'predictions'/regime/(split+'.jsonl.gz'),rows)
        report=dict(metrics=measurements,calibration=policies,baseline_reproduction=baseline,
                    source_calibration_sufficient=calibration['calibration_sufficient'],
                    missing_layers=calibration['missing_layers'],retention=judge(measurements['eval'],policies))
        freeze.save(out/'report'/(regime+'.json'),report);reports[regime]=report
        print('completed',regime,flush=True)
    freeze.save(out/'feature_sources.json',list(feature_sources.values()))
    summary=dict(status='complete',meaning='development_comparison_not_blind_test',regimes={
        r:dict(retention=v['retention'],calibration=v['calibration'],baseline_reproduction=v['baseline_reproduction'],
               system_query={s:m['system_query'] for s,m in v['metrics'].items()},missing_layers=v['missing_layers']) for r,v in reports.items()})
    freeze.save(out/'summary.json',summary)
    freeze.save(out/'run.complete.json',dict(status='complete',meaning='execution_complete_not_scientific_pass',
        regimes={r:{m:v['status'] for m,v in report['retention']['branches'].items()} for r,report in reports.items()}))
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--out',type=Path,default=DEFAULT_OUT)
    parser.add_argument('--spec',type=Path,default=DEFAULT_SPEC)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args(argv)
    run(args.source,args.out,args.spec,args.resume)


if __name__=='__main__':
    main()
