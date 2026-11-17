import copy
import itertools
import math
from pathlib import Path
import tempfile
import unittest

from scripts import rq1_joint_supplement as module
from test_rq1_independent_supplement import row


def online(i, u=(1, 0), groups=((0, 1),)):
    return dict(key=['job',i,1],job_id='job',id=1,epoch=0,index=i,frame=i,
                timestamp=i*.1,source_ids=list(range(len(u))),U=list(u),
                X=[[0.]*5 for _ in u],C=[None]*len(u),C_missing=[True]*len(u),
                groups=[list(g) for g in groups],query_present=True,newborn=False,
                output_present=True,identity_ok=True)


MODEL=dict(mean=[0.]*7,scale=[1.]*7,coef=[0.]*7,intercept=math.log(4.))


class JointTest(unittest.TestCase):
    def test_external_unrealizable_status_is_used_without_hiding_missing_complete_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'scores';external=root/'external'
            job=dict(job_id='external',split='cal',rows_path=str(external/'rows.jsonl.gz'),
                     status_path=str(external/'complete.json'))
            module.freeze.save(source/'manifest.json',dict(jobs=[job]))
            module.data.atomic_json(external/'complete.json',dict(status='UNREALIZABLE'))
            config=dict(source_scores=str(source))
            self.assertEqual(list(module.raw_jobs(config,'cal')),[])
            (external/'complete.json').write_text('{"status":"COMPLETE"}')
            with self.assertRaises(FileNotFoundError):
                module.source_records(config,'cal',MODEL,.25)

    def test_distribution_and_unknown_marginalization(self):
        p=[.3,.8,.6];groups=[[0,1,2]]
        mass=sum(math.exp(module.log_probability(u,p,groups,.75))
                 for u in itertools.product((0,1),repeat=3))
        self.assertAlmostEqual(mass,1.)
        expected=sum(math.exp(module.log_probability([1,z,0],p,groups,.75)) for z in (0,1))
        self.assertAlmostEqual(math.exp(module.log_probability([1,-1,0],p,groups,.75)),expected)
        self.assertAlmostEqual(math.exp(module.log_probability([-1,1,-1],p,groups,.75)),.8)

    def test_zero_singleton_pure_report_and_effect_direction(self):
        for rho in (0.,.5,.9):
            self.assertAlmostEqual(module.combination([1,0],[.8,.8],[[0],[1]],rho)['Joint'],-math.log(.2))
            self.assertEqual(module.combination([1,1],[.8,.8],[[0,1]],rho)['Joint'],0.)
        ind=module.combination([0,0],[.8,.8],[[0,1]],0.)['Joint']
        self.assertLess(module.combination([0,0],[.8,.8],[[0,1]],.5)['Joint'],ind)
        self.assertGreater(module.combination([1,0],[.8,.8],[[0,1]],.5)['Joint'],-math.log(.2))
        self.assertAlmostEqual(module.combination([1,0],[.8,.8],[[0,1]],0.)['Group'],-math.log(.2)/2)

    def test_invalid_events_partition_and_numeric_failure(self):
        for u,groups in (([2,0],[[0,1]]),([1,0],[[0],[0]])):
            with self.assertRaises(ValueError):module.combination(u,[.8,.8],groups,.5)
        with self.assertRaises(ValueError):module.combination([1,0],[.8,float('nan')],[[0,1]],.5)
        self.assertTrue(math.isfinite(module.combination([0]*100,[1.]*100,[list(range(100))],.9)['Joint']))

    def test_windows_are_causal_label_free_and_reset(self):
        rows=[online(i) for i in range(12)]
        first=module.window_records(rows,MODEL,.5)
        changed=copy.deepcopy(rows)
        for r in changed:r.update(query_truth=0,family='F2',attack_k=99,parent='hidden')
        self.assertEqual(first,module.window_records(changed,MODEL,.5))
        self.assertEqual(first[tuple(rows[-1]['key'])]['n_frames'],10)
        changed[-1]['timestamp']+=1
        self.assertEqual(module.window_records(changed,MODEL,.5)[tuple(changed[-1]['key'])]['n_frames'],1)

    def test_global_budget_zero_exact_and_failure_fallback(self):
        rows=[row(i,decision='accept') for i in range(100)]
        for i,r in enumerate(rows):
            r['reject_eligible']=i<4;r['scores']['Cond']=float(i<4)
            r['decisions']['Cond']='reject' if i<2 else 'accept'
            r['supplement_scores'].update(Group=float(i%4+1),Joint=r['scores']['Cond'])
        policies={m:module.supplement.calibrate(rows,m) for m in module.BRANCHES}
        self.assertAlmostEqual(policies['Group']['added_true_reject_weight'],.02)
        result=module.apply(rows,policies,0.)
        self.assertTrue(all(r['decisions']['Joint']==r['decisions']['Cond'] and
                            r['scores']['Joint']==r['scores']['Cond'] for r in result))
        fail=row(101,decision='accept');fail['supplement_scores'].update(Group=None,Joint=None)
        fail['decisions']['Cond']='accept';fail['scores']['Cond']=None
        module.apply([fail],{m:dict(status='active',tau=1.) for m in module.BRANCHES},.5)
        self.assertEqual(fail['decisions']['Joint'],'accept')

    def test_fit_weights_ties_and_uninformative_status(self):
        records=[]
        for parent,n in (('a',1),('b',3)):
            for i in range(n):
                r=online(i,u=(1,));r.update(parent=parent,kind='clean',query_truth=1,job_id=parent)
                records.append((r,dict(u=[1],p=[.8],groups=[[0]])))
        fitted=module.fit_records(records,[0.,.25,.5,.75,.9])
        self.assertEqual(fitted['rho'],0.)
        self.assertEqual(fitted['status'],'no_identifying_groups')
        self.assertAlmostEqual(fitted['by_parent']['a']['weight'],.5)
        self.assertAlmostEqual(fitted['by_parent']['b']['weight'],.5)
        self.assertEqual(module.fit_records([], [0.,.25])['status'],'unestimable')

    def test_control_risk_is_a_retention_gate_and_raw_metadata_is_checked(self):
        def cells(cd,reject=.01):
            return dict(correct_definite=cd,true=dict(weighted=dict(accept=.9,reject=reject)),
                        false=dict(weighted=dict(accept=.01)))
        measurement=dict(system_query={'Cond':cells(.8),'Group':cells(.8,.1),'Joint':cells(.9)},
            paired_timeliness={'Joint':dict(never_difference=0.,weighted_median_delay_difference_seconds=0.)},
            transitions={'Joint':{'0':dict(cells={'unknown/reject':dict(n=1)})}},family_k={})
        verdict=module.judge(measurement,{'Joint':dict(status='active')},.5,[])
        self.assertEqual(verdict['status'],'not_retained')
        self.assertEqual(verdict['checks']['control_risk_Group']['status'],'fail')
        raw=online(0);records=module.window_records([raw],MODEL,.5)
        predicted=dict(raw,n_frames=1,scores={'Cond':-math.log(.2)})
        predicted['epoch']=1
        with self.assertRaisesRegex(ValueError,'metadata differs epoch'):module.attach([predicted],records,.5)

    def test_synthetic_fit_evaluate_preserves_old_and_skips_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);scores=root/'scores';report=root/'report';ind=root/'ind';out=root/'out'
            config=dict(window=10,rho_grid=[0,.25,.5,.75,.9],source_scores=str(scores),
                        source_report=str(report),source_independent=str(ind),source_normal_models=str(root/'normal.json'),
                        old_parent_splits={p:'fit' for p in ('p0','p1','p2','p3','p4','p5')})
            module.freeze.save(root/'config.json',config);(root/'SDS.md').write_text('synthetic frozen SDS')
            model=copy.deepcopy(MODEL);model['train_parents']=list(config['old_parent_splits'])
            module.freeze.save(root/'normal.json',dict(models={'D':model}))
            raw_jobs=[];folds=[]
            for parent in model['train_parents']:
                raw=online(0,u=(1,),groups=((0,),));raw.update(job_id=parent,key=[parent,0,1],parent=parent,split='fit',kind='clean',query_truth=1)
                path=scores/'jobs'/parent/'rows.jsonl.gz';module.freeze.rows_once(path,[raw])
                raw_jobs.append(dict(job_id=parent,parent=parent,split='fit',kind='clean',rows_path=str(path)))
                train=[p for p in model['train_parents'] if p!=parent];held_model=dict(model,train_parents=train)
                normal='folds/'+parent+'/normal.json';module.freeze.save(scores/normal,dict(models={'D':held_model},held_parent=parent,train_parents=train))
                folds.append(dict(parent=parent,normal=normal,train_parents=train))
            module.freeze.save(scores/'features.complete.json',dict(folds=folds))
            bundle=dict(models={'Count':dict(mean=[0.]*5,scale=[1.]*5,coef=[0.]*5,intercept=1.)},method_status={'Count':{'status':'ok'}})
            count_policy=dict(A=.5,R=-.5);cond_policy=dict(status='active',tau=100.,base_true_reject=0.,delta=.02,added_true_reject_weight=0.)
            predictions={};eval_jobs=[]
            for split in ('cal','eval'):
                raw=[]
                for i in range(100):
                    r=online(i,u=(1,1,0),groups=((0,),(1,),(2,)))
                    r.update(job_id=split,key=[split,i,1],parent=split,split=split,kind='clean',family='clean',attack_k=0,
                             query_truth=1,attack_role=None,origin='synthetic')
                    raw.append(r)
                path=(scores if split=='cal' else report)/'jobs'/split/'rows.jsonl.gz';module.freeze.rows_once(path,raw)
                job=dict(job_id=split,parent=split,split=split,kind='clean',rows_path=str(path))
                (raw_jobs if split=='cal' else eval_jobs).append(job)
                features=[]
                for window in module.kernel.windows(raw,10):
                    feature={k:window[-1].get(k) for k in module.legacy.METADATA}
                    feature.update(module.heads.window_features(window,{'D':model},0.));features.append(feature)
                module.freeze.rows_once((scores if split=='cal' else report)/'features'/split/(split+'.jsonl.gz'),features)
                predictions[split]=module.new_predictions(features,bundle,count_policy,cond_policy)
            module.freeze.save(scores/'manifest.json',dict(jobs=raw_jobs))
            regimes={r:dict(eval_false=['F1','F2'] if r=='mixed' else ['F2'] if r=='F1_only' else ['F1']) for r in module.REGIMES}
            module.freeze.save(report/'manifest.json',dict(jobs=eval_jobs,config=dict(regimes=regimes)))
            for regime in module.REGIMES:
                module.freeze.save(report/'models'/(regime+'.json'),bundle)
                module.freeze.save(report/'calibration'/(regime+'.json'),dict(policies={'Count':count_policy},expected_layers=[['F1',1],['F2',1]]))
                module.freeze.save(ind/'calibration'/(regime+'.json'),dict(branches={'Cond':cond_policy},source_calibration_sufficient=False,observed_layers=[],missing_layers=[['F1',1]]))
                for split,rows in predictions.items():module.freeze.rows_once(ind/'predictions'/regime/(split+'.jsonl.gz'),rows)
            fitted=module.fit(root/'config.json',out)
            self.assertEqual(fitted['rho'],0.)
            summary=module.evaluate(root/'config.json',out)
            self.assertEqual(summary['additional_status'],'skipped_structural_zero')
            saved=list(module.data.read_rows(out/'predictions/existing/F1_only/eval.jsonl.gz'))
            self.assertEqual(len(saved),100)
            self.assertEqual(saved[0]['scores']['Cond'],saved[0]['scores']['Joint'])
            self.assertEqual(saved[0]['decisions']['Cond'],saved[0]['decisions']['Joint'])
            self.assertEqual(module.freeze.read(out/'report/existing/mixed.json')['baseline_reproduction']['cal']['status'],'pass')


if __name__=='__main__':unittest.main()
