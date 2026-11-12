"""One mocked fit fixture, with real split/status/clean-row filtering."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name('fit_ready.py')


class FitReadyTest(unittest.TestCase):
    def test_fit_filtering_readiness_and_original_score_gate(self):
        self.assertTrue(RUNNER.exists(), 'external fit-ready helper is missing')
        spec = importlib.util.spec_from_file_location('fit_ready', RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        jobs = [dict(job_id='clean', split='fit'), dict(job_id='attack', split='fit'),
                dict(job_id='cal-unready', split='cal'), dict(job_id='eval-unready', split='eval')]
        code = dict(commit='549e86fbc2b6fae0bf608cb6344253466f4f6e7c', files=[])
        expected = [dict(kind='clean', query_truth=1, id=1),
                    dict(kind='clean', query_truth=-1, newborn=True, id=2)]
        oof = dict(rho=.5, status='ok')
        models, status = {'fixture': 'model'}, {'fixture': 'method-status'}
        with tempfile.TemporaryDirectory(prefix='rq1-fit-ready-mock-') as tmp:
            out = Path(tmp)
            runner.data.atomic_json(out / 'manifest.json', dict(jobs=jobs, code=code))
            runner.data.atomic_json(out / 'jobs/clean/complete.json', {'status': 'COMPLETE'})
            with runner.data.atomic_rows(out / 'jobs/clean/rows.jsonl.gz') as write:
                for row in expected:
                    write(row)
            with runner.data.atomic_rows(out / 'jobs/attack/rows.jsonl.gz') as write:
                write(dict(kind='attack', id=999))
            with patch.object(runner.data, 'code_record', return_value=code), \
                    patch.object(runner.fitting, 'fit_rho_oof', return_value=oof) as rho_fit, \
                    patch.object(runner.fitting, 'fit_models', return_value=models) as model_fit, \
                    patch.object(runner.fitting, 'method_status', return_value=status) as method_status:
                with self.assertRaisesRegex(RuntimeError, 'fit job not COMPLETE'):
                    runner.fit(out)
                rho_fit.assert_not_called()
                self.assertFalse((out / 'models.json').exists())
                runner.data.atomic_json(out / 'jobs/attack/complete.json', {'status': 'COMPLETE'})
                runner.fit(out)
                rho_fit.assert_called_once_with(expected, W=10)
                model_fit.assert_called_once_with(expected)
                method_status.assert_called_once_with(models, .5)
                self.assertEqual(json.loads((out / 'models.json').read_text()), dict(
                    models=models, rho=.5, rho_fit=oof, method_status=status, code=code, n_input_rows=2))
                provenance, = out.glob('fit_ready.*.json')
                self.assertFalse(json.loads(provenance.read_text())['prepare_complete_at_start'])
                before = (out / 'models.json').read_bytes()
                with self.assertRaises(FileExistsError):
                    runner.fit(out)
                self.assertEqual((out / 'models.json').read_bytes(), before)
            with self.assertRaisesRegex(RuntimeError, 'prepare is incomplete'):
                runner.run.score(out)
        print('mock fixture: all fit jobs required, only clean fit rows consumed; original score gate PASS')


if __name__ == '__main__':
    unittest.main()
