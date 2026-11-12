"""External job scheduler for the frozen 549e86f scorer; no algorithm changes."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import fcntl
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time

# spawn imports numpy/scipy afresh after these explicit per-process limits.
THREAD_ENV = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
              'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS')
for name in THREAD_ENV:
    os.environ[name] = '1'

CORE = Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-temporal-2026-11-12')
sys.path.insert(0, str(CORE))
from scripts.rq1_temporal import data, kernel, run

VARIANTS = [('main', 10, .9), ('W5', 5, .9), ('W20', 20, .9),
            ('s05', 10, .5), ('s095', 10, .95)]


def score_job(out, job_id, fitted):
    status = json.loads((out / 'jobs' / job_id / 'complete.json').read_text())
    if status['status'] == 'UNREALIZABLE':
        return
    rows = list(data.read_rows(out / 'jobs' / job_id / 'rows.jsonl.gz'))
    for name, W, s in VARIANTS:
        dest = out / 'scores' / name / (job_id + '.jsonl.gz')
        if dest.exists():
            continue
        with data.atomic_rows(dest) as write:
            for window in kernel.windows(rows, W):
                result = kernel.score_window(window, fitted['models'], fitted['rho'], W, s)
                write(run.prediction(window[-1], result))
        print('scored variant', job_id, name, len(rows), flush=True)
    print('scored', job_id, len(rows), flush=True)


def score(out, workers=8):
    if workers < 1:
        raise ValueError('workers must be positive')
    out = Path(out).resolve(strict=True)
    # Keep the inode in place so waiting/new runners always lock the same file.
    with (out / '.parallel_score.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another parallel score runner is writing this out') from exc
        run.require_prepare(out)
        if (out / 'score.complete.json').exists():
            raise FileExistsError('score already complete')
        fitted = json.loads((out / 'models.json').read_text())
        spec = json.loads((out / 'manifest.json').read_text())
        jobs = [job['job_id'] for job in spec['jobs']]
        if len(jobs) != len(set(jobs)):
            raise ValueError('duplicate job_id would create concurrent writers')
        code = data.code_record()
        if code['commit'] != '549e86fbc2b6fae0bf608cb6344253466f4f6e7c':
            raise RuntimeError('core checkout is not the frozen 549e86f commit')
        started = datetime.now(timezone.utc).isoformat()
        begin = time.monotonic()
        with ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = [pool.submit(score_job, out, job_id, fitted) for job_id in jobs]
            for future in futures:
                future.result()
        runner = data.source_record(Path(__file__))
        runner.update(workers=workers, started_utc=started,
                      elapsed_seconds=time.monotonic() - begin,
                      runtime=dict(python=sys.version, executable=sys.executable,
                                   platform=platform.platform(), pid=os.getpid(),
                                   start_method='spawn', numpy=importlib.metadata.version('numpy'),
                                   scipy=importlib.metadata.version('scipy'),
                                   thread_env={name: os.environ[name] for name in THREAD_ENV}))
        data.atomic_json(out / 'score.complete.json', dict(
            variants=VARIANTS, method_status=fitted['method_status'], code=code, runner=runner))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    score(args.out, args.workers)


if __name__ == '__main__':
    main()
