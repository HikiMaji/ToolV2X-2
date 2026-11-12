"""Finite numerical fixtures, not research evidence."""
import copy
import itertools
import math
import unittest
from unittest.mock import patch
import numpy as np

try:
    from . import kernel, fit
except ImportError:
    from scripts.rq1_temporal import kernel, fit


def prediction(u):
    n = len(u)
    return dict(u=np.array(u), hC=np.linspace(.3, .7, n), hB=np.full(n, .4),
                D=np.full(n, .6), emit=np.tile([.2, .85], (n, 1)),
                trans=np.tile([[.8, .2], [.1, .9]], (n, 1, 1)))


def row(t, u=(1, 0), parent='p', **kw):
    r = dict(parent=parent, job_id=parent, id=1, epoch=0, index=t, frame=t,
             timestamp=t / 10, source_ids=list(range(len(u))), U=list(u),
             X=[[t / 10, 0, 1, .5, .2] for _ in u], C=[.3] * len(u),
             C_missing=[False] * len(u), groups=[list(range(len(u)))],
             query_present=True, output_present=True, identity_ok=True,
             newborn=False, kind='clean', split='fit', query_truth=1,
             query_gt_id='gt', Z=[(t + i) % 2 for i in range(len(u))])
    r.update(kw)
    return r


def models():
    def m(d, p):
        return dict(mean=[0.] * d, scale=[1.] * d, coef=[0.] * d,
                    intercept=math.log(p / (1 - p)))
    return dict(D=m(7, .6), h_B=m(5, .4), h_C=m(6, .5),
                emission=m(6, .7), transition=m(7, .6), pi=.45,
                T_base=[[.8, .2], [.3, .7]])


