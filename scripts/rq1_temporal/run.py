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


def calibrate(rows,method,expected_layers=None,alpha=.05):
    primary_rows={truth:[r for r in rows if primary(r,truth)] for truth in (0,1)}
    policy=dict(A=None,R=None,alpha=alpha,missing_layers=[],status='ok',branch={})
    observed={(r['family'],r['attack_k']) for r in primary_rows[0]}
    policy['missing_layers']=[list(x) for x in sorted(set(expected_layers or [])-observed)]
    if policy['missing_layers']:
        policy['status']='not_calibrated_for_missing_layers'
    for branch,error_truth,positive in [('A',0,True),('R',1,False)]:
        subset=primary_rows[error_truth]
        if not subset:
            policy['branch'][branch]=dict(status='not_estimable',reason='missing error class',n=0)
            continue
        # Cumulative tie blocks keep the scan O(n log n), with the full class
        # denominator retained even when a record cannot make this decision.
        total_weight=weights(subset,error_truth)
        layer_rows=defaultdict(list)
        for r in subset:
            layer_rows[(r['family'],r['attack_k'])].append(r)
        contributions=defaultdict(dict)
        for r,w in zip(subset,total_weight):
            contributions[tuple(r['key'])]['overall']=float(w)
        for layer,group in layer_rows.items():
            for r,w in zip(group,weights(group,error_truth)):
                contributions[tuple(r['key'])][str(layer)]=float(w)
        blocks=defaultdict(list)
        for r in rows:
            score=r['scores'].get(method)
            if score is not None and (score>0 if positive else score<0):
                blocks[score].append(r)
        mass=Counter();accepted=None
        for threshold in sorted(blocks,reverse=positive):
            proposed=mass.copy()
            for r in blocks[threshold]:
                eligible=r['accept_eligible'] if positive else r['reject_eligible']
                if r['finite'] and eligible:
                    proposed.update(contributions.get(tuple(r['key']),{}))
            if any(v>alpha+1e-12 for v in proposed.values()):
                break
            mass=proposed;accepted=threshold
        else:
            accepted=0.
        policy[branch]=accepted
        policy['branch'][branch]=dict(status='ok' if accepted is not None else 'disabled',n=len(subset),n_parents=len({r['parent'] for r in subset}),n_epochs=len({epoch(r) for r in subset}))
    return policy


def six_cells(rows,method):
    result={}
    for truth,label in [(1,'true'),(0,'false')]:
        subset=[r for r in rows if primary(r,truth)]; w=weights(subset,truth)
        counts={d:sum(r['decisions'][method]==d for r in subset) for d in DECISIONS}
        result[label]=dict(n=len(subset),parents=len({r['parent'] for r in subset}),epochs=len({epoch(r) for r in subset}),counts=counts,
                           raw={d:counts[d]/len(subset) if subset else None for d in DECISIONS},
                           weighted={d:float(sum(v for r,v in zip(subset,w) if r['decisions'][method]==d)) if subset else None for d in DECISIONS})
    t=result['true']['weighted']['accept'];f=result['false']['weighted']['reject']
    result['correct_definite']=None if t is None or f is None else (t+f)/2
    return result


def trajectories(rows,method,truth):
    groups=defaultdict(list)
    selected={epoch(r) for r in rows if primary(r,truth)}
    for row in rows:
        if epoch(row) in selected and row.get('query_present') and not row.get('newborn'):
            groups[epoch(row)].append(row)
    results=[]
    for key,values in sorted(groups.items(),key=lambda kv:str(kv[0])):
        values.sort(key=lambda r:r['index']); accepted=[r for r in values if r['decisions'][method]=='accept']
        streak=longest=0; prev=None
        for r in values:
            wrong=primary(r,truth) and r['decisions'][method]==('reject' if truth else 'accept')
            streak=(streak+1 if prev is not None and r['index']==prev+1 else 1) if wrong else 0
            longest=max(longest,streak);prev=r['index']
        results.append(dict(epoch=list(key),parent=values[0]['parent'],n=len(values),n_labelled_primary=sum(primary(r,truth) for r in values),ever_accept=bool(accepted),
                            ever_false_accept=bool(any(primary(r,0) and r['decisions'][method]=='accept' for r in values)) if truth==0 else None,
                            first_accept_delay=None if not accepted else accepted[0]['timestamp']-values[0]['timestamp'],longest_error=longest))
    return dict(n=len(results),never_accepted=sum(not r['ever_accept'] for r in results),
                ever_false_accept=sum(r['ever_false_accept'] for r in results) if truth==0 else None,rows=results)


