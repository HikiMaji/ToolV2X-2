"""Synthetic workflow checks; never prepare or fit the real batch."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.rq1_temporal import data, run as old
from scripts.rq1_score_revision import run, prepare
from scripts.rq1_score_revision.test_heads import row, normal_models


def feature_rows():
    result=[]
    for p in range(6):
        for truth,family in [(1,'clean'),(0,'F1'),(0,'F2')]:
            for i in range(4):
                r=row(i,parent='p'+str(p),job_id=str(p)+family,kind='clean' if truth else 'attack',
                      family=family,query_truth=truth,attack_role=None if truth else 'target',
                      origin='reference' if truth else 'score_revision',attack_k=0 if truth else 1)
                x=[-float(i+1),-float(5-i),float(i%2),i+1,3,2]
                r.update(features={m:x for m in run.heads.BASE_METHODS},finite=True,
                         delta_T=float((2*truth-1)*(i+1)))
                result.append(r)
    return result


class PipelineContracts(unittest.TestCase):
    def test_parallel_cal_eval_features_match_serial_and_resume_per_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);serial=root/'serial';parallel=root/'parallel';jobs=[]
            for split,family in [('cal','clean'),('cal','F1'),('eval','clean'),('eval','F2')]:
                jid=split+family;source=root/'source'/jid
                j=dict(job_id=jid,parent=split,split=split,kind='clean' if family=='clean' else 'attack',
                       family=family,attack_k=0 if family=='clean' else 1,origin='reference',
                       rows_path=str(source/'rows.jsonl.gz'),status_path=str(source/'complete.json'))
                jobs.append(j)
                with data.atomic_rows(source/'rows.jsonl.gz') as write:
                    for i in range(4):
                        write(row(i,job_id=jid,key=[jid,i,1],parent=split,split=split,kind=j['kind'],
                                  family=family,attack_k=j['attack_k'],origin=j['origin'],
                                  query_truth=1 if family=='clean' else 0,
                                  attack_role=None if family=='clean' else 'target',U=[i%2,1,0]))
                data.atomic_json(source/'complete.json',dict(status='COMPLETE'))
            for out in (serial,parallel):
                data.atomic_json(out/'manifest.json',dict(jobs=jobs))
            partial=parallel/'features/cal/calclean.jsonl.gz.partial'
            partial.parent.mkdir(parents=True);partial.write_text('interrupted')
            fitted=dict(models=normal_models(),rho=.5)
            run._cal_eval_features(serial,fitted,1)
            with patch.object(prepare,'iter_rows',wraps=prepare.iter_rows) as read:
                run._cal_eval_features(parallel,fitted,2)
                self.assertEqual(read.call_count,2)
            snapshots={}
            for j in jobs:
                relative=Path('features')/j['split']/(j['job_id']+'.jsonl.gz')
                expected=list(data.read_rows(serial/relative));actual=list(data.read_rows(parallel/relative))
                self.assertEqual(actual,expected)
                self.assertEqual([r['n_frames'] for r in actual],[1,2,3,4])
                self.assertEqual([r['index'] for r in actual],[0,1,2,3])
                self.assertTrue(all(r['job_id']==j['job_id'] and r['origin']=='reference' for r in actual))
                snapshots[relative]=(parallel/relative).read_bytes()
            self.assertFalse(partial.exists())
            with patch.object(run.heads,'window_features',side_effect=AssertionError('completed job reran')):
                run._cal_eval_features(parallel,fitted,1)
            self.assertTrue(all((parallel/p).read_bytes()==b for p,b in snapshots.items()))

    def test_dependency_change_or_missing_source_refuses_stage_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';config=prepare.read_config()
            config['source_manifest']['path']='/fixture_read_only_source/manifest.json'
            data.atomic_json(out/'manifest.json',dict(config=config,jobs=[]))
            data.atomic_json(out/'prepare.complete.json',{})
            data.atomic_json(out/'support.json',prepare.support_summary([],config))
            dependency=root/'old_run.py';dependency.write_bytes(Path(run.original.__file__).read_bytes())
            with patch.object(run.original,'__file__',str(dependency)):
                run.features(out)
                snapshot=(out/'pipeline.json').read_bytes();marker=(out/'features.complete.json').read_bytes()
                record=json.loads(snapshot)
                paths={r['path'] for r in record['code']}
                self.assertTrue({str(Path(m.__file__).resolve()) for m in (run.heads,run.prepare,run.fitting,run.kernel,run.original,run.data)}<=paths)
                dependency.write_text(dependency.read_text()+'\n# fixture dependency change\n')
                with self.assertRaisesRegex(ValueError,'code/config changed'):
                    run.features(out)
                self.assertEqual((out/'pipeline.json').read_bytes(),snapshot)
                self.assertEqual((out/'features.complete.json').read_bytes(),marker)
                dependency.unlink()
                with self.assertRaisesRegex(ValueError,'dependency source unavailable'):
                    run.fit(out)
                self.assertFalse((out/'fit.complete.json').exists())

    def test_imported_normal_code_must_match_frozen_hash_before_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'fit.py'
            source.write_text(Path(run.fitting.__file__).read_text()+'\n# changed frozen implementation\n')
            with patch.object(run.fitting,'__file__',str(source)):
                with self.assertRaisesRegex(ValueError,'frozen imported normal code changed'):
                    run._provenance(root/'out',prepare.read_config())
            self.assertFalse((root/'out/pipeline.json').exists())

    def test_source_only_selection_precedes_scaler_and_balanced_weights(self):
        rows=[]
        for parent in ('a','b','c'):
            for kind,family,truth,origin in [('clean','clean',1,'reference'),('attack','F1',0,'score_revision'),('attack','F2',0,'score_revision'),('attack','F0',0,'reference')]:
                rows.append(row(parent=parent,job_id=parent+family,kind=kind,family=family,query_truth=truth,origin=origin,attack_role='target' if truth==0 else None))
        chosen=run.supervision(rows,['F1'])
        self.assertEqual({r['family'] for r in chosen},{'clean','F1'})
        weights=run.training_weights(chosen)
        self.assertAlmostEqual(weights[[r['query_truth']==0 for r in chosen]].sum(),.5)
        self.assertAlmostEqual(weights[[r['query_truth']==1 for r in chosen]].sum(),.5)
        draws=run.resample_parents(chosen,['a','a','c'])
        self.assertEqual({r['parent'] for r in draws},{'draw_0','draw_1','draw_2'})
        self.assertEqual(sum(r['original_parent']=='a' for r in draws),4)

    def test_calibration_aliases_keep_original_module_untouched(self):
        before=old.METHODS
        rows=[]
        for truth in (0,1):
            for i in range(20):
                r=row(i,split='cal',kind='clean' if truth else 'attack',family='clean' if truth else 'F1',query_truth=truth,attack_role=None if truth else 'target',job_id='c' if truth else 'f')
                r.update(scores={m:2. if truth else -2. for m in run.METHODS},finite=True,accept_eligible=True,reject_eligible=True)
                rows.append(r)
        policies=run.calibrate(rows,{('F1',1)})
        for r in rows:
            r['decisions']={m:old.decide(r,m,policies[m]) for m in run.METHODS}
        result=run.six_cells(rows)
        self.assertAlmostEqual(result['J']['correct_definite'],1.)
        self.assertEqual(old.METHODS,before)
        policy=run.calibrate([r for r in rows if r['kind']=='clean'],{('F1',1)})['J']
        self.assertIsNone(policy['A'])

    def test_paired_epoch_timeliness_uses_only_primary_labels_and_equal_epochs(self):
        records=[]
        for parent,id,n,jfirst,mfirst in [('a',1,20,4,1),('a',2,2,0,1),('b',3,3,None,None)]:
            for i in range(n):
                r=row(i,parent=parent,id=id,job_id=parent,query_truth=-1 if id==1 and i==0 else 1)
                r['decisions']={'J':'accept' if i==jfirst else 'unknown','MATE_policy':'accept' if i==mfirst else 'unknown'}
                records.append(r)
        result=run.paired_timeliness(records)
        self.assertAlmostEqual(result['J_never'],.5)
        self.assertAlmostEqual(result['MATE_policy_never'],.5)
        self.assertEqual(result['shared_ever_epochs'],2)
        self.assertAlmostEqual(result['weighted_median_delay_difference_seconds'],-.1)
        self.assertAlmostEqual(result['epochs'][0]['origin'],.1)

    def test_bootstrap_precheck_skips_single_parent_cell(self):
        rows=[row(parent='p'+str(p),kind='attack',family='F1',attack_k=1,query_truth=0,attack_role='target') for p in range(6)]
        rows.append(row(parent='p0',kind='attack',family='F2',attack_k=3,query_truth=0,attack_role='target'))
        result=run.bootstrap_precheck(rows,prepare.read_config())
        self.assertEqual(result['status'],'interval_support_insufficient')
        self.assertAlmostEqual(result['cells']['F2/3']['missing_probability_lower_bound'],(5/6)**6)

    def test_source_only_scaler_excludes_target_features_and_optimizer_failure_stays_unestimable(self):
        rows=feature_rows();reference=run.fit_regime(rows,['F1'])
        altered=copy.deepcopy(rows)
        for r in altered:
            if r['family']=='F2':
                r['features']={m:[1e9]*6 for m in run.heads.BASE_METHODS}
        changed=run.fit_regime(altered,['F1'])
        self.assertEqual(reference,changed)
        for method in run.heads.BASE_METHODS:
            self.assertEqual(changed['models'][method]['class_weight'],[.5,.5])
        with patch.object(run.heads,'fit_base',side_effect=RuntimeError('fixture nonconvergence')):
            failed=run.fit_regime(rows,['F1'])
        self.assertIsNone(failed['models']['J'])
        self.assertEqual(failed['method_status']['D_head']['optimizer_ok'],False)

    def test_missing_normal_fold_disables_only_affected_head_and_records_coverage(self):
        rows=feature_rows()
        for r in rows:
            if r['parent']=='p0':
                r['method_status']={m:dict(status='unestimable',reason='outer fold emission missing') for m in ('T_head','I_Jmargin','G')}
                for m in ('T_head','I_Jmargin','G'):
                    r['features'][m]=None
        fitted=run.fit_regime(rows,['F1'])
        self.assertIsNotNone(fitted['models']['D_head'])
        self.assertIsNone(fitted['models']['T_head'])
        self.assertIsNone(fitted['models']['J'])
        self.assertEqual(fitted['method_status']['T_head']['coverage']['missing_usable_parents'],['p0'])
        self.assertEqual(fitted['method_status']['T_head']['coverage']['by_parent']['p0']['normal_states'],{'unestimable':8})

    def test_bootstrap_reestimates_and_retains_invalid_replicates(self):
        rows=feature_rows();config=prepare.read_config()
        config['parent_splits']={p:'fit' for p in sorted({r['parent'] for r in rows})}
        config['coefficient_interval']['repetitions']=4
        fitted=run.fit_regime(rows,['F1','F2'])
        interval=run.coefficient_interval(rows,config,fitted)
        self.assertEqual(interval['performed_repetitions'],4)
        self.assertEqual(interval['n_valid'],4)
        self.assertEqual(len(interval['draws']),4)
        with patch.object(run.heads,'fit_increment',return_value=dict(delta_informative=False)):
            invalid=run.coefficient_interval(rows,config,fitted)
        self.assertEqual(invalid['status'],'invalid_fraction_exceeded')
        self.assertEqual(invalid['failures'],{'delta_uninformative':4})
        self.assertIsNone(invalid['interval'])

    def test_six_cells_and_net_false_risk_use_hierarchical_denominators(self):
        rows=[]
        for i in range(10):
            rows.append(row(i,parent='a',job_id='a',decisions={m:'accept' if i<9 else 'unknown' for m in run.METHODS}))
        rows.append(row(parent='b',job_id='b',decisions={m:'reject' for m in run.METHODS}))
        for i in range(4):
            rows.append(row(i,parent='a',job_id='fa',kind='attack',family='F1',attack_k=1,query_truth=0,
                            attack_role='target',decisions={m:'accept' if i==0 else 'reject' for m in run.METHODS}))
        rows.append(row(parent='b',job_id='fb',kind='attack',family='F1',attack_k=2,query_truth=0,
                        attack_role='target',decisions={m:'unknown' for m in run.METHODS}))
        result=run.six_cells(rows)['J']
        self.assertAlmostEqual(result['true']['weighted']['accept'],.45)
        self.assertAlmostEqual(result['true']['weighted']['reject'],.5)
        self.assertAlmostEqual(result['false']['weighted']['accept'],.125)
        self.assertAlmostEqual(result['correct_definite'],.4125)
        before=run.transitions(rows,'T_head')['0']
        self.assertEqual(before['newly_false_accepted_weight'],0.)

    def test_fold_isolation_and_three_regime_end_to_end_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);config=prepare.read_config();config['parent_splits']={**{'p'+str(i):'fit' for i in range(6)},'c':'cal','e':'eval'}
            jobs=[];planned=[]
            for split,parents in [('fit',['p'+str(i) for i in range(6)]),('cal',['c']),('eval',['e'])]:
                for parent in parents:
                    variants=[('clean',0)]+[(f,k) for f in ('F1','F2') for k in (1,2)]
                    if parent=='p0':
                        variants.append(('F1',3))
                    for family,k in variants:
                        jid=parent+family+str(k);dest=out/'jobs'/jid
                        j=dict(job_id=jid,parent=parent,split=split,kind='clean' if family=='clean' else 'attack',
                               family=family,attack_k=k,origin='score_revision' if split=='fit' and k else 'reference',
                               rows_path=str(dest/'rows.jsonl.gz'),status_path=str(dest/'complete.json'))
                        jobs.append(j)
                        if split=='fit' and k:
                            planned.append(j)
                        with data.atomic_rows(dest/'rows.jsonl.gz') as write:
                            for i in range(12):
                                u=[1,1,1] if not k else [1,0,0] if k==1 else [1,1,0]
                                if i%3==0:
                                    u=[1,0,1] if not k else [1,0,0]
                                write(row(i,job_id=jid,parent=parent,split=split,kind=j['kind'],family=family,attack_k=k,
                                    origin=j['origin'],query_truth=1 if not k else 0,attack_role=None if not k else 'target',U=u))
                        data.atomic_json(dest/'complete.json',dict(status='COMPLETE'))
            config['planned_fit_attacks']=planned
            normal_path=out/'old_models.json';data.atomic_json(normal_path,dict(models=normal_models(),rho=.5))
            config['source_models']=data.source_record(normal_path)
            # The read-only source boundary is distinct from this fixture output.
            config['source_manifest']['path']='/fixture_read_only_source/manifest.json'
            data.atomic_json(out/'manifest.json',dict(config=config,jobs=jobs))
            data.atomic_json(out/'prepare.complete.json',dict(status='complete'))
            data.atomic_json(out/'support.json',prepare.support_summary(prepare.iter_rows(out,'fit'),config))
            normal_inputs=[];rho_inputs=[]
            def fit_normal(rows):
                normal_inputs.append(sorted({r['parent'] for r in rows}))
                self.assertTrue(all(r['kind']=='clean' and r['split']=='fit' for r in rows))
                return normal_models()
            def fit_rho(rows,W):
                rho_inputs.append(sorted({r['parent'] for r in rows}))
                return dict(status='ok',rho=.5,folds=[])
            with patch.object(run.fitting,'fit_models',side_effect=fit_normal),patch.object(run.fitting,'fit_rho_oof',side_effect=fit_rho):
                run.features(out)
            self.assertEqual(normal_inputs,rho_inputs)
            self.assertEqual(len(normal_inputs),6)
            for i,parents in enumerate(normal_inputs):
                self.assertNotIn('p'+str(i),parents)
                self.assertEqual(len(parents),5)
            run.fit(out);run.score(out);run.report(out)
            result=json.loads((out/'report/metrics.json').read_text())
            self.assertEqual(result['parameter_stability']['status'],'interval_support_insufficient')
            self.assertEqual(result['parameter_stability']['performed_repetitions'],0)
            self.assertTrue(all(r['data_support_met'] for r in result['regimes'].values()))
            self.assertEqual(result['regimes']['F1_only']['cal_false'],['F1'])
            self.assertEqual(result['regimes']['F1_only']['eval_false'],['F2'])
            self.assertEqual(set(result['regimes']['mixed']['metrics']['eval']['family_k']),{f+'/'+str(k) for f in ('F0','F1','F2','F3') for k in (1,2,3)})
            self.assertEqual(result['regimes']['mixed']['metrics']['eval']['coverage']['n_rows'],60)
            before=(out/'features.complete.json').read_bytes()
            with patch.object(run.fitting,'fit_models',side_effect=AssertionError('completed fold reran')):
                run.features(out)
            self.assertEqual((out/'features.complete.json').read_bytes(),before)

    def test_all_unsupported_produces_report_without_normal_fit(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);config=prepare.read_config()
            data.atomic_json(out/'manifest.json',dict(config=config,jobs=[]))
            data.atomic_json(out/'prepare.complete.json',dict(status='complete'))
            support=prepare.support_summary([],config);data.atomic_json(out/'support.json',support)
            with patch.object(run.fitting,'fit_models',side_effect=AssertionError('must skip OOF')):
                run.features(out);run.fit(out);run.score(out);run.report(out)
            result=json.loads((out/'report/metrics.json').read_text())
            self.assertEqual(result['status'],'not_tested_data_support')
            self.assertEqual(set(result['regimes']),{'mixed','F1_only','F2_only'})
            self.assertFalse((out/'folds').exists())
            before=(out/'report/metrics.json').read_bytes();run.report(out)
            self.assertEqual((out/'report/metrics.json').read_bytes(),before)

    def test_partial_support_and_empty_source_calibration_remain_untested(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);config=prepare.read_config()
            config['source_manifest']['path']='/fixture_read_only_source/manifest.json'
            support=prepare.support_summary([],config)
            support['any_regime_supported']=True
            support['regimes']['F1_only']['data_support_met']=True
            data.atomic_json(out/'manifest.json',dict(config=config,jobs=[]))
            data.atomic_json(out/'support.json',support)
            data.atomic_json(out/'prepare.complete.json',{})
            data.atomic_json(out/'features.complete.json',{})
            with data.atomic_rows(out/'features/fit/fold.jsonl.gz') as write:
                for r in feature_rows():
                    write(r)
            run.fit(out);run.score(out);run.report(out)
            result=json.loads((out/'report/metrics.json').read_text())
            self.assertEqual(result['regimes']['mixed']['status'],'not_tested_data_support')
            self.assertEqual(result['regimes']['F2_only']['status'],'not_tested_data_support')
            source=result['regimes']['F1_only']
            self.assertEqual(source['status'],'insufficient_calibration')
            self.assertIsNone(source['policies']['J']['A'])
            self.assertEqual(source['retention']['status'],'not_tested')
            self.assertEqual(result['cross_family_claim']['status'],'evidence_insufficient')

    def test_numeric_failure_retains_unknown_denominator_for_all_methods(self):
        fitted=run.fit_regime(feature_rows(),['F1','F2'])
        r=row(U=[7,0,1])
        r.update(run.heads.window_features([r],normal_models(),.5))
        scored=run.score_row(r,fitted)
        self.assertFalse(scored['finite'])
        self.assertTrue(all(x is None for x in scored['scores'].values()))
        scored['decisions']={m:'unknown' for m in run.METHODS}
        for m,values in run.six_cells([scored]).items():
            self.assertEqual(values['true']['n'],1)
            self.assertEqual(values['true']['weighted']['unknown'],1.)


if __name__=='__main__':
    unittest.main()
