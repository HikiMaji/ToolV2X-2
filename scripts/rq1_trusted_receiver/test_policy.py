"""Hand-computed calibration and public-policy regressions."""
import math
import numpy as np
import unittest
from scripts.rq1_trusted_receiver import run


def public(**changes):
    row = dict(query_present=True, newborn=False, input_fault=False,
        I=None, F=0., I_eligible=False, F_eligible=True,
        output_present=True, identity_ok=True, accept_eligible=True,
        reject_eligible=True, C=2., R=0., MissCount=0.)
    row.update(changes)
    return row


def sample(index, truth=1, family='F1', **changes):
    row = dict(public(), key=['clean' if truth else family, index*2, 1],
        job_id='clean' if truth else family, id=1, epoch=0, parent='P', split='cal',
        kind='clean' if truth else 'attack', query_truth=truth,
        family='clean' if truth else family, attack_k=0 if truth else 1,
        attack_role=None if truth else 'target', index=index, frame=index*2,
        timestamp=index*.1, w=10, d=3, m=2)
    row.update(changes)
    return row


class CalibrationTests(unittest.TestCase):
    def test_hand_table_budget_and_boundary(self):
        rows = [sample(i) for i in range(100)]
        for i, value in enumerate((.9, .8, .7)):
            rows[i]['F'] = value
        # Strong support conflicts at row zero; raw F must still spend two percent.
        for i in range(10):
            rows[i].update(I=.9, I_eligible=True)
        for i, value in enumerate((9., 8., 7., 6., 5., 4.), 10):
            rows[i]['R'] = value
        rows += [sample(i, 0, C=3. if i < 5 else -1.) for i in range(100)]
        policy = run.calibrate(rows, [('F1', 1)], 'LocalCond')
        self.assertEqual(policy['tauF'], .7)
        self.assertEqual(policy['tauP'], .9)
        self.assertAlmostEqual(policy['budget']['raw_F_true_reject'], .02)
        self.assertAlmostEqual(policy['budget']['local_true_reject'], 0.)
        # Both raw-F true alarms conflict, so R can use five percent; five exceed 4.
        self.assertEqual(policy['tauR'], 4.)
        self.assertEqual(policy['tauC'], 2.)
        self.assertAlmostEqual(policy['budget']['final_true_reject'], .05)
        self.assertAlmostEqual(policy['budget']['final_false_accept']['overall'], .05)
        self.assertEqual(run.decide(public(F=.7), policy, 'LocalCond')['decision'], 'accept')

    def test_raw_i_uses_each_complete_false_layer_and_no_conflict_discount(self):
        rows = [sample(i, I=.8, I_eligible=True) for i in range(100)]
        rows += [sample(i, 0, I=.8 if i == 0 else None,
                        I_eligible=i == 0, F=1.) for i in range(10)]
        rows += [sample(i, 0, 'F2') for i in range(100)]
        policy = run.calibrate(rows, [('F1', 1), ('F2', 1)], 'Local')
        self.assertTrue(math.isinf(policy['tauP']))
        self.assertEqual(policy['coverage']['false']['F1/1']['rows'], 10)
        self.assertEqual(policy['branches']['local_accept']['reason'], 'no_positive_quality_region')

    def test_missing_layer_closes_acceptance_but_keeps_normal_rejection(self):
        rows = [sample(i, F=1. if i == 0 else 0., R=8. if i < 3 else 0.) for i in range(100)]
        rows += [sample(i, 0) for i in range(100)]
        policy = run.calibrate(rows, [('F1', 1), ('F2', 1)], 'LocalCond')
        self.assertEqual(policy['status'], 'not_estimable_false_coverage')
        self.assertTrue(math.isinf(policy['tauP']))
        self.assertTrue(math.isinf(policy['tauC']))
        self.assertEqual(run.decide(public(R=9.), policy, 'LocalCond')['decision'], 'reject')
        self.assertEqual(run.decide(public(C=999.), policy, 'LocalCond')['decision'], 'unknown')

    def test_no_positive_accept_quality_closes_branch(self):
        rows = [sample(i, C=0.) for i in range(20)] + [sample(i, 0, C=3.) for i in range(20)]
        p = run.calibrate(rows, [('F1', 1)], 'LocalCount')
        self.assertTrue(math.isinf(p['tauC']))
        self.assertEqual(p['branches']['remote_accept']['reason'], 'no_positive_quality_region')

    def test_actual_local_errors_spend_separate_remaining_budgets(self):
        rows = [sample(i) for i in range(100)]
        rows[0]['F'], rows[1]['F'], rows[2]['F'] = .9, .9, .8
        for i, value in enumerate((6., 5., 4., 3., 2., 1.), 3):
            rows[i]['R'] = value
        rows[20].update(I=.9, I_eligible=True)
        fake = [sample(i, 0, C=3. if 1 <= i <= 4 else -1.) for i in range(100)]
        fake[0].update(I=.9, I_eligible=True)
        policy = run.calibrate(rows+fake, [('F1', 1)], 'LocalCond')
        self.assertAlmostEqual(policy['budget']['local_true_reject'], .02)
        self.assertAlmostEqual(policy['budget']['local_false_accept']['F1/1'], .01)
        self.assertAlmostEqual(policy['budget']['remaining_true_reject'], .03)
        self.assertAlmostEqual(policy['budget']['remaining_false_accept']['F1/1'], .04)
        self.assertEqual((policy['tauR'], policy['tauC']), (3., 2.))
        self.assertAlmostEqual(policy['budget']['final_true_reject'], .05)
        self.assertAlmostEqual(policy['budget']['final_false_accept']['F1/1'], .05)

    def test_candidate_pool_excludes_unknown_labels_and_attack_background(self):
        rows = [sample(i, F=.1, I=.8, I_eligible=True, R=0., C=2.) for i in range(100)]
        rows += [sample(i, 0, C=-1.) for i in range(100)]
        baseline = run.calibrate(rows, [('F1', 1)], 'LocalCond')
        polluted = rows + [sample(1000, query_truth=-1, F=.09, I=.81,
            I_eligible=True, C=2.01), sample(1001, 0, query_truth=1,
            F=.09, I=.81, I_eligible=True, C=2.01)]
        actual = run.calibrate(polluted, [('F1', 1)], 'LocalCond')
        for key in ('tauF', 'tauP', 'tauR', 'tauC', 'budget'):
            self.assertEqual(actual[key], baseline[key])
        with self.assertRaises(ValueError):
            run.calibrate(rows+[sample(1000, 0, 'F2')], [('F1', 1)], 'LocalCond')