def evaluate(rows):
    main={m:six_cells(rows,m) for m in METHODS}
    eligible={m:six_cells([r for r in rows if r['accept_eligible'] or r['reject_eligible']],m) for m in METHODS}
    native={}
    for truth,label in [(1,'true'),(0,'false')]:
        subset=[r for r in rows if primary(r,truth)];w=weights(subset,truth)
        native[label]=dict(n=len(subset),adopted=sum(r['native_adopted'] for r in subset),weighted_adoption=float(sum(v for r,v in zip(subset,w) if r['native_adopted'])) if subset else None)
    strata={}
    for field in ('attack_k','family','common_group','C_positive','m','parent'):
        strata[field]={str(v):{m:six_cells([r for r in rows if r[field]==v],m) for m in METHODS} for v in sorted({r[field] for r in rows},key=str)}
    nll={}
    for method in kernel.METHODS:
        subset=[r for r in rows if primary(r,1)]; weights_all=weights(subset,1)
        valid=[(r,w) for r,w in zip(subset,weights_all) if r['normal_loglik'].get(method) is not None]
        nll[method]=dict(n=len(valid),n_primary=len(subset),coverage_weight=float(sum(w for _,w in valid)),
                         window_nll=float(sum(-w*r['normal_loglik'][method] for r,w in valid)/sum(w for _,w in valid)) if valid else None)
    unknown=[r for r in rows if r['query_truth'] not in (0,1)]
    background=[r for r in rows if r['kind']=='attack' and r['query_truth']==1]
    occluder=[r for r in rows if r.get('attack_role')=='occluder']
    newborn=[r for r in rows if r.get('newborn')]
    deltas={}
    for truth in (0,1):
        subset=[r for r in rows if primary(r,truth)];w=weights(subset,truth)
        deltas[str(truth)]={}
        for field in ('delta_T','delta_F'):
            valid=[(r[field],v) for r,v in zip(subset,w) if r.get(field) is not None]
            deltas[str(truth)][field]=dict(n=len(valid),coverage_weight=float(sum(v for _,v in valid)),
                     weighted_mean=float(sum(x*v for x,v in valid)/sum(v for _,v in valid)) if valid else None,
                     quantiles=np.percentile([x for x,_ in valid],[0,25,50,75,100]).tolist() if valid else None)
    return dict(system_query=main,eligible=eligible,native_MATE=native,strata=strata,normal_probability=nll,state_delta=deltas,
                n_rows=len(rows),numeric_failure=sum(not r['finite'] for r in rows),unknown_labels=len(unknown),
                unknown_label_decisions={m:dict(Counter(r['decisions'][m] for r in unknown)) for m in METHODS},
                attack_true_background=dict(n=len(background),decisions={m:dict(Counter(r['decisions'][m] for r in background)) for m in METHODS}),
                auxiliary_occluder=dict(n=len(occluder),decisions={m:dict(Counter(r['decisions'][m] for r in occluder)) for m in METHODS}),
                newborn_system=dict(n=len(newborn),output_truth=dict(Counter(str(r['output_truth']) for r in newborn)),native_adopted=sum(r['native_adopted'] for r in newborn)),
                trajectories={m:{str(t):trajectories(rows,m,t) for t in (0,1)} for m in METHODS})


