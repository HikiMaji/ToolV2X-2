"""Resumable frozen prepare/fit/score/report CLI. No phase overwrites results."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import traceback
import numpy as np
from . import data, fit as fitting, kernel

METHODS=kernel.METHODS+('MATE_policy',)
DECISIONS=('accept','unknown','reject')


def require_prepare(out):
    if not (Path(out)/'prepare.complete.json').exists():
        raise RuntimeError('prepare is incomplete')


def prepare(out):
    out=Path(out)
    if (out/'prepare.complete.json').exists():
        raise FileExistsError('prepare already complete')
    spec=data.manifest(out);data.prepare_legacy(out,spec)
    subprocess.run([str(data.RUNTIME),'-m','scripts.rq1_temporal.native_adapter','--out',str(out.resolve())],
                   cwd=Path(__file__).resolve().parents[2],check=True)
    statuses={j['job_id']:json.loads((out/'jobs'/j['job_id']/'complete.json').read_text()) for j in spec['jobs']}
    data.atomic_json(out/'prepare.complete.json',dict(jobs=statuses,attempted_attacks=sum(j['origin']=='native' and j['kind']=='attack' for j in spec['jobs']),
                     unrealizable=sum(s['status']=='UNREALIZABLE' for s in statuses.values()),code=data.code_record()))


def fit(out):
    out=Path(out); require_prepare(out)
    if (out/'models.json').exists():
        raise FileExistsError('models already exist')
    # Keep unknown-label and no-query history for OOF; fitting filters supervision internally.
    rows=[r for r in data.all_rows(out,'fit') if r['kind']=='clean']
    oof=fitting.fit_rho_oof(rows,W=10); models=fitting.fit_models(rows)
    data.atomic_json(out/'models.json',dict(models=models,rho=oof['rho'],rho_fit=oof,
                     method_status=fitting.method_status(models,oof['rho']),code=data.code_record(),n_input_rows=len(rows)))


def prediction(row,result):
    names=('key','job_id','id','epoch','parent','split','kind','family','attack_k','attack_role','index','frame','timestamp',
           'query_truth','query_gt_id','output_truth','query_present','newborn','output_present','identity_ok','native_adopted','native_mean')
    output={k:row.get(k) for k in names}
    output.update({k:result[k] for k in ('scores','normal_loglik','method_status','finite','n_frames','accept_eligible','reject_eligible')})
    mean=row.get('native_mean')
    output['scores']['MATE_policy']=None if mean is None or not np.isfinite(mean) else mean-.5
    output['method_status']['MATE_policy']=dict(status='ok' if output['scores']['MATE_policy'] is not None else 'unavailable',reason=None if mean is not None else 'native mean unavailable')
    if not result['finite']:
        output['scores']['MATE_policy']=None
        output['method_status']['MATE_policy']=dict(status='numeric_failure',reason=result.get('error'))
    output.update(m=len(result['opportunity_union']),supports=len(result['support_union']),
                  common_group=any(sum(row['U'][i] in (0,1) and row['X'][i] is not None for i in g)>=2 for g in row['groups']),
                  C_positive=any(c is not None and c>0 and not missing for c,missing in zip(row['C'],row['C_missing'])),
                  delta_T=result.get('window',{}).get('delta_T'),delta_F=result.get('window',{}).get('delta_F'),
                  error=result.get('error'))
    return data.finite_json(output)


def score(out):
    out=Path(out); require_prepare(out)
    if (out/'score.complete.json').exists():
        raise FileExistsError('score already complete')
    fitted=json.loads((out/'models.json').read_text());spec=json.loads((out/'manifest.json').read_text())
    variants=[('main',10,.9),('W5',5,.9),('W20',20,.9),('s05',10,.5),('s095',10,.95)]
    for job in spec['jobs']:
        status=json.loads((out/'jobs'/job['job_id']/'complete.json').read_text())
        if status['status']=='UNREALIZABLE':
            continue
        rows=list(data.read_rows(out/'jobs'/job['job_id']/'rows.jsonl.gz'))
        for name,W,s in variants:
            dest=out/'scores'/name/(job['job_id']+'.jsonl.gz')
            if dest.exists():
                continue
            with data.atomic_rows(dest) as write:
                for window in kernel.windows(rows,W):
                    result=kernel.score_window(window,fitted['models'],fitted['rho'],W,s)
                    write(prediction(window[-1],result))
            print('scored variant',job['job_id'],name,len(rows),flush=True)
        print('scored',job['job_id'],len(rows),flush=True)
    data.atomic_json(out/'score.complete.json',dict(variants=variants,method_status=fitted['method_status'],code=data.code_record()))


def primary(row,truth):
    if not row.get('query_present') or row.get('newborn'):
        return False
    if truth==1:
        return row['kind']=='clean' and row['query_truth']==1
    return row['kind']=='attack' and row['query_truth']==0 and row.get('attack_role')=='target'


def epoch(row):
    return (row['job_id'],row['id'],row['epoch'])


def weights(rows,truth):
    """Normalized weights for the actual class subset, including unknown decisions."""
    if not rows:
        return np.array([])
    layers=defaultdict(lambda:defaultdict(lambda:defaultdict(set)))
    for row in rows:
        layer=(row['family'],row['attack_k']) if truth==0 else ('clean',0)
        layers[layer][row['parent']][epoch(row)].add(row['index'])
    result=[]
    for row in rows:
        layer=(row['family'],row['attack_k']) if truth==0 else ('clean',0); parents=layers[layer];epochs=parents[row['parent']]
        result.append(1/(len(layers)*len(parents)*len(epochs)*len(epochs[epoch(row)])))
    return np.asarray(result)


def decide(row,method,policy):
    score=row['scores'].get(method)
    if score is None or not row['finite']:
        return 'unknown'
    if row['accept_eligible'] and policy['A'] is not None and score>0 and score>=policy['A']:
        return 'accept'
    if row['reject_eligible'] and policy['R'] is not None and score<0 and score<=policy['R']:
        return 'reject'
    return 'unknown'


# Scores remain on disk. Only one split's fixed-width scalars enter RAM.
_INT_FIELDS=('id','epoch','index','frame','query_truth','output_truth','attack_k','m','supports','n_frames')
_BOOL_FIELDS=('query_present','newborn','output_present','identity_ok','native_adopted','finite','accept_eligible','reject_eligible','common_group','C_positive')
_CODE_FIELDS=('parent','job_id','family')
_REPORT_DTYPE=np.dtype([(k,'i4') for k in _INT_FIELDS+_CODE_FIELDS]+[(k,'?') for k in _BOOL_FIELDS]+
    [('split','i1'),('kind','i1'),('attack_role','i1'),('timestamp','f8'),('delta_T','f8'),('delta_F','f8')]+
    [('s_'+m,'f8') for m in METHODS]+[('l_'+m,'f8') for m in kernel.METHODS]+[('d_'+m,'i1') for m in METHODS])


class ReportRows:
    def __init__(self, values, codes):
        self.values=values;self.codes=codes

    def __len__(self):
        return len(self.values)

    def subset(self, mask):
        return ReportRows(self.values[mask],self.codes)

    @classmethod
    def from_rows(cls, rows):
        if isinstance(rows,cls):
            return rows
        codes={k:[] for k in _CODE_FIELDS};lookups={k:{} for k in _CODE_FIELDS}
        array=np.empty(len(rows),dtype=_REPORT_DTYPE)
        for i,row in enumerate(rows):
            array[i]=pack_report_row(row,codes,lookups)
        return cls(array,codes)


def pack_report_row(row,codes,lookups):
    record=np.zeros((),dtype=_REPORT_DTYPE)
    for k in _INT_FIELDS:
        value=row.get(k,0);record[k]=-2 if value is None else value
    for k in _BOOL_FIELDS:
        record[k]=bool(row.get(k,False))
    for k in _CODE_FIELDS:
        value=row[k]
        if value not in lookups[k]:
            lookups[k][value]=len(codes[k]);codes[k].append(value)
        record[k]=lookups[k][value]
    record['split']=('fit','cal','eval').index(row['split'])
    record['kind']=int(row['kind']=='attack');record['attack_role']={None:0,'target':1,'occluder':2}.get(row.get('attack_role'),0)
    record['timestamp']=row['timestamp']
    for k in ('delta_T','delta_F'):
        record[k]=np.nan if row.get(k) is None else row[k]
    for prefix,key,methods in [('s_','scores',METHODS),('l_','normal_loglik',kernel.METHODS)]:
        for m in methods:
            value=row.get(key,{}).get(m);record[prefix+m]=np.nan if value is None else value
    for m in METHODS:
        record['d_'+m]=DECISIONS.index(row.get('decisions',{}).get(m,'unknown'))
    return record


def report_cache(out,name,spec):
    import sqlite3
    path=Path(out)/'report/cache'/(name+'.sqlite');path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        return path
    temp=path.with_suffix('.partial.sqlite')
    if temp.exists():
        temp.unlink()
    connection=sqlite3.connect(str(temp));connection.execute('PRAGMA cache_size=-2048')
    connection.execute('CREATE TABLE rows (split INTEGER, job TEXT, frame INTEGER, id INTEGER, scalars BLOB, payload TEXT)')
    codes={k:[] for k in _CODE_FIELDS};lookups={k:{} for k in _CODE_FIELDS}
    try:
        for job in spec['jobs']:
            source=Path(out)/'scores'/name/(job['job_id']+'.jsonl.gz')
            if not source.exists():
                continue
            for row in data.read_rows(source):
                packed=pack_report_row(row,codes,lookups)
                payload=json.dumps(row,allow_nan=False) if name=='main' else None
                connection.execute('INSERT INTO rows VALUES (?,?,?,?,?,?)',(int(packed['split']),row['job_id'],row['frame'],row['id'],packed.tobytes(),payload))
            connection.commit()
            print('report cached',name,job['job_id'],flush=True)
        connection.execute('CREATE INDEX ordering ON rows(split,job,frame,id)')
        connection.execute('CREATE TABLE metadata (codes TEXT)');connection.execute('INSERT INTO metadata VALUES (?)',(json.dumps(codes),));connection.commit()
    finally:
        connection.close()
    temp.replace(path)
    return path


def load_report_split(path,split):
    import sqlite3
    with sqlite3.connect(str(path)) as connection:
        connection.execute('PRAGMA cache_size=-2048');code=('fit','cal','eval').index(split)
        size=connection.execute('SELECT count(*) FROM rows WHERE split=?',(code,)).fetchone()[0]
        values=np.empty(size,dtype=_REPORT_DTYPE)
        for i,(blob,) in enumerate(connection.execute('SELECT scalars FROM rows WHERE split=?',(code,))):
            values[i]=np.frombuffer(blob,dtype=_REPORT_DTYPE)[0]
        codes=json.loads(connection.execute('SELECT codes FROM metadata').fetchone()[0])
    return ReportRows(values,codes)


def primary_mask(rows,truth):
    a=rows.values;query=a['query_present']&~a['newborn']
    return query&(a['kind']==(0 if truth else 1))&(a['query_truth']==truth)&((a['attack_role']==1) if truth==0 else True)


def column_weights(rows,truth):
    a=rows.values;n=len(a)
    if not n:
        return np.empty(0)
    layer_keys=np.column_stack([a['family'],a['attack_k']]) if truth==0 else np.zeros((n,1),dtype=int)
    _,layer=np.unique(layer_keys,axis=0,return_inverse=True)
    parent_keys=np.column_stack([layer,a['parent']]);parents,parent=np.unique(parent_keys,axis=0,return_inverse=True)
    epochs,ep,counts=np.unique(np.column_stack([parent,a['job_id'],a['id'],a['epoch']]),axis=0,return_inverse=True,return_counts=True)
    parent_counts=np.bincount(parents[:,0]);epoch_counts=np.bincount(epochs[:,0])
    return 1/(len(parent_counts)*parent_counts[layer]*epoch_counts[parent]*counts[ep])


def apply_policies(rows,policies):
    a=rows.values
    for m in METHODS:
        score=a['s_'+m];p=policies[m];decision=a['d_'+m];decision[:]=1
        if p['A'] is not None:
            decision[a['finite']&a['accept_eligible']&(score>0)&(score>=p['A'])]=0
        if p['R'] is not None:
            decision[a['finite']&a['reject_eligible']&(score<0)&(score<=p['R'])]=2


def calibrate(rows,method,expected_layers=None,alpha=.05):
    rows=ReportRows.from_rows(rows);a=rows.values
    masks={t:primary_mask(rows,t) for t in (0,1)}
    observed={(rows.codes['family'][int(f)],int(k)) for f,k in zip(a['family'][masks[0]],a['attack_k'][masks[0]])}
    policy=dict(A=None,R=None,alpha=alpha,missing_layers=[list(x) for x in sorted(set(expected_layers or [])-observed)],status='ok',branch={})
    if policy['missing_layers']:
        policy['status']='not_calibrated_for_missing_layers'
    for branch,error_truth,positive in [('A',0,True),('R',1,False)]:
        error=masks[error_truth];goal=masks[1-error_truth];error_rows=rows.subset(error)
        if not error.any():
            policy['branch'][branch]=dict(status='not_estimable',reason='missing error class',n=0);continue
        scores=a['s_'+method];eligible=a['accept_eligible'] if positive else a['reject_eligible']
        candidate=(error|goal)&a['finite']&eligible&np.isfinite(scores)&((scores>0) if positive else (scores<0))
        order=np.flatnonzero(candidate);order=order[np.argsort(-scores[order] if positive else scores[order],kind='stable')]
        correct=np.zeros(len(a));correct[goal]=column_weights(rows.subset(goal),1-error_truth)
        wrong=np.zeros(len(a));wrong[error]=column_weights(error_rows,error_truth)
        accepted=None;best=0.
        if len(order):
            ends=np.r_[np.flatnonzero(scores[order][1:]!=scores[order][:-1]),len(order)-1]
            quality=np.cumsum(correct[order])[ends];allowed=np.cumsum(wrong[order])[ends]<=alpha+1e-12
            layers=np.unique(np.column_stack([a['family'][error],a['attack_k'][error]]),axis=0)
            for family,k in layers:
                layer=error&(a['family']==family)&(a['attack_k']==k);mass=np.zeros(len(a));mass[layer]=column_weights(rows.subset(layer),error_truth)
                allowed &= np.cumsum(mass[order])[ends]<=alpha+1e-12
            if allowed.any():
                best=float(quality[allowed].max())
                # Closed is the most conservative zero-quality candidate. Sorting
                # visits narrower thresholds first, so first ties remain conservative.
                if best>1e-12:
                    choice=np.flatnonzero(allowed&(quality>=best-1e-12))[0];accepted=float(scores[order[ends[choice]]])
        policy[branch]=accepted
        policy['branch'][branch]=dict(status='ok' if accepted is not None else 'disabled',correct_weight=best,n=int(error.sum()),
            n_parents=len(np.unique(error_rows.values['parent'])),n_epochs=len(np.unique(np.column_stack([error_rows.values[k] for k in ('job_id','id','epoch')]),axis=0)))
    return policy


def six_cells_many(rows,methods=METHODS):
    rows=ReportRows.from_rows(rows);result={m:{} for m in methods}
    for truth,label in [(1,'true'),(0,'false')]:
        subset=rows.subset(primary_mask(rows,truth));a=subset.values;w=column_weights(subset,truth)
        parents=len(np.unique(a['parent']));epochs=len(np.unique(np.column_stack([a[k] for k in ('job_id','id','epoch')]),axis=0))
        for method in methods:
            decision=a['d_'+method];counts={d:int((decision==i).sum()) for i,d in enumerate(DECISIONS)}
            result[method][label]=dict(n=len(a),parents=parents,epochs=epochs,counts=counts,
                raw={d:counts[d]/len(a) if len(a) else None for d in DECISIONS},weighted={d:float(w[decision==i].sum()) if len(a) else None for i,d in enumerate(DECISIONS)})
    for method in methods:
        t=result[method]['true']['weighted']['accept'];f=result[method]['false']['weighted']['reject']
        result[method]['correct_definite']=None if t is None or f is None else (t+f)/2
    return result


def six_cells(rows,method):
    return six_cells_many(rows,(method,))[method]


def trajectories(rows,method,truth,writer=None):
    rows=ReportRows.from_rows(rows);a=rows.values;primary=primary_mask(rows,truth);valid=a['query_present']&~a['newborn']
    _,groups=np.unique(np.column_stack([a[k] for k in ('job_id','id','epoch')]),axis=0,return_inverse=True);selected=np.unique(groups[primary]);indices=np.flatnonzero(valid&np.isin(groups,selected))
    indices=indices[np.lexsort((a['index'][indices],groups[indices]))];boundaries=np.r_[0,np.flatnonzero(groups[indices][1:]!=groups[indices][:-1])+1,len(indices)] if len(indices) else [0]
    result=dict(n=0,never_accepted=0,ever_false_accept=0 if truth==0 else None,accepted_delay_median=None,n_accepted=0)
    details=[] if writer is None else None;delays=[]
    for begin,end in zip(boundaries,boundaries[1:]):
        ix=indices[begin:end];values=a[ix];decisions=values['d_'+method];accepted=np.flatnonzero(decisions==0)
        wrong=primary[ix]&(decisions==(2 if truth else 0));streak=longest=0;prev=None
        for index,error in zip(values['index'],wrong):
            streak=(streak+1 if prev is not None and index==prev+1 else 1) if error else 0;longest=max(longest,streak);prev=index
        first=values[0];delay=None if not len(accepted) else float(values['timestamp'][accepted[0]]-first['timestamp'])
        detail=dict(epoch=[rows.codes['job_id'][first['job_id']],int(first['id']),int(first['epoch'])],parent=rows.codes['parent'][first['parent']],
                    n=len(ix),n_labelled_primary=int(primary[ix].sum()),ever_accept=bool(len(accepted)),ever_false_accept=bool((primary[ix]&(decisions==0)).any()) if truth==0 else None,
                    first_accept_delay=delay,longest_error=int(longest))
        result['n']+=1;result['never_accepted']+=not len(accepted)
        if truth==0:result['ever_false_accept']+=detail['ever_false_accept']
        if delay is not None:delays.append(delay)
        if writer is None:details.append(detail)
        else:writer(dict(method=method,truth=truth,**detail))
    result['n_accepted']=len(delays);result['accepted_delay_median']=float(np.median(delays)) if delays else None
    if writer is None:result['rows']=details
    return result


def evaluate(rows,cal_layers=None,trajectory_writer=None):
    rows=ReportRows.from_rows(rows);a=rows.values
    main=six_cells_many(rows);eligible_rows=rows.subset(a['accept_eligible']|a['reject_eligible'])
    eligible=six_cells_many(eligible_rows);native={}
    for truth,label in [(1,'true'),(0,'false')]:
        subset=rows.subset(primary_mask(rows,truth));w=column_weights(subset,truth)
        native[label]=dict(n=len(subset),adopted=int(subset.values['native_adopted'].sum()),weighted_adoption=float(w[subset.values['native_adopted']].sum()) if len(subset) else None)
    strata={}
    for field in ('attack_k','family','common_group','C_positive','m','parent'):
        strata[field]={}
        for value in np.unique(a[field]):
            label=rows.codes[field][value] if field in ('family','parent') else str(value)
            subset=rows.subset(a[field]==value);strata[field][str(label)]=six_cells_many(subset)
    joint={}
    for family,k in np.unique(np.column_stack([a['family'],a['attack_k']]),axis=0):
        label=rows.codes['family'][family];subset=rows.subset((a['family']==family)&(a['attack_k']==k))
        joint[label+'/'+str(k)]=dict(family=label,k=int(k),cal_status='observed' if (label,int(k)) in (cal_layers or set()) else 'not_calibrated',
                                   methods=six_cells_many(subset))
    clean=rows.subset(primary_mask(rows,1));w=column_weights(clean,1);nll={}
    for m in kernel.METHODS:
        ll=clean.values['l_'+m];valid=np.isfinite(ll);mass=w[valid].sum()
        nll[m]=dict(n=int(valid.sum()),n_primary=len(clean),coverage_weight=float(mass),window_nll=float(-w[valid]@ll[valid]/mass) if mass else None)
    deltas={}
    for truth in (0,1):
        subset=rows.subset(primary_mask(rows,truth));w=column_weights(subset,truth);deltas[str(truth)]={}
        for field in ('delta_T','delta_F'):
            v=subset.values[field];valid=np.isfinite(v);mass=w[valid].sum()
            deltas[str(truth)][field]=dict(n=int(valid.sum()),coverage_weight=float(mass),weighted_mean=float(w[valid]@v[valid]/mass) if mass else None,
                quantiles=np.percentile(v[valid],[0,25,50,75,100]).tolist() if valid.any() else None)
    def decision_counts(mask):
        return {m:{d:int((a['d_'+m][mask]==i).sum()) for i,d in enumerate(DECISIONS) if (a['d_'+m][mask]==i).any()} for m in METHODS}
    unknown=~np.isin(a['query_truth'],[0,1]);background=(a['kind']==1)&(a['query_truth']==1);occluder=a['attack_role']==2;newborn=a['newborn']
    result=dict(system_query=main,eligible=eligible,native_MATE=native,strata=strata,family_k=joint,normal_probability=nll,state_delta=deltas,
        method_score_coverage={m:dict(n_finite=int(np.isfinite(a['s_'+m]).sum()),n_total=len(rows)) for m in METHODS},
        n_rows=len(rows),numeric_failure=int((~a['finite']).sum()),unknown_labels=int(unknown.sum()),unknown_label_decisions=decision_counts(unknown),
        attack_true_background=dict(n=int(background.sum()),decisions=decision_counts(background)),auxiliary_occluder=dict(n=int(occluder.sum()),decisions=decision_counts(occluder)),
        newborn_system=dict(n=int(newborn.sum()),output_truth={str(None if v==-2 else v):int((a['output_truth'][newborn]==v).sum()) for v in np.unique(a['output_truth'][newborn])},native_adopted=int(a['native_adopted'][newborn].sum())),
        trajectories={m:{str(t):trajectories(rows,m,t,trajectory_writer) for t in (0,1)} for m in METHODS})
    return result


def paired_bootstrap(rows,repetitions=1000):
    rows=ReportRows.from_rows(rows);a=rows.values;parents=np.unique(a['parent']);tables={}
    for parent in parents:
        subset=rows.subset(a['parent']==parent);v=subset.values;table={}
        for truth in (0,1):
            chosen=primary_mask(subset,truth)
            for family,k in np.unique(np.column_stack([v['family'][chosen],v['attack_k'][chosen]]),axis=0):
                group=subset.subset(chosen&(v['family']==family)&(v['attack_k']==k));w=column_weights(group,truth)
                table[(truth,int(family),int(k))]={m:float(w[group.values['d_'+m]==(0 if truth else 2)].sum()) for m in kernel.METHODS}
        tables[int(parent)]=table
    pairs=(('C','D'),('T','C'),('J','T'),('J','G'));values={x+'-'+y:[] for x,y in pairs};rng=np.random.RandomState(0)
    if len(parents):
        for _ in range(repetitions):
            sampled=[tables[int(parents[i])] for i in rng.randint(len(parents),size=len(parents))];classes={}
            for truth in (0,1):
                layers=sorted({key for table in sampled for key in table if key[0]==truth})
                classes[truth]={m:float(np.mean([np.mean([table[key][m] for table in sampled if key in table]) for key in layers])) if layers else None for m in kernel.METHODS}
            metric={m:None if classes[0][m] is None or classes[1][m] is None else (classes[0][m]+classes[1][m])/2 for m in kernel.METHODS}
            for x,y in pairs:
                if metric[x] is not None and metric[y] is not None:values[x+'-'+y].append(metric[x]-metric[y])
    return dict(n_parents=len(parents),repetitions=repetitions,seed=0,description='paired development-parent descriptive stability, not risk certification',
        intervals={k:dict(n=len(v),percentile95=np.percentile(v,[2.5,97.5]).tolist() if v else None) for k,v in values.items()})


def method_decisions(metrics,method_status=None):
    def difference(a,b):
        return None if a is None or b is None else a-b
    statuses=method_status or {};availability={m:(statuses.get(m,{}).get('status')=='ok' if m!='MATE_policy' else True) and metrics.get('method_score_coverage',{}).get(m,{}).get('n_finite',0)>0 for m in METHODS}
    result=dict(retention_status='pending_Task3_approved_criteria',method_status=statuses,method_estimable=availability)
    for name,x,y in [('proxy_vs_direct','C','D'),('temporal_vs_static','T','C'),('joint_vs_temporal','J','T'),('joint_vs_group','J','G'),('joint_vs_MATE_policy','J','MATE_policy')]:
        a,b=metrics['system_query'][x],metrics['system_query'][y]
        nll=metrics['normal_probability'];tx=metrics['trajectories'][x]['1'];ty=metrics['trajectories'][y]['1']
        result[name]=dict(comparison_estimable=availability[x] and availability[y] and a['correct_definite'] is not None and b['correct_definite'] is not None,
            correct_definite_difference=difference(a['correct_definite'],b['correct_definite']),
            true_accept_difference=difference(a['true']['weighted']['accept'],b['true']['weighted']['accept']),
            false_accept_difference=difference(a['false']['weighted']['accept'],b['false']['weighted']['accept']),
            accepted_delay_median_difference=difference(tx['accepted_delay_median'],ty['accepted_delay_median']),
            normal_window_nll_difference=difference(nll.get(x,{}).get('window_nll'),nll.get(y,{}).get('window_nll')),
            family_k_false_accept_difference={layer:difference(v['methods'][x]['false']['weighted']['accept'],v['methods'][y]['false']['weighted']['accept']) for layer,v in metrics['family_k'].items()})
    return result


def plot_six(out,metrics):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure=Figure(figsize=(12,7));FigureCanvasAgg(figure);axes=figure.subplots(1,2,sharey=True)
    labels=[m+' '+t for m in METHODS for t in ('true','false')]
    for ax,split in zip(axes,('cal','eval')):
        for y,(method,truth) in enumerate((m,t) for m in METHODS for t in ('true','false')):
            left=0.
            for d,color in zip(DECISIONS,('#3975b7','#aaaeb4','#d16b5d')):
                value=metrics[split]['system_query'][method][truth]['weighted'][d]
                if value is not None:
                    ax.barh(y,value,left=left,color=color);left+=value
        ax.set(title=split,xlim=(0,1),yticks=range(len(labels)),yticklabels=labels);ax.invert_yaxis()
    figure.suptitle('Development primary queries: accept / unknown / reject');figure.tight_layout();figure.savefig(out/'six_cells.png',dpi=160)


def attack_coverage(out,spec):
    result={}
    for job in spec['jobs']:
        if job['kind']!='attack':
            continue
        key=job['family']+'/'+str(job['attack_k']);group=result.setdefault(key,dict(family=job['family'],k=job['attack_k'],attempted=0,UNREALIZABLE=0,
            injected_tasks=0,legacy_injection_unverified=0,entity_coverage_tasks=0,entity_coverage_missing=0,entities={}))
        group['attempted']+=1
        status=json.loads((Path(out)/'jobs'/job['job_id']/'complete.json').read_text())
        if status['status']=='UNREALIZABLE':
            group['UNREALIZABLE']+=1;continue
        if status.get('attack_constructed'):
            group['injected_tasks']+=1
        else:
            group['legacy_injection_unverified']+=1
        coverage=status.get('entity_coverage')
        if not coverage:
            group['entity_coverage_missing']+=1;continue
        group['entity_coverage_tasks']+=1
        for role,phases in coverage.items():
            for phase,counts in phases.items():
                dest=group['entities'].setdefault(role,{}).setdefault(phase,Counter());dest.update(counts)
    for group in result.values():
        group['entity_coverage_status']='complete' if not group['entity_coverage_missing'] else 'not_available_for_all_tasks'
        group['entities']={r:{p:dict(c) for p,c in phases.items()} for r,phases in group['entities'].items()}
    return result


def stream_main_outputs(out,cache,policies,spec,fitted):
    import sqlite3
    destination=Path(out)/'report';cases={k:[] for k in ('common_group','J_T_different','T_accept_J_other','J_accept_T_other')}
    predictions=destination/'predictions.jsonl.gz'
    # Payload is decoded one record at a time; case candidates are capped at 48.
    from contextlib import nullcontext
    context=data.atomic_rows(predictions) if not predictions.exists() else nullcontext(None)
    with context as write,sqlite3.connect(str(cache)) as connection:
        connection.execute('PRAGMA cache_size=-2048')
        for payload, in connection.execute('SELECT payload FROM rows ORDER BY job,frame,id'):
            row=json.loads(payload);row['decisions']={m:decide(row,m,policies[m]) for m in METHODS}
            if write is not None:write(row)
            if row['split']!='eval':continue
            predicates=dict(common_group=row['common_group'],J_T_different=row['decisions']['J']!=row['decisions']['T'],
                T_accept_J_other=row['decisions']['T']=='accept' and row['decisions']['J']!='accept',
                J_accept_T_other=row['decisions']['J']=='accept' and row['decisions']['T']!='accept')
            for name,condition in predicates.items():
                if condition and len(cases[name])<12:cases[name].append(row)
    if not (destination/'cases.json').exists():
        selected={tuple(r['key']) for group in cases.values() for r in group};details={}
        for job in spec['jobs']:
            if not any(key[0]==job['job_id'] for key in selected):continue
            for window in kernel.windows(data.read_rows(Path(out)/'jobs'/job['job_id']/'rows.jsonl.gz'),10):
                key=tuple(window[-1]['key'])
                if key in selected:details[key]=dict(row=data.compact(window[-1]),diagnostics=kernel.score_window(window,fitted['models'],fitted['rho']))
        data.atomic_json(destination/'cases.json',{name:[dict(prediction=r,**details[tuple(r['key'])]) for r in group] for name,group in cases.items()})


def report(out):
    out=Path(out)
    if not (out/'score.complete.json').exists():raise RuntimeError('score incomplete')
    if (out/'report.complete.json').exists():raise FileExistsError('report already complete')
    spec=json.loads((out/'manifest.json').read_text());fitted=json.loads((out/'models.json').read_text())
    expected_layers={(j['family'],j['attack_k']) for j in spec['jobs'] if j['kind']=='attack' and j['split']=='cal'}
    destination=out/'report';destination.mkdir(exist_ok=True);reports={};main_cache=None;main_policies=None
    for name,_,_ in json.loads((out/'score.complete.json').read_text())['variants']:
        cache=report_cache(out,name,spec);cal=load_report_split(cache,'cal')
        observed={(cal.codes['family'][int(f)],int(k)) for f,k in zip(cal.values['family'][primary_mask(cal,0)],cal.values['attack_k'][primary_mask(cal,0)])}
        # Clean is a separate calibration class, not an attack family/k stratum.
        if primary_mask(cal,1).any():observed.add(('clean',0))
        policies={m:calibrate(cal,m,expected_layers) for m in METHODS};apply_policies(cal,policies);metrics={}
        for split in ('cal','eval'):
            rows=cal if split=='cal' else load_report_split(cache,'eval')
            if split=='eval':apply_policies(rows,policies)
            epoch_path=destination/'epochs'/(name+'_'+split+'.jsonl.gz')
            from contextlib import nullcontext
            with (data.atomic_rows(epoch_path) if not epoch_path.exists() else nullcontext(lambda row:None)) as writer:
                metrics[split]=evaluate(rows,observed,writer)
            metrics[split]['epoch_details']=str(epoch_path.relative_to(out))
            if split=='eval':
                differences=method_decisions(metrics[split],fitted.get('method_status'))
                bootstrap=paired_bootstrap(rows) if name=='main' else None
                del rows
            else:
                del rows;del cal
            print('report summarized',name,split,metrics[split]['n_rows'],flush=True)
        reports[name]=dict(metrics=metrics,policies=policies,method_decisions=differences)
        if name=='main':
            reports[name]['bootstrap']=bootstrap;main_cache=cache;main_policies=policies
    stream_main_outputs(out,main_cache,main_policies,spec,fitted)
    metrics=dict(variants=reports,rho=fitted['rho_fit'],model_support=fitted['models']['diagnostics'],method_status=fitted['method_status'],
        attack_coverage=attack_coverage(out,spec),code=data.code_record(),
        MATE_policy='mean minus 0.5 under the same calibrated decision policy; native adoption reported separately')
    if not (destination/'metrics.json').exists():data.atomic_json(destination/'metrics.json',metrics)
    if not (destination/'six_cells.png').exists():plot_six(destination,reports['main']['metrics'])
    if not (destination/'summary.md').exists():
        lines=['# 时序条件联合核验开发结果','','14个已使用开发父录制。此结果不是独立未见评估，也不提供风险保证。',
            '主参数 W=10，s=0.9。门限只取cal，敏感性分别重新cal，不按eval挑选。',
            '主假风险只统计target。F3辅助occluder、未实现任务、无target query和标签未知覆盖分别报告。','',
            '| 方法 | 真采纳 | 真拒绝 | 假采纳 | 假拒绝 | correct definite |','|---|---:|---:|---:|---:|---:|']
        for method in METHODS:
            m=reports['main']['metrics']['eval']['system_query'][method];vals=[m['true']['weighted']['accept'],m['true']['weighted']['reject'],m['false']['weighted']['accept'],m['false']['weighted']['reject'],m['correct_definite']]
            lines.append('| '+method+' | '+' | '.join('NA' if v is None else '%.4f'%v for v in vals)+' |')
        lines+=['','组件不可估状态及共同数值失败见metrics.json；不可估方法保留unknown，不删共同分母。',
            '这里只报告观察差异和可估状态。保留决定待Task3按已批准标准裁决，不以NLL降低另加保留门槛。','',
            '```json',json.dumps(reports['main']['method_decisions'],ensure_ascii=False,indent=2),'```']
        temp=destination/'summary.md.partial';temp.write_text('\n'.join(lines)+'\n');temp.replace(destination/'summary.md')
    data.atomic_json(out/'report.complete.json',dict(code=data.code_record(),report=str(destination)))


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('prepare','fit','score','report'));parser.add_argument('--out',type=Path,default=data.DEFAULT_OUT)
    args=parser.parse_args(argv)
    try:
        globals()[args.stage](args.out)
    except Exception as exc:
        error=args.out/(args.stage+'.error.json')
        if not error.exists():
            data.atomic_json(error,dict(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc()))
        raise


if __name__=='__main__':
    main()
