"""Clarify multi-miss mixed groups; derivative signs only, no rho or threshold choice."""
import json
import math
from pathlib import Path
import sys

ROOT=Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-score-revision-2026-11-13')
sys.path.insert(0,str(ROOT/'scripts'))
import rq1_evidence_scope_audit as audit

OUT=Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_evidence_scope_audit_2026_11_16/run_001')
source=audit.SOURCE
manifest=audit.read(source/'manifest.json')
old=Path(manifest['config']['source_original_scores'])
model=audit.read(manifest['config']['source_normal_models'])['models']['D']
jobmap={j['job_id']:j for j in manifest['jobs']+audit.read(old/'manifest.json')['jobs']}
flags=('multiple_misses','mixed_multiple_misses','strengthening','weakening')
report={'scope':'same-p_D group conditional-score derivative signs; not estimated dependency or effect', 'splits':{}}

def annotate(stream):
    for row in audit.annotate(stream,model):
        u,p,_=row['_audit'];f={k:False for k in flags}
        for g in row['groups']:
            ones=[i for i in g if u[i]==1];zeros=[i for i in g if u[i]==0]
            f['multiple_misses'] |= len(zeros)>=2
            f['mixed_multiple_misses'] |= bool(ones) and len(zeros)>=2
            if not zeros or len(ones)+len(zeros)<2:continue
            bp=math.prod(p[i] for i in ones);ba=bp*math.prod(1-p[i] for i in zeros)
            kp=min((p[i] for i in ones),default=1.)
            ka=max(0.,kp-max(p[i] for i in zeros))
            left,right=ka*bp,ba*kp
            if not math.isclose(left,right,rel_tol=1e-12,abs_tol=0.):
                f['strengthening' if left<right else 'weakening']=True
        row['_joint_scope']=f
        yield row

for split in ('cal','eval'):
    chosen={tuple(r['key']):r for r in audit.rows(OUT/('mixed_'+split+'_joined.jsonl.gz'))
            if r['eligible'] and r['decision']!='reject'}
    seen=set()
    for jid in sorted({r['job_id'] for r in chosen.values()}):
        job=jobmap[jid];base=source if split=='eval' else old
        path=Path(job.get('rows_path',base/'jobs'/jid/'rows.jsonl.gz'))
        for win in audit.windows(annotate(audit.rows(path)),10):
            key=tuple(win[-1]['key'])
            if key not in chosen:continue
            chosen[key].update({k:any(r['_joint_scope'][k] for r in win) for k in flags})
            seen.add(key)
    assert seen==set(chosen)
    report['splits'][split]={}
    for truth,name in ((1,'true'),(0,'false')):
        group=[r for r in chosen.values() if r['query_truth']==truth]
        report['splits'][split][name]={k:dict(n=sum(r[k] for r in group),mass=math.fsum(r['mass'] for r in group if r[k]),
                parents=len({r['parent'] for r in group if r[k]}),
                entities=len({r['job_id'] for r in group if r[k]}) if truth==0 else None) for k in flags}
        if truth==0:
            report['splits'][split][name]['by_family_k']={f'{f}/{k}':{flag:dict(n=sum(r[flag] for r in group if (r['family'],r['attack_k'])==(f,k)),
                  mass=math.fsum(r['mass'] for r in group if (r['family'],r['attack_k'])==(f,k) and r[flag])) for flag in flags}
                  for f,k in sorted({(r['family'],r['attack_k']) for r in group})}
target=OUT/'joint_multiplicity.json'
assert not target.exists()
target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