def paired_bootstrap(rows,repetitions=1000):
    parents=sorted({r['parent'] for r in rows}); byparent={p:[r for r in rows if r['parent']==p] for p in parents}
    rng=np.random.RandomState(0);pairs=(('C','D'),('T','C'),('J','T'),('J','G'))
    values={a+'-'+b:[] for a,b in pairs}
    if not parents:
        return dict(n_parents=0,description='no eval parents',intervals={})
    tables={}
    for parent,subset in byparent.items():
        table={}
        for truth in (0,1):
            selected=[r for r in subset if primary(r,truth)]
            layers=sorted({(r['family'],r['attack_k']) for r in selected})
            for layer in layers:
                group=[r for r in selected if (r['family'],r['attack_k'])==layer]
                w=weights(group,truth)
                table[(truth,layer)]={m:float(sum(v for r,v in zip(group,w) if r['decisions'][m]==('accept' if truth else 'reject'))) for m in kernel.METHODS}
        tables[parent]=table
    for _ in range(repetitions):
        sampled=[tables[parents[i]] for i in rng.randint(len(parents),size=len(parents))]
        classes={}
        for truth in (0,1):
            layers=sorted({layer for table in sampled for t,layer in table if t==truth})
            classes[truth]={m:float(np.mean([np.mean([table[(truth,layer)][m] for table in sampled if (truth,layer) in table]) for layer in layers])) if layers else None for m in kernel.METHODS}
        metric={m:None if classes[0][m] is None or classes[1][m] is None else (classes[0][m]+classes[1][m])/2 for m in kernel.METHODS}
        for a,b in pairs:
            if metric[a] is not None and metric[b] is not None:
                values[a+'-'+b].append(metric[a]-metric[b])
    return dict(n_parents=len(parents),repetitions=repetitions,seed=0,description='paired development-parent descriptive stability, not risk certification',
                intervals={k:dict(n=len(v),percentile95=np.percentile(v,[2.5,97.5]).tolist() if v else None) for k,v in values.items()})


def method_decisions(metrics):
    eva=metrics['system_query'];prob=metrics['normal_probability']
    def compare(a,b):
        x,y=eva[a],eva[b];nx,ny=prob[a]['window_nll'],prob[b]['window_nll']
        estimable=nx is not None and ny is not None and x['correct_definite'] is not None and y['correct_definite'] is not None
        risk=estimable and x['true']['weighted']['reject']<=.05 and x['false']['weighted']['accept']<=.05
        return dict(retain_increment=bool(risk and nx<ny and x['correct_definite']>y['correct_definite']),
                    comparison_estimable=estimable,rule='lower clean window NLL, higher correct definite, and both development empirical risks <=5%; no eval retuning')
    return dict(proxy_vs_direct=compare('C','D'),temporal_vs_static=compare('T','C'),joint_vs_temporal=compare('J','T'),
                joint_vs_group=dict(retain_increment=bool(eva['J']['correct_definite'] is not None and eva['G']['correct_definite'] is not None and eva['J']['correct_definite']>eva['G']['correct_definite']
                      and eva['J']['true']['weighted']['reject']<=.05 and eva['J']['false']['weighted']['accept']<=.05)))


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


