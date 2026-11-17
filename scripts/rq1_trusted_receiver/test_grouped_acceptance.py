"""Small hand tables for cal-only grouped acceptance screening."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.rq1_temporal import data
from scripts.rq1_trusted_receiver import run
from scripts.rq1_trusted_receiver import grouped_acceptance as grouped
from scripts.rq1_trusted_receiver.test_policy import sample


def policy(tau=1.):
    return dict(tauF=.5, tauP=.7, tauR=2., tauC=tau, status='active',
        required_layers=[['F1', 1]], missing_layers=[])


def table(false_per_parent=20, concentrated=5, true_lost=1):
    rows = [sample(i, parent='T', C=1.5 if i < true_lost else 3., R=0.) for i in range(100)]
    for p in range(5):
        for i in range(false_per_parent):
            row = sample(i, 0, parent='P'+str(p), job_id='fake'+str(p),
                key=['fake'+str(p), i*2, 1], C=1.5 if p == 0 and i < concentrated else -1.)
            rows.append(row)
    return rows


def saved(rows, policies):
    for row in rows:
        row['decisions'], row['decision_reasons'] = {}, {}
        for method in grouped.METHODS:
            result = run.decide({k: row.get(k) for k in run.PUBLIC_FIELDS}, policies[method], method)
            row['decisions'][method] = result['decision']
            row['decision_reasons'][method] = result['reason']
    return rows


class GroupedTests(unittest.TestCase):
    def test_average_five_percent_with_single_parent_twentyfive(self):
        original = policy()
        candidate, report = grouped.screen_method(table(), original, 'LocalCond')
        self.assertEqual(original, policy())
        self.assertAlmostEqual(report['old']['false_accept']['overall'], .05)
        self.assertAlmostEqual(report['old']['false_accept']['F1/1/P0'], .25)
        self.assertEqual(candidate['tauC'], 3.)
        self.assertEqual((candidate['tauF'], candidate['tauP'], candidate['tauR']), (.5, .7, 2.))
        self.assertAlmostEqual(report['true_accept_loss'], .01)
        self.assertTrue(report['go'])
        self.assertEqual(report['new']['false_accept']['F1/1/P0'], 0.)

    def test_local_risk_cannot_be_repaired_by_message_threshold(self):
        rows = table()
        for row in rows:
            if row['parent'] == 'P0' and row['index'] < 2:
                row.update(I=.9, I_eligible=True)
        candidate, report = grouped.screen_method(rows, policy(), 'LocalCount')
        self.assertTrue(math.isinf(candidate['tauC']))
        self.assertEqual(report['status'], 'infeasible_local_risk')
        self.assertAlmostEqual(report['new']['false_accept']['F1/1/P0'], .1)
        self.assertFalse(report['go'])

    def test_old_threshold_is_explicit_and_kept_when_already_valid(self):
        # No score equals old 1.2; raising to 3 would tie true adoption.
        candidate, report = grouped.screen_method(table(concentrated=0), policy(1.2), 'LocalCond')
        self.assertEqual(candidate['tauC'], 1.2)
        self.assertEqual(report['status'], 'unchanged')
        self.assertTrue(report['go'])

    def test_loss_above_two_percent_or_no_remote_mass_cannot_go(self):
        _, report = grouped.screen_method(table(true_lost=3), policy(), 'LocalCount')
        self.assertAlmostEqual(report['true_accept_loss'], .03)
        self.assertFalse(report['go'])
        rows = table()
        for row in rows:
            if row['kind'] == 'clean': row['C'] = 1.5
        _, report = grouped.screen_method(rows, policy(), 'LocalCount')
        self.assertEqual(report['new']['remote_true_accept'], 0.)
        self.assertFalse(report['go'])

    def test_missing_layer_not_zero_and_only_accept_to_unknown(self):
        rows = table()
        rows[99]['R'] = 3.
        original = policy()
        candidate, report = grouped.screen_method(rows, original, 'LocalCond')
        for row in rows:
            public_row = {k: row.get(k) for k in run.PUBLIC_FIELDS}
            old = run.decide(public_row, original, 'LocalCond')['decision']
            new = run.decide(public_row, candidate, 'LocalCond')['decision']
            self.assertTrue(old == new or (old, new) == ('accept', 'unknown'))
        original['required_layers'].append(['F2', 1])
        _, report = grouped.screen_method(rows, original, 'LocalCond')
        self.assertIsNone(report['new']['false_accept']['F2/1'])
        self.assertEqual(report['missing_layers'], ['F2/1'])
        self.assertFalse(report['go'])

    def test_cli_entry_reads_only_cal_sources_and_requires_both_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp)/'source', Path(tmp)/'screen'
            for regime in grouped.REGIMES:
                policies = {m: policy() for m in grouped.METHODS}
                rows = table()
                # LocalCond already rejects low-score true rows; Count loses three percent.
                for row in rows[:3]: row.update(C=1.5, R=3.)
                data.atomic_json(source/'calibration'/(regime+'.json'), policies)
                with data.atomic_rows(source/'predictions'/regime/'cal.jsonl.gz') as write:
                    for row in saved(rows, policies): write(row)
            read_rows = data.read_rows
            def guarded(path):
                self.assertEqual(Path(path).name, 'cal.jsonl.gz')
                return read_rows(path)
            with patch.object(grouped.data, 'read_rows', guarded):
                result = grouped.screen(source, out)
            self.assertFalse(result['regimes']['mixed']['go'])
            self.assertTrue(result['regimes']['mixed']['methods']['LocalCond']['go'])
            self.assertFalse(result['regimes']['mixed']['methods']['LocalCount']['go'])
            self.assertTrue((out/'candidate_policies.json').exists())
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                ['binding.json', 'candidate_policies.json', 'screen.json'])


if __name__ == '__main__':
    unittest.main()
