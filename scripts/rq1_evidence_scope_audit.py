"""Read existing predictions/evidence once; never fit, calibrate or change decisions."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rq1_temporal.kernel import windows

SOURCE = Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_report_freeze_2026_11_13/run_001')
REGIMES = ('mixed', 'F1_only', 'F2_only')
FLAGS = ('group_00', 'group_mix', 'group_11', 'joint_possible')


def read(p):
    return json.loads(Path(p).read_text())


def rows(p):
    with gzip.open(p, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def primary(r):
    return (r['query_present'] and not r['newborn'] and
            (r['kind'] == 'clean' and r['query_truth'] == 1 or
             r['kind'] == 'attack' and r['query_truth'] == 0 and r['attack_role'] == 'target'))


def ep(r):
    return (r['job_id'], r['id'], r['epoch'])


def weights(rs):
    buckets = defaultdict(lambda: defaultdict(Counter))
    seen = set()
    for r in rs:
        key = (ep(r), r['index'])
        assert key not in seen, ('duplicate', key)
        seen.add(key)
        layer = (r['family'], r['attack_k']) if r['query_truth'] == 0 else ('clean', 0)
        buckets[layer][r['parent']][ep(r)] += 1
    out = []
    for r in rs:
        layer = (r['family'], r['attack_k']) if r['query_truth'] == 0 else ('clean', 0)
        parents = buckets[layer]; epochs = parents[r['parent']]
        out.append(1 / (len(buckets) * len(parents) * len(epochs) * epochs[ep(r)]))
    assert not out or abs(math.fsum(out) - 1) < 1e-10
    return out


def quantiles(pairs):
    pairs = sorted(pairs)
    total = math.fsum(w for _, w in pairs)
    if not total:
        return {str(q): None for q in (.1, .5, .9, .95, .99)}
    result = {}; cumulative = 0.; qi = 0; levels = (.1, .5, .9, .95, .99)
    for value, w in pairs:
        cumulative += w
        while qi < len(levels) and cumulative + 1e-14 >= total * levels[qi]:
            result[str(levels[qi])] = value; qi += 1
    return result


def summary(rs):
    mass = math.fsum(r['mass'] for r in rs)
    patterns = Counter()
    pattern_mass = defaultdict(float)
    for r in rs:
        tag = ('both' if r['group_00'] and r['group_mix'] else
               '00_only' if r['group_00'] else 'mixed_only' if r['group_mix'] else 'neither')
        patterns[tag] += 1; pattern_mass[tag] += r['mass']
    return dict(n=len(rs), mass=mass, parents=len({r['parent'] for r in rs}),
                epochs=len({ep(r) for r in rs}),
                fake_entities=len({r['job_id'] for r in rs if r['query_truth'] == 0}),
                R_ind=quantiles([(r['R_ind'], r['mass']) for r in rs]),
                miss_p_effective=quantiles([(r['miss_p_eff'], r['mass']) for r in rs if r['miss_p_eff'] is not None]),
                patterns={k:dict(n=patterns[k], mass=pattern_mass[k]) for k in ('neither','00_only','mixed_only','both')},
                groups={k:dict(n=sum(bool(r[k]) for r in rs),
                               mass=math.fsum(r['mass'] for r in rs if r[k])) for k in FLAGS})


def auc(ts, fs):
    """Within-cell probability a false R exceeds a true R, with half credit ties."""
    values = sorted((round(r['R_ind'], 10), r['mass']) for r in ts)
    x = [p[0] for p in values]; prefix = [0.]
    for _, w in values:
        prefix.append(prefix[-1] + w)
    mt = math.fsum(r['mass'] for r in ts); mf = math.fsum(r['mass'] for r in fs)
    numerator = math.fsum(r['mass'] * (prefix[bisect_left(x, round(r['R_ind'],10))] +
                          .5 * (prefix[bisect_right(x,round(r['R_ind'],10))] -
                                prefix[bisect_left(x,round(r['R_ind'],10))])) for r in fs)
    return numerator / (mt * mf)


def small(r):
    keys = ('key','parent','query_truth','family','attack_k','epoch','index','timestamp',
            'counts','R_ind','miss_p_eff','accept_eligible','reject_eligible',*FLAGS,
            'current_U','current_p','current_C','current_groups','source_ids','window_R_by_source')
    out={k:r[k] for k in keys}
    out.update(Count=r['decision'],saved_D_zero=r['D_decision'])
    return out


def median_record(rs):
    total = math.fsum(r['mass'] for r in rs); acc = 0.
    for r in sorted(rs, key=lambda r:(r['R_ind'],r['key'])):
        acc += r['mass']
        if acc + 1e-14 >= total / 2:
            return small(r)


def matched(rs):
    cells = defaultdict(lambda: {0:[],1:[]})
    for r in rs:
        key = (r['parent'], *r['counts'], r['accept_eligible'],r['reject_eligible'])
        cells[key][r['query_truth']].append(r)
    common = []
    for key, c in cells.items():
        if c[0] and c[1]:
            mt=math.fsum(r['mass'] for r in c[1]); mf=math.fsum(r['mass'] for r in c[0])
            common.append((key,c,mt,mf,min(mt,mf),auc(c[1],c[0])))
    overlap=math.fsum(v[4] for v in common)
    matched_t=[r for v in common for r in v[1][1]]; matched_f=[r for v in common for r in v[1][0]]
    byparent={}
    for p in sorted({v[0][0] for v in common}):
        group=[v for v in common if v[0][0]==p]; mass=math.fsum(v[4] for v in group)
        byparent[p]=dict(cells=len(group),overlap_mass=mass,
                        auc=math.fsum(v[4]*v[5] for v in group)/mass)
    result=dict(cells=len(common),overlap_mass=overlap,
                auc=math.fsum(v[4]*v[5] for v in common)/overlap if overlap else None,
                true=summary(matched_t),false=summary(matched_f),by_parent=byparent)
    if common:
        best=sorted(common,key=lambda v:(-v[4],v[0]))[0]
        result['largest_shared_cell']=dict(stratum=list(best[0]),
            true=summary(best[1][1]),false=summary(best[1][0]),auc=best[5],
            true_median_record=median_record(best[1][1]),false_median_record=median_record(best[1][0]))
    return result


def describe(rs):
    result={}
    for truth,name in ((1,'true'),(0,'false')):
        group=[r for r in rs if r['query_truth']==truth]
        bydecision={d:summary([r for r in group if r['decision']==d]) for d in ('accept','unknown','reject')}
        remaining=[r for r in group if r['decision']!='reject']
        eligible=[r for r in remaining if r['eligible']]
        result[name]=dict(all=summary(group),decisions=bydecision,
            remaining=summary(remaining),eligible_remaining=summary(eligible),
            ineligible_remaining=summary([r for r in remaining if not r['eligible']]),
            saved_Count_to_D_zero={a:{b:summary([r for r in group if r['decision']==a and r['D_decision']==b])
                for b in ('accept','unknown','reject')} for a in ('accept','unknown','reject')})
    eligible=[r for r in rs if r['eligible'] and r['decision']!='reject']
    result['matched_all']=matched(rs)
    result['matched_remaining_eligible']=matched(eligible)
    result['matched_remaining_by_family_k']={f'{f}/{k}':matched([r for r in eligible if r['query_truth']==1 or (r['family'],r['attack_k'])==(f,k)])
        for f,k in sorted({(r['family'],r['attack_k']) for r in rs if r['query_truth']==0})}
    result['eligibility_CD_upper_bound']=result['false']['eligible_remaining']['mass']/2
    result['by_parent']={p:{name:summary([r for r in eligible if r['parent']==p and r['query_truth']==truth])
        for truth,name in ((1,'true'),(0,'false'))} for p in sorted({r['parent'] for r in rs})}
    result['false_accept_entities']={j:dict(records=summary([r for r in rs if r['job_id']==j and r['query_truth']==0 and r['decision']=='accept']),
        representative=median_record([r for r in rs if r['job_id']==j and r['query_truth']==0 and r['decision']=='accept']))
        for j in sorted({r['job_id'] for r in rs if r['query_truth']==0 and r['decision']=='accept'})}
    return result


def direct(row,model):
    u=[];p=[]
    for event,x,c,missing in zip(row['U'],row['X'],row['C'],row['C_missing']):
        if x is None or len(x)!=5 or not all(math.isfinite(v) for v in x):
            u.append(-1);p.append(None);continue
        bad=bool(missing or c is None or not math.isfinite(c))
        x=[*x,0. if bad else c,float(bad)]
        s=model['intercept']+math.fsum((v-m)/scale*b for v,m,scale,b in zip(x,model['mean'],model['scale'],model['coef']))
        prob=1/(1+math.exp(-s)) if s>=0 else math.exp(s)/(1+math.exp(s))
        p.append(min(1-1e-6,max(1e-6,prob)));u.append(event if event in (0,1) else -1)
    return u,p


def annotate(stream,model):
    for row in stream:
        u,p=direct(row,model);flags={k:False for k in FLAGS}
        assert sorted(i for g in row['groups'] for i in g)==list(range(len(u)))
        for g in row['groups']:
            observed=[u[i] for i in g if u[i]>=0]
            if len(observed)>=2:
                flags['group_00'] |= all(v==0 for v in observed)
                flags['group_mix'] |= 0 in observed and 1 in observed
                flags['group_11'] |= all(v==1 for v in observed)
                flags['joint_possible'] |= 0 in observed
        row['_audit']=(u,p,flags)
        yield row


def self_check():
    t=[dict(R_ind=0.,mass=.1),dict(R_ind=2.,mass=.2)]
    f=[dict(R_ind=1.,mass=.4),dict(R_ind=2.,mass=.6)]
    assert abs(auc(t,f)-(.4/3+.6*2/3))<1e-12
    assert auc(t,[dict(R_ind=3.,mass=1.)])==1.
    assert auc(t,[dict(R_ind=-1.,mass=1.)])==0.
    assert quantiles([(1.,.95),(2.,.05)])['0.95']==1.


def run(out):
    started=time.monotonic();self_check();out.mkdir(parents=True,exist_ok=False)
    manifest=read(SOURCE/'manifest.json');old=Path(manifest['config']['source_original_scores'])
    model=read(manifest['config']['source_normal_models'])['models']['D']
    records={};membership={};input_sizes={}
    for regime in REGIMES:
        for split in ('cal','eval'):
            path=SOURCE/'predictions'/regime/(split+'.jsonl.gz');input_sizes[str(path)]=path.stat().st_size
            keys=[];count=0
            for r in rows(path):
                count+=1
                if not primary(r):continue
                key=tuple(r['key']);keys.append(key)
                if key not in records:
                    keep=('key','job_id','id','epoch','parent','split','kind','family','attack_k','attack_role',
                          'query_truth','index','timestamp','source_ids','accept_eligible','reject_eligible','finite')
                    records[key]={k:r[k] for k in keep}
                    records[key].update(counts=tuple(int(v) for v in r['Count_inputs']),regimes={})
                canonical=records[key]
                assert canonical['counts']==tuple(r['Count_inputs']) and canonical['epoch']==r['epoch']
                canonical['regimes'][regime]=dict(decision=r['decisions']['Count'],D_decision=r['decisions']['D_zero'],
                    eligible=bool(r['finite'] and r['reject_eligible'] and r.get('error') is None and r['method_status']['Count']['status']=='ok'))
            assert len(keys)==len(set(keys));membership[(regime,split)]=keys
            print('read predictions',regime,split,'primary',len(keys),'all',count,flush=True)
    cached={}
    for split,base in [('eval',SOURCE),('cal',old)]:
        for job_id in sorted({r['job_id'] for r in records.values() if r['split']==split}):
            path=base/'features'/split/(job_id+'.jsonl.gz');input_sizes[str(path)]=path.stat().st_size
            for f in rows(path):
                key=tuple(f['key'])
                if key not in records:continue
                assert f['finite'] and f['features']['D_head'] is not None
                r=records[key];x=f['features']['D_head']
                assert r['counts']==tuple([int(x[2]),sum(f['n_minus']),*f['context']])
                r['R_ind']=-x[1];r['miss_p_eff']=None if not sum(f['n_minus']) else -math.expm1(x[1]/sum(f['n_minus']))
                r['window_R_by_source']=[-v[1] for v in f['sources']['D_head']]
                assert key not in cached;cached[key]=True
    assert set(cached)==set(records)
    jobs=manifest['jobs']+[j for j in read(old/'manifest.json')['jobs'] if j['split']=='cal']
    jobmap={j['job_id']:j for j in jobs};seen=set();max_error=0.
    for job_id in sorted({r['job_id'] for r in records.values()}):
        job=jobmap[job_id];base=SOURCE if job['split']=='eval' else old
        path=Path(job.get('rows_path',base/'jobs'/job_id/'rows.jsonl.gz'));input_sizes[str(path)]=path.stat().st_size
        for win in windows(annotate(rows(path),model),10):
            last=win[-1];key=tuple(last['key'])
            if key not in records:continue
            r=records[key];assert r['epoch']==last['epoch']
            n=len(last['source_ids']);plus=sum(sum(v==1 for v in row['_audit'][0]) for row in win)
            minus=sum(sum(v==0 for v in row['_audit'][0]) for row in win)
            d=sum(any(row['_audit'][0][i]>=0 for row in win) for i in range(n))
            m=sum(any(row['_audit'][0][i]==1 for row in win) for i in range(n))
            assert r['counts']==(plus,minus,len(win),d,m),(key,'window count mismatch')
            reconstructed=math.fsum(-math.log1p(-p) for row in win for u,p in zip(*row['_audit'][:2]) if u==0)
            error=abs(reconstructed-r['R_ind']);max_error=max(max_error,error)
            assert error<1e-9,(key,'R mismatch',reconstructed,r['R_ind'])
            r.update({flag:any(row['_audit'][2][flag] for row in win) for flag in FLAGS})
            r.update(current_U=last['_audit'][0],current_p=last['_audit'][1],current_C=last['C'],current_groups=last['groups'])
            seen.add(key)
    assert seen==set(records)
    report=dict(scope='retrospective_existing_development_evidence_no_new_decisions',
                input_files=input_sizes,checks=dict(primary_keys=len(records),max_R_reconstruction_error=max_error),regimes={})
    for regime in REGIMES:
        report['regimes'][regime]={}
        for split in ('cal','eval'):
            selected=[dict(records[k],**records[k]['regimes'][regime]) for k in membership[(regime,split)]]
            for truth in (0,1):
                group=[r for r in selected if r['query_truth']==truth]
                for r,mass in zip(group,weights(group)):r['mass']=mass
            data=describe(selected)
            saved=read(SOURCE/'report_corrected'/(regime+'.json'))['metrics'][split]['system_query']['Count']
            for name in ('true','false'):
                assert data[name]['all']['n']==saved[name]['n']
                for decision in ('accept','unknown','reject'):
                    a=data[name]['decisions'][decision];assert a['n']==saved[name]['counts'][decision]
                    assert abs(a['mass']-saved[name]['weighted'][decision])<1e-10
            report['regimes'][regime][split]=data
            with gzip.open(out/(regime+'_'+split+'_joined.jsonl.gz'),'wt') as stream:
                for r in selected:
                    stream.write(json.dumps({k:v for k,v in r.items() if k!='regimes'},ensure_ascii=False,allow_nan=False)+'\n')
            print('described',regime,split,flush=True)
    report['elapsed_seconds']=time.monotonic()-started
    (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (out/'complete.json').write_text(json.dumps(dict(status='complete',elapsed_seconds=report['elapsed_seconds'],checks=report['checks']),indent=2)+'\n')
    print(json.dumps(report['checks']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
