import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.rq1_temporal import data
from scripts.rq1_trusted_receiver import run as core
from scripts.rq1_trusted_receiver.test_policy import sample

MODULE = Path(__file__).with_name('evaluate_grouped_acceptance.py')
spec = importlib.util.spec_from_file_location('evaluate_grouped_acceptance', MODULE)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def policies():
    return {m: dict(tauF=.5, tauP=.7, tauR=2., tauC=1., status='active') for m in core.METHODS}


def rows(loss=3):
    old = policies()
    result = [sample(i, split='eval', C=1.5 if i < loss else 3.,
                     R=3. if i < loss else 0.) for i in range(100)]
    result += [sample(i, 0, split='eval', C=-1., R=3., MissCount=3.) for i in range(20)]
    for row in result:
        row['scores'] = {m: row['C'] for m in core.METHODS}
        row['decisions'], row['decision_reasons'] = {}, {}
        for method in core.METHODS:
            actual = core.decide(core._public(row), old[method], method)
            row['decisions'][method], row['decision_reasons'][method] = actual['decision'], actual['reason']
            row['local_state'] = actual['local_state']
    return result


class DriverTests(unittest.TestCase):
    def test_no_go_does_not_read_source_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            screen = Path(tmp)/'screen'
            data.atomic_json(screen/'screen.json', dict(go_regimes=[]))
            with patch.object(driver.data, 'read_rows', side_effect=AssertionError('no predictions may be read')):
                result = driver.evaluate(Path(tmp)/'missing_source', screen)
            self.assertEqual(result['regimes'], {})
            self.assertTrue((screen/'evaluation/evaluate.report.json').exists())

    def test_only_tauC_may_increase_and_source_rows_unchanged(self):
        old = policies()
        new = copy.deepcopy(old)
        new['LocalCount']['tauC'] = new['LocalCond']['tauC'] = 2.
        driver.validate_policies(old, new)
        original = rows()
        snapshot = copy.deepcopy(original)
        revised = driver.reapply(original, old, new)
        self.assertEqual(original, snapshot)
        for before, after in zip(original, revised):
            self.assertEqual(before['key'], after['key'])
            self.assertEqual(before['scores'], after['scores'])
            self.assertEqual(after['previous_decisions'], before['decisions'])
            for method in core.METHODS:
                a, b = before['decisions'][method], after['decisions'][method]
                self.assertTrue(a == b or (a, b) == ('accept', 'unknown'))
        for change in (dict(tauR=3.), dict(tauC=.5)):
            changed = copy.deepcopy(new)
            changed['LocalCount'].update(change)
            with self.assertRaises(ValueError): driver.validate_policies(old, changed)

    def test_own_adoption_loss_blocks_pass_and_local_reference_failure_does_not(self):
        old = policies()
        new = copy.deepcopy(old)
        new['LocalCount']['tauC'] = new['LocalCond']['tauC'] = 2.
        passing = dict(Local=dict(status='not_retained', checks={}),
                       LocalCond=dict(status='retained', checks={}))
        for loss, expected in ((3, 'not_retained'), (0, 'retained')):
            revised = driver.reapply(rows(loss), old, new)
            measured = core.measurements(revised, [('F1', 1)])
            with patch.object(driver.core, '_judge', return_value=passing):
                verdict = driver.judge(measured, new, {}, driver.comparisons(revised))
            self.assertEqual(verdict['status'], expected)
            self.assertEqual(verdict['checks']['own_TA_loss_LocalCount']['status'], 'fail' if loss else 'pass')

    def test_entry_writes_separate_outputs_and_preserves_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, screen = Path(tmp)/'source', Path(tmp)/'screen'
            old = policies()
            new = copy.deepcopy(old)
            for method in ('LocalCount', 'LocalCond'): new[method]['tauC'] = 2.
            data.atomic_json(screen/'screen.json', dict(go_regimes=['mixed']))
            data.atomic_json(screen/'candidate_policies.json', dict(mixed={m: new[m] for m in ('LocalCount', 'LocalCond')}))
            data.atomic_json(source/'calibration/mixed.json', old)
            data.atomic_json(source/'evaluate.binding.json', dict(config=dict(required_k=[1],
                regimes=dict(mixed=dict(cal_families=['F1'], eval_families=['F1'])),
                domains=dict(original_3=['P']), criteria={})))
            for split in ('cal', 'eval'):
                with data.atomic_rows(source/'predictions/mixed'/(split+'.jsonl.gz')) as write:
                    for row in rows(0): write(dict(row, split=split))
            data.atomic_json(screen/'binding.json', dict(source_run=str(source.resolve()),
                sources=[data.source_record(source/'calibration/mixed.json'),
                         data.source_record(source/'predictions/mixed/cal.jsonl.gz')]))
            before = {str(p): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            result = driver.evaluate(source, screen)
            self.assertIn('mixed', result['regimes'])
            out = screen/'evaluation'
            self.assertTrue((out/'report/mixed/eval.json').exists())
            self.assertIn('by_group', result['regimes']['mixed']['eval'])
            self.assertIn('original_3', result['regimes']['mixed']['eval']['by_domain'])
            self.assertEqual(before, {str(p): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            with self.assertRaises(FileExistsError): driver.evaluate(source, screen)


if __name__ == '__main__':
    unittest.main()