def report(out):
    out=Path(out)
    if not (out/'score.complete.json').exists():
        raise RuntimeError('score incomplete')
    if (out/'report.complete.json').exists():
        raise FileExistsError('report already complete')
    spec=json.loads((out/'manifest.json').read_text());fitted=json.loads((out/'models.json').read_text())
    expected_layers={(j['family'],j['attack_k']) for j in spec['jobs'] if j['kind']=='attack' and j['split']=='cal'}
    reports={};main_rows=[]
    for name,_,_ in json.loads((out/'score.complete.json').read_text())['variants']:
        rows=[]
        for job in spec['jobs']:
            path=out/'scores'/name/(job['job_id']+'.jsonl.gz')
            if path.exists():
                rows.extend(data.read_rows(path))
        cal=[r for r in rows if r['split']=='cal'];policies={m:calibrate(cal,m,expected_layers) for m in METHODS}
        for row in rows:
            row['decisions']={m:decide(row,m,policies[m]) for m in METHODS}
        metrics={split:evaluate([r for r in rows if r['split']==split]) for split in ('cal','eval')}
        reports[name]=dict(metrics=metrics,policies=policies,method_decisions=method_decisions(metrics['eval']))
        if name=='main':
            main_rows=rows
            reports[name]['bootstrap']=paired_bootstrap([r for r in rows if r['split']=='eval'])
        else:
            del rows
    destination=out/'report';destination.mkdir(exist_ok=True)
    # Report is pure transformation. On an interruption retain completed files.
    metrics=dict(variants=reports,rho=fitted['rho_fit'],model_support=fitted['models']['diagnostics'],
                 method_status=fitted['method_status'],attack_tasks={j['job_id']:json.loads((out/'jobs'/j['job_id']/'complete.json').read_text()) for j in spec['jobs'] if j['kind']=='attack'},
                 code=data.code_record(),MATE_policy='mean minus 0.5 under the same calibrated decision policy; native adoption reported separately')
    if not (destination/'metrics.json').exists():
        data.atomic_json(destination/'metrics.json',metrics)
    if not (destination/'predictions.jsonl.gz').exists():
        with data.atomic_rows(destination/'predictions.jsonl.gz') as write:
            for row in main_rows:
                write(row)
    ordered=sorted([r for r in main_rows if r['split']=='eval'],key=lambda r:(str(r['key'][0]),r['key'][1],r['key'][2]))
    cases=dict(common_group=[r for r in ordered if r['common_group']][:12],
               J_T_different=[r for r in ordered if r['decisions']['J']!=r['decisions']['T']][:12])
    cases['T_accept_J_other']=[r for r in ordered if r['decisions']['T']=='accept' and r['decisions']['J']!='accept'][:12]
    cases['J_accept_T_other']=[r for r in ordered if r['decisions']['J']=='accept' and r['decisions']['T']!='accept'][:12]
    if not (destination/'cases.json').exists():
        selected={tuple(r['key']) for group in cases.values() for r in group}
        details={}
        for job in spec['jobs']:
            if not any(key[0]==job['job_id'] for key in selected):
                continue
            for window in kernel.windows(data.read_rows(out/'jobs'/job['job_id']/'rows.jsonl.gz'),10):
                key=tuple(window[-1]['key'])
                if key in selected:
                    details[key]=dict(row=data.compact(window[-1]),diagnostics=kernel.score_window(window,fitted['models'],fitted['rho']))
        cases={name:[dict(prediction=r,**details[tuple(r['key'])]) for r in group] for name,group in cases.items()}
        data.atomic_json(destination/'cases.json',cases)
    if not (destination/'six_cells.png').exists():
        plot_six(destination,reports['main']['metrics'])
    if not (destination/'summary.md').exists():
        lines=['# 时序条件联合核验开发结果','','14个已使用开发父录制。此结果不是独立未见评估，也不提供风险保证。',
               '主参数 W=10，s=0.9。门限只取cal，敏感性分别重新cal，不按eval挑选。',
               '主假风险只统计target，F3辅助occluder单列。未实现攻击和未知标签保留任务分母。','',
               '| 方法 | 真采纳 | 真拒绝 | 假采纳 | 假拒绝 | correct definite |','|---|---:|---:|---:|---:|---:|']
        for method in METHODS:
            m=reports['main']['metrics']['eval']['system_query'][method]
            vals=[m['true']['weighted']['accept'],m['true']['weighted']['reject'],m['false']['weighted']['accept'],m['false']['weighted']['reject'],m['correct_definite']]
            lines.append('| '+method+' | '+' | '.join('NA' if v is None else '%.4f'%v for v in vals)+' |')
        lines+=['','组件不可估状态及共同数值失败见metrics.json；不可估方法保留unknown，不删共同分母。',
                '主方法裁决仅按预声明开发标准记录，不自动重选参数或追加攻击。','', '```json',json.dumps(reports['main']['method_decisions'],ensure_ascii=False,indent=2),'```']
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