class PublicDecisionTests(unittest.TestCase):
    def setUp(self):
        self.policy = dict(tauF=.5, tauP=.7, tauR=2., tauC=1., status='active')

    def test_single_local_support_survives_silence_and_score_failure(self):
        for mode in ('Local', 'LocalCount', 'LocalCond'):
            got = run.decide(public(I=.7, I_eligible=True, accept_eligible=False,
                C=None, R=None, MissCount=99.), self.policy, mode)
            self.assertEqual(got['decision'], 'accept')
            self.assertEqual(got['local_state'], 'support')

    def test_conflict_fault_and_missing_output_cannot_fall_through(self):
        for change, reason in ((dict(I=.9, I_eligible=True, F=.6), 'local_conflict'),
            (dict(input_fault=True), 'input_fault'),
            (dict(I=.9, I_eligible=True, output_present=False), 'local_support_no_output'),
            (dict(I=.9, I_eligible=True, identity_ok=False), 'local_support_identity_unavailable')):
            got = run.decide(public(R=99., **change), self.policy, 'LocalCond')
            self.assertEqual((got['decision'], got['reason']), ('unknown', reason))

    def test_strict_positive_i_and_strict_reject_boundaries(self):
        policy = dict(self.policy, tauP=0.)
        self.assertEqual(run.decide(public(I=0., I_eligible=True, C=None, F=.5, R=2.), policy, 'LocalCond')['decision'], 'unknown')
        self.assertEqual(run.decide(public(R=2.01), policy, 'LocalCond')['decision'], 'reject')
        self.assertEqual(run.decide(public(C=1.), policy, 'LocalCond')['decision'], 'accept')
        self.assertEqual(run.decide(public(R=None, C=1.), policy, 'LocalCond')['decision'], 'accept')
        self.assertEqual(run.decide(public(C=None, R=3.), policy, 'LocalCond')['decision'], 'reject')
        self.assertEqual(run.decide(public(MissCount=2., R=99.), policy, 'LocalCount')['decision'], 'accept')
        self.assertEqual(run.decide(public(MissCount=3., R=None, C=None), policy, 'LocalCount')['decision'], 'reject')
        self.assertEqual(run.decide(public(R=99.), dict(policy, status='infeasible_local_risk'), 'LocalCond')['decision'], 'unknown')
        self.assertEqual(run.decide(public(query_present=False, R=99.), policy, 'LocalCond')['decision'], 'unknown')

    def test_rejects_labels_and_attack_fields(self):
        for field in ('query_truth', 'controlled_sources', 'family', 'attack_k', 'Z'):
            with self.assertRaises(ValueError):
                run.decide(public(**{field: 1}), self.policy, 'LocalCond')

