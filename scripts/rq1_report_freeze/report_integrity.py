"""Revise only saved report integrity guards after the frozen run has ended."""
import argparse
from collections import Counter
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path

REVISION='rq1_expected_unknown_v1'
NUMERICAL_CODE_COMMIT='4b90295c48abdf73c5e42855e05f930fc2fbdc2a'
SPEC=Path(__file__).resolve().parents[2]/'docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/report_integrity_revision.md'
HEALTHY=('ok','reference')


def expected_reason(row,method,global_state):
    """The two predeclared no-score Unknown cases; never infer missing fields."""
    state=row.get('method_status',{}).get(method,{})
    scores=row.get('scores',{})
    if (global_state.get('status') not in HEALTHY or row.get('finite') is not True
            or method not in scores or scores[method] is not None
            or state.get('status')!='unavailable' or row.get('error') is not None
            or state.get('error') is not None or row.get('decisions',{}).get(method)!='unknown'):
        return None
    if row.get('accept_eligible') is False and row.get('reject_eligible') is False:
        return 'no_common_decision_eligibility'
    if (method=='MATE_policy' and global_state.get('status')=='reference'
            and row.get('output_present') is False and 'native_mean' in row
            and row['native_mean'] is None and row.get('native_adopted') is False):
        return 'expected_reference_abstention'
    return None


def _primary(row):
    if not row.get('query_present') or row.get('newborn'):
        return False
    return (row['kind']=='clean' and row['query_truth']==1 or
            row['kind']=='attack' and row['query_truth']==0 and row.get('attack_role')=='target')


def _missing(row,method):
    score=row['scores'].get(method)
    return score is None or not math.isfinite(score)


def _failed(row,method):
    return (not row.get('finite',False) or
            row.get('method_status',{}).get(method,{}).get('status','unavailable') not in HEALTHY)


def _coverage(original,rows,method,global_state):
    result=copy.deepcopy(original)
    observed=dict(n_total=len(rows),n_missing_score=sum(_missing(r,method) for r in rows),
                  n_failed=sum(_failed(r,method) for r in rows),
                  states=dict(Counter(r.get('method_status',{}).get(method,{}).get('status','unavailable') for r in rows)))
    if any(original[k]!=value for k,value in observed.items()):
        raise ValueError('saved primary coverage differs from predictions: '+method)
    expected=Counter();missing=failed=0
    for row in rows:
        reason=expected_reason(row,method,global_state)
        if reason:
            expected[reason]+=1
        else:
            missing+=_missing(row,method)
            # An explicit error must remain blocking even if its stored status is ok.
            failed+=bool(_failed(row,method) or row.get('error') is not None or
                         row.get('method_status',{}).get(method,{}).get('error') is not None)
    result.update(expected_unknown_by_reason=dict(expected),n_missing_score_blocking=missing,n_failed_blocking=failed)
    return result


def _verdict(checks):
    statuses={check['status'] for check in checks.values()}
    return 'not_retained' if 'fail' in statuses else 'evidence_insufficient' if 'insufficient' in statuses else 'retained'


def correct_report(report,predictions):
    """Copy a saved report, adding coverage fields and changing only guard results."""
    corrected=copy.deepcopy(report)
    for split in ('cal','eval'):
        rows=[r for r in predictions[split] if _primary(r)]
        coverage=corrected['metrics'][split]['method_score_coverage']
        for method,counts in coverage.items():
            counts['primary']=_coverage(counts['primary'],rows,method,report['method_status'][method])
    coverage=corrected['metrics']['eval']['method_score_coverage']
    for retention in corrected['retention'].values():
        checks=retention['checks']
        for name,check in checks.items():
            for prefix,field in [('primary_missing_score/','n_missing_score_blocking'),('primary_failed/','n_failed_blocking')]:
                if name.startswith(prefix):
                    method=name[len(prefix):]
                    if check.get('direction')!='max' or check['limit']!=0.:
                        raise ValueError('unexpected integrity guard '+name)
                    check['value']=coverage[method]['primary'][field]
                    if check['status']!='insufficient':
                        check['status']='pass' if check['value']<=check['limit']+1e-12 else 'fail'
        # The original utility snapshot precedes only the CD increment checks.
        retention['risk_utility_status']=_verdict({name:check for name,check in checks.items() if not name.startswith('CD_gain_over_')})
        retention['status']=_verdict(checks)
    return corrected


