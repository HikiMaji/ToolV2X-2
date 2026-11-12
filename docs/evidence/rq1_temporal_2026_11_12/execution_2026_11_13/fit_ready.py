"""Fit frozen models once all fit jobs complete, while cal/eval prepare continues."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
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
from scripts.rq1_temporal import data, fit as fitting, run


def fit(out):
    out = Path(out).resolve(strict=True)
    with (out / '.models.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another fit-ready model writer is running') from exc
        if (out / 'models.json').exists():
            raise FileExistsError('models already exist')
        if not (out / 'manifest.json').exists():
            raise RuntimeError('existing manifest is required')
        spec = data.manifest(out)
        if spec['code']['commit'] != '549e86fbc2b6fae0bf608cb6344253466f4f6e7c':
            raise RuntimeError('manifest is not from frozen 549e86f')
        fit_jobs = [job for job in spec['jobs'] if job['split'] == 'fit']
        if not fit_jobs:
            raise RuntimeError('manifest has no fit jobs')
        for job in fit_jobs:
            path = out / 'jobs' / job['job_id'] / 'complete.json'
            if not path.exists() or json.loads(path.read_text())['status'] != 'COMPLETE':
                raise RuntimeError('fit job not COMPLETE: ' + job['job_id'])
        data.atomic_json(out / ('fit_ready.' + str(time.time_ns()) + '.json'), dict(
            runner=data.source_record(Path(__file__)), fit_jobs=[j['job_id'] for j in fit_jobs],
            started_utc=datetime.now(timezone.utc).isoformat(),
            prepare_complete_at_start=(out / 'prepare.complete.json').exists(),
            executable=sys.executable, python=sys.version,
            thread_env={name: os.environ[name] for name in THREAD_ENV}))
        # Same data selection, fitting sequence and models.json fields as frozen run.fit.
        rows = [r for r in data.all_rows(out, 'fit') if r['kind'] == 'clean']
        oof = fitting.fit_rho_oof(rows, W=10)
        models = fitting.fit_models(rows)
        data.atomic_json(out / 'models.json', dict(
            models=models, rho=oof['rho'], rho_fit=oof,
            method_status=fitting.method_status(models, oof['rho']),
            code=data.code_record(), n_input_rows=len(rows)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    fit(parser.parse_args().out)
