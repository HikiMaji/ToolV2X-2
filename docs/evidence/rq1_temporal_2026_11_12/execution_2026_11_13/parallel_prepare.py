"""Resume the three independent native cal/eval parents using frozen functions."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time

THREAD_ENV = ('NUMBA_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
              'MKL_NUM_THREADS', 'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
              'NUMEXPR_NUM_THREADS')
for name in THREAD_ENV:
    os.environ[name] = '1'

CORE = Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-temporal-2026-11-12')
sys.path.insert(0, str(CORE))
from scripts.rq1_temporal import data, run


def prepare_parent(out, parent):
    from scripts.rq1_temporal import native_adapter
    original = data.NEW_PARENTS
    try:
        data.NEW_PARENTS = (parent,)
        native_adapter.prepare(out)
    finally:
        data.NEW_PARENTS = original


def prepare(out):
    out = Path(out).resolve(strict=True)
    with (out / '.parallel_prepare.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another parallel prepare runner is writing this out') from exc
        if (out / 'prepare.complete.json').exists():
            raise FileExistsError('prepare already complete')
        if not (out / 'manifest.json').exists() or not (out / 'native_runtime.json').exists():
            raise RuntimeError('existing manifest and native_runtime are required')
        spec = data.manifest(out)  # Validate existing source hashes; never construct a manifest.
        if spec['code']['commit'] != '549e86fbc2b6fae0bf608cb6344253466f4f6e7c':
            raise RuntimeError('manifest is not from frozen 549e86f')
        jobs = spec['jobs']
        if len(jobs) != len({j['job_id'] for j in jobs}):
            raise ValueError('duplicate job_id would create concurrent writers')
        pending = set()
        for job in jobs:
            complete = out / 'jobs' / job['job_id'] / 'complete.json'
            status = json.loads(complete.read_text())['status'] if complete.exists() else None
            if job['origin'] == 'legacy':
                if status != 'COMPLETE' or not (out / 'legacy' / (job['job_id'] + '.jsonl.gz')).exists():
                    raise RuntimeError('legacy jobs and joined caches must already be complete')
            elif job['origin'] == 'native' and job['parent'] in data.NEW_PARENTS:
                if status not in ('COMPLETE', 'UNREALIZABLE'):
                    if job['split'] == 'fit':
                        raise RuntimeError('native fit jobs must already be complete')
                    pending.add(job['parent'])
            else:
                raise ValueError('unexpected job origin or parent')
        parents = [parent for parent in data.NEW_PARENTS if parent in pending]
        if len(parents) > 3:
            raise ValueError('only the three native cal/eval parents may be scheduled')
        record = dict(runner=data.source_record(Path(__file__)), parents=parents, workers=3,
                      started_utc=datetime.now(timezone.utc).isoformat(),
                      executable=sys.executable, python=sys.version, start_method='spawn',
                      thread_env={name: os.environ[name] for name in THREAD_ENV})
        data.atomic_json(out / ('parallel_prepare.' + str(time.time_ns()) + '.json'), record)
        with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = [pool.submit(prepare_parent, out, parent) for parent in parents]
            for future in futures:
                future.result()
        if not all((out / 'jobs' / j['job_id'] / 'complete.json').exists() for j in jobs):
            raise RuntimeError('parent workers returned with incomplete jobs')
        for parent in data.NEW_PARENTS:
            cache = out / 'parents' / parent.replace('/', '__')
            if not all((cache / name).exists() for name in ('scans.jsonl.gz', 'provenance.json')):
                raise RuntimeError('native scan caches must be complete before summary')
        # All scans/jobs are now cached; original prepare only revisits caches and summarizes.
        run.prepare(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    prepare(parser.parse_args().out)
