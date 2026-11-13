#!/usr/bin/env python3
"""Independent frozen-protocol recount. Python stdlib only; no production imports.

Run only after the parent confirms report.complete. This audits saved scores,
fixed calibration thresholds and reported statistics, not feature/model validity.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

METHODS = ('D_head', 'T_head', 'I_Jmargin', 'J', 'G', 'Q', 'MATE_policy')
STATES = ('accept', 'reject', 'unknown')
REGIMES = {
    'mixed': {'fit': ('F1','F2'), 'cal': ('F0','F1','F2'), 'eval': ('F0','F1','F2')},
    'F1_only': {'fit': ('F1',), 'cal': ('F1',), 'eval': ('F2',)},
    'F2_only': {'fit': ('F2',), 'cal': ('F2',), 'eval': ('F1',)},
}
TOL = 1e-10


def read_json(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def read_lines(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        rows = []
        for line in stream:
            if line.strip():
                row = json.loads(line)
                for large in ('method_status','contributions','sources'):
                    row.pop(large, None)
                rows.append(row)
        return rows


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def epoch(row):
    # job_id prevents accidental fusion of repeated replay backgrounds.
    return (row['parent'], row['job_id'], str(row['id']), str(row['epoch']))


def identity(row):
    return epoch(row) + (row['index'],)


def cell(row):
    return '%s/k%s' % (row['family'], row['attack_k'])


def primary_class(row):
    if not row['query_present'] or row['newborn']:
        return None
    if row['kind'] == 'clean' and row['query_truth'] == 1:
        return 'true'
    if row['kind'] == 'attack' and row['attack_role'] == 'target' and row['query_truth'] == 0:
        return 'false'
    return None


def selected(row, regime, split):
    return row['kind'] == 'clean' or row['family'] in REGIMES[regime][split]


def weights(rows, false=False):
    """Class-conditional mass 1; false family/k -> parent -> epoch -> scan."""
    groups = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for i, row in enumerate(rows):
        groups[cell(row) if false else 'all'][row['parent']][epoch(row)].append(i)
    result = [0.0] * len(rows)
    for parents in groups.values():
        for epochs in parents.values():
            for indices in epochs.values():
                value = 1.0 / (len(groups) * len(parents) * len(epochs) * len(indices))
                for i in indices:
                    result[i] = value
    if rows:
        assert abs(math.fsum(result) - 1.0) < TOL
    return result


def class_summary(rows, method, false=False):
    raw = Counter(row['_decision'][method] for row in rows)
    mass = weights(rows, false)
    return {'n': len(rows), 'counts': {s: raw[s] for s in STATES},
            'raw': {s:raw[s]/len(rows) if rows else None for s in STATES},
            'weighted': {s: math.fsum(w for row,w in zip(rows,mass)
                                     if row['_decision'][method] == s) if rows else None
                         for s in STATES},
            'parents': len({r['parent'] for r in rows}),
            'query_epochs': len({epoch(r) for r in rows}),
            'injected_entities': len({r['job_id'] for r in rows}) if false else None}


def summary(rows, method):
    tr = [r for r in rows if primary_class(r) == 'true']
    fa = [r for r in rows if primary_class(r) == 'false']
    result = {'true': class_summary(tr, method), 'false': class_summary(fa, method, True)}
    ta, fr = result['true']['weighted']['accept'], result['false']['weighted']['reject']
    result['correct_definite'] = (ta + fr) / 2 if ta is not None and fr is not None else None
    result['family_k'] = {}
    for family in ('F0','F1','F2','F3'):
        for k in (1,2,3):
            key = '%s/k%s' % (family,k)
            result['family_k'][key] = class_summary([r for r in fa if cell(r) == key], method, True)
    return result


def weighted_median(pairs):
    if not pairs:
        return None
    cumulative = 0.0
    total = math.fsum(w for _,w in pairs)
    for value, weight in sorted(pairs):
        cumulative += weight / total
        if cumulative >= .5 - 1e-15:
            return value
    return sorted(pairs)[-1][0]


def timing(rows):
    epochs = defaultdict(list)
    for row in rows:
        if primary_class(row) == 'true':
            epochs[epoch(row)].append(row)
    parents = defaultdict(list)
    for key in epochs:
        parents[key[0]].append(key)
    never = {m: 0.0 for m in METHODS}
    first = {}
    for key, values in epochs.items():
        origin = min(float(r['timestamp']) for r in values)
        first[key] = {}
        for method in METHODS:
            adopted = [float(r['timestamp']) for r in values if r['_decision'][method] == 'accept']
            first[key][method] = min(adopted) - origin if adopted else None
            if not adopted:
                never[method] += 1 / (len(parents) * len(parents[key[0]]))
    common = [key for key in epochs if first[key]['J'] is not None and first[key]['MATE_policy'] is not None]
    common_parents = Counter(key[0] for key in common)
    pairs = [(first[key]['J'] - first[key]['MATE_policy'],
              1 / (len(common_parents) * common_parents[key[0]])) for key in common]
    return {'true_query_epochs': len(epochs), 'parents': len(parents),
            'never_adopted': never if epochs else {m: None for m in METHODS},
            'never_adopted_J_minus_MATE': never['J']-never['MATE_policy'] if epochs else None,
            'shared_ever_adopted_epochs': len(common), 'shared_parents': len(common_parents),
            'paired_first_adoption_delay_weighted_median_seconds': weighted_median(pairs),
            'shared_epoch_delay_differences': [dict(parent=k[0], job_id=k[1], id=k[2], epoch=k[3],
                                                  difference=first[k]['J']-first[k]['MATE_policy']) for k in common]}


def thresholds(calibration, method):
    # These alternatives cover data schemas only; no threshold selection is done.
    block = calibration['policies'][method]
    return block['A'], block['R']


def decide(row, method, calibration):
    score = row['scores'][method]
    finite_flag = row['finite'][method] if isinstance(row['finite'],dict) else row['finite']
    if not finite_flag or score is None or not math.isfinite(score):
        return 'unknown'
    if not row['query_present'] or row['newborn']:
        return 'unknown'
    positive, negative = thresholds(calibration, method)
    if positive is not None and row['accept_eligible'] and score >= positive:
        return 'accept'
    if negative is not None and row['reject_eligible'] and score <= negative:
        return 'reject'
    return 'unknown'


def compare_number(actual, expected, path, errors):
    if isinstance(actual,(list,tuple)) and isinstance(expected,(list,tuple)):
        if len(actual)!=len(expected):
            errors.append({'path':path,'independent':actual,'reported':expected})
        else:
            for j,(a,b) in enumerate(zip(actual,expected)):
                compare_number(a,b,path+'.'+str(j),errors)
        return
    if actual is None or expected is None:
        if actual != expected:
            errors.append({'path': path, 'independent': actual, 'reported': expected})
    elif isinstance(actual,(int,float)) and isinstance(expected,(int,float)):
        if abs(actual-expected) > TOL:
            errors.append({'path': path, 'independent': actual, 'reported': expected})
    elif actual != expected:
        errors.append({'path': path, 'independent': actual, 'reported': expected})


def compare_summary(actual, reported, path, errors):
    for cls in ('true','false'):
        compare_number(actual[cls]['n'], reported[cls]['n'], path+'.'+cls+'.n', errors)
        for form in ('counts','raw','weighted'):
            for state in STATES:
                compare_number(actual[cls][form][state], reported[cls][form][state],
                               path+'.'+cls+'.'+form+'.'+state, errors)
        compare_number(actual[cls]['parents'],reported[cls]['parents'],path+'.'+cls+'.parents',errors)
        compare_number(actual[cls]['query_epochs'],reported[cls]['epochs'],path+'.'+cls+'.epochs',errors)
    compare_number(actual['correct_definite'], reported['correct_definite'],path+'.correct_definite', errors)


def check_le(value, bound):
    return {'value':value, 'bound':bound, 'status': 'untested' if value is None else
            ('pass' if value <= bound+1e-12 else 'fail')}


def check_ge(value, bound):
    return {'value':value, 'bound':bound, 'status': 'untested' if value is None else
            ('pass' if value >= bound-1e-12 else 'fail')}


def difference(a,b):
    return a-b if a is not None and b is not None else None


def numeric_gates(methods, time):
    j = methods['J']
    cd = lambda m: methods[m]['correct_definite']
    result = {'CD_J_minus_'+m: check_ge(difference(cd('J'),cd(m)), .01 if m in ('I_Jmargin','G','Q') else 0)
              for m in ('I_Jmargin','G','Q','D_head','T_head')}
    result['TA_MATE_minus_TA_J'] = check_le(difference(methods['MATE_policy']['true']['weighted']['accept'],j['true']['weighted']['accept']),.05)
    result['true_reject'] = check_le(j['true']['weighted']['reject'],.05)
    result['false_accept'] = check_le(j['false']['weighted']['accept'],.05)
    for key, value in j['family_k'].items():
        result[key+'/false_accept'] = check_le(value['weighted']['accept'],.05)
        for baseline in ('T_head','MATE_policy'):
            result[key+'/FA_J_minus_'+baseline] = check_le(difference(value['weighted']['accept'],methods[baseline]['family_k'][key]['weighted']['accept']),.02)
    result['never_adopted_J_minus_MATE'] = check_le(time['never_adopted_J_minus_MATE'],.05)
    result['paired_first_adoption_delay_seconds'] = check_le(time['paired_first_adoption_delay_weighted_median_seconds'],.5)
    return result


def transfer_gates(own, mixed, target_family):
    j, i = own['J'], own['I_Jmargin']
    result = {'false_accept':check_le(j['false']['weighted']['accept'],.05),
              'true_reject':check_le(j['true']['weighted']['reject'],.05),
              'CD_J_minus_I':check_ge(difference(j['correct_definite'],i['correct_definite']),0),
              'CD_mixed_minus_transfer':check_le(difference(mixed['J']['correct_definite'],j['correct_definite']),.05),
              'TA_mixed_minus_transfer':check_le(difference(mixed['J']['true']['weighted']['accept'],j['true']['weighted']['accept']),.05),
              'CD_strictly_positive':{'value':j['correct_definite'],'status':'untested' if j['correct_definite'] is None else ('pass' if j['correct_definite']>0 else 'fail')}}
    for key,value in j['family_k'].items():
        if key.startswith(target_family+'/'):
            result[key+'/false_accept'] = check_le(value['weighted']['accept'],.05)
    return result


def audit_score_coverage(out, regime, split, prediction_rows, errors):
    pred = {identity(r):r for r in prediction_rows}
    if len(pred) != len(prediction_rows):
        errors.append({'path':regime+'/'+split,'error':'duplicate prediction identity'})
    files = sorted((out/'scores'/regime/split).glob('*.jsonl.gz'))
    if not files:
        raise ValueError('No saved score files: '+str(out/'scores'/regime/split))
    eligible_count = 0
    matched = 0
    raw_count = 0
    seen = set()
    for path in files:
        for row in read_lines(path):
            raw_count += 1
            if not selected(row,regime,split):
                continue
            eligible_count += 1
            key = identity(row)
            if key in seen:
                errors.append({'path':str(path),'error':'duplicate score identity','identity':key})
            seen.add(key)
            if key not in pred:
                continue
            matched += 1
            for method in METHODS:
                compare_number(pred[key]['scores'][method],row['scores'][method],
                               regime+'/'+split+'/'+str(key)+'/scores/'+method,errors)
            for field in ('query_present','newborn','query_truth','kind','attack_role','parent','family','attack_k','accept_eligible','reject_eligible','timestamp','finite'):
                compare_number(pred[key][field],row[field],regime+'/'+split+'/'+str(key)+'/'+field,errors)
    missing = len(set(pred)-seen)
    if missing:
        errors.append({'path':regime+'/'+split,'error':'predictions absent from saved scores','n':missing})
    return {'score_files':len(files),'raw_score_rows':raw_count,'regime_selected_score_rows':eligible_count,
            'prediction_rows':len(prediction_rows),'matched_prediction_rows':matched,
            'prediction_matched_fraction': matched/len(prediction_rows) if prediction_rows else None,
            'selected_score_prediction_fraction':matched/eligible_count if eligible_count else None,
            'selected_scores_without_predictions':eligible_count-matched}


def interval_coverage(out):
    support = read_json(out/'support.json')
    parents = defaultdict(set)
    for entity in support['entities'].values():
        if entity['distinct_false_query_scans'] > 0:
            parents['%s/k%s'%(entity['family'],entity['attack_k'])].add(entity['parent'])
    cells = {key:{'parents':len(value),'parent_ids':sorted(value),
                  'omission_probability_lower_bound':(1-len(value)/6)**6}
             for key,value in parents.items()}
    insufficient = any(x['omission_probability_lower_bound']>.05 for x in cells.values())
    return {'source':'support.json entity coverage; not an independently refitted interval',
            'cells':cells,'expected_mixed_interval_state': 'interval_support_insufficient' if insufficient else 'requires_saved_interval_review',
            'independent_CI_computed':False}


def fit_audit(out, errors):
    manifest=read_json(out/'manifest.json')
    fit_parents={p for p,s in manifest['parent_splits'].items() if s=='fit'}
    raw=[]
    paths=sorted((out/'features/fit').glob('*.jsonl.gz'))
    for path in paths:
        raw.extend(read_lines(path))
    for r in raw:
        if r['parent'] not in fit_parents or r['split']!='fit':
            errors.append({'path':'features/fit','error':'non-fit parent in OOF features','parent':r['parent']})
    results={}
    for regime in REGIMES:
        saved=read_json(out/'models'/(regime+'.json'))
        data=[r for r in raw if primary_class(r) and selected(r,regime,'fit')]
        true=[r for r in data if primary_class(r)=='true']
        false=[r for r in data if primary_class(r)=='false']
        data=true+false
        mass=[w*.5 for w in weights(true)]+[w*.5 for w in weights(false,True)]
        parents=sorted({r['parent'] for r in data})
        false_cells=sorted({r['family']+'/'+str(r['attack_k']) for r in false})
        prefix='models/'+regime
        compare_number(saved['fit_false'],list(REGIMES[regime]['fit']),prefix+'.fit_false',errors)
        compare_number(len(data),saved['n_supervision'],prefix+'.n_supervision',errors)
        result={'n_supervision':len(data),'true':len(true),'false':len(false),
                'train_parents':parents,'false_cells':false_cells,'heads':{}}
        for method in ('D_head','T_head','I_Jmargin','G'):
            model=saved['models'][method]
            valid=[r for r in data if isinstance(r['features'][method],list)
                   and len(r['features'][method])==6 and all(math.isfinite(v) for v in r['features'][method])]
            compare_number(len(valid),len(data),prefix+'.'+method+'.usable_no_exclusion',errors)
            compare_number(model['n_samples'],len(data),prefix+'.'+method+'.n_samples',errors)
            compare_number(model['train_parents'],parents,prefix+'.'+method+'.train_parents',errors)
            compare_number(model['fit_false'],list(REGIMES[regime]['fit']),prefix+'.'+method+'.fit_false',errors)
            compare_number(model['false_cells'],false_cells,prefix+'.'+method+'.false_cells',errors)
            compare_number(model['class_weight'],[.5,.5],prefix+'.'+method+'.class_weight',errors)
            mean=[math.fsum(w*r['features'][method][j] for r,w in zip(data,mass)) for j in range(6)]
            std=[math.sqrt(math.fsum(w*(r['features'][method][j]-mean[j])**2 for r,w in zip(data,mass))) for j in range(6)]
            constant=[v<=1e-6 for v in std]
            scale=[1.0 if c else v for c,v in zip(constant,std)]
            for field,value in [('mean',mean),('std',std),('scale',scale),('constant',constant)]:
                for j,v in enumerate(value):
                    compare_number(v,model[field][j],prefix+'.'+method+'.'+field+'.'+str(j),errors)
            for j in range(6):
                if constant[j]:compare_number(model['coef'][j],0,prefix+'.'+method+'.constant_coef.'+str(j),errors)
            if any(model['coef'][j]<-TOL for j in (0,1)):
                errors.append({'path':prefix+'.'+method,'error':'coefficient sign constraint violated'})
            cov=saved['method_status'][method]['coverage']
            compare_number(cov['n_supervision'],len(data),prefix+'.'+method+'.coverage.n_supervision',errors)
            compare_number(cov['n_usable'],len(data),prefix+'.'+method+'.coverage.n_usable',errors)
            compare_number(cov['n_excluded'],0,prefix+'.'+method+'.coverage.n_excluded',errors)
            compare_number(cov['expected_parents'],parents,prefix+'.'+method+'.coverage.expected_parents',errors)
            compare_number(cov['usable_parents'],parents,prefix+'.'+method+'.coverage.usable_parents',errors)
            count=Counter(r['parent'] for r in data)
            for parent,n in count.items():
                compare_number(cov['by_parent'][parent]['n_supervision'],n,prefix+'.'+method+'.coverage.'+parent+'.n_supervision',errors)
                compare_number(cov['by_parent'][parent]['n_usable'],n,prefix+'.'+method+'.coverage.'+parent+'.n_usable',errors)
            result['heads'][method]={'mean':mean,'std':std,'scale':scale,'n_usable':len(valid),
                                    'usable_fraction':len(valid)/len(data),'optimizer_ok_saved':model['optimizer_ok']}
        base=saved['models']['I_Jmargin']
        base_scores=[base['intercept']+math.fsum(c*(v-m)/z for c,v,m,z in zip(base['coef'],r['features']['I_Jmargin'],base['mean'],base['scale'])) for r in data]
        for method,values in [('J',[r['delta_T'] for r in data]),('Q',[v*v for v in base_scores])]:
            if not all(v is not None and math.isfinite(v) for v in values):
                errors.append({'path':prefix+'.'+method,'error':'nonfinite fit increment input'})
                continue
            rms=math.sqrt(math.fsum(w*v*v for w,v in zip(mass,values)))
            avg=math.fsum(w*v for w,v in zip(mass,values))
            std=math.sqrt(math.fsum(w*(v-avg)**2 for w,v in zip(mass,values)))
            mod=saved['models'][method]
            compare_number(rms,mod['rms'],prefix+'.'+method+'.rms',errors)
            compare_number(std,mod['std'],prefix+'.'+method+'.std',errors)
            compare_number(mod['coefficient'],mod['coef_std']/rms,prefix+'.'+method+'.coefficient',errors)
            result[method+'_input']={'rms':rms,'std':std,'n_samples':len(values),'optimizer_ok_saved':mod['optimizer_ok']}
        if regime=='mixed':
            cells=defaultdict(set)
            for r in false:cells[r['family']+'/'+str(r['attack_k'])].add(r['parent'])
            ci=saved['coefficient_interval']
            for key,ps in cells.items():
                e=ci['precheck']['cells'][key]
                compare_number(e['n_parents'],len(ps),prefix+'.interval.'+key+'.n_parents',errors)
                compare_number(e['parent_ids'],sorted(ps),prefix+'.interval.'+key+'.parent_ids',errors)
                compare_number(e['missing_probability_lower_bound'],(1-len(ps)/6)**6,prefix+'.interval.'+key+'.omission',errors)
            unsupported=sorted(key for key,ps in cells.items() if (1-len(ps)/6)**6>.05)
            compare_number(sorted(ci['precheck']['unsupported_cells']),unsupported,prefix+'.interval.unsupported_cells',errors)
            if unsupported:
                compare_number(ci['status'],'interval_support_insufficient',prefix+'.interval.status',errors)
                compare_number(ci['performed_repetitions'],0,prefix+'.interval.performed_repetitions',errors)
                compare_number(ci['interval'],None,prefix+'.interval.interval',errors)
            result['interval_precheck']={'unsupported_cells':unsupported,'status':ci['status'],'independent_interval_computed':False}
        results[regime]=result
    folds=[]
    for path in sorted((out/'folds').glob('*/normal.json')):
        normal=read_json(path)
        held=normal['held_parent']
        expected=fit_parents-{held}
        compare_number(normal['train_parents'],sorted(expected),'folds/'+held+'.train_parents',errors)
        for name,model in normal['models'].items():
            if isinstance(model,dict) and 'train_parents' in model:
                compare_number(model['train_parents'],sorted(expected),'folds/'+held+'.'+name+'.train_parents',errors)
        nested=normal['rho_fit']['folds']
        compare_number(sorted(f['parent'] for f in nested),sorted(expected),'folds/'+held+'.rho.validation_parents',errors)
        for fold in nested:
            compare_number(fold['train_parents'],sorted(expected-{fold['parent']}),'folds/'+held+'.rho.'+fold['parent']+'.train_parents',errors)
        folds.append({'held_parent':held,'train_parents':normal['train_parents'],'nested_rho_folds':len(nested)})
    compare_number(sorted(f['held_parent'] for f in folds),sorted(fit_parents),'folds.held_parent_coverage',errors)
    return {'n_feature_files':len(paths),'n_raw_feature_rows':len(raw),'regimes':results,'folds':folds,
            'boundary':'scaler/increment moments reproduced from allowed OOF rows; model optimization not rerun; fold isolation checked from saved metadata'}


def compare_timing(actual, expected, prefix, errors):
    for own,key in [('true_query_epochs','n_primary_true_epochs'),('parents','n_parents'),
                    ('shared_ever_adopted_epochs','shared_ever_epochs'),
                    ('never_adopted_J_minus_MATE','never_difference'),
                    ('paired_first_adoption_delay_weighted_median_seconds','weighted_median_delay_difference_seconds')]:
        compare_number(actual[own],expected[key],prefix+'.'+key,errors)
    for method in ('J','MATE_policy'):
        compare_number(actual['never_adopted'][method],expected[method+'_never'],prefix+'.'+method+'_never',errors)


def self_check():
    def row(parent,ident,index,family='F1',k=1):
        return dict(parent=parent,job_id=parent,id=ident,epoch=0,index=index,family=family,attack_k=k)
    data = [row('a',1,0),row('a',1,1),row('a',2,0),row('b',1,0)]
    assert weights(data) == [.125,.125,.25,.5]
    probe_errors=[]
    compare_number([.5000000000000001,.5],[.5,.5],'class_weight',probe_errors)
    assert not probe_errors
    compare_number([.500001,.5],[.5,.5],'class_weight',probe_errors)
    assert len(probe_errors)==1
    data += [row('a',3,0,'F2',2)]
    assert weights(data,True) == [.0625,.0625,.125,.25,.5]
    assert weighted_median([(1,.5),(2,.5)]) == 1
    assert check_le(None,.05)['status']=='untested'
    assert check_ge(.009,.01)['status']=='fail'
    calibration = {'policies':{m:{'A':1.0,'R':-1.0} for m in METHODS}}
    probe = dict(row('a',1,0), query_present=True, newborn=False, kind='clean',
                 query_truth=1, attack_role=None, timestamp=0.0, accept_eligible=True,
                 reject_eligible=True, scores={m:2.0 for m in METHODS}, finite=True)
    assert primary_class(probe)=='true'
    assert decide(probe,'J',calibration)=='accept'
    probe['newborn']=True
    assert primary_class(probe) is None and decide(probe,'J',calibration)=='unknown'
    probe['newborn']=False
    probe['kind']='attack'
    probe['query_truth']=0
    probe['attack_role']='target'
    assert primary_class(probe)=='false'
    probe['attack_role']='background'
    assert primary_class(probe) is None
    def timing_row(parent,ident,index,timestamp,j,mate):
        r = dict(row(parent,ident,index),kind='clean',query_present=True,newborn=False,
                 query_truth=1,attack_role=None,timestamp=timestamp)
        r['_decision'] = {m:'unknown' for m in METHODS}
        r['_decision']['J']=j
        r['_decision']['MATE_policy']=mate
        return r
    example = [timing_row('a',1,0,0,'unknown','accept'),
               timing_row('a',1,1,.4,'accept','unknown'),
               timing_row('a',2,0,0,'unknown','accept'),
               timing_row('b',1,0,0,'accept','accept')]
    t=timing(example)
    assert t['never_adopted_J_minus_MATE']==.25
    assert t['paired_first_adoption_delay_weighted_median_seconds']==0
    assert t['shared_ever_adopted_epochs']==2
    print('SELF_CHECK_PASS: hierarchical weighting, primary denominator, fixed policies, paired timing, median and gate boundaries')


def run(args):
    out = args.out.resolve()
    if not (out/'report.complete.json').exists() and not (out/'report.complete').exists():
        raise ValueError('report.complete absent; parent must confirm completion before run')
    metrics_path = out/'report/metrics.json'
    reported = read_json(metrics_path)
    manifest = read_json(out/'manifest.json')
    parent_splits = manifest['parent_splits']
    errors = []
    report = {'schema':'independent_rq1_score_recount_v1','independence':{
        'stdlib_only':True,'production_statistics_imported_or_read':False,
        'thresholds_reselected':False,'models_or_attacks_run':False,
        'independent_unit':'parent recording; query epochs and timestamps are nested measurements',
        'not_verified':['normal/model fitting correctness','feature causality','optimizer convergence beyond saved diagnostics','full-model uncertainty']},
        'inputs':{'metrics_path':str(metrics_path),'metrics_sha256':digest(metrics_path),
                  'script_sha256':digest(__file__)},'regimes':{}}
    all_rows = {}
    for regime in REGIMES:
        calibration_path = out/'calibration'/(''+regime+'.json')
        calibration = read_json(calibration_path)
        for method in METHODS:
            a,r = thresholds(calibration,method)
            if a is not None and a <= 0:
                errors.append({'path':str(calibration_path)+'/'+method,'error':'A must be positive'})
            if r is not None and r >= 0:
                errors.append({'path':str(calibration_path)+'/'+method,'error':'R must be negative'})
        compare_number(calibration['cal_false'],list(REGIMES[regime]['cal']),regime+'.cal_false',errors)
        regime_result = {'calibration_sha256':digest(calibration_path),'splits':{}}
        for split in ('cal','eval'):
            path = out/'report/predictions'/regime/(split+'.jsonl.gz')
            rows = read_lines(path)
            all_rows[regime,split] = rows
            illegal_families = Counter()
            mismatch = Counter()
            for row in rows:
                if parent_splits[row['parent']] != split:
                    errors.append({'path':str(path),'error':'parent split violation','parent':row['parent']})
                if not selected(row,regime,split):
                    illegal_families[row['family']] += 1
                row['_decision'] = {method:decide(row,method,calibration) for method in METHODS}
                for method in METHODS:
                    if row['_decision'][method] != row['decisions'][method]:
                        mismatch[method] += 1
            if illegal_families:
                errors.append({'path':str(path),'error':'regime family isolation violation','families':dict(illegal_families)})
            if mismatch:
                errors.append({'path':str(path),'error':'fixed-threshold decision mismatch','by_method':dict(mismatch)})
            methods = {method:summary(rows,method) for method in METHODS}
            for method, actual in methods.items():
                expected = reported['regimes'][regime]['metrics'][split]['system_query'][method]
                compare_summary(actual,expected,regime+'.'+split+'.system_query.'+method,errors)
            for key,layer in reported['regimes'][regime]['metrics'][split]['family_k'].items():
                own_key=key.replace('/','/k')
                for method in METHODS:
                    actual=methods[method]['family_k'][own_key]
                    exp=layer['metrics'][method]['false']
                    compare_number(actual['n'],exp['n'],regime+'.'+split+'.'+key+'.'+method+'.n',errors)
                    for form in ('counts','raw','weighted'):
                        for state in STATES:
                            compare_number(actual[form][state],exp[form][state],regime+'.'+split+'.'+key+'.'+method+'.'+form+'.'+state,errors)
            class_counts = Counter(primary_class(r) or 'excluded' for r in rows)
            family_cells = {key:dict(n=value['n'],parents=value['parents'],query_epochs=value['query_epochs'],injected_entities=value['injected_entities'])
                            for key,value in methods['J']['family_k'].items()}
            regime_result['splits'][split] = {'prediction_sha256':digest(path),'n_rows':len(rows),
                 'primary_class_counts':dict(class_counts),'family_k_coverage':family_cells,
                 'decision_mismatch_counts':dict(mismatch),'methods':methods,'timing':timing(rows),
                 'score_coverage':audit_score_coverage(out,regime,split,rows,errors)}
            st=regime_result['splits'][split]
            compare_timing(st['timing'],reported['regimes'][regime]['metrics'][split]['paired_timeliness'],regime+'.'+split+'.timing',errors)
            if split=='cal':
                compare_number(sorted({r['parent'] for r in rows}),calibration['cal_parents'],regime+'.cal_parents',errors)
                compare_number(sorted({r['job_id'] for r in rows}),calibration['cal_job_ids'],regime+'.cal_job_ids',errors)
        report['regimes'][regime] = regime_result
    mixed_eval = report['regimes']['mixed']['splits']['eval']
    report['main_numeric_gates'] = numeric_gates(mixed_eval['methods'],mixed_eval['timing'])
    check_map={'true_reject':'true_reject_rate','false_accept':'false_accept_rate',
               'paired_first_adoption_delay_seconds':'paired_first_adoption_delay'}
    saved_checks=reported['regimes']['mixed']['retention']['checks']
    for key,value in report['main_numeric_gates'].items():
        if value['value'] is None:
            continue
        skey=check_map.get(key,key)
        if '/false_accept' in key:
            skey=key.replace('/k','/').replace('/false_accept','_FA_J')
        elif '/FA_J_minus_' in key:
            skey=key.replace('/k','/').replace('/FA_J_minus_','_FA_J_minus_')
        compare_number(value['value'],saved_checks[skey]['value'],'mixed.retention.'+skey+'.value',errors)
        compare_number(value['status'],saved_checks[skey]['status'],'mixed.retention.'+skey+'.status',errors)
    report['transfer_gates'] = {}
    for regime,target in (('F1_only','F2'),('F2_only','F1')):
        own = report['regimes'][regime]['splits']['eval']['methods']
        matched = [r for r in all_rows['mixed','eval'] if r['kind']=='clean' or r['family']==target]
        mixed_methods = {m:summary(matched,m) for m in METHODS}
        report['transfer_gates'][regime] = {'same_target_mixed':mixed_methods,
                                         'gates':transfer_gates(own,mixed_methods,target)}
        saved=reported['regimes'][regime]['retention']['checks']
        mapping={'false_accept':'false_accept_global','CD_strictly_positive':'CD_J_strictly_positive'}
        for key,value in report['transfer_gates'][regime]['gates'].items():
            if value['value'] is None:
                continue
            skey=mapping.get(key,key).replace('/k','/').replace('/false_accept','_false_accept')
            compare_number(value['value'],saved[skey]['value'],regime+'.retention.'+skey+'.value',errors)
            compare_number(value['status'],saved[skey]['status'],regime+'.retention.'+skey+'.status',errors)
        for method in METHODS:
            compare_summary(mixed_methods[method],reported['regimes']['mixed']['target_family_metrics'][target][method],
                            regime+'.same_target_mixed.'+method,errors)
    report['coefficient_interval_coverage'] = interval_coverage(out)
    report['fit_isolation_and_scaler_audit'] = fit_audit(out,errors)
    report['errors'] = errors
    report['statistical_recount_status'] = 'PASS' if not errors else 'FAIL'
    destination = args.destination.resolve()
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'recount.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines = ['# 独立结果重计','', '统计重计 '+report['statistical_recount_status']+'，差异 '+str(len(errors))+' 项。', '',
             '本次仅用标准库，独立重建分级权重、固定门限判决、真假六格、family/k风险及配对epoch时效。未读取生产统计实现，未重新选门限、拟合模型或生成攻击。', '',
             '## 主评价', '', '|方法|真采纳|真拒绝|真未知|假采纳|假拒绝|假未知|正确明确率|', '|---|---:|---:|---:|---:|---:|---:|---:|']
    pct = lambda x:'未测' if x is None else '%.4f%%'%(100*x)
    for m,v in mixed_eval['methods'].items():
        values = [v['true']['weighted'][s] for s in STATES]+[v['false']['weighted'][s] for s in STATES]+[v['correct_definite']]
        lines.append('|'+m+'|'+'|'.join(pct(v) for v in values)+'|')
    lines += ['', '## 判据', '']
    for key,value in report['main_numeric_gates'].items():
        lines.append('- '+key+' '+value['status']+'，数值 '+str(value['value'])+'，门槛 '+str(value['bound']))
    lines += ['', '## 两向族迁移', '']
    for regime,info in report['transfer_gates'].items():
        lines.append('- '+regime)
        for key,value in info['gates'].items():
            if value['status']!='untested':
                lines.append('  - '+key+' '+value['status']+'，数值 '+str(value['value']))
    lines += ['', '## 研究判断', '',
              '联合项不能保留。除c区间支持不足外，还须按上述实际CD增益判断。双向迁移也应按实际失败项处理，不能把所有失败归为区间缺失。', '',
              '## 覆盖与证据边界','',
              '父录制是独立单位。注入实体不是query epoch，中央轨迹碎裂不增加独立攻击实体。窗口与重复时刻也不增加独立样本。', '',
              '联合系数区间覆盖预检查 '+report['coefficient_interval_coverage']['expected_mixed_interval_state']+'。本次不独立重拟合区间，不能用经验低风险替代总体风险保证。', '',
              'source-only的头标准化与增量缩放已用排除目标族和F0的折外特征独立重计，并与保存参数一致核对。正常模型外层及rho内层的父隔离已核对保存元数据。这些检查不等于重跑优化器或证明所有在线特征的因果合法性。', '']
    for regime,r in report['regimes'].items():
        for split,s in r['splits'].items():
            c=s['score_coverage']
            lines.append('- '+regime+'/'+split+'，预测 '+str(c['prediction_rows'])+'，已匹配原评分 '+str(c['matched_prediction_rows'])+'，预测匹配率 '+str(c['prediction_matched_fraction'])+'，方案所选评分覆盖率 '+str(c['selected_score_prediction_fraction']))
    lines += ['', '两种族迁移方向须分别判定。其通过只能排除部分族特有规律，不能证明一般真实性。旧开发父录制已被反复查看，本批不能称未见终测。', '', '完整率差、逐层分母、原始计数及差异见recount.json。']
    (destination/'result_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['statistical_recount_status'],'differences':len(errors),'output':str(destination/'recount.json')}))
    return 0 if not errors else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parent.parent/'run_001')
    parser.add_argument('--destination',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--self-check',action='store_true')
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
