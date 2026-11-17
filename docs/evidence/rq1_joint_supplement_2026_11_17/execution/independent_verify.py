"""Independent source-based verification; no production calibration/metric imports."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path

METHODS = ('Count', 'Cond', 'Group', 'Joint')
ADDED = METHODS[2:]
REGIMES = ('mixed', 'F1_only', 'F2_only')
TOL = 1e-10


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def ep(r):
    return r['job_id'], r['id'], r['epoch']


def primary(r, truth):
    if not r['query_present'] or r['newborn'] or r['query_truth'] != truth:
        return False
    return r['kind'] == 'clean' if truth else r['kind'] == 'attack' and r['attack_role'] == 'target'


def weights(rs, truth):
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in rs:
        layer = (r['family'], r['attack_k']) if truth == 0 else ('clean', 0)
        tree[layer][r['parent']][ep(r)].add(r['index'])
    result = []
    for r in rs:
        layer = (r['family'], r['attack_k']) if truth == 0 else ('clean', 0)
        parents = tree[layer]
        epochs = parents[r['parent']]
        result.append(1 / len(tree) / len(parents) / len(epochs) / len(epochs[ep(r)]))
    assert not result or abs(math.fsum(result) - 1) < TOL
    return result


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def eligible(r):
    return (r['query_present'] and not r['newborn'] and r['finite']
            and r.get('error') is None and r['method_status']['Count']['status'] in ('ok', 'reference')
            and finite(r['scores']['Count']) and r['reject_eligible']
            and r['decisions']['Count'] != 'reject')


def fit_threshold(clean, method):
    ww = weights(clean, 1)
    base = math.fsum(w for r, w in zip(clean, ww) if r['decisions']['Count'] == 'reject')
    delta = min(.02, max(0., .05 - base))
    result = dict(base_true_reject=base, delta=delta, tau=None,
                  added_true_reject_weight=0., enabled=False)
    pool = [(r['review_scores'][method], w) for r, w in zip(clean, ww) if eligible(r)]
    if not clean or delta == 0 or any(not finite(v) for v, _ in pool):
        return result
    mass = defaultdict(list)
    for value, w in pool:
        if method == 'BaseTail' or value > 0:
            mass[value].append(w)
    if not mass:
        return result
    remaining = math.fsum(w for values in mass.values() for w in values)
    for value in sorted(mass):
        remaining -= math.fsum(mass[value])
        if remaining <= delta + 1e-12:
            result.update(tau=value, enabled=True,
                          added_true_reject_weight=math.fsum(w for v, w in pool if v > value))
            return result
    raise AssertionError('maximum candidate must have zero strict tail')


def decision(r, method, policy):
    base = r['decisions']['Count']
    if base == 'reject' or not eligible(r) or not policy['enabled']:
        return base
    value = r['review_scores'][method]
    return 'reject' if finite(value) and value > policy['tau'] else base


def six(rs):
    result = {m: {} for m in METHODS}
    for truth, name in ((1, 'true'), (0, 'false')):
        subset = [r for r in rs if primary(r, truth)]
        ww = weights(subset, truth)
        for method in METHODS:
            counts = Counter(r['review_decisions'][method] for r in subset)
            result[method][name] = dict(n=len(subset), parents=len({r['parent'] for r in subset}),
                epochs=len({ep(r) for r in subset}),
                counts={d: counts[d] for d in ('accept', 'unknown', 'reject')},
                weighted={d: math.fsum(w for r, w in zip(subset, ww)
                          if r['review_decisions'][method] == d) if subset else None
                          for d in ('accept', 'unknown', 'reject')})
    for method, value in result.items():
        t = value['true']['weighted']['accept']
        f = value['false']['weighted']['reject']
        value['correct_definite'] = (t + f) / 2 if t is not None and f is not None else None
    return result


def paired(rs, method):
    grouped = defaultdict(list)
    for r in rs:
        if primary(r, 1):
            grouped[(r['parent'], *ep(r))].append(r)
    parents = Counter(k[0] for k in grouped)
    never = {'Cond': 0., method: 0.}
    shared = []
    for key, group in grouped.items():
        first = {m: min((r['timestamp'] for r in group if r['review_decisions'][m] == 'accept'),
                        default=None) for m in ('Cond', method)}
        for m in first:
            if first[m] is None:
                never[m] += 1 / len(parents) / parents[key[0]]
        if all(v is not None for v in first.values()):
            shared.append((key[0], first[method] - first['Cond']))
    sp = Counter(p for p, _ in shared)
    ordered = sorted((value, 1 / len(sp) / sp[p]) for p, value in shared)
    cumulative = 0.
    median = None
    for value, w in ordered:
        cumulative += w
        if cumulative >= .5:
            median = value
            break
    return dict(n_primary_true_epochs=len(grouped), n_parents=len(parents),
                candidate_never=never[method] if grouped else None,
                baseline_never=never['Cond'] if grouped else None,
                never_difference=never[method] - never['Cond'] if grouped else None,
                shared_ever_epochs=len(shared), weighted_median_delay_difference_seconds=median)


def metrics(rs):
    family = sorted({(r['family'], r['attack_k']) for r in rs if primary(r, 0)})
    return dict(system_query=six(rs),
        family_k={f'{f}/{k}': six([r for r in rs if (r['family'], r['attack_k']) == (f, k)])
                  for f, k in family},
        by_parent={p: six([r for r in rs if r['parent'] == p]) for p in sorted({r['parent'] for r in rs})},
        first_windows={name: six([r for r in rs if lower <= r['w'] <= upper])
                       for name, lower, upper in (('length_1', 1, 1), ('length_2_to_9', 2, 9), ('length_10', 10, 10))},
        paired_timeliness={m: paired(rs, m) for m in ADDED})


def close(a, b, where, tol=TOL):
    if isinstance(b, float):
        assert a is not None and math.isclose(a, b, rel_tol=tol, abs_tol=tol), (where, a, b)
    else:
        assert a == b, (where, a, b)


def subset(a, b, where):
    if isinstance(b, dict):
        for k, value in b.items():
            assert k in a, (where, 'missing', k)
            subset(a[k], value, str(where)+'/'+str(k))
    else:
        close(a, b, where)


def emission(u, p, groups, rho):
    """Independent implementation in probability space (at most three sources)."""
    assert sorted(i for g in groups for i in g) == list(range(len(u)))
    assert all(g for g in groups) and all(v in (-1, 0, 1) for v in u)
    terms = []
    for group in groups:
        ones = [i for i in group if u[i] == 1]
        zeros = [i for i in group if u[i] == 0]
        independent = math.prod([p[i] for i in ones]+[1-p[i] for i in zeros])
        common = max(0., min((p[i] for i in ones), default=1.)
                            - max((p[i] for i in zeros), default=0.))
        q = (1-rho)*independent + rho*common
        assert q > 0 and math.isfinite(q)
        terms.append(math.log(q))
    return math.fsum(terms)


def events(r, model):
    u, p = [], []
    assert all(v in (-1, 0, 1) for v in r['U'])
    for i, value in enumerate(r['U']):
        x = r['X'][i]
        if x is None or len(x) != 5 or not all(finite(v) for v in x):
            u.append(-1); p.append(None); continue
        c = r['C'][i]
        missing = r['C_missing'][i] or not finite(c)
        xx = list(x) + [0. if missing else c, float(bool(missing))]
        z = model['intercept'] + math.fsum((v-m)/s*b for v,m,s,b in
            zip(xx, model['mean'], model['scale'], model['coef']))
        raw = 1/(1+math.exp(-z)) if z >= 0 else math.exp(z)/(1+math.exp(z))
        u.append(value); p.append(min(1-1e-6, max(1e-6, raw)))
    return u, p


def frame_score(r, model, rho):
    u, p = events(r, model)
    assert sorted(i for g in r['groups'] for i in g) == list(range(len(u)))
    if not r['query_present'] or r['newborn']:
        return dict(Cond=0., Group=0., Joint=0., u=u,nll_ind=None,nll_joint=None,patterns={})
    ind = -math.fsum(math.log1p(-p[i]) for i,v in enumerate(u) if v == 0)
    group = math.fsum(-math.fsum(math.log1p(-p[i]) for i in g if u[i] == 0)
                     / sum(u[i] in (0,1) for i in g)
                     for g in r['groups'] if any(u[i] in (0,1) for i in g))
    plus = [1 if v == 1 else -1 for v in u]
    joint = emission(plus,p,r['groups'],rho)-emission(u,p,r['groups'],rho)
    patterns=Counter()
    for g in r['groups']:
        values=[u[i] for i in g if u[i]>=0]
        if len(values)>1:
            patterns['common_00' if all(v==0 for v in values) else 'common_11' if all(v==1 for v in values) else 'common_mixed']+=1
    return dict(Cond=ind, Group=group, Joint=joint, u=u,
                nll_ind=-emission(u,p,r['groups'],0.),nll_joint=-emission(u,p,r['groups'],rho),patterns=patterns)


def windows_scores(rr, model, rho):
    histories, result = {}, {}
    for r in rr:
        key = r['job_id'], r['id']
        old = histories.get(key, [])
        if old:
            prev = old[-1][0]
            if not (r['index'] == prev['index']+1 and
                    abs(r['timestamp']-prev['timestamp']-.1) <= 1e-6 and
                    r['source_ids'] == prev['source_ids'] and r['epoch'] == prev['epoch']):
                old = []
        now = frame_score(r, model, rho)
        if not r['query_present'] or r['newborn']:
            histories.pop(key,None); window = []
            values = {m:now[m] for m in ('Cond','Group','Joint')}
        else:
            window = (old+[(r,now)])[-10:]
            histories[key] = window
            values = {m:math.fsum(x[m] for _,x in window) for m in ('Cond','Group','Joint')}
        n = len(r['U'])
        opportunity = [any(x['u'][i] >= 0 for _,x in window) for i in range(n)]
        support = [any(x['u'][i] == 1 for _,x in window) for i in range(n)]
        nplus = sum(x['u'].count(1) for _,x in window)
        nminus = sum(x['u'].count(0) for _,x in window)
        values['Count_inputs'] = [nplus,nminus,len(window),sum(opportunity),sum(support)]
        values['accept_eligible'] = bool(sum(opportunity)>=2 and sum(support)>=2 and
                                        r.get('output_present') and r.get('identity_ok'))
        values['reject_eligible'] = bool(sum(opportunity)>=2 and nminus>0)
        values['metadata'] = {k:r[k] for k in ('job_id','key','id','frame','index','timestamp','epoch',
            'source_ids','query_present','newborn','parent','kind','split','family','attack_k',
            'query_truth','attack_role') if k in r}
        values['diagnostics']=dict(n_frames=len(window),nll_ind=now['nll_ind'],nll_joint=now['nll_joint'])
        for pattern in ('common_00','common_11','common_mixed'):
            values['diagnostics'][pattern]=sum(bool(x['patterns'].get(pattern)) for _,x in window)
        assert tuple(r['key']) not in result
        result[tuple(r['key'])] = values
    return result


def verify_rho(config, run):
    source = Path(config['source_scores'])
    index = read(source/'features.complete.json')['folds']
    manifest = read(source/'manifest.json')
    fit_parents = {p for p,role in config['old_parent_splits'].items() if role == 'fit'}
    assert {f['parent'] for f in index} == fit_parents
    records, predictions, source_records = [], [], []
    for fold in index:
        parent = fold['parent']
        bundle = read(source/fold['normal'])
        assert bundle['held_parent'] == parent
        assert set(bundle['train_parents']) == fit_parents-{parent}
        assert set(fold['train_parents']) == fit_parents-{parent}
        model = bundle['models']['D']
        assert set(model['train_parents']) == fit_parents-{parent}
        jobs = [j for j in manifest['jobs'] if j['parent'] == parent and j['kind'] == 'clean']
        assert len(jobs) == 1
        path = Path(jobs[0]['rows_path'])
        source_records.append(dict(parent=parent,normal=str((source/fold['normal']).resolve()),rows_path=str(path)))
        for r in rows(path):
            if primary(r,1):
                u,p = events(r,model)
                if any(v in (0,1) for v in u):
                    records.append(r);predictions.append((u,p,r['groups']))
    actual = read(run/'rho.json')
    if not records:
        assert actual['rho'] is None and actual['status']=='unestimable'
        assert not actual['objectives']
        return dict(rho=None,status='unestimable',n_supervision=0), manifest
    ww = weights(records,1)
    grid = config['rho_grid']
    losses = {str(float(rho)):math.fsum(-w*emission(u,p,g,rho)
              for w,(u,p,g) in zip(ww,predictions)) for rho in grid}
    informative = any(any(sum(u[i] in (0,1) for i in g)>=2 for g in groups)
                      for u,p,groups in predictions)
    # The actual tie rule is absolute tolerance to the smallest objective.
    best = min(losses.values())
    selected = min(r for r in grid if losses[str(float(r))] <= best+1e-12) if informative else 0
    close(actual['rho'],selected,'rho selected')
    for rho in grid:
        found = next(v for k,v in actual['objectives'].items() if float(k)==rho)
        close(found,losses[str(float(rho))],('rho objective',rho))
    for parent in fit_parents:
        indices = [i for i,r in enumerate(records) if r['parent']==parent]
        close(actual['by_parent'][parent]['weight'],math.fsum(ww[i] for i in indices),('rho parent weight',parent))
        for rho in grid:
            expected = math.fsum(-ww[i]*emission(*predictions[i],rho) for i in indices) / math.fsum(ww[i] for i in indices)
            got = next(v for k,v in actual['by_parent'][parent]['objectives'].items() if float(k)==rho)
            close(got,expected,('rho parent loss',parent,rho))
    assert actual['n_rows']==len(records)
    close(actual['weight_sum'],math.fsum(ww),'rho weight sum')
    patterns=Counter();informative_parents=set();informative_epochs=set();n_informative=0
    for parent in fit_parents:
        pp=Counter();count=0
        for r,(u,p,groups) in zip(records,predictions):
            if r['parent']!=parent:continue
            current=Counter()
            for group in groups:
                values=[u[i] for i in group if u[i]>=0]
                if len(values)>1:
                    current['common_00' if all(v==0 for v in values) else 'common_11' if all(v==1 for v in values) else 'common_mixed']+=1
            pp.update(current)
            if current:
                count+=1;informative_parents.add(parent);informative_epochs.add((parent,)+ep(r))
        assert actual['by_parent'][parent]['informative_frames']==count
        assert actual['by_parent'][parent]['patterns']==dict(pp)
        n_informative+=count;patterns.update(pp)
    subset(actual['coverage'],dict(patterns=dict(patterns),informative_frames=n_informative,
        informative_parents=sorted(informative_parents),informative_epochs=len(informative_epochs)),'rho coverage')
    for expected,got in zip(source_records,actual['source_folds']):
        assert got['parent']==expected['parent']
        assert got['normal']['path']==expected['normal']
        assert got['rows_path']['path']==expected['rows_path']
    return dict(rho=selected,n_supervision=len(records),informative=informative,objectives=losses,
                source_folds=source_records), manifest


def source_inventory(config,run):
    """One manifest-level status check; explicit external paths take precedence."""
    result={}
    for split,name in (('cal','source_scores'),('eval','source_report')):
        source=Path(config[name]);manifest=read(source/'manifest.json');counts=Counter()
        for job in manifest['jobs']:
            if job['split']!=split:continue
            path=Path(job.get('rows_path',source/'jobs'/job['job_id']/'rows.jsonl.gz'))
            if path.exists():counts['rows_available']+=1;continue
            status=Path(job.get('status_path',source/'jobs'/job['job_id']/'complete.json'))
            assert read(status)['status']=='UNREALIZABLE',(job['job_id'],'missing rows without unrealizable status',str(status))
            counts['UNREALIZABLE']+=1
        result[split]=dict(counts)
    if (run/'confirmation').exists():
        root=run/'confirmation';manifest=read(root/'manifest.json');complete=read(root/'prepare.complete.json')
        assert manifest['jobs']==config['jobs']
        assert set(complete['jobs'])=={j['job_id'] for j in config['jobs']}
        statuses={}
        for job in manifest['jobs']:
            marker=read(root/'jobs'/job['job_id']/'complete.json')
            assert marker==complete['jobs'][job['job_id']]
            assert marker['status'] in ('COMPLETE','UNREALIZABLE')
            statuses[job['job_id']]=marker['status']
        result['confirmation']=dict(counts=dict(Counter(statuses.values())),tasks=statuses,
                                    resolved_source=str(root.resolve()))
    return result


def transitions(rs,method):
    result = {}
    for truth in (0,1):
        selected = [r for r in rs if primary(r,truth)]
        ww = weights(selected,truth)
        cells = {a+'/'+b:dict(n=0,weighted=0.) for a in ('accept','unknown','reject')
                 for b in ('accept','unknown','reject')}
        for r,w in zip(selected,ww):
            c = cells[r['decisions']['Cond']+'/'+r['decisions'][method]]
            c['n']+=1;c['weighted']+=w
        result[str(truth)] = dict(n=len(selected),from_method='Cond',to_method=method,cells=cells)
    return result


def retention(rs, measure, policies, rho, regime):
    main=measure['system_query'];j=main['Joint'];cond=main['Cond'];g=main['Group']
    time=measure['paired_timeliness']['Joint']
    def maximum(value,limit):return 'insufficient' if value is None else 'pass' if value <= limit+1e-12 else 'fail'
    def minimum(value,limit):return 'insufficient' if value is None else 'pass' if value >= limit-1e-12 else 'fail'
    difference=lambda a,b:None if a is None or b is None else a-b
    gates=dict(true_reject=maximum(j['true']['weighted']['reject'],.05),
        false_accept=maximum(j['false']['weighted']['accept'],.05),
        true_accept_loss=maximum(difference(cond['true']['weighted']['accept'],j['true']['weighted']['accept']),.02),
        never_accept_increase=maximum(time['never_difference'],.02),
        paired_delay=maximum(time['weighted_median_delay_difference_seconds'],.5),
        cd_gain_Cond=minimum(difference(j['correct_definite'],cond['correct_definite']),.01),
        cd_gain_Group=minimum(difference(j['correct_definite'],g['correct_definite']),.01),
        active=minimum(int(policies['Joint']['status']=='active' and rho is not None and rho>0),1),
        changed_primary=minimum(int(any(r['decisions']['Joint']!=r['decisions']['Cond'] for r in rs if primary(r,0) or primary(r,1))),1))
    support={}
    for layer,value in measure['family_k'].items():
        selected=[r for r in rs if primary(r,0) and r['family']+'/'+str(r['attack_k'])==layer]
        support[layer]=dict(parents=len({r['parent'] for r in selected}),entities=len({r['job_id'] for r in selected}))
        gates['false_accept_'+layer]=maximum(value['Joint']['false']['weighted']['accept'],.05)
    required=[f+'/'+str(k) for f in ('F1','F2') if regime=='mixed' or f!=regime[:2] for k in (1,2)]
    for layer in required:
        value=support.get(layer)
        enough=bool(value and min(value.values())>=3)
        gates['coverage_'+layer]=minimum(min(value.values()) if enough else None,3)
    for method in ('Cond','Group'):
        risks=[maximum(main[method]['true']['weighted']['reject'],.05),maximum(main[method]['false']['weighted']['accept'],.05)]
        risks += [maximum(v[method]['false']['weighted']['accept'],.05) for v in measure['family_k'].values()]
        status='fail' if 'fail' in risks else 'insufficient' if 'insufficient' in risks else 'pass'
        gates['control_risk_'+method]=status
    status='not_retained' if 'fail' in gates.values() else 'evidence_insufficient' if 'insufficient' in gates.values() else 'retained'
    return dict(gates=gates,status=status,support=support)


def verify_domain(config, run, domain, regime, split, model, rho, score_cache):
    produced=list(rows(run/'predictions'/domain/regime/(split+'.jsonl.gz')))
    assert len(produced)==len({tuple(r['key']) for r in produced})
    source=Path(config['source_independent'])
    if domain=='additional':
        manifest=read(run/'confirmation/manifest.json')
        base_model=read(Path(config['source_report'])/'models'/(regime+'.json'))['models']['Count']
        base_policy=read(Path(config['source_report'])/'calibration'/(regime+'.json'))['policies']['Count']
        assert manifest['jobs']==config['jobs']
        expected_jobs=set()
        for job in manifest['jobs']:
            marker=read(run/'confirmation/jobs'/job['job_id']/'complete.json')
            assert marker['status'] in ('COMPLETE','UNREALIZABLE')
            allowed=job['kind']=='clean' or regime=='mixed' or job['family']!=regime[:2]
            if allowed and marker['status']=='COMPLETE':expected_jobs.add(job['job_id'])
        assert {r['job_id'] for r in produced}==expected_jobs
    original_rows=list(rows(source/'predictions'/regime/(split+'.jsonl.gz'))) if domain=='existing' else None
    if original_rows is not None:
        old={tuple(r['key']):r for r in original_rows}
        assert set(old)=={tuple(r['key']) for r in produced}
        for r in produced:
            for field,value in old[tuple(r['key'])].items():
                if isinstance(value,dict) and field in ('scores','decisions','method_status','supplement_scores','supplement_status'):
                    for k,v in value.items():assert r[field][k]==v,(domain,regime,split,r['key'],field,k)
                else:assert r[field]==value,(domain,regime,split,r['key'],field)
    calibration=read(run/'calibration'/(regime+'.json'))
    old_policy=read(source/'calibration'/(regime+'.json'))['branches']['Cond']
    assert calibration['Cond']==old_policy
    for jid in {r['job_id'] for r in produced}:
        cache_key=domain,split,jid
        if cache_key not in score_cache:
            if domain=='additional':path=run/'confirmation/jobs'/jid/'rows.jsonl.gz'
            elif split=='eval':path=Path(config['source_report'])/'jobs'/jid/'rows.jsonl.gz'
            else:
                manifest=read(Path(config['source_scores'])/'manifest.json')
                path=Path(next(j['rows_path'] for j in manifest['jobs'] if j['job_id']==jid))
            raw=list(rows(path))
            score_cache[cache_key]=windows_scores(raw,model,rho or 0.)
        lookup=score_cache[cache_key]
        assert set(lookup)=={tuple(r['key']) for r in produced if r['job_id']==jid}
        for r in (r for r in produced if r['job_id']==jid):
            rebuilt=lookup[tuple(r['key'])]
            for field,value in rebuilt['metadata'].items():assert r[field]==value,(r['key'],'raw metadata',field)
            subset(r['joint_diagnostics'],rebuilt['diagnostics'],(r['key'],'diagnostics'))
            for method in ('Cond','Group','Joint'):
                expected=rebuilt[method]
                got=r['scores'][method]
                if got is not None:close(got,expected,(r['key'],method,'arithmetic'),tol=1e-8)
                elif r['finite']:assert method=='Joint' and rho is None,(r['key'],method,'unexpected null')
            if rho==0:
                assert r['scores']['Joint']==r['scores']['Cond']
                assert r['decisions']['Joint']==r['decisions']['Cond']
            if domain=='additional':
                for field in ('Count_inputs','accept_eligible','reject_eligible'):
                    assert r[field]==rebuilt[field],(r['key'],'Count geometry',field)
                score=base_model['intercept']+math.fsum((x-m)/s*b for x,m,s,b in
                    zip(rebuilt['Count_inputs'],base_model['mean'],base_model['scale'],base_model['coef']))
                close(r['scores']['Count'],score,(r['key'],'new Count score'))
                score=r['scores']['Count'];expected='unknown'
                if r['finite'] and score is not None:
                    if r['accept_eligible'] and base_policy['A'] is not None and score>0 and score>=base_policy['A']:expected='accept'
                    elif r['reject_eligible'] and base_policy['R'] is not None and score<0 and score<=base_policy['R']:expected='reject'
                assert r['decisions']['Count']==expected,(r['key'],'new Count decision')
    # Arithmetic tolerance above does not alter any decision comparison below.
    for r in produced:
        r['review_scores']={m:r['scores'][m] for m in ADDED}
        r['review_decisions']={m:r['decisions'][m] for m in METHODS}
        for method in ADDED:
            policy=calibration['branches'][method]
            expect=decision(r,method,dict(policy,enabled=policy['status']=='active'))
            assert r['decisions'][method]==expect,(domain,regime,split,r['key'],method,'strict decision')
        if domain=='additional':
            r['review_scores']['Cond']=r['scores']['Cond']
            expect=decision(r,'Cond',dict(old_policy,enabled=old_policy['status']=='active'))
            assert r['decisions']['Cond']==expect,(r['key'],'new Cond decision')
    if split=='cal':
        clean=[r for r in produced if primary(r,1)]
        for method in ADDED:
            expected=fit_threshold(clean,method);actual=calibration['branches'][method]
            for f in ('tau','base_true_reject','delta','added_true_reject_weight'):
                close(actual[f],expected[f],(regime,method,'calibration',f))
            assert (actual['status']=='active')==expected['enabled']
    measure=metrics(produced)
    report=read(run/'report'/domain/(regime+'.json'))
    actual=report['metrics'][split]
    for part in ('system_query','by_parent','first_windows','paired_timeliness'):
        subset(actual[part],measure[part],(domain,regime,split,part))
    for layer,value in measure['family_k'].items():
        subset(actual['family_k'][layer]['metrics'],value,(domain,regime,split,'family_k',layer))
    for method in ADDED:
        subset(actual['transitions'][method],transitions(produced,method),(domain,regime,split,'transitions',method))
    clean=[r for r in produced if primary(r,1)]
    if clean:
        ww=weights(clean,1)
        if any(not finite(r['joint_diagnostics'][k]) for r in clean for k in ('nll_ind','nll_joint')):
            nll=dict(status='failure',n_rows=len(clean))
        else:
            nll=dict(status='ok',n_rows=len(clean),weight_sum=math.fsum(ww),
                independent=math.fsum(w*r['joint_diagnostics']['nll_ind'] for r,w in zip(clean,ww)),
                joint=math.fsum(w*r['joint_diagnostics']['nll_joint'] for r,w in zip(clean,ww)))
        subset(actual['normal_frame_nll'],nll,(domain,regime,split,'normal_nll'))
    for pattern in ('common_00','common_11','common_mixed'):
        selected=[r for r in produced if r['joint_diagnostics'][pattern]]
        subset(actual['group_patterns'][pattern],dict(n_windows=len(selected),metrics=six(selected)),
               (domain,regime,split,'patterns',pattern))
    verdict=retention(produced,measure,calibration['branches'],rho,regime) if split=='eval' else None
    if verdict:
        close(report['retention']['status'],verdict['status'],(domain,regime,'retention'))
        for gate,status in verdict['gates'].items():
            close(report['retention']['checks'][gate]['status'],status,(domain,regime,gate))
    return dict(n_all=len(produced),system_query=measure['system_query'],independent_verdict=verdict)


def self_check():
    u,p,g=[0,0],[.7,.7],[[0,1]]
    close(emission(u,p,g,0),math.log(.09),'independent emission')
    close(emission([-1,-1],p,g,.5),0.,'unknown marginal')
    close(emission([1,0],p,g,.5),math.log(.105),'mixed emission')
    close(emission([1,-1],p,g,.5),math.log(.7),'report marginal')
    assert emission(u,p,g,.5)>emission(u,p,g,0)
    # Strict comparisons are not softened by the arithmetic comparison tolerance.
    r=dict(query_present=True,newborn=False,finite=True,error=None,reject_eligible=True,
           scores={'Count':1.},method_status={'Count':{'status':'ok'}},decisions={'Count':'unknown'},
           review_scores={'Joint':1.})
    policy=dict(enabled=True,tau=1.)
    assert decision(r,'Joint',policy)=='unknown'
    r['review_scores']['Joint']=1.+2.**-52
    assert decision(r,'Joint',policy)=='reject'


def verify(config_path,run):
    config=read(config_path);run=Path(run)
    proof,manifest=verify_rho(config,run)
    proof['source_inventory']=source_inventory(config,run)
    proof['rho_artifact_source']=str((run/'rho.json').resolve())
    if proof['rho'] is None:
        assert not (run/'confirmation').exists()
        proof.update(status='unestimable_verified',meaning='not_a_successful_joint_experiment')
        with (run/'independent_verify.json').open('x') as stream:json.dump(proof,stream,indent=2)
        return
    model=read(config['source_normal_models'])['models']['D']
    rho=proof['rho'];proof['domains']={};cache={}
    domains=['existing']
    if rho>0:domains.append('additional')
    else:assert not (run/'confirmation').exists(), 'rho0 must not start confirmation frontend'
    for domain in domains:
        proof['domains'][domain]={}
        for regime in REGIMES:
            splits=('cal','eval') if domain=='existing' else ('eval',)
            proof['domains'][domain][regime]={split:verify_domain(config,run,domain,regime,split,model,rho,cache)
                                             for split in splits}
            print('independently verified',domain,regime,flush=True)
    summary=read(run/'summary.json')
    assert summary['rho']==read(run/'rho.json')
    if rho>0:
        actual=summary['additional_task_statuses']
        expected=proof['source_inventory']['confirmation']['tasks']
        # Production stores complete terminal records to retain constructability details.
        assert set(actual)==set(expected)
        assert {k:(v['status'] if isinstance(v,dict) else v) for k,v in actual.items()}==expected
    statuses=[]
    for domain in domains:
        for regime in REGIMES:
            status=proof['domains'][domain][regime]['eval']['independent_verdict']['status']
            statuses.append(status)
            close(summary['retention'][domain+'/'+regime]['status'],status,('summary',domain,regime))
    expected='retained' if rho>0 and all(s=='retained' for s in statuses) else 'not_retained' if rho==0 or 'not_retained' in statuses else 'insufficient'
    close(summary['overall_retention'],expected,'summary overall retention')
    close(read(run/'run.complete.json')['overall_retention'],expected,'completion retention')
    proof.update(status='passed',implementation='stdlib_only_no_production_fit_score_calibration_metrics_imports',
                 arithmetic_tolerance=1e-8,decision_comparison='strict_saved_score_gt_saved_tau_no_epsilon')
    target=run/'independent_verify.json'
    with target.open('x') as stream:json.dump(proof,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print('independent verification passed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--run',type=Path)
    args=parser.parse_args();self_check()
    if args.self_check:print('independent synthetic checks passed; no real fitting or scoring performed')
    else:
        if args.config is None or args.run is None:parser.error('--config and --run required')
        verify(args.config,args.run)
