"""Bounded semantic fixtures; never load the real new evaluation batch."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scripts.rq1_score_revision import heads, no_miss_constant as zero, run as legacy
from scripts.rq1_score_revision.test_no_miss_constant import features
from scripts.rq1_temporal import data, run as original


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.rq1_report_freeze import run, prepare
        cls.module, cls.prepare = run, prepare
        cls.rows = features()
        for r in cls.rows:
            r['n_minus'] = [2, 0]
        cls.old = legacy.fit_regime(cls.rows, ['F1', 'F2'])
        cls.zero = zero.fit_zero(cls.rows, cls.old, ['F1', 'F2'])

    def test_count_uses_observed_minus_and_zero_newborn_context(self):
        r = copy.deepcopy(self.rows[0]); r['context'] = [10, 3, 2]; r['n_minus'] = [1, 0, 2]
        self.assertEqual(self.module.count_inputs(r), [2, 3, 10, 3, 2])
        r.update(newborn=True, context=[0, 0, 0], n_minus=[])
        r['features']['D_head'] = [0.] * 6
        self.assertEqual(self.module.count_inputs(r), [0.] * 5)
        r.update(newborn=False, context=[1, 3, 2]); r.pop('n_minus')
        with self.assertRaises(ValueError): self.module.count_inputs(r)

    def test_free_count_coefficient_and_g_d_zero(self):
        model = self.module.fit_count([[i, 0, 1, 2, 2] for i in range(8)], [1]*4+[0]*4, [1/8]*8)
        self.assertLess(model['coef'][0], 0)
        fitted = self.module.fit_controls(self.rows, self.zero, ['F1'])
        self.assertEqual(fitted['models']['G_zero']['coef'][4], 0.)
        self.assertEqual(fitted['models']['Count']['fit_false'], ['F1'])
        altered = copy.deepcopy(self.rows)
        for r in altered:
            if r['family'] == 'F2': r['features']['D_head'][2] = 1e12
        again = self.module.fit_controls(altered, self.zero, ['F1'])
        self.assertEqual(fitted['models'], again['models'])
        cq = fitted['models']['CountQ']; base = fitted['models']['Count']
        selected = legacy.supervision(self.rows, ['F1'])
        offsets = [heads.base_score(base, self.module.count_inputs(r)) for r in selected]
        expected = heads.fit_increment(np.square(offsets), [r['query_truth'] for r in selected], legacy.training_weights(selected), offsets, [r['parent'] for r in selected], joint=False)
        self.assertEqual(cq, expected)
        self.assertNotIn('intercept', cq)

    def test_invalid_supervision_does_not_disappear(self):
        rows = copy.deepcopy(self.rows); rows[0]['n_minus'] = None
        fitted = self.module.fit_controls(rows, self.zero, ['F1','F2'])
        self.assertIsNone(fitted['models']['Count'])
        self.assertEqual(fitted['method_status']['Count']['status'], 'unestimable')
        self.assertIsNotNone(fitted['models']['G_zero'])

    def test_frozen_five_and_nine_method_policy_and_failure_isolation(self):
        controls = self.module.fit_controls(self.rows, self.zero, ['F1','F2'])
        bundle = self.module.model_bundle(self.old, self.zero, controls)
        raw = copy.deepcopy(self.rows[0]); scored = self.module.score_feature(raw, bundle)
        expected = zero.score_feature(raw, self.old, self.zero)
        for m in self.module.FROZEN:
            self.assertEqual(scored['scores'][m], expected['scores'][m])
        policies = {m:dict(A=.01, R=-.01) for m in self.module.METHODS}
        self.module.apply_decisions([scored], policies)
        self.assertEqual(set(scored['decisions']), set(self.module.METHODS))
        totals = self.module.six_cells([scored])
        self.assertEqual(len(totals), 9)
        raw['n_minus'] = None
        failed = self.module.score_feature(raw, bundle)
        self.assertIsNone(failed['scores']['Count'])
        self.assertEqual(failed['scores']['D_zero'], expected['scores']['D_zero'])
        self.assertEqual(failed['finite'], expected['finite'])

    def test_weighted_cells_physical_entities_fail_and_insufficient(self):
        rows = []
        for p, n in [('p0', 3), ('p1', 1)]:
            for truth in (1, 0):
                for i in range(n):
                    r = copy.deepcopy(self.rows[0 if truth else 4]); r.update(parent=p, job_id=p+str(truth), split='eval', epoch=i, index=i)
                    r.update(w=1, d=2, m=2, scores={m:1. for m in self.module.METHODS}, method_status={m:dict(status='ok') for m in self.module.METHODS})
                    r['decisions'] = {m:'accept' for m in self.module.METHODS}; rows.append(r)
        metrics = self.module.metrics(rows, {('F1',1)}, ['F1'])
        self.assertEqual(metrics['system_query']['Count']['false']['weighted']['accept'], 1.)
        support = metrics['family_k']['F1/1']['support']
        self.assertEqual(support['entities'], 2)
        self.assertEqual(support['query_epochs'], 4)
        completed=dict(jobs={'missing':dict(status='UNREALIZABLE')})
        coverage=self.module.construction_coverage(dict(jobs=[dict(job_id='missing',parent='p0',kind='attack',family='F1',attack_k=1)]),completed,[])
        self.assertEqual(coverage['definite_false_entities'],0)
        self.assertEqual(coverage['unrealizable'],1)
        self.assertEqual(metrics['first_windows']['length_2_to_9']['Count']['true']['weighted']['accept'], None)
        config = self.module.read_config()
        state = {m:dict(status='ok') for m in self.module.METHODS}
        verdict = self.module.judge('mixed', metrics, state, True, config, True)
        self.assertEqual(verdict['main']['checks']['false_accept']['status'], 'fail')
        self.assertEqual(verdict['main']['checks']['F1/1/coverage']['status'], 'insufficient')
        rows[0].update(query_present=False)
        rows[1]['query_truth'] = -1
        rows[2].update(newborn=True)
        self.assertEqual(self.module.six_cells(rows)['Count']['true']['n'], 1)
        only_true=[r for r in rows if r['query_truth']==1]
        missing=self.module.metrics(only_true,set(),['F1'])
        self.assertEqual(self.module.judge('mixed',missing,state,True,config,True)['main']['status'],'evidence_insufficient')

    def test_primary_unavailable_blocks_candidate_and_required_comparisons(self):
        config=self.module.read_config();state={m:dict(status='ok') for m in self.module.METHODS};rows=[]
        for parent in ('a','b','c'):
            clean=copy.deepcopy(self.rows[0]);clean.update(parent=parent,job_id=parent+'clean',split='eval',w=10,d=3,m=2)
            clean.update(scores={m:1. for m in self.module.METHODS},method_status=copy.deepcopy(state),decisions={m:'accept' for m in self.module.METHODS})
            rows.append(clean)
            for family in ('F1','F2'):
                for k in (1,2):
                    for index in range(20):
                        row=copy.deepcopy(self.rows[4]);row.update(parent=parent,job_id=parent+family+str(k),family=family,attack_k=k,index=index,timestamp=.1*index,split='eval',w=10,d=3,m=2)
                        row.update(scores={m:-1. for m in self.module.METHODS},method_status=copy.deepcopy(state),decisions={m:'reject' for m in self.module.METHODS})
                        for m in ('Count','CountQ','I_zero','G_zero','Q_zero'): row['decisions'][m]='unknown'
                        rows.append(row)
        measurement=self.module.metrics(rows,set(),['F1','F2'])
        original_verdict=self.module.judge('mixed',measurement,state,True,config,True)
        self.assertTrue(all(v['status']=='retained' and v['risk_utility_status']=='retained' for v in original_verdict.values()))
        for method,label in [('D_zero','main'),('J_zero','joint'),('D_old','main'),('MATE_policy','main'),('MATE_policy','joint'),('I_zero','joint'),('Count','main'),('CountQ','main'),('G_zero','joint'),('Q_zero','joint')]:
            with self.subTest(method=method,label=label):
                altered=copy.deepcopy(rows);altered[1]['scores'][method]=None
                altered[1]['method_status'][method]=dict(status='unavailable',reason='feature unavailable')
                altered[1]['decisions'][method]='unknown'
                metrics=self.module.metrics(altered,set(),['F1','F2'])
                verdict=self.module.judge('mixed',metrics,state,True,config,True)[label]
                self.assertNotEqual(verdict['risk_utility_status'],'retained')
                self.assertNotEqual(verdict['status'],'retained')
                self.assertEqual(metrics['system_query'][method]['false']['n'],240)
                self.assertGreater(metrics['system_query'][method]['false']['counts']['unknown'],0)
                primary=metrics['method_score_coverage'][method]['primary']
                self.assertEqual(primary['n_missing_score'],1)
                self.assertEqual(primary['n_failed'],1)
        only_true=[r for r in rows if original.primary(r,1)]
        absent=self.module.metrics(only_true,set(),['F1','F2'])
        verdict=self.module.judge('mixed',absent,state,True,config,True)
        for value in verdict.values():
            self.assertEqual(value['risk_utility_status'],'evidence_insufficient')
            self.assertEqual(value['status'],'evidence_insufficient')

    def test_config_tasks_and_parent_roles_are_frozen(self):
        config = self.module.read_config()
        self.assertEqual(len(config['jobs']), 30)
        self.prepare.register_parents(config)
        self.assertTrue(all(data.SPLITS[p]=='eval' for p in config['additional_eval_parents']))
        bad = copy.deepcopy(config); bad['jobs'] = bad['jobs'][:-1]
        with self.assertRaises(ValueError): self.module.validate_config(bad)

    def test_all_dispatches_native_prepare_then_local_numerics(self):
        with tempfile.TemporaryDirectory() as tmp:
            order=[]
            with patch.object(self.module.subprocess,'run',side_effect=lambda *a,**k:order.append(('prepare',a[0]))), patch.object(self.module,'fit',side_effect=lambda *a:order.append(('fit',None))), patch.object(self.module,'evaluate',side_effect=lambda *a:order.append(('evaluate',None))):
                self.module.main(['--stage','all','--out',tmp])
            self.assertEqual([name for name,_ in order],['prepare','fit','evaluate'])
            self.assertEqual(order[0][1][0],str(data.RUNTIME))
            self.assertEqual(order[0][1][4],'prepare')
            self.assertEqual(order[0][1][-1],'4')

    def test_fit_evaluate_and_resume_synthetic_batch(self):
        config = copy.deepcopy(self.module.read_config())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';zsource=root/'zero';out=root/'new'
            config['source_original_scores']=str(source);config['source_zero_scores']=str(zsource)
            config['source_manifest']=str(source/'manifest.json');config['source_features']=str(source/'features')
            config['source_normal_models']=str(root/'normal.json')
            splits={**{'p'+str(i):'fit' for i in range(6)},**{'c'+str(i):'cal' for i in range(5)},**{'e'+str(i):'eval' for i in range(3)}}
            config['old_parent_splits']=splits
            data.atomic_json(root/'normal.json',dict(models={},rho=0.))
            fitrows=copy.deepcopy(self.rows);calrows=features('cal',['c'+str(i) for i in range(5)])
            for r in calrows: r['n_minus']=[2,0]
            jobs=[];statuses={};folds=[]
            for p in sorted({r['parent'] for r in fitrows}):
                relative='features/fit/'+p+'.jsonl.gz';folds.append(dict(parent=p,features=relative))
                self.module.rows_once(source/relative,[r for r in fitrows if r['parent']==p])
            for jid in sorted({r['job_id'] for r in calrows}):
                group=[r for r in calrows if r['job_id']==jid];r=group[0]
                jobs.append({k:r[k] for k in ('job_id','parent','split','kind','family','attack_k','origin')})
                statuses[jid]=dict(status='COMPLETE',rows=len(group))
                self.module.rows_once(source/'features/cal'/(jid+'.jsonl.gz'),group)
            data.atomic_json(source/'manifest.json',dict(config=dict(parent_splits=splits),jobs=jobs))
            data.atomic_json(source/'prepare.complete.json',dict(status='COMPLETE',jobs=statuses))
            data.atomic_json(source/'features.complete.json',dict(status='complete',folds=folds))
            for stage in ('fit','score','report'): data.atomic_json(source/(stage+'.complete.json'),dict(status='complete'))
            for regime,spec in config['regimes'].items():
                data.atomic_json(source/'models'/(regime+'.json'),self.old)
                data.atomic_json(source/'calibration'/(regime+'.json'),dict(policies={}))
                data.atomic_json(zsource/'models'/(regime+'.json'),self.zero)
                families=['F0','F1','F2'] if regime=='mixed' else spec['fit_false']
                rows=[zero.score_feature(r,self.old,self.zero) for r in legacy._domain(calrows,families)]
                expected={(r['family'],r['attack_k']) for r in rows if original.primary(r,0)}
                policies={m:original.calibrate(original.ReportRows.from_rows([dict(r,scores={'D':r['scores'][m]},m=r['d'],supports=r['m'],n_frames=r['w']) for r in rows]),'D',expected_layers=expected) for m in self.module.FROZEN}
                for r in rows: r['decisions']={m:original.decide(r,m,policies[m]) for m in self.module.FROZEN}
                data.atomic_json(zsource/'calibration'/(regime+'.json'),dict(policies=policies))
                self.module.rows_once(zsource/'predictions'/regime/'cal.jsonl.gz',rows)
                data.atomic_json(zsource/'report'/(regime+'.json'),dict(metrics=dict(eval=dict(system_query={m:original.six_cells(original.ReportRows.from_rows([dict(r,decisions={'D':r['decisions'][m]},m=r['d'],supports=r['m'],n_frames=r['w']) for r in rows]),'D') for m in self.module.FROZEN}))))
            self.module.fit(config,out)
            first_models={r:(out/'models'/(r+'.json')).read_bytes() for r in config['regimes']}
            self.module.fit(config,out)
            self.assertEqual(first_models,{r:(out/'models'/(r+'.json')).read_bytes() for r in config['regimes']})
            newstatuses={}
            for j in config['jobs']:
                group=features('eval',[j['parent']]);group=[r for r in group if r['family']==j['family']]
                for r in group:
                    r.update(job_id=j['job_id'],key=[j['job_id'],r['index'],r['id']],attack_k=j['attack_k'],origin='report_freeze',n_minus=[2,0])
                self.module.rows_once(out/'features/eval'/(j['job_id']+'.jsonl.gz'),group)
                dest=out/'jobs'/j['job_id']
                self.module.rows_once(dest/'rows.jsonl.gz',group)
                self.module.rows_once(dest/'online.jsonl.gz',[]);self.module.rows_once(dest/'entity_coverage.jsonl.gz',[])
                data.atomic_json(dest/'attack.json',dict(status='CLEAN' if j['kind']=='clean' else 'VALID'))
                status=dict(status='COMPLETE',rows=len(group));newstatuses[j['job_id']]=status;data.atomic_json(dest/'complete.json',status)
            data.atomic_json(out/'manifest.json',dict(jobs=config['jobs'],config=config,parents={}))
            data.atomic_json(out/'prepare.complete.json',dict(status='COMPLETE',jobs=newstatuses))
            result=self.module.evaluate(config,out,1)
            self.assertEqual(result['meaning'],'execution_complete_not_scientific_pass')
            self.assertEqual(self.module.evaluate(config,out,1),result)
            for regime in config['regimes']:
                predictions=list(data.read_rows(out/'predictions'/regime/'eval.jsonl.gz'))
                self.assertTrue(predictions)
                self.assertTrue(all(set(r['decisions'])==set(self.module.METHODS) for r in predictions))
            config['jobs'][0]['seed']=1
            with self.assertRaises(ValueError): self.module.bind(config,out)

    def test_worker_resumes_same_job_and_uses_public_scans_before_labels(self):
        config = self.module.read_config(); job = dict(config['jobs'][0]); scans = []
        for i in range(98):
            scans.append(dict(index=i, frame=i*2, timestamp=i*.1, gt={}, echo={}, messages=[dict(source_id=1,frame=i*2,timestamp=i*.1,pose_xyz=[0,0,0],yaw=0,tracks=[],fov_boundary=None)]))
        calls = []
        def replay(job, spec, public, attack):
            public = list(public); self.assertEqual(len(public),98)
            self.assertNotIn('gt', public[0]); self.assertEqual(public[0]['messages'][0]['fov_boundary'], [])
            calls.append('replay'); return iter([])
        def labels(events, scans, job, attack, diagnostics, coverage):
            self.assertEqual(calls, ['replay']); calls.append('labels'); return iter([])
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp); path=out/'scans.jsonl.gz'
            with data.atomic_rows(path) as write:
                for s in scans: write(s)
            manifest=dict(jobs=[job],parents={job['parent']:dict(scan_path=str(path),spec=dict(source_ids=[1]))})
            data.atomic_json(out/'manifest.json',manifest)
            with patch.object(self.prepare.native,'replay_online',side_effect=RuntimeError('technical fixture failure')):
                with self.assertRaises(RuntimeError): self.prepare.worker(out,job['job_id'])
            self.assertTrue((out/'jobs'/job['job_id']/'error.json').exists())
            self.assertFalse((out/'jobs'/job['job_id']/'complete.json').exists())
            with patch.object(self.prepare.native,'replay_online',side_effect=replay), patch.object(self.prepare.native,'attach_labels',side_effect=labels):
                self.prepare.worker(out,job['job_id']); self.prepare.worker(out,job['job_id'])
            self.assertEqual(calls, ['replay','labels'])
            self.assertEqual(json.loads((out/'jobs'/job['job_id']/'complete.json').read_text())['status'],'COMPLETE')


if __name__ == '__main__': unittest.main()