class EvaluationTests(unittest.TestCase):
    def test_join_rejects_bad_keys_and_new_features_ignore_offline_fields(self):
        from scripts.rq1_temporal import data
        import tempfile
        from pathlib import Path
        import json
        model = dict(mean=[0.]*7, scale=[1.]*7, coef=[0.]*7, intercept=0.)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            row = sample(0)
            row.update(source_ids=[1, 2, 3], U=[1, 1, 0], X=[[0.]*5]*3,
                C=[0., 0., 0.], C_missing=[False]*3, groups=[[0, 1, 2]],
                Z=[999], controlled_sources=[999])
            job = dict(job_id=row['job_id'], parent='P', split='cal', kind='clean',
                family='clean', attack_k=0, rows_path=str(out/'rows.gz'), features_path=None)
            with data.atomic_rows(job['rows_path']) as write: write(row)
            local = dict(public(), parent='P', receiver_id=3, key=row['key'],
                job_id=row['job_id'], id=1, frame=0, index=0, timestamp=0., receiver_timestamp=0.)
            with data.atomic_rows(out/'jobs'/job['job_id']/'local.jsonl.gz') as write: write(local)
            first = run.evaluation_rows(job, out, {'D': model}, receiver_id=3)
            self.assertAlmostEqual(first[0]['R'], -math.log(.5))
            self.assertEqual(first[0]['MissCount'], 1.)
            self.assertEqual(first[0]['context'], [1, 3, 2])
            self.assertNotIn('controlled_sources', first[0])
            # A sidecar may not silently drop a candidate from the common denominator.
            job['job_id'] = 'absent'
            with data.atomic_rows(out/'jobs'/'absent'/'local.jsonl.gz') as write: write(dict(local, key=['bad', 0, 1]))
            with self.assertRaises(ValueError): run.evaluation_rows(job, out, {'D': model}, receiver_id=3)

    def test_evaluate_entry_freezes_roles_layers_and_all_unknown_denominators(self):
        from scripts.rq1_temporal import data
        import tempfile
        from pathlib import Path
        import json
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            model = dict(mean=[0.]*5, scale=[1.]*5, coef=[1., 0., 0., 0., 0.], intercept=0.)
            data.atomic_json(out/'count.json', dict(models=dict(Count=model)))
            data.atomic_json(out/'normal.json', dict(models=dict(D={})))
            jobs, parents, complete = [], [], {}
            for split in ('fit', 'cal', 'eval'):
                parents.append(dict(parent=split, split=split, receiver_id=3))
                for truth, family in ((1, 'clean'), (0, 'F1'), (0, 'F2')):
                    jid = split+family
                    job = dict(job_id=jid, parent=split, kind='clean' if truth else 'attack',
                        family=family, attack_k=0 if truth else 1, split=split,
                        rows_path=str(out/(jid+'.rows.gz')), features_path=str(out/(jid+'.features.gz')),
                        online_path=str(out/(jid+'.online.gz')))
                    jobs.append(job)
                    if split == 'fit':
                        complete[jid] = dict(status='SHAPE_ONLY', rows=0)
                        continue
                    row = sample(0, truth, family, job_id=jid, parent=split, split=split,
                        key=[jid, 0, 1], input_fault=split=='eval')
                    feature = dict(row, features=dict(D_head=[0., 0., 2., 1., 3., 2.]),
                        finite=True, context=[1, 3, 2], n_minus=[0, 0, 1], source_ids=[1, 2, 3])
                    row.update(source_ids=[1, 2, 3], U=[1, 1, 0], X=[[0.]*5]*3)
                    with data.atomic_rows(job['online_path']) as write: write({'key': row['key']})
                    with data.atomic_rows(job['rows_path']) as write: write(row)
                    with data.atomic_rows(job['features_path']) as write: write(feature)
                    with data.atomic_rows(out/'jobs'/jid/'local.jsonl.gz') as write: write(dict(
                        _pub=0, **{k: row[k] for k in run.PUBLIC_FIELDS},
                        key=row['key'], parent=split, receiver_id=3, job_id=jid,
                        id=1, frame=0, index=0, timestamp=0., receiver_timestamp=0.))
                    complete[jid] = dict(rows=1)
            data.atomic_json(out/'prepare.complete.json', dict(status='COMPLETE', jobs=complete))
            config = dict(parents=parents, jobs=jobs, model_sources=dict(p_D=str(out/'normal.json'),
                Count_models=dict(F1_only=str(out/'count.json'))), required_k=[1],
                regimes=dict(F1_only=dict(cal_families=['F1'], eval_families=['F2'])),
                domains=dict(heldout=['eval']))
            data.atomic_json(out/'prepare.config.json', config)
            report = run.evaluate(config, out)
            result = report['regimes']['F1_only']['eval']
            self.assertEqual(result['system_query']['LocalCond']['true']['n'], 1)
            self.assertEqual(result['system_query']['LocalCond']['false']['n'], 1)
            self.assertEqual(result['system_query']['LocalCond']['false']['counts']['unknown'], 1)
            policy = json.loads((out/'calibration/F1_only.json').read_text())['LocalCond']
            self.assertEqual(policy['required_layers'], [['F1', 1]])
            self.assertNotIn('F2/1', policy['coverage']['false'])
            self.assertEqual(result['by_domain']['heldout']['Local']['true']['n'], 1)
            self.assertTrue((out/'evaluate.complete.json').exists())
            self.assertEqual(run.evaluate(config, out), report)
            changed = dict(config, parents=[dict(p, receiver_id=99) for p in parents])
            with self.assertRaisesRegex(ValueError, 'prepared parent'):
                run.evaluate(changed, out)


