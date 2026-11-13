"""New no-miss-constant contracts, using synthetic features and real fitting."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scripts.rq1_score_revision import heads, run as legacy
from scripts.rq1_temporal import data, run as original


def features(split='fit', parents=None):
    result=[]
    for parent in parents or ['p'+str(i) for i in range(6)]:
        for truth,family in [(1,'clean'),(0,'F1'),(0,'F2')]:
            jid=parent+'_'+split+'_'+family
            for i in range(4):
                w=i+1;d=2+i%2;m=2;q=.1 if truth else 3.
                sources=[[-.2*w,-q*w,w],[-.3*w,0.,w]]+([[0.,-q*w,0.]] if d==3 else [])
                x=np.r_[np.sum(sources,axis=0),[w,d,m]].tolist()
                result.append(dict(key=[jid,i,1],job_id=jid,id=1,epoch=0,parent=parent,
                    split=split,kind='clean' if truth else 'attack',family=family,
                    attack_k=0 if truth else 1,attack_role=None if truth else 'target',
                    origin='reference' if truth else 'score_revision',index=i,frame=i,timestamp=i*.1,
                    query_truth=truth,query_gt_id=1 if truth else None,output_truth=truth,
                    query_present=True,newborn=False,output_present=True,identity_ok=True,
                    native_mean=.8 if truth else .2,native_adopted=bool(truth),source_ids=list(range(d)),
                    context=[w,d,m],features={k:list(x) for k in heads.BASE_METHODS},
                    sources={k:copy.deepcopy(sources) for k in heads.BASE_METHODS},
                    method_status={k:dict(status='ok') for k in heads.BASE_METHODS},finite=True,
                    accept_eligible=True,reject_eligible=True,delta_T=(2*truth-1)*(i-1.5)))
    return result


def source_fixture(root, config):
    source=root/'source';fitrows=features();jobs=[]
    for split in ('cal','eval'):
        rows=features(split,[split])
        for jid in sorted({r['job_id'] for r in rows}):
            group=[r for r in rows if r['job_id']==jid];r=group[0]
            jobs.append({k:r[k] for k in ('job_id','split','parent','kind','family','attack_k','origin')})
            with data.atomic_rows(source/'features'/split/(jid+'.jsonl.gz')) as write:
                for r in group:write(r)
    folds=[]
    for parent in sorted({r['parent'] for r in fitrows}):
        rel='features/fit/'+parent+'.jsonl.gz';folds.append(dict(parent=parent,features=rel))
        with data.atomic_rows(source/rel) as write:
            for r in fitrows:
                if r['parent']==parent:write(r)
    manifest=dict(config=dict(parent_splits={**{p:'fit' for p in sorted({r['parent'] for r in fitrows})},'cal':'cal','eval':'eval'}),jobs=jobs)
    data.atomic_json(source/'manifest.json',manifest)
    for stage in ('prepare','fit','score','report'):
        data.atomic_json(source/(stage+'.complete.json'),dict(status='complete',jobs={j['job_id']:dict(status='COMPLETE',rows=4) for j in jobs}) if stage=='prepare' else dict(status='complete'))
    data.atomic_json(source/'features.complete.json',dict(status='complete',folds=folds))
    data.atomic_json(source/'support.json',dict(regimes={r:dict(data_support_met=True) for r in config['regimes']}))
    for regime,spec in config['regimes'].items():
        fitted=legacy.fit_regime(fitrows,spec['fit_false']);fitted.update(data_support_met=True,status='fitted')
        data.atomic_json(source/'models'/(regime+'.json'),fitted)
        scored={split:legacy._domain([legacy.score_row(r,fitted) for r in features(split,[split])],spec[split+'_false']) for split in ('cal','eval')}
        expected={(j['family'],j['attack_k']) for j in jobs if j['kind']=='attack' and j['split']=='cal' and j['family'] in spec['cal_false']}
        policies=legacy.calibrate(scored['cal'],expected)
        data.atomic_json(source/'calibration'/(regime+'.json'),dict(policies=policies))
        for split,rows in scored.items():
            with data.atomic_rows(source/'report/predictions'/regime/(split+'.jsonl.gz')) as write:
                for r in rows:
                    r['decisions']={m:original.decide(r,m,policies[m]) for m in legacy.METHODS};write(r)
    return source


class NoMissConstantContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.rq1_score_revision import no_miss_constant
        cls.module=no_miss_constant
        cls.rows=features();cls.old=legacy.fit_regime(cls.rows,['F1','F2'])

    def test_fit_zero_source_selection_scaler_and_structural_gamma(self):
        n=self.module;before=copy.deepcopy(self.rows)
        fitted=n.fit_zero(self.rows,self.old,['F1'])
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if r['family']=='F2':r['features']={m:[1e9]*6 for m in heads.BASE_METHODS}
        self.assertEqual(fitted,n.fit_zero(changed,self.old,['F1']))
        for source_family,target_family in [('F2','F1')]:
            altered=copy.deepcopy(self.rows)
            for r in altered:
                if r['family']==target_family:r['features']={m:[1e9]*6 for m in heads.BASE_METHODS}
            self.assertEqual(n.fit_zero(self.rows,self.old,[source_family]),n.fit_zero(altered,self.old,[source_family]))
        self.assertEqual(self.rows,before)
        selected=legacy.supervision(self.rows,['F1']);weights=legacy.training_weights(selected)
        x=np.asarray([r['features']['D_head'] for r in selected]);mean=weights@x
        std=np.sqrt(weights@((x-mean)**2))
        for method in ('D_zero','I_zero'):
            model=fitted['models'][method]
            self.assertEqual(heads.raw_parameters(model)['coef'][4],0.)
            np.testing.assert_allclose(np.asarray(model['mean'])[[0,1,2,3,5]],mean[[0,1,2,3,5]])
            np.testing.assert_allclose(np.asarray(model['std'])[[0,1,2,3,5]],std[[0,1,2,3,5]])
            self.assertGreater(model['original_d_std'],0.)
            self.assertEqual(model['class_weight'],[.5,.5])
            self.assertLessEqual(model['free_parameters'],6)
        self.assertNotIn('intercept',fitted['models']['J_zero'])

    def test_condition_miss_direction_and_cut_preserves_beta(self):
        n=self.module;fitted=n.fit_zero(self.rows,self.old,['F1','F2'])
        model=fitted['models']['I_zero'];coef=heads.raw_parameters(model)['coef']
        self.assertGreater(coef[1],0.)
        base=heads.base_score(model,[0,0,0,4,2,2])
        low=heads.base_score(model,[0,np.log1p(-1e-6),0,4,3,2])-base
        high=heads.base_score(model,[0,np.log1p(-.9),0,4,3,2])-base
        self.assertLess(abs(low),1e-4);self.assertLess(high,low)
        old=copy.deepcopy(self.old);old['models']['I_Jmargin'].update(mean=[1.,2.,3.,4.,5.,6.],scale=[1.,2.,3.,4.,2.,5.],coef=[0.,2.,0.,0.,-6.,10.],intercept=7.)
        r=self.rows[1];out=n.score_feature(r,old,fitted);gamma=-3.
        self.assertAlmostEqual(out['scores']['I_cut'],out['scores']['I_old']-gamma*(r['context'][1]-r['context'][2]))
        x=r['features']['I_Jmargin'];raw=heads.raw_parameters(old['models']['I_Jmargin'])
        expected=raw['intercept']+raw['coef'][1]*x[1]+(raw['coef'][4]+raw['coef'][5])*x[5]
        self.assertAlmostEqual(out['scores']['I_cut'],expected)
        for method in ('D_zero','I_zero'):
            self.assertAlmostEqual(out['contributions'][method]['score'],out['scores'][method])

    def test_missing_parent_and_missing_delta_preserve_unknown_denominator(self):
        n=self.module
        failed=n.fit_zero([r for r in self.rows if r['parent']!='p0'],self.old,['F1'])
        self.assertIsNone(failed['models']['D_zero'])
        broken=copy.deepcopy(self.rows);broken[0]['delta_T']=None
        partial=n.fit_zero(broken,self.old,['F1'])
        self.assertIsNone(partial['models']['J_zero'])
        scored=[n.score_feature(r,self.old,failed) for r in features('eval',['e'])]
        policies={m:dict(A=.1,R=-.1) for m in n.METHODS};metrics=n.evaluate(scored,policies,set())
        self.assertEqual(metrics['system_query']['D_zero']['true']['counts']['unknown'],4)
        self.assertEqual(metrics['coverage']['primary_false'],8)
        self.assertIsNotNone(scored[0]['scores']['D_old'])
        self.assertEqual(set(scored[0]['method_status']['D_zero']),{'status','reason'})

    def test_eight_method_mapping_six_cells_and_paired_delay(self):
        n=self.module;before=original.METHODS
        rows=[]
        for parent,npoints,newfirst,oldfirst in [('a',4,2,1),('b',2,None,None)]:
            for i,r in enumerate(features('eval',[parent])[:npoints]):
                r.update(w=1 if i==0 else 2,d=3,m=2,scores={m:-2. for m in n.METHODS})
                r['scores']['D_zero']=2. if i==newfirst else 0.
                r['scores']['D_old']=2. if i==oldfirst else 0.
                rows.append(r)
        false=features('eval',['c'])[4:8]
        for r in false:r.update(w=10,d=3,m=2,scores={m:-2. for m in n.METHODS})
        rows+=false;policies={m:dict(A=1.,R=-1.) for m in n.METHODS}
        metrics=n.evaluate(rows,policies,{('F1',1)})
        self.assertEqual(tuple(metrics['system_query']),n.METHODS)
        self.assertEqual(original.METHODS,before)
        self.assertAlmostEqual(metrics['system_query']['D_zero']['true']['weighted']['accept'],.125)
        self.assertEqual(metrics['system_query']['D_zero']['false']['counts']['reject'],4)
        pair=metrics['paired_timeliness']['D_zero']
        self.assertEqual(pair['shared_ever_epochs'],1)
        self.assertAlmostEqual(pair['never_difference'],0.)
        self.assertAlmostEqual(pair['weighted_median_delay_difference_seconds'],.1)
        self.assertEqual(metrics['family_k']['F3/3']['status'],'not_tested')
        self.assertEqual(metrics['first_windows']['length_2_to_9']['D_zero']['true']['n'],4)
        self.assertEqual(metrics['transitions']['D_zero']['1']['cells']['unknown/accept']['n'],1)
        self.assertIn('I_cut_old_policy',metrics)

    def test_temporary_runner_resume_binding_and_protected_paths(self):
        n=self.module
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=n.read_config();source=source_fixture(root,config);out=root/'out'
            result=n.run(source,out)
            self.assertEqual(result['status'],'complete')
            metrics=json.loads((out/'report/metrics.json').read_text())
            self.assertEqual(set(metrics['regimes']),set(config['regimes']))
            self.assertEqual(set(metrics['retention']),{'D_zero','I_zero','J_zero'})
            predictions=out/'predictions/mixed/eval.jsonl.gz';snapshot=predictions.read_bytes();mtime=predictions.stat().st_mtime_ns
            self.assertEqual(result,n.run(source,out));self.assertEqual(predictions.read_bytes(),snapshot)
            self.assertEqual(predictions.stat().st_mtime_ns,mtime)
            model=out/'models/mixed.json';model_mtime=model.stat().st_mtime_ns
            (out/'run.complete.json').unlink();(out/'regimes/mixed.complete.json').unlink()
            (out/'models/mixed.complete.json').unlink()
            self.assertEqual(result,n.run(source,out))
            self.assertEqual(model.stat().st_mtime_ns,model_mtime)
            self.assertEqual(predictions.stat().st_mtime_ns,mtime)
            binding=json.loads((out/'binding.json').read_text());binding['config']['loss']['l2']=.1
            (out/'binding.json').write_text(json.dumps(binding))
            with self.assertRaisesRegex(ValueError,'binding'):n.run(source,out)
            for dest in (source,source/'nested',root):
                with self.assertRaisesRegex(ValueError,'isolated'):n.run(source,dest)

    def test_partial_ignored_and_old_mismatch_stops(self):
        n=self.module
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=source_fixture(root,n.read_config());out=root/'out'
            (out/'models').mkdir(parents=True)
            (out/'models/mixed.json.partial').write_text('interrupted')
            calpath=source/'calibration/mixed.json';saved=json.loads(calpath.read_text())
            saved['policies']['D_head']['A']=99.;calpath.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError,'old policy'):n.run(source,out)
            self.assertFalse((out/'run.complete.json').exists())
            self.assertTrue((out/'error.json').exists())
            self.assertFalse((out/'models/mixed.json.partial').exists())

    def test_uninformative_increment_and_nonfinite_fit_stay_explicit(self):
        n=self.module;rows=copy.deepcopy(self.rows)
        for r in rows:r['delta_T']=1.
        fitted=n.fit_zero(rows,self.old,['F1'])
        self.assertEqual(fitted['models']['J_zero']['status'],'delta_uninformative')
        self.assertEqual(fitted['models']['J_zero']['coefficient'],0.)
        rows[0]['features']['D_head'][1]=float('nan')
        failed=n.fit_zero(rows,self.old,['F1'])
        self.assertIsNone(failed['models']['D_zero'])
        self.assertEqual(failed['method_status']['D_zero']['status'],'unestimable')
        self.assertIsNotNone(failed['models']['I_zero'])

    def test_retention_requires_each_regime_and_keeps_adverse_risk(self):
        n=self.module;fitted=n.fit_zero(self.rows,self.old,['F1','F2'])
        rows=[n.score_feature(r,self.old,fitted) for r in features('eval',['e'])]
        policies={m:dict(A=.01,R=-.01) for m in n.METHODS}
        metrics=n.evaluate(rows,policies,{('F1',1),('F2',1)})
        report=dict(status='evaluated',calibration_sufficient=True,method_status=fitted['method_status'],metrics=dict(eval=metrics))
        reports={regime:copy.deepcopy(report) for regime in n.read_config()['regimes']}
        reports['F2_only']['metrics']['eval']['system_query']['D_zero']['false']['weighted']['accept']=.2
        verdict=n.retention(reports,n.read_config())['D_zero']
        self.assertEqual(verdict['checks']['F2_only/false_accept']['status'],'fail')
        self.assertEqual(verdict['status'],'not_retained')
        reports['F2_only']=dict(status='not_tested_data_support')
        verdict=n.retention(reports,n.read_config())['D_zero']
        self.assertEqual(verdict['checks']['F2_only_available']['status'],'insufficient')
        unknown=n.evaluate(rows,{m:dict(A=None,R=None) for m in n.METHODS},set())
        for regime in reports:reports[regime]=dict(report,metrics=dict(eval=unknown))
        verdict=n.retention(reports,n.read_config())['D_zero']
        self.assertEqual(verdict['checks']['mixed/false_accept']['status'],'insufficient')
        self.assertNotEqual(verdict['status'],'retained')

    def test_source_missing_feature_stops_and_untested_regime_stays_untested(self):
        n=self.module
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=source_fixture(root,n.read_config())
            support=json.loads((source/'support.json').read_text())
            support['regimes']['F1_only']['data_support_met']=False
            (source/'support.json').write_text(json.dumps(support))
            n.run(source,root/'out')
            metrics=json.loads((root/'out/report/metrics.json').read_text())
            self.assertEqual(metrics['regimes']['F1_only']['status'],'not_tested_data_support')
            self.assertEqual(metrics['retention']['D_zero']['checks']['F1_only_available']['status'],'insufficient')
            next((source/'features/eval').glob('*.jsonl.gz')).unlink()
            with self.assertRaisesRegex(ValueError,'inventory mismatch'):n.run(source,root/'missing')
            self.assertFalse((root/'missing/models').exists())

    def test_old_record_checks_labels_scores_decisions_and_keys(self):
        n=self.module;fitted=n.fit_zero(self.rows,self.old,['F1','F2'])
        rows=[n.score_feature(r,self.old,fitted) for r in features('eval',['e'])]
        saved=[legacy.score_row(r,self.old) for r in features('eval',['e'])]
        policies={m:dict(A=1.,R=-1.) for m in n.METHODS}
        oldpolicies={old:policies[new] for new,old in n.OLD.items()}
        for group in (rows,saved):
            for r in group:r['decisions']={m:'unknown' for m in r['scores']}
        n._verify_old(rows,saved,policies,oldpolicies,n.read_config())
        for field,value,message in [('query_truth',-1,'metadata'),('key',['bad',0,1],'key')]:
            changed=copy.deepcopy(saved);changed[0][field]=value
            with self.assertRaisesRegex(ValueError,message):n._verify_old(rows,changed,policies,oldpolicies,n.read_config())
        changed=copy.deepcopy(saved);changed[0]['scores']['D_head']+=1.
        with self.assertRaisesRegex(ValueError,'old score'):n._verify_old(rows,changed,policies,oldpolicies,n.read_config())
        changed=copy.deepcopy(saved);changed[0]['decisions']['D_head']='accept'
        with self.assertRaisesRegex(ValueError,'old decision'):n._verify_old(rows,changed,policies,oldpolicies,n.read_config())


if __name__=='__main__':unittest.main()