class KernelTests(unittest.TestCase):
    def test_forward_matches_independent_path_enumeration(self):
        # Catches first-frame propagation and consuming U before scoring.
        seq = [prediction([1, 0]), prediction([0, 0]), prediction([1, 1])]
        want = 0.
        states = list(itertools.product((0, 1), repeat=2))
        for path in itertools.product(states, repeat=3):
            pr = math.prod(seq[0]['hC'][i] if path[0][i] else 1-seq[0]['hC'][i] for i in range(2))
            for t, z in enumerate(path):
                if t:
                    pr *= math.prod(seq[t]['trans'][i, path[t-1][i], z[i]] for i in range(2))
                p = [seq[t]['emit'][i, z[i]] for i in range(2)]
                u = seq[t]['u']
                indep = math.prod(p[i] if u[i] else 1-p[i] for i in range(2))
                common = max(0., min([p[i] for i in range(2) if u[i]] or [1.])
                             - max([p[i] for i in range(2) if not u[i]] or [0.]))
                pr *= .5*indep + .5*common
            want += pr
        got = kernel.normal_window(seq, [[0, 1]], .5)
        self.assertAlmostEqual(math.exp(got['loglik']), want, places=12)
        self.assertAlmostEqual(sum(got['posterior']), 1.)
        first_p = np.array([.395, .655])
        np.testing.assert_allclose(got['steps'][0]['p'], first_p)

    def test_sequence_mass_unknown_and_rho_zero(self):
        for n in (2, 3):
            mass = 0.
            for vals in itertools.product((0, 1), repeat=2*n):
                seq = [prediction(vals[:n]), prediction(vals[n:])]
                mass += math.exp(kernel.normal_window(seq, [list(range(n))], .7)['loglik'])
            self.assertAlmostEqual(mass, 1., places=12)
        partial = kernel.normal_window([prediction([1, -1])], [[0, 1]], .7)
        total = sum(math.exp(kernel.normal_window([prediction([1, b])], [[0, 1]], .7)['loglik']) for b in (0, 1))
        self.assertAlmostEqual(math.exp(partial['loglik']), total)
        seq = [prediction([1, 0]), prediction([0, 1])]
        joint = kernel.normal_window(seq, [[0, 1]], 0.)
        singles = sum(kernel.normal_window([
            dict(u=p['u'][i:i+1], hC=p['hC'][i:i+1], emit=p['emit'][i:i+1], trans=p['trans'][i:i+1])
            for p in seq], [[0]], 0.)['loglik'] for i in range(2))
        self.assertAlmostEqual(joint['loglik'], singles)

    def test_false_markov_shared_zero_never_revives(self):
        got = kernel.false_window([[1, 0], [-1, -1], [1, 1]], .9)
        self.assertEqual(got['steps'][0]['family_weights'][3], 0.)
        self.assertEqual(got['steps'][2]['family_weights'][3], 0.)
        self.assertEqual(got['steps'][1]['loglik'], 0.)
        first = .25 * (.1*.9 + .2*.8 + .4*.6)
        self.assertAlmostEqual(math.exp(got['steps'][0]['loglik']), first)
        # Exact two-observation independent-family path probabilities.
        want = .25 * sum(r*(1-r)*(r+.9**2*(1-r))*(r*(1-.9**2)) for r in (.1,.2,.4))
        self.assertAlmostEqual(math.exp(got['loglik']), want)

    def test_permutation_and_window_expiry(self):
        seq = [prediction([1,0,1]), prediction([0,1,-1])]
        a = kernel.normal_window(seq, [[0,1],[2]], .75)
        perm = [2,0,1]
        b = kernel.normal_window([{k: np.asarray(v)[perm] for k,v in p.items()} for p in seq], [[1,2],[0]], .75)
        self.assertAlmostEqual(a['loglik'], b['loglik'])
        rows = [row(0, (0,0)), row(1), row(2, (1,1))]
        a = kernel.score_window(rows, models(), .5, W=2)
        rows[0]['U'] = [1,1]
        b = kernel.score_window(rows, models(), .5, W=2)
        self.assertEqual(a['scores'], b['scores'])

    def test_online_boundary_missing_and_eligibility(self):
        r = row(0)
        a = fit.predict_row(r, models())
        r.update(Z=[999], query_truth=999, kind='invalid', split='eval', attack_k=7)
        b = fit.predict_row(r, models())
        for k in a:
            np.testing.assert_allclose(a[k], b[k])
        r['C_missing'][0] = True
        r['X'][1] = None
        pred = fit.predict_row(r, models())
        self.assertEqual(pred['u'][1], -1)
        self.assertEqual(pred['hC'][0], pred['hB'][0])
        np.testing.assert_allclose(pred['trans'][0], models()['T_base'])
        self.assertEqual(pred['hC'][1], .45)
        rs = [row(t, (1,-1)) for t in range(3)]
        self.assertFalse(kernel.score_window(rs, models(), .5)['accept_eligible'])
        rs.append(row(3, (-1,1)))
        self.assertTrue(kernel.score_window(rs, models(), .5)['accept_eligible'])
        rs[-1]['output_present'] = False
        self.assertFalse(kernel.score_window(rs, models(), .5)['accept_eligible'])
        rs[-1]['U'] = [-1,-1]
        out = kernel.score_window(rs[-1:], models(), .5)
        self.assertTrue(out['finite'])
        self.assertEqual(set(out['scores'].values()), {0.})

    def test_score_decomposition_first_frame_and_no_label_access(self):
        class OnlineOnly(dict):
            def get(self, key, *args):
                if key in {'Z','truth','query_truth','split','kind','attack_k','attack_role'}:
                    raise AssertionError('offline key read: '+key)
                return super().get(key,*args)
            def __getitem__(self,key):
                if key in {'Z','truth','query_truth','split','kind','attack_k','attack_role'}:
                    raise AssertionError('offline key read: '+key)
                return super().__getitem__(key)
        rows = [OnlineOnly(row(t,(1,0))) for t in range(3)]
        result = kernel.score_window(rows,models(),.5)
        summary = result['window']
        self.assertAlmostEqual(result['scores']['J'],sum(summary['e'])+summary['delta_T']-summary['delta_F'])
        self.assertAlmostEqual(result['scores']['Jind'],sum(summary['e'])-summary['delta_F'])
        first = kernel.score_window(rows[:1],models(),.5)
        self.assertAlmostEqual(first['scores']['T'],first['scores']['C'])
        self.assertTrue(result['reject_eligible'])
        self.assertAlmostEqual(result['normal_loglik']['J'],summary['normal_loglik'])
        self.assertEqual(len(result['steps']['J']),3)
        bad_models = models()
        bad_models['emission']['coef'][0] = float('nan')
        failed = kernel.score_window(rows,bad_models,.5)
        self.assertFalse(failed['finite'])
        self.assertEqual(set(failed['scores'].values()),{None})
        self.assertTrue(failed['error'])
        self.assertEqual(failed['method_status']['D']['status'],'numeric_failure')

    def test_empty_observation_is_exactly_unit_likelihood_and_keeps_slot(self):
        seq = [prediction([1,0,1]),prediction([-1,-1,-1])]
        a = kernel.normal_window(seq,[[0,1,2]],.75)
        self.assertEqual(a['steps'][1]['loglik'],0.)
        self.assertEqual(a['steps'][1]['delta'],0.)
        b = kernel.false_window([[1,0,1],[-1,-1,-1]])
        self.assertEqual(b['steps'][1]['loglik'],0.)
        self.assertEqual(b['steps'][0]['family_weights'],b['steps'][1]['family_weights'])
        out = kernel.score_window([row(0),row(1,(-1,-1)),row(2,(-1,1))],models(),.5,W=2)
        self.assertEqual(out['n_frames'],2)
        self.assertEqual(out['support_union'],[1])
        self.assertFalse(out['accept_eligible'])
        seven = kernel.normal_window([prediction([1,0,1,0,-1,1,0])],[list(range(7))],.9)
        self.assertTrue(math.isfinite(seven['loglik']))
        self.assertEqual(len(seven['posterior']),128)

    def test_windows_reset_only_on_online_lifecycle(self):
        rs = [row(0), row(1, query_truth=0), row(2, id=2), row(4, id=2),
              row(5, id=2, query_present=False, newborn=True), row(6, id=2)]
        self.assertEqual([len(w) for w in kernel.windows(rs)], [1,2,1,1,1,1])


