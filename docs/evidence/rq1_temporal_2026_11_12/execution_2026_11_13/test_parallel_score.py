"""One synthetic scheduling fixture; never reads or writes run_001."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'

CORE = Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-temporal-2026-11-12')
sys.path.insert(0, str(CORE))
from scripts.rq1_temporal import data, fit, run
from scripts.rq1_temporal.test_temporal import models, row

RUNNER = Path(__file__).with_name('parallel_score.py')


def fixture(out):
    jobs = [{'job_id': name} for name in ('a', 'b', 'unrealizable')]
    data.atomic_json(out / 'prepare.complete.json', {})
    data.atomic_json(out / 'manifest.json', {'jobs': jobs})
    fitted = models()
    data.atomic_json(out / 'models.json', dict(
        models=fitted, rho=.5, method_status=fit.method_status(fitted, .5)))
    for job in jobs:
        name = job['job_id']
        data.atomic_json(out / 'jobs' / name / 'complete.json', dict(
            status='UNREALIZABLE' if name == 'unrealizable' else 'ok'))
        if name == 'unrealizable':
            continue
        with data.atomic_rows(out / 'jobs' / name / 'rows.jsonl.gz') as write:
            for t in range(12 if name == 'a' else 7):
                r = row(t, ((t // 2) % 2, (t // 3) % 2), parent=name)
                r.update(key=[name, t, 1], family='clean', attack_k=0,
                         native_mean=.7 if t % 2 else None)
                if t == 2:
                    r['C'][0] = None
                    r['C_missing'][0] = True
                if t == 3:
                    r['X'][1] = None
                if t == 4:
                    r['U'] = [-1, -1]
                if t == 5:
                    r['output_present'] = False
                write(r)


def invoke(out):
    return subprocess.run([sys.executable, str(RUNNER), '--out', str(out),
                           '--workers', '2'], text=True, capture_output=True)


class ParallelScoreTest(unittest.TestCase):
    def test_one_fixture_matches_serial_and_preserves_completion_contract(self):
        self.assertTrue(RUNNER.exists(), 'external parallel score runner is missing')
        with tempfile.TemporaryDirectory(prefix='rq1-parallel-fixture-') as tmp:
            base = Path(tmp)
            serial, parallel, failed = [base / name for name in ('serial', 'parallel', 'failed')]
            fixture(serial)
            shutil.copytree(serial, parallel)
            shutil.copytree(serial, failed)
            run.score(serial)

            # A completed shard must be skipped without touching its bytes or mtime.
            shard = Path('scores/main/a.jsonl.gz')
            (parallel / shard).parent.mkdir(parents=True)
            shutil.copy2(serial / shard, parallel / shard)
            preserved = ((parallel / shard).read_bytes(), (parallel / shard).stat().st_mtime_ns)
            result = invoke(parallel)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            paths = sorted(p.relative_to(serial) for p in (serial / 'scores').rglob('*.jsonl.gz'))
            self.assertEqual(len(paths), 10)
            self.assertEqual(paths, sorted(p.relative_to(parallel) for p in (parallel / 'scores').rglob('*.jsonl.gz')))
            compared = 0
            for path in paths:
                expected, actual = list(data.read_rows(serial / path)), list(data.read_rows(parallel / path))
                self.assertEqual(actual, expected, str(path))
                compared += len(actual)
            self.assertEqual(preserved, ((parallel / shard).read_bytes(), (parallel / shard).stat().st_mtime_ns))
            marker = parallel / 'score.complete.json'
            complete = json.loads(marker.read_text())
            original = json.loads((serial / 'score.complete.json').read_text())
            for key in ('variants', 'method_status', 'code'):
                self.assertEqual(complete[key], original[key])
            self.assertEqual(complete['runner']['sha256'], hashlib.sha256(RUNNER.read_bytes()).hexdigest())
            self.assertEqual(complete['runner']['workers'], 2)
            self.assertTrue(all(v == '1' for v in complete['runner']['runtime']['thread_env'].values()))
            before = marker.read_bytes()
            result = invoke(parallel)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('score already complete', result.stderr)
            self.assertEqual(marker.read_bytes(), before)

            # One missing input is a real worker exception, never a complete stage.
            (failed / 'jobs/b/rows.jsonl.gz').unlink()
            result = invoke(failed)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FileNotFoundError', result.stderr)
            self.assertFalse((failed / 'score.complete.json').exists())
            with (failed / '.parallel_score.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = invoke(failed)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('another parallel score runner', result.stderr)
                self.assertFalse((failed / 'score.complete.json').exists())
            print(f'fixture: {len(paths)} shards, {compared} rows equal; skip/refusal/failure/lock PASS')


if __name__ == '__main__':
    unittest.main()
