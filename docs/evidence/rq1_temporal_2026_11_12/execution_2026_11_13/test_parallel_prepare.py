"""One mocked parent-ownership fixture; no native replay or real run input."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name('parallel_prepare.py')


class ParallelPrepareTest(unittest.TestCase):
    def test_parent_ownership_and_summary_only_after_all_successes(self):
        self.assertTrue(RUNNER.exists(), 'external parallel prepare runner is missing')
        spec = importlib.util.spec_from_file_location('parallel_prepare', RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        from scripts.rq1_temporal import native_adapter
        parents = runner.data.NEW_PARENTS
        jobs = [dict(job_id='legacy', origin='legacy', parent='old', kind='clean', split='fit')]
        for i, parent in enumerate(parents):
            for j in range(1 if i == 0 else 2):
                jobs.append(dict(job_id=f'p{i}_{j}', origin='native', parent=parent,
                                 kind='clean' if j == 0 else 'attack', split=runner.data.SPLITS[parent]))
        code = dict(commit='549e86fbc2b6fae0bf608cb6344253466f4f6e7c', files=[])
        owners, finished, submissions = {}, [], []

        def native_prepare(out):
            self.assertEqual(len(runner.data.NEW_PARENTS), 1)
            parent, = runner.data.NEW_PARENTS
            cache = out / 'parents' / parent.replace('/', '__')
            cache.mkdir(parents=True)
            (cache / 'scans.jsonl.gz').touch()
            (cache / 'provenance.json').touch()
            for job in jobs:
                if job['parent'] == parent:
                    self.assertNotIn(job['job_id'], owners)
                    owners[job['job_id']] = parent
                    runner.data.atomic_json(out / 'jobs' / job['job_id'] / 'complete.json', {'status': 'COMPLETE'})
            finished.append(parent)

        def summarize(out):
            self.assertEqual(finished, list(parents[1:]))
            self.assertEqual(runner.data.NEW_PARENTS, parents)
            self.assertTrue(all((out / 'jobs' / j['job_id'] / 'complete.json').exists() for j in jobs))
            runner.data.atomic_json(out / 'prepare.complete.json', {'summarized': True})

        class Future:
            def __init__(self, fn, args):
                self.fn, self.args = fn, args

            def result(self):
                return self.fn(*self.args)

        class Pool:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def __enter__(self):
                self_test.assertEqual(self.kwargs['max_workers'], 3)
                self_test.assertEqual(self.kwargs['mp_context'].get_start_method(), 'spawn')
                return self

            def __exit__(self, *args):
                pass

            def submit(self, fn, *args):
                submissions.append(args[1])
                return Future(fn, args)

        self_test = self
        with tempfile.TemporaryDirectory(prefix='rq1-parent-mock-') as tmp:
            out = Path(tmp)
            runner.data.atomic_json(out / 'manifest.json', dict(jobs=jobs, code=code))
            manifest_before = (out / 'manifest.json').read_bytes()
            runner.data.atomic_json(out / 'native_runtime.json', {})
            (out / 'legacy').mkdir()
            (out / 'legacy/legacy.jsonl.gz').touch()
            for job in jobs[:2]:
                runner.data.atomic_json(out / 'jobs' / job['job_id'] / 'complete.json', {'status': 'COMPLETE'})
            cache = out / 'parents' / parents[0].replace('/', '__')
            cache.mkdir(parents=True)
            (cache / 'scans.jsonl.gz').touch()
            (cache / 'provenance.json').touch()
            with patch.object(runner.data, 'code_record', return_value=code), \
                    patch.object(runner, 'ProcessPoolExecutor', Pool), \
                    patch.object(native_adapter, 'prepare', side_effect=native_prepare), \
                    patch.object(runner.run, 'prepare', side_effect=summarize) as final:
                runner.prepare(out)
                self.assertEqual(final.call_count, 1)
            self.assertEqual(submissions, list(parents[1:]))
            self.assertEqual(len(owners), 6)
            self.assertEqual((out / 'manifest.json').read_bytes(), manifest_before)
            provenance, = out.glob('parallel_prepare.*.json')
            record = json.loads(provenance.read_text())
            self.assertEqual(record['parents'], list(parents[1:]))
            self.assertEqual(record['workers'], 3)
            self.assertEqual(record['thread_env']['NUMBA_NUM_THREADS'], '1')
            self.assertTrue((out / 'prepare.complete.json').exists())
        print('mock fixture: 3 parent submissions, 6 unique job owners; final summary after all successes PASS')


if __name__ == '__main__':
    unittest.main()
