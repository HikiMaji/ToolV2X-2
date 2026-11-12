"""Resume independent native jobs through persistent execution-only directory views."""
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

from parallel_prepare import data, run, THREAD_ENV, prepare_parent


def job_view(out, spec, job, manifest_source):
    view = out / '_job_views' / job['job_id']
    view.mkdir(parents=True, exist_ok=True)
    selected = dict(spec, jobs=[dict(job)], execution_view=dict(
        purpose='execution-only filter; official full manifest remains authoritative',
        official_manifest=manifest_source, job_id=job['job_id'], parent=job['parent']))
    manifest = view / 'manifest.json'
    if manifest.exists():
        if json.loads(manifest.read_text()) != selected:
            raise RuntimeError('existing job view differs: ' + job['job_id'])
    else:
        data.atomic_json(manifest, selected)
    for name in ('jobs', 'parents', 'native_runtime.json'):
        link, target = view / name, out / name
        if link.is_symlink():
            if link.resolve() != target.resolve():
                raise RuntimeError('job view symlink has a different target: ' + str(link))
        elif link.exists():
            raise FileExistsError('job view path is not a symlink: ' + str(link))
        else:
            link.symlink_to(target, target_is_directory=target.is_dir())
    return view


def prepare(out, workers=8):
    if workers < 1:
        raise ValueError('workers must be positive')
    out = Path(out).resolve(strict=True)
    # Shared with parallel_prepare.py; never run alongside the original unlocked prepare.
    with (out / '.parallel_prepare.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another parallel prepare runner is writing this out') from exc
        if (out / 'prepare.complete.json').exists():
            raise FileExistsError('prepare already complete')
        if not (out / 'manifest.json').exists() or not (out / 'native_runtime.json').exists():
            raise RuntimeError('existing manifest and native_runtime are required')
        spec = data.manifest(out)
        if spec['code']['commit'] != '549e86fbc2b6fae0bf608cb6344253466f4f6e7c':
            raise RuntimeError('manifest is not from frozen 549e86f')
        jobs = spec['jobs']
        if len(jobs) != len({job['job_id'] for job in jobs}):
            raise ValueError('duplicate job_id would create concurrent writers')
        for parent in data.NEW_PARENTS:
            cache = out / 'parents' / parent.replace('/', '__')
            if not all((cache / name).exists() for name in ('scans.jsonl.gz', 'provenance.json')):
                raise RuntimeError('all four native scan caches must already be complete')
        pending = []
        for job in jobs:
            path = out / 'jobs' / job['job_id'] / 'complete.json'
            status = json.loads(path.read_text())['status'] if path.exists() else None
            if job['split'] == 'fit' and status != 'COMPLETE':
                raise RuntimeError('all fit jobs must already be COMPLETE')
            if job['origin'] == 'legacy':
                if status != 'COMPLETE' or not (out / 'legacy' / (job['job_id'] + '.jsonl.gz')).exists():
                    raise RuntimeError('legacy jobs and joined caches must already be complete')
            elif job['origin'] == 'native' and job['parent'] in data.NEW_PARENTS:
                if status is None:
                    pending.append(job)
                elif status not in ('COMPLETE', 'UNREALIZABLE'):
                    raise RuntimeError('unexpected completed native status: ' + str(status))
            else:
                raise ValueError('unexpected job origin or native parent')
        manifest_source = data.source_record(out / 'manifest.json')
        assignments = [(job_view(out, spec, job, manifest_source), job['parent']) for job in pending]
        data.atomic_json(out / ('parallel_prepare_jobs.' + str(time.time_ns()) + '.json'), dict(
            runner=data.source_record(Path(__file__)),
            parent_helper=data.source_record(Path(__file__).with_name('parallel_prepare.py')),
            official_manifest=manifest_source, pending_jobs=pending, workers=workers,
            started_utc=datetime.now(timezone.utc).isoformat(), executable=sys.executable,
            python=sys.version, start_method='spawn',
            thread_env={name: os.environ[name] for name in THREAD_ENV}))
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = [pool.submit(prepare_parent, view, parent) for view, parent in assignments]
            for future in futures:
                future.result()
        if not all((out / 'jobs' / job['job_id'] / 'complete.json').exists() for job in jobs):
            raise RuntimeError('job workers returned with incomplete jobs')
        run.prepare(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    prepare(args.out, args.workers)
