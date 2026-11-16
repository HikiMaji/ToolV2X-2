import copy
from pathlib import Path
import tempfile
import unittest

from scripts import rq1_independent_supplement as module


def row(i, score=0., decision='unknown'):
    return dict(key=['job',i,1], job_id='job', frame=i, id=1, epoch=0,
                parent='parent', index=i, timestamp=i*.1, split='cal',
                kind='clean', family='clean', attack_k=0, query_truth=1,
                query_present=True, newborn=False, finite=True,
                accept_eligible=True, reject_eligible=False,
                scores={'Count':1.,'D_zero':1.},
                decisions={'Count':decision,'D_zero':decision},
                method_status={'Count':{'status':'ok'}},
                supplement_scores={m:score for m in module.BRANCHES})


class SupplementTest(unittest.TestCase):
    def test_global_budget_and_strict_ties(self):
        rows=[row(i) for i in range(100)]
        for i,s in enumerate([1.,2.,3.,3.]):
            rows[i]['reject_eligible']=True
            rows[i]['supplement_scores']['Cond']=s
        policy=module.calibrate(rows,'Cond')
        self.assertEqual(policy['tau'],2.)
        self.assertAlmostEqual(policy['added_true_reject_weight'],.02)
        self.assertEqual(module.decide('unknown',True,True,False,True,2.,policy)['decision'],'unknown')
        self.assertEqual(module.decide('unknown',True,True,False,True,3.,policy)['decision'],'reject')

    def test_basetail_keeps_signed_threshold(self):
        rows=[row(i) for i in range(100)]
        for i,s in enumerate([-3.,-2.,-1.]):
            rows[i]['reject_eligible']=True
            rows[i]['supplement_scores']['BaseTail']=s
        policy=module.calibrate(rows,'BaseTail')
        self.assertEqual(policy['tau'],-3.)
        self.assertAlmostEqual(policy['added_true_reject_weight'],.02)

    def test_budget_exhaustion_and_candidate_failure_close_branch(self):
        rows=[row(i,decision='reject' if i<5 else 'unknown') for i in range(100)]
        self.assertEqual(module.calibrate(rows,'Cond')['reason'],'no_remaining_budget')
        rows=[row(i) for i in range(100)]
        rows[0]['reject_eligible']=True
        rows[0]['supplement_scores']['Cond']=None
        policy=module.calibrate(rows,'Cond')
        self.assertEqual(policy['status'],'disabled')
        self.assertEqual(policy['n_clean_primary'],100)
        self.assertEqual(policy['reason'],'candidate_score_failure')

    def test_failure_and_disabled_fallback_without_label_inputs(self):
        active=dict(status='active',tau=1.)
        self.assertEqual(module.decide('reject',False,True,False,True,None,active)['decision'],'reject')
        self.assertEqual(module.decide('unknown',False,True,False,True,9.,active)['decision'],'unknown')
        self.assertEqual(module.decide('accept',True,True,False,True,None,active)['decision'],'accept')
        self.assertEqual(module.decide('accept',True,True,False,True,9.,dict(status='disabled'))['decision'],'accept')
        self.assertEqual(module.decide('accept',True,False,True,True,9.,active)['decision'],'accept')
        failed=row(1,9.);failed.update(error='shared feature failure',reject_eligible=True)
        policies={m:active for m in module.BRANCHES}
        result=module.apply([failed],policies)[0]
        for method in module.BRANCHES:
            self.assertEqual(result['decisions'][method],'unknown')
            self.assertEqual(result['supplement_status'][method],'base_failure')

    def test_scores_join_all_rows_and_validate_count_inputs(self):
        r=row(1);r.update(context=[1,1,0],n_minus=[1],w=1,d=1,m=0,Count_inputs=[0,1,1,1,0])
        feature=copy.deepcopy(r);feature['features']={'D_head':[0.,-2.,0.,1.,1.,0.]}
        unknown=copy.deepcopy(r);unknown.update(key=['job',2,1],frame=2,query_truth=-1,kind='attack',family='F1')
        other=copy.deepcopy(feature);other.update(key=unknown['key'],frame=2,query_truth=-1,kind='attack',family='F1')
        joined=module.join_features([r,unknown],[feature,other])
        self.assertEqual(len(joined),2)
        self.assertEqual(joined[1]['supplement_scores'],{'Cond':2.,'MissCount':1.,'BaseTail':-1.})
        feature['features']['D_head'][2]=1.
        with self.assertRaisesRegex(ValueError,'Count inputs'):
            module.join_features([r],[feature])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            module.join_features([r,r],[feature])

    def test_predictions_ignore_labels_and_preserve_accept_subset(self):
        r=row(1,9.,'accept');r['reject_eligible']=True
        policies={m:dict(status='active',tau=1.) for m in module.BRANCHES}
        first=module.apply([copy.deepcopy(r)],policies)[0]
        r.update(query_truth=-1,family='F2',attack_k=99,parent='other')
        second=module.apply([r],policies)[0]
        for m in module.BRANCHES:
            self.assertEqual(first['decisions'][m],second['decisions'][m])
            self.assertEqual(second['decisions'][m],'reject')

    def test_synthetic_pipeline_preserves_baselines_missing_layers_and_empty_time_support(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';features=root/'normal_features'
            spec=root/'SDS.md';spec.write_text('frozen synthetic fixture')
            module.data.atomic_json(source/'manifest.json',dict(config=dict(source_features=str(features))))
            rows=[row(i) for i in range(100)]
            for i,r in enumerate(rows):
                r.update(context=[1,1,0],n_minus=[1],w=1,d=1,m=0,n_frames=1,
                         Count_inputs=[0.,1.,1.,1.,0.],reject_eligible=i<4)
            fake=copy.deepcopy(rows[0]);fake.update(key=['attack',0,1],job_id='attack',
                kind='attack',family='F1',attack_k=1,attack_role='target',query_truth=0)
            rows.append(fake)
            for split in ('cal','eval'):
                split_rows=copy.deepcopy(rows)
                for r in split_rows:r['split']=split
                directory=features/'cal' if split=='cal' else source/'features/eval'
                for job in ('job','attack'):
                    with module.data.atomic_rows(directory/(job+'.jsonl.gz')) as write:
                        for r in split_rows:
                            if r['job_id']==job:
                                feature=copy.deepcopy(r);feature['features']={'D_head':[0.,-float(r['index']%4+1),0.,1.,1.,0.]}
                                write(feature)
                for regime in module.REGIMES:
                    with module.data.atomic_rows(source/'predictions'/regime/(split+'.jsonl.gz')) as write:
                        for r in split_rows:write(r)
            for regime in module.REGIMES:
                module.data.atomic_json(source/'calibration'/(regime+'.json'),dict(
                    calibration_sufficient=False,observed_layers=[['F1',1]],
                    expected_layers=[['F1',1],['F1',3]],missing_layers=[['F1',3]]))
                expected={m:module.original.six_cells(module.freeze.table(rows,m),'D') for m in ('Count','D_zero')}
                module.data.atomic_json(source/'report_corrected'/(regime+'.json'),dict(metrics={s:dict(system_query=expected) for s in ('cal','eval')}))
            result=module.run(source,root/'out',spec)
            self.assertEqual(result['status'],'complete')
            report=module.freeze.read(root/'out/report/mixed.json')
            self.assertEqual(report['baseline_reproduction']['eval']['Count']['status'],'pass')
            self.assertEqual(report['metrics']['eval']['family_k']['F1/3']['status'],'not_tested')
            self.assertEqual(report['retention']['branches']['Cond']['checks']['paired_delay']['status'],'insufficient')
            saved=list(module.data.read_rows(root/'out/predictions/mixed/eval.jsonl.gz'))
            self.assertEqual(len(saved),101)
            self.assertIn('supplement_status',saved[-1])


if __name__=='__main__':
    unittest.main()
