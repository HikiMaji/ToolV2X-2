"""Finite checks for the frozen conditional kernel; no research run is launched."""
import importlib.util
import itertools
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
if importlib.util.find_spec('rq1_conditional_revision'):
    import rq1_conditional_revision as cr
    import run_rq1_conditional_revision as run
else:
    cr = run = None


class ConditionalRevisionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cr, 'conditional kernel must be implemented')

    def context(self):
        return {'anchor': 9, 'groups': ((1, 2),), 'observed': (9, 1, 2),
                'p_clear': {1: .9, 2: .65}, 'p_blocked': {1: .1, 2: .05}, 'C': (0,)}

    def test_bayes_marginals_normalization_and_hidden_event(self):
        self.assertAlmostEqual(cr.visibility_weight(1, .8, .8), 16 / 17, delta=1e-12)
        self.assertAlmostEqual(cr.visibility_weight(0, .8, .8), .5, delta=1e-12)
        c = self.context()
        def prob(e, joint=True):
            return math.exp(cr.true_logprob(e, c['groups'], c['p_clear'], c['p_blocked'],
                                           .8, .8, c['C'], True, joint))
        patterns = [{9: 1, 1: a, 2: b} for a, b in itertools.product((0, 1), repeat=2)]
        self.assertAlmostEqual(sum(map(prob, patterns)), 1, delta=1e-12)
        self.assertAlmostEqual(prob({9: 1, 1: 1}), .5, delta=1e-12)
        self.assertAlmostEqual(sum(prob(e) for e in patterns if e[1]), .5, delta=1e-12)
        self.assertAlmostEqual(prob({9: 1, 1: 1, 2: 1}), .295, delta=1e-12)
        self.assertAlmostEqual(prob({9: 1, 1: 1, 2: 1}, False), .175, delta=1e-12)
        self.assertEqual(prob({9: 1}), 1)

    def test_false_family_and_partial_hidden_member(self):
        patterns = [{9: 1, 1: a, 2: b} for a, b in itertools.product((0, 1), repeat=2)]
        probs = [cr.false_probabilities(e, (1, 2)) for e in patterns]
        for k in range(4):
            self.assertAlmostEqual(sum(p[k] for p in probs), 1, delta=1e-12)
        self.assertEqual(cr.false_probabilities({9: 1}, (1, 2)), (1., 1., 1., 1.))
        self.assertAlmostEqual(sum(sum(p) / 4 for e, p in zip(patterns, probs) if e[1]), .425)
        self.assertAlmostEqual(cr.actual_false_probability({9: 1, 1: 1}, (1, 2), {'kind': 'partial'}), .6)
        self.assertAlmostEqual(cr.actual_false_probability({9: 1, 1: 0}, (1, 2), {'kind': 'partial'}), .4)
        self.assertEqual(cr.actual_false_probability({9: 1, 1: 1}, (1,), {'kind': 'partial'}), 1)

    def test_scores_decomposition_identity_order_and_no_c_read(self):
        c = self.context()
        a = cr.score_methods(c, {9: 1, 1: 0, 2: 1}, cr.REFERENCE)
        b = cr.score_methods({**c, 'observed': (2, 9, 1), 'groups': ((2, 1),)},
                             {2: 1, 9: 1, 1: 0}, cr.REFERENCE)
        self.assertEqual(a, b)
        for name in cr.METHODS:
            self.assertTrue(a[name]['supported'])
            self.assertEqual(a[name]['score'], round(a[name]['raw_score'], 12))
        j = a['Jc']
        self.assertAlmostEqual(j['raw_score'], sum(j['e_i'].values()) + sum(j['delta_g']) + j['gamma'], delta=1e-12)
        other = cr.score_methods({**c, 'C': (1,)}, {9: 1, 1: 0, 2: 1}, cr.REFERENCE)
        for method in ('I0', 'J0'):
            self.assertEqual(a[method], other[method])
        for bit in (0, 1):
            single = cr.score_methods(c, {9: 1, 1: bit}, cr.REFERENCE)
            self.assertEqual(single['Ic']['score'], single['Jc']['score'])
        none = cr.score_methods(c, {9: 1}, cr.REFERENCE)
        for s in none.values():
            self.assertEqual(s['score'], 0)
            self.assertEqual(cr.decide(s['score'], s['supported'], False, cr.disabled_policy()), 'unknown')
        with self.assertRaises(ValueError):
            cr.score_methods(c, {1: 1, 2: 0}, cr.REFERENCE)

    def test_fixed_counts_weights_c_marginalization_and_generation_isolation(self):
        base = run.build_base_contexts()
        rows = run.build_rows(base, cr.REFERENCE, cr.REFERENCE)
        self.assertEqual(Counter(c['N'] for c in base), {2: 4, 3: 12, 4: 18})
        self.assertEqual(Counter(r['N'] for r in rows), {2: 12, 3: 84, 4: 364})
        contexts = {r['context_id']: r for r in rows}
        self.assertEqual(Counter(c['N'] for c in contexts.values()), {2: 8, 3: 36, 4: 84})
        for key in ('wT',):
            self.assertAlmostEqual(sum(r[key] for r in rows), 1, delta=1e-12)
            self.assertAlmostEqual(sum(r[key] for r in rows if r['eligible']), 11 / 18, delta=1e-12)
        for k in range(4):
            self.assertAlmostEqual(sum(r['wFk'][k] for r in rows), 1, delta=1e-12)
        for c in base:
            part = [r for r in rows if r['base_id'] == c['base_id']]
            for bits in itertools.product((0, 1), repeat=len(c['observed']) - 1):
                events = {c['anchor']: 1, **dict(zip([i for i in c['observed'] if i != c['anchor']], bits))}
                marginal = sum(r['cue_prob'] * r['probT'] for r in part if r['events'] == events)
                expected = math.exp(cr.true_logprob(events, c['groups'], c['p_clear'], c['p_blocked'], .8, .8, (), False, True))
                self.assertAlmostEqual(marginal, expected, delta=1e-12)
        stress = run.build_rows(base, cr.REFERENCE, {'theta': .6, 'accuracy': .95}, {'kind': 'independent', 'r': .6})
        self.assertEqual([r['scores'] for r in rows], [r['scores'] for r in stress])
        self.assertNotEqual([r['wT'] for r in rows], [r['wT'] for r in stress])
        self.assertEqual(len(run.stress_configs()), 8)

    def test_frozen_boundary_score_equalities(self):
        base = run.build_base_contexts()
        for accuracy in (.5, 1.):
            params = {'theta': .8, 'accuracy': accuracy}
            for row in run.build_rows(base, params, params):
                s = row['scores']
                pairs = (('I0', 'Ic'), ('J0', 'Jc')) if accuracy == .5 else (('Jc', 'JcF'),)
                for x, y in pairs:
                    self.assertEqual(s[x]['score'], s[y]['score'])
                if row['N'] == 2:
                    self.assertEqual(s['Ic']['score'], s['Jc']['score'])

    def test_context_worst_and_event_conditioned_mixture_denominators(self):
        # Two contexts: max before summing yields .8, max after summing gives .5.
        rows = []
        for c, probabilities in enumerate(((.8, .2, .8, .2), (.2, .8, .2, .8))):
            for adopted in (True, False):
                pf = probabilities if adopted else tuple(1 - p for p in probabilities)
                rows.append({'context_id': c, 'context_weight': .5, 'eligible': True,
                             'probT': .5, 'probFk': pf, 'wT': .25, 'wFk': [p * .5 for p in pf],
                             'scores': {'Jc': {'score': 1 if adopted else -1, 'supported': True}}})
        policy = {'adopt_enabled': True, 'reject_enabled': True, 'tau_A': 1., 'tau_R': -1.}
        result = cr.evaluate_policy(rows, 'Jc', policy, True)
        self.assertAlmostEqual(result['context_worst_false_adopt'], .8)
        self.assertAlmostEqual(result['context_worst_false_reject'], .2)
        self.assertAlmostEqual(result['max_context_false_adopt'], .8)
        part = [rows[0], rows[2]]
        part[0] = {**part[0], 'wFk': [.4, 0., .1, 0.]}
        part[1] = {**part[1], 'wFk': [.1, 0., .1, 0.], 'scores': {'Jc': {'score': -1., 'supported': True}}}
        conditional = cr.evaluate_policy(part, 'Jc', policy, True, event_conditioned=True)
        self.assertIsNone(conditional['context_worst_false_adopt'])
        self.assertEqual(conditional['context_extrema_undefined_reason'], 'event_conditioned_stratum')
        self.assertIsNone(conditional['Fk'][1]['rates']['adopt'])
        self.assertAlmostEqual(conditional['Q_F']['rates']['adopt'], 5 / 7)
        self.assertEqual(conditional['Fk'][1]['undefined_reason'], 'zero_denominator')

    def test_policy_sign_zero_disabled_and_zero_mass(self):
        rows = []
        for score, wt, wf in ((2., .45, .01), (1., .05, .49), (-1., .01, .45), (-2., .49, .05)):
            rows.append({'context_id': 0, 'context_weight': 1., 'eligible': True, 'probT': wt, 'probFk': [wf] * 4,
                         'wT': wt, 'wFk': [wf] * 4, 'scores': {'Ic': {'score': score, 'supported': True}}})
        fit = cr.fit_policy(rows, 'Ic', .05)
        self.assertEqual(fit['policy']['tau_A'], 2.)
        self.assertFalse(fit['policy']['reject_enabled'])
        policy = {'adopt_enabled': True, 'reject_enabled': True, 'tau_A': 0., 'tau_R': 0.}
        self.assertEqual(cr.decide(0., True, True, policy), 'unknown')
        self.assertEqual(cr.decide(1., False, True, policy), 'unknown')
        self.assertEqual(cr.decide(2., True, True, cr.disabled_policy()), 'unknown')
        zero = cr.evaluate_policy([], 'Ic', policy, True)
        self.assertIsNone(zero['correct_clear'])
        self.assertEqual(zero['true']['undefined_reason'], 'zero_denominator')
        self.assertFalse(cr.fit_policy([], 'Ic', .05)['policy']['adopt_enabled'])

    def test_envelope_reject_tie_can_improve_mixture_secondary_objective(self):
        rows = []
        for score, wt, pf in ((-1., .01, (.9, .8, .6, 0.)), (1., .99, (.1, .2, .4, 1.))):
            rows.append({'context_id': 0, 'context_weight': 1., 'eligible': True,
                         'probT': wt, 'probFk': pf, 'wT': wt, 'wFk': pf,
                         'scores': {'Ec': {'score': score, 'supported': True}}})
        fitted = cr.fit_policy(rows, 'Ec', .05, robust=True)
        self.assertFalse(fitted['policy']['adopt_enabled'])
        self.assertTrue(fitted['policy']['reject_enabled'])
        self.assertEqual(fitted['metrics']['context_worst_false_reject'], 0.)
        self.assertAlmostEqual(fitted['metrics']['Q_F']['rates']['reject'], .575)

    def test_zero_true_probability_is_infinite_evidence_without_nan(self):
        c = self.context()
        c.update(p_clear={1: 0., 2: 0.}, p_blocked={1: 0., 2: 0.})
        scores = cr.score_methods(c, {9: 1, 1: 1, 2: 1}, cr.REFERENCE)
        for value in scores.values():
            self.assertTrue(value['supported'])
            self.assertEqual(value['score'], -math.inf)
        run.json_safe(scores)

    def test_anchor_only_has_no_eligible_max_context_and_actual_stress_uses_actual_f(self):
        c = self.context()
        scores = cr.score_methods(c, {9: 1}, cr.REFERENCE)
        row = {'context_id': 'empty', 'context_weight': 1., 'eligible': False,
               'wT': 1., 'wFk': [1.] * 4, 'scores': scores}
        overall = cr.evaluate_policy([row], 'Jc', cr.disabled_policy(), False)
        self.assertEqual(overall['true']['rates']['unknown'], 1.)
        self.assertIsNone(overall['max_context_false_adopt'])
        eligible = cr.evaluate_policy([row], 'Jc', cr.disabled_policy(), True)
        self.assertEqual(eligible['Q_F']['undefined_reason'], 'zero_denominator')
        rows = []
        for positive in (True, False):
            score = 1. if positive else -1.
            rows.append({'context_id': 'one', 'context_weight': 1., 'eligible': True,
                         'wT': .5, 'wFk': [.5] * 4, 'wActualF': .9 if positive else .1,
                         'N': 2, 'layout': 'independent', 'quality': 'high', 'peer_count': 1,
                         'C_type': 'all_clear', 'pattern': 'all_report' if positive else 'all_unreported',
                         'scores': {m: {'score': score, 'supported': True} for m in cr.METHODS}})
        policy = {'adopt_enabled': True, 'reject_enabled': True, 'tau_A': 1., 'tau_R': -1.}
        policies = dict.fromkeys(cr.METHODS, policy)
        stress = run.summarize_stress(rows, policies, {'attack': {'kind': 'independent', 'r': .9}})
        self.assertEqual(stress['actual_risk']['Jc']['false_adopt'], .9)
        self.assertEqual(stress['report']['overall']['Jc']['eligible']['Q_F']['rates']['adopt'], .5)
        self.assertTrue(stress['actual_risk']['Jc']['exceeds_5_percent'])
        cue_stress = run.summarize_stress(rows, policies, {'generation': cr.REFERENCE})
        self.assertEqual(cue_stress['actual_risk']['Jc']['false_adopt'], .5)

    def test_small_fixture_report_outputs_without_running_research_batch(self):
        base = {**run.build_base_contexts()[0], 'base_weight': 1.}
        rows = run.build_rows([base], cr.REFERENCE, cr.REFERENCE)
        frontiers = {m: [cr.fit_policy(rows, m, e, robust=m == 'Ec') for e in run.BUDGETS] for m in cr.METHODS}
        policies = {m: frontiers[m][1]['policy'] for m in cr.METHODS}
        strata = run.summarize_strata(rows, policies)
        stress = [run.summarize_stress(rows, policies, {'name': 'fixture'})]
        common = {m: cr.evaluate_policy(rows, m, policies['Ic'], True) for m in ('Ic', 'Jc')}
        run.json_safe(run.transitions(rows, policies))
        text = run.summary_text({'source_commit': 'fixture', 'elapsed_seconds': 0.}, frontiers, strata, stress, common)
        self.assertIn('F4', text)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            run.plot_results(output, frontiers, stress)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'main_frontier.png', 'main_frontier.svg', 'stress_risk.png', 'stress_risk.svg'})

    def test_output_boundary_and_json_forbids_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'result'
            run.prepare_output(output)
            run.save_json(output / 'config.json', {'infinite': math.inf, 'missing': None})
            self.assertIn('"+inf"', (output / 'config.json').read_text())
            with self.assertRaises(FileExistsError):
                run.prepare_output(output)
            with self.assertRaises(ValueError):
                run.save_json(output / 'bad.json', {'bad': math.nan})


if __name__ == '__main__':
    unittest.main()