class FitTests(unittest.TestCase):
    def test_weighting_constraints_unestimable_and_roundtrip(self):
        records = [(row(0,parent='a'),0), (row(0,parent='a'),1),
                   (row(1,parent='a'),0), (row(0,parent='b'),0)]
        np.testing.assert_allclose(fit.sample_weights(records), [.125,.125,.25,.5])
        X = [[0,0],[1,0],[2,1],[3,1]]
        m = fit.fit_logistic(X, [0,0,1,1], [1]*4, [-1,1])
        self.assertLessEqual(m['coef'][0], 0.)
        self.assertGreaterEqual(m['coef'][1], 0.)
        with self.assertRaises(ValueError):
            fit.fit_logistic(X, [1]*4, [1]*4, [0,0])
        rs = [row(t, ((t//2)%2, (t//3)%2), parent=p) for p in ('a','b','c') for t in range(12)]
        m = fit.fit_models(rs)
        self.assertEqual(m['diagnostics']['train_parents'], ['a','b','c'])
        self.assertTrue(np.isfinite(fit.predict_row(rs[0], m)['emit']).all())
        oof = fit.fit_rho_oof(rs)
        self.assertEqual(set(oof['objectives']), {'0.0','0.25','0.5','0.75','0.9'})
        self.assertEqual(len(oof['folds']), 3)
        self.assertEqual(oof['status'],'ok')

    def test_single_proxy_class_keeps_estimable_direct_model(self):
        rows = [row(t, ((t//2)%2, (t//3)%2), parent=p, Z=[1,1])
                for p in ('a','b') for t in range(12)]
        fitted = fit.fit_models(rows)
        self.assertEqual(fitted['component_status']['D']['status'],'ok')
        self.assertEqual(fitted['component_status']['h_B']['status'],'unestimable')
        direct = fit.predict_row(rows[-1],{'D':fitted['D']})
        self.assertTrue(np.isfinite(direct['D']).all())
        out = kernel.score_window(rows[-2:],fitted,None)
        self.assertTrue(out['finite'])
        self.assertTrue(math.isfinite(out['scores']['D']))
        for method in ('B','C','T','J','Jind','G'):
            self.assertIsNone(out['scores'][method])
            self.assertEqual(out['method_status'][method]['status'],'unestimable')
            self.assertTrue(out['method_status'][method]['reason'])
        oof = fit.fit_rho_oof(rows)
        self.assertEqual(oof['status'],'unestimable')
        self.assertIsNone(oof['rho'])

    def test_no_adjacent_transitions_keeps_static_methods(self):
        rows = [row(2*t, ((t//2)%2,(t//3)%2),parent=p,Z=[t%2,(t+1)%2])
                for p in ('a','b') for t in range(12)]
        fitted = fit.fit_models(rows)
        self.assertEqual(fitted['component_status']['T_base']['status'],'unestimable')
        out = kernel.score_window(rows[-1:],fitted,None)
        for method in ('D','B','C'):
            self.assertTrue(math.isfinite(out['scores'][method]))
            self.assertEqual(out['method_status'][method]['status'],'ok')
        for method in ('T','J','Jind','G'):
            self.assertIsNone(out['scores'][method])
        # OOF failure disables J even when final all-fit T is estimable.
        complete = [row(t,(t%2,(t+1)%2),parent=p,Z=[(t+offset)%2]*2)
                    for p,offset in (('a',0),('b',1)) for t in range(2)]
        full = fit.fit_models(complete)
        failed_oof = fit.fit_rho_oof(complete)
        self.assertIsNone(failed_oof['rho'])
        out = kernel.score_window(complete[-2:],full,failed_oof['rho'])
        self.assertTrue(math.isfinite(out['scores']['T']))
        self.assertEqual(out['method_status']['J']['status'],'unestimable')

    def test_oof_uses_full_window_loss_not_last_increment(self):
        rs = [row(t, (1,1), parent=p) for p in ('a','b') for t in range(2)]
        def fake_normal(preds, groups, rho, mode='J'):
            return dict(loglik=-len(preds)*(1+rho), steps=[dict(loglik=-999)])
        with patch.object(fit, 'fit_models', return_value=models()), patch.object(kernel, 'normal_window', side_effect=fake_normal):
            out = fit.fit_rho_oof(rs)
        self.assertAlmostEqual(out['objectives']['0.0'], 1.5)
        self.assertAlmostEqual(out['objectives']['0.5'], 2.25)
        self.assertEqual(out['rho'], 0.)


if __name__ == '__main__':
    unittest.main()
