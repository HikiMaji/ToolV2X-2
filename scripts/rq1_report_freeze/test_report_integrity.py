"""Temporary saved-report fixtures only; no real batch or score generation."""
import copy
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest

METHODS=('Count','CountQ','D_old','D_zero','I_zero','J_zero','G_zero','Q_zero','MATE_policy')


def row():
    return dict(kind='clean',query_truth=1,query_present=True,newborn=False,finite=True,error=None,
                accept_eligible=False,reject_eligible=False,output_present=False,native_mean=None,native_adopted=False,
                scores={m:None for m in METHODS},method_status={m:dict(status='unavailable') for m in METHODS},decisions={m:'unknown' for m in METHODS})


def raw_coverage(rows,method):
    return dict(n_total=len(rows),n_finite=sum(r['scores'][method] is not None and math.isfinite(r['scores'][method]) for r in rows),numeric_failures=0,states={'unavailable':len(rows)},
                primary=dict(n_total=len(rows),n_missing_score=len(rows),n_failed=len(rows),states={'unavailable':len(rows)}))


def report_fixture():
    rows=[row(),row()];rows[1].update(reject_eligible=True)
    states={m:dict(status='reference' if m=='MATE_policy' else 'ok') for m in METHODS}
    cells={m:dict(true=dict(n=2,weighted=dict(accept=0.,unknown=1.,reject=0.)),false=dict(n=0,weighted=dict(accept=None,unknown=None,reject=None)),correct_definite=None) for m in METHODS}
    measurement=dict(method_score_coverage={m:raw_coverage(rows,m) for m in METHODS},system_query=cells,first_windows=dict(length_1=cells),by_parent=dict(parent=cells),family_k={'F1/1':dict(support={'parents':3,'entities':3})},paired_timeliness=dict(sentinel=[1,2,3]))
    retention={}
    for name in ('main','joint'):
        checks={}
        for method in ('D_zero','MATE_policy'):
            for prefix in ('primary_missing_score/','primary_failed/'):
                checks[prefix+method]=dict(value=2,limit=0.,status='fail',direction='max',denominator=measurement['method_score_coverage'][method]['primary'])
        checks.update(false_accept=dict(value=.01,limit=.05,status='pass'),CD_gain_over_Count=dict(value=.02,limit=.01,status='pass'))
        retention[name]=dict(candidate='D_zero' if name=='main' else 'J_zero',status='not_retained',risk_utility_status='not_retained',checks=checks)
    report=dict(method_status=states,metrics=dict(cal=copy.deepcopy(measurement),eval=copy.deepcopy(measurement)),retention=retention,
                policies={m:dict(A=1.,R=-1.) for m in METHODS},calibration=dict(missing_layers=[['F1',1]]),old_development_system_query=cells)
    return report,rows


class ReportIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.rq1_report_freeze import report_integrity
        cls.module=report_integrity

    def test_exact_expected_unknown_conditions_and_blocking_boundaries(self):
        base=row()
        self.assertEqual(self.module.expected_reason(base,'D_zero',dict(status='ok')),'no_common_decision_eligibility')
        base.update(reject_eligible=True)
        self.assertEqual(self.module.expected_reason(base,'MATE_policy',dict(status='reference')),'expected_reference_abstention')
        self.assertIsNone(self.module.expected_reason(base,'D_zero',dict(status='ok')))
        cases=[({'finite':False},'reference'),({'error':'failure'},'reference'),({'error':''},'reference'),({'native_mean':.2},'reference'),({'native_adopted':True},'reference'),({'output_present':True},'reference'),({},'ok'),({},'unestimable')]
        for changes,global_status in cases:
            with self.subTest(changes=changes,global_status=global_status):
                candidate=copy.deepcopy(base);candidate.update(changes)
                self.assertIsNone(self.module.expected_reason(candidate,'MATE_policy',dict(status=global_status)))
        for score in (float('nan'),float('inf'),-float('inf'),0.):
            candidate=copy.deepcopy(base);candidate['scores']['MATE_policy']=score
            self.assertIsNone(self.module.expected_reason(candidate,'MATE_policy',dict(status='reference')))
        for field in ('native_mean',):
            candidate=copy.deepcopy(base);candidate.pop(field)
            self.assertIsNone(self.module.expected_reason(candidate,'MATE_policy',dict(status='reference')))
        for location,key in [('scores','MATE_policy'),('decisions','MATE_policy')]:
            candidate=copy.deepcopy(base);candidate[location].pop(key)
            self.assertIsNone(self.module.expected_reason(candidate,'MATE_policy',dict(status='reference')))
        candidate=copy.deepcopy(base);candidate['method_status']['MATE_policy']['status']='numeric_failure'
        self.assertIsNone(self.module.expected_reason(candidate,'MATE_policy',dict(status='reference')))

    def test_only_integrity_checks_change_and_insufficient_stays(self):
        report,rows=report_fixture();before=copy.deepcopy(report)
        report['retention']['joint']['checks']['tasks_complete']=dict(value=0,limit=1,status='insufficient')
        report['retention']['main']['checks']['primary_missing_score/MATE_policy']['status']='insufficient'
        corrected=self.module.correct_report(report,dict(cal=rows,eval=rows))
        self.assertEqual(corrected['policies'],before['policies'])
        for split in ('cal','eval'):
            old=before['metrics'][split];new=corrected['metrics'][split]
            self.assertEqual({k:v for k,v in new.items() if k!='method_score_coverage'},{k:v for k,v in old.items() if k!='method_score_coverage'})
            mate=new['method_score_coverage']['MATE_policy']['primary']
            self.assertEqual(mate['n_missing_score'],2);self.assertEqual(mate['n_failed'],2)
            self.assertEqual(mate['n_missing_score_blocking'],0);self.assertEqual(mate['n_failed_blocking'],0)
            self.assertEqual(mate['expected_unknown_by_reason'],dict(no_common_decision_eligibility=1,expected_reference_abstention=1))
            self.assertEqual(new['method_score_coverage']['D_zero']['primary']['n_missing_score_blocking'],1)
        check=corrected['retention']['main']['checks']['primary_missing_score/MATE_policy']
        self.assertEqual(check['value'],0);self.assertEqual(check['status'],'insufficient')
        self.assertEqual(corrected['retention']['main']['checks']['false_accept'],before['retention']['main']['checks']['false_accept'])
        self.assertNotEqual(corrected['retention']['main']['risk_utility_status'],'retained')
        legal=copy.deepcopy(rows);legal[1]['reject_eligible']=False
        corrected=self.module.correct_report(before,dict(cal=legal,eval=legal))
        self.assertEqual(corrected['retention']['main']['status'],'retained')
        self.assertEqual(corrected['retention']['main']['risk_utility_status'],'retained')
        insufficient=copy.deepcopy(before)
        insufficient['retention']['main']['checks']['primary_failed/MATE_policy']['status']='insufficient'
        corrected=self.module.correct_report(insufficient,dict(cal=legal,eval=legal))
        self.assertEqual(corrected['retention']['main']['status'],'evidence_insufficient')
        self.assertEqual(corrected['retention']['main']['risk_utility_status'],'evidence_insufficient')
        guarded=copy.deepcopy(before);guarded['retention']['main']['checks']['estimable']=dict(status='fail',value=0.,limit=1.)
        corrected=self.module.correct_report(guarded,dict(cal=legal,eval=legal))
        self.assertEqual(corrected['retention']['main']['status'],'not_retained')

    def test_failed_and_explicit_error_rows_remain_blocking(self):
        report,rows=report_fixture()
        for field,value in [('finite',False),('error','explicit failure')]:
            altered=copy.deepcopy(rows);altered[0][field]=value
            # Keep the raw saved counts for finite=False (already unavailable).
            corrected=self.module.correct_report(report,dict(cal=altered,eval=altered))
            primary=corrected['metrics']['eval']['method_score_coverage']['MATE_policy']['primary']
            self.assertEqual(primary['n_missing_score_blocking'],1)
            self.assertEqual(primary['n_failed_blocking'],1)
            self.assertEqual(corrected['retention']['main']['status'],'not_retained')

    def test_revision_requires_complete_and_preserves_all_source_bytes(self):
        report,rows=report_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            with self.assertRaises(RuntimeError): self.module.revise(out)
            self.assertFalse((out/'report_corrected').exists())
            def write(path,value):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            write(out/'run.complete.json',dict(status='complete'))
            write(out/'binding.json',dict(config={'frozen':True},code=[]))
            metrics=dict(status='complete',regimes=dict(mixed=report),construction_coverage={'entities':24})
            write(out/'report/metrics.json',metrics);write(out/'report/mixed.json',report)
            (out/'report/summary.md').write_text('original summary\n')
            for split in ('cal','eval'):
                p=out/'predictions/mixed'/(split+'.jsonl.gz');p.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(p,'wt') as stream:
                    for r in rows: stream.write(json.dumps(r)+'\n')
            original={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
            complete=self.module.revise(out)
            self.assertEqual(complete['status'],'complete')
            for path,value in original.items(): self.assertEqual((out/path).read_bytes(),value)
            corrected=json.loads((out/'report_corrected/metrics.json').read_text())
            self.assertEqual(corrected['construction_coverage'],metrics['construction_coverage'])
            self.assertEqual(corrected['regimes']['mixed']['metrics']['eval']['system_query'],report['metrics']['eval']['system_query'])
            self.assertEqual(self.module.revise(out),complete)
            manifest=json.loads((out/'report_corrected/source_manifest.json').read_text())
            self.assertTrue(manifest['numerical_code_commit'].startswith('4b90295'))
            self.assertTrue((out/'report_corrected/revision.complete.json').is_file())


if __name__=='__main__': unittest.main()
