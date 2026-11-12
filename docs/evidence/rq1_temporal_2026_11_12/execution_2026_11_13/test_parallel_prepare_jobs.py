"""One mocked view fixture; no native replay or real run files."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).with_name('parallel_prepare_jobs.py')


class JobViewsTest(unittest.TestCase):
    def test_same_parent_views_own_outputs_and_summarize_only_after_success(self):
        self.assertTrue(RUNNER.exists(), 'job-view runner is missing')
        sys.path.insert(0, str(RUNNER.parent))
        spec = importlib.util.spec_from_file_location('parallel_prepare_jobs', RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        from scripts.rq1_temporal import native_adapter
        parents = runner.data.NEW_PARENTS
        jobs = [dict(job_id='legacy', origin='legacy', split='fit', parent='old'),
                dict(job_id='fit', origin='native', split='fit', parent=parents[0]),
                *[dict(job_id=name, origin='native', split='cal', parent=parents[1])
                  for name in ('a', 'b')]]
        code = dict(commit='549e86fbc2b6fae0bf608cb6344253466f4f6e7c', files=[])
        submissions, owners = [], {}
        fail_b = True

        class Future:
            def __init__(self, fn, args):
                self.fn, self.args = fn, args

            def result(self):
                if fail_b and self.args[0].name == 'b':
                    raise RuntimeError('fixture worker failure')
                return self.fn(*self.args)

        class Pool:
            def __init__(self, **kwargs):
                self_test.assertEqual(kwargs['max_workers'], 8)
                self_test.assertEqual(kwargs['mp_context'].get_start_method(), 'spawn')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def submit(self, fn, *args):
                submissions.append(args[0].name)
                return Future(fn, args)

        def native_prepare(view):
            selected = json.loads((view / 'manifest.json').read_text())['jobs']
            self.assertEqual(len(selected), 1)
            job, = selected
            self.assertEqual(runner.data.NEW_PARENTS, (job['parent'],))
            self.assertEqual(job['parent'], parents[1])
            self.assertNotIn(job['job_id'], owners)
            owners[job['job_id']] = job['parent']
            for link in ('jobs', 'parents', 'native_runtime.json'):
                self.assertTrue((view / link).is_symlink())
                self.assertEqual((view / link).resolve(), (out / link).resolve())
            runner.data.atomic_json(view / 'jobs' / job['job_id'] / 'complete.json', {'status': 'COMPLETE'})

        def summarize(destination):
            self.assertEqual(destination, out)
            self.assertEqual(set(owners), {'a', 'b'})
            self.assertTrue(all((out / 'jobs' / job['job_id'] / 'complete.json').exists() for job in jobs))
            self.assertEqual(runner.data.NEW_PARENTS, parents)
            runner.data.atomic_json(out / 'prepare.complete.json', {'summarized': True})

        self_test = self
        with tempfile.TemporaryDirectory(prefix='rq1-job-views-mock-') as tmp:
            out = Path(tmp)
            runner.data.atomic_json(out / 'manifest.json', dict(jobs=jobs, code=code, scope='official full fixture'))
            original = (out / 'manifest.json').read_bytes()
            runner.data.atomic_json(out / 'native_runtime.json', {})
            (out / 'legacy').mkdir()
            (out / 'legacy/legacy.jsonl.gz').touch()
            for job in jobs[:2]:
                runner.data.atomic_json(out / 'jobs' / job['job_id'] / 'complete.json', {'status': 'COMPLETE'})
            for parent in parents:
                cache = out / 'parents' / parent.replace('/', '__')
                cache.mkdir(parents=True)
                (cache / 'scans.jsonl.gz').touch()
                (cache / 'provenance.json').touch()
            with patch.object(runner.data, 'code_record', return_value=code), \
                    patch.object(runner, 'ProcessPoolExecutor', Pool), \
                    patch.object(native_adapter, 'prepare', side_effect=native_prepare), \
                    patch.object(runner.run, 'prepare', side_effect=summarize) as final:
                with self.assertRaisesRegex(RuntimeError, 'fixture worker failure'):
                    runner.prepare(out)
                final.assert_not_called()
                self.assertFalse((out / 'prepare.complete.json').exists())
                fail_b = False
                runner.prepare(out)
                final.assert_called_once_with(out)
            self.assertEqual(submissions, ['a', 'b', 'b'])
            self.assertEqual(len(owners), 2)
            self.assertEqual((out / 'manifest.json').read_bytes(), original)
            for name in ('a', 'b'):
                view = out / '_job_views' / name
                metadata = json.loads((view / 'manifest.json').read_text())
                self.assertEqual(metadata['scope'], 'official full fixture')
                self.assertEqual(metadata['execution_view']['job_id'], name)
                self.assertTrue((out / 'jobs' / name / 'complete.json').exists())
        print('mock fixture: same-parent unique owners, real outputs, unchanged manifest, failure gate and final summary PASS')


if __name__ == '__main__':
    unittest.main()