class ReviewRegressionTests(unittest.TestCase):
    def fixture(self, out, change=None, saved_feature=None):
        from scripts.rq1_temporal import data
        row = sample(0)
        row.update(source_ids=[1, 2, 3], U=[1, 1, 0], X=[[0.]*5]*3,
            C=[0.]*3, C_missing=[False]*3, groups=[[0, 1, 2]])
        job = dict(job_id=row['job_id'], parent='P', split='cal', kind='clean',
            family='clean', attack_k=0, rows_path=str(out/'rows.gz'), features_path=None)
        with data.atomic_rows(job['rows_path']) as write: write(row)
        local = dict(public(I=.9, I_eligible=True), key=row['key'],
            parent='P', receiver_id=3, job_id=row['job_id'], id=1,
            frame=0, index=0, timestamp=0., receiver_timestamp=0.)
        local.update(change or {})
        with data.atomic_rows(out/'jobs'/job['job_id']/'local.jsonl.gz') as write: write(local)
        if saved_feature is not None:
            job['features_path'] = str(out/'features.gz')
            feature = dict(row, **saved_feature)
            with data.atomic_rows(job['features_path']) as write: write(feature)
        model = dict(mean=[0.]*7, scale=[1.]*7, coef=[0.]*7, intercept=0.)
        return job, model

    def test_same_key_wrong_sidecar_identity_or_query_flags_rejected(self):
        import tempfile
        from pathlib import Path
        for field, value in (('parent', 'WRONG'), ('receiver_id', 999),
                ('query_present', False), ('newborn', True), ('receiver_timestamp', .01)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                job, model = self.fixture(out, {field: value})
                with self.assertRaisesRegex(ValueError, 'sidecar'):
                    run.evaluation_rows(job, out, {'D': model}, receiver_id=3)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            job, model = self.fixture(out)
            job['local_path'] = str(out/'other_receiver.gz')
            with self.assertRaisesRegex(ValueError, 'prepare product'):
                run.evaluation_rows(job, out, {'D': model}, receiver_id=3)

    def test_public_counts_match_legacy_ten_scan_windows_and_resets(self):
        from scripts.rq1_temporal import kernel
        from scripts.rq1_score_revision import heads
        from scripts.rq1_report_freeze import run as freeze
        model = dict(mean=[0.]*7, scale=[1.]*7, coef=[0.]*7, intercept=0.)
        rows = []
        for i in range(13):
            row = sample(i, timestamp=i*.1 if i < 12 else 2., source_ids=[1, 2, 3],
                U=[1, i % 2, 0], X=[[0.]*5, [0.]*5, None if i % 2 else [0.]*5],
                C=[0.]*3, C_missing=[False]*3, groups=[[0, 1, 2]])
            row['index'] = i if i < 12 else 20
            rows.append({k: row[k] for k in run.WINDOW_FIELDS if k in row})
        windows = list(kernel.windows(rows, 10))
        self.assertEqual([len(windows[-2]), len(windows[-1])], [10, 1])
        for window in windows:
            legacy = heads.window_features(window, {'D': model}, 0., W=10)
            counts = run._event_counts(window)
            self.assertEqual(counts['Count_inputs'], freeze.count_inputs(legacy))
            for field in ('context', 'n_minus', 'n_frames', 'accept_eligible', 'reject_eligible'):
                self.assertEqual(counts[field], legacy[field])

    def test_d_failure_retains_count_inputs_misses_and_message_decisions(self):
        import tempfile
        from pathlib import Path
        from scripts.rq1_report_freeze import run as freeze
        from scripts.rq1_score_revision import heads
        good_model = dict(mean=[0.]*7, scale=[1.]*7, coef=[0.]*7, intercept=0.)
        bad_model = dict(good_model, mean=[1.e308]*7, scale=[1.e-308]*7)
        count = dict(mean=[0.]*5, scale=[1.]*5, coef=[1., 0., 0., 0., 0.], intercept=0.)
        saved_bad = dict(features={'D_head': None}, finite=False, error='D numeric failure',
            context=[0, 0, 0], n_minus=[], n_frames=0,
            accept_eligible=False, reject_eligible=False)
        for d_model, saved in ((good_model, None), (None, None), ({}, None),
                              (bad_model, None), (good_model, saved_bad)):
            with self.subTest(model=d_model, saved=saved is not None), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                job, _ = self.fixture(out, saved_feature=saved)
                with np.errstate(over='ignore', invalid='ignore'):
                    rows = run.evaluation_rows(job, out, {'D': d_model}, receiver_id=3)
                row = rows[0]
                self.assertEqual(row['Count_inputs'], [2., 1., 1., 3., 2.])
                self.assertEqual(row['MissCount'], 1.)
                self.assertTrue(row['accept_eligible'])
                self.assertTrue(row['reject_eligible'])
                if d_model is good_model and saved is None:
                    self.assertEqual(row['Count_inputs'], freeze.count_inputs(row))
                    self.assertAlmostEqual(row['R'], -math.log(.5))
                else:
                    self.assertIsNone(row['R'])
                public_row = {k: row.get(k) for k in run.PUBLIC_FIELDS}
                public_row.update(I=None, I_eligible=False, C=heads.base_score(count, row['Count_inputs']))
                policy = dict(tauF=.5, tauP=.7, tauR=2., tauC=1.)
                self.assertEqual(run.decide(public_row, policy, 'LocalCount')['decision'], 'accept')
                self.assertEqual(run.decide(public_row, policy, 'LocalCond')['decision'], 'accept')
                self.assertEqual(run.decide(public_row, dict(policy, tauR=0.), 'LocalCount')['decision'], 'reject')


if __name__ == '__main__':
    unittest.main()