def _read(path):
    return json.loads(Path(path).read_text())


def _rows(path):
    with gzip.open(path,'rt') as stream:
        for line in stream:
            if line.strip(): yield json.loads(line)


def _record(path):
    path=Path(path).resolve();digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
    return dict(path=str(path),bytes=path.stat().st_size,sha256=digest.hexdigest())


def _write_once(path,content):
    path=Path(path)
    if path.exists():
        if path.read_bytes()!=content: raise ValueError('corrected artifact already differs: '+str(path))
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.partial');temp.write_bytes(content);temp.replace(path)


def _json_once(path,value):
    _write_once(path,(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def revise(out):
    """Write report_corrected only, after run.complete; preserve all source bytes."""
    out=Path(out).resolve();complete=out/'run.complete.json'
    if not complete.is_file() or _read(complete).get('status')!='complete':
        raise RuntimeError('original run.complete is required before report revision')
    for artifact in _read(complete).get('artifacts',[]):
        if not (out/artifact).is_file(): raise RuntimeError('original completed artifact missing: '+artifact)
    original=_read(out/'report/metrics.json');source_paths=[complete,out/'binding.json',out/'report/metrics.json',out/'report/summary.md']
    reports={}
    for regime,report in original['regimes'].items():
        path=out/'report'/(regime+'.json')
        if _read(path)!=report: raise ValueError('aggregate and individual original reports differ: '+regime)
        prediction_paths={split:out/'predictions'/regime/(split+'.jsonl.gz') for split in ('cal','eval')}
        source_paths += [path,*prediction_paths.values()]
        reports[regime]=correct_report(report,{split:_rows(p) for split,p in prediction_paths.items()})
    metrics=copy.deepcopy(original);metrics['regimes']=reports
    manifest=dict(report_revision=REVISION,numerical_code_commit=NUMERICAL_CODE_COMMIT,
                  source_files=[_record(p) for p in source_paths],
                  correction_code=_record(__file__),correction_spec=_record(SPEC),
                  numerical_code=[_record(Path(__file__).with_name(p)) for p in ('run.py','prepare.py')],
                  changes='only primary integrity coverage and guard-derived verdicts; saved scores and scientific statistics unchanged')
    destination=out/'report_corrected'
    if destination.is_symlink(): raise ValueError('report_corrected cannot be a symlink')
    _json_once(destination/'source_manifest.json',manifest)
    for regime,report in reports.items(): _json_once(destination/(regime+'.json'),report)
    _json_once(destination/'metrics.json',metrics)
    # Reuse the original formatter; it only formats already saved statistics.
    from .run import summary
    text='# 报告完整性修正 '+REVISION+'\n\n数值代码保持 '+NUMERICAL_CODE_COMMIT+'。只修正合法无分数Unknown的完整性统计和派生裁决。\n\n'+summary(metrics)
    _write_once(destination/'summary.md',text.encode())
    artifacts=['source_manifest.json','metrics.json','summary.md']+[regime+'.json' for regime in reports]
    marker=dict(status='complete',report_revision=REVISION,numerical_code_commit=NUMERICAL_CODE_COMMIT,
                meaning='saved_report_integrity_revision_only',artifacts=artifacts,
                retention={r:{name:value['status'] for name,value in report['retention'].items()} for r,report in reports.items()})
    _json_once(destination/'revision.complete.json',marker)
    return marker


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='completed original run directory; writes its report_corrected child only')
    args=parser.parse_args(argv);revise(args.out)


if __name__=='__main__': main()
