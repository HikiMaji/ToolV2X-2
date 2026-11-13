"""Read-only legacy binding and resumable preparation of 26 frozen fit attacks."""
import os

for _thread_variable in ('NUMBA_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS',
                         'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_thread_variable] = '1'

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, ExitStack
import fcntl
import itertools
import json
from pathlib import Path
import subprocess
import traceback

from scripts.rq1_temporal import data, native_adapter as native

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO/'docs/REALLY_MAYBE/rq1_score_revision_2026_11_13/frozen_config.json'
LEGACY_GT = data.EVIDENCE/'oqea_h1_retrain_2026_10_30_envfix1/run_001/offline_gt/offline_gt.json'
LEGACY_DETECTIONS = data.EVIDENCE/'oqea_h1_retrain_2026_10_30_envfix1/run_001/detections'
MESSAGE_FIELDS = ('source_id', 'frame', 'timestamp', 'pose_xyz', 'yaw', 'tracks', 'fov_boundary')


def read_config(path=None):
    """Return the frozen JSON unchanged; validate task identities before use."""
    config = json.loads(Path(path or DEFAULT_CONFIG).read_text())
    jobs = config['planned_fit_attacks']
    if len(jobs) != 26 or len({j['job_id'] for j in jobs}) != 26:
        raise ValueError('expected 26 distinct frozen fit attempts')
    for job in jobs:
        ids, k = job['source_ids'], job['attack_k']
        if (job['split'] != 'fit' or config['parent_splits'][job['parent']] != 'fit'
                or job['family'] not in ('F1', 'F2') or job['seed'] != 0
                or not 1 <= k < len(ids) or len(set(ids)) != len(ids)
                or job['controlled_sources'] != ids[:k] or job['normal_probe_source'] != ids[k]
                or job['job_id'] != data.job_id(job['parent'], job['family'], k)):
            raise ValueError('frozen construction metadata mismatch '+job['job_id'])
    return config


def iter_rows(out, split=None):
    """Yield whole jobs in manifest order and their original frame order, with Z."""
    out = Path(out)
    manifest = json.loads((out/'manifest.json').read_text())
    for job in manifest['jobs']:
        if split is not None and job['split'] != split:
            continue
        dest = out/'jobs'/job['job_id']
        complete = Path(job.get('status_path', dest/'complete.json'))
        if not complete.exists():
            raise RuntimeError('job not completed '+job['job_id'])
        status = json.loads(complete.read_text())
        if status['status'] == 'UNREALIZABLE':
            continue
        if status['status'] != 'COMPLETE':
            raise RuntimeError('job not complete '+job['job_id'])
        previous = None
        for original in data.read_rows(Path(job.get('rows_path', dest/'rows.jsonl.gz'))):
            if original['job_id'] != job['job_id']:
                raise ValueError('row/job mismatch')
            if previous is not None and original['frame'] < previous:
                raise ValueError('nonascending row frames '+job['job_id'])
            previous = original['frame']
            row = dict(original)
            for field in ('parent', 'split', 'kind', 'family', 'attack_k'):
                if field in row and row[field] != job[field]:
                    raise ValueError('row metadata mismatch '+field)
                row[field] = job[field]
            row['origin'] = job['origin']
            if 'source_clean_job_id' in job:
                row['source_clean_job_id'] = job['source_clean_job_id']
            yield row


def support_summary(rows, config):
    """Count one injected target per planned job, merging tracker fragments."""
    planned = {j['job_id']: j for j in config['planned_fit_attacks']}
    scans = {jid: set() for jid in planned}
    fragments = {jid: set() for jid in planned}
    for row in rows:
        jid = row['job_id']
        if jid not in planned:
            continue
        job = planned[jid]
        if any(row[key] != job[key] for key in ('parent', 'family', 'attack_k', 'split')):
            raise ValueError('support metadata mismatch '+jid)
        if (row.get('query_present') and not row.get('newborn', False)
                and row.get('query_truth') == 0 and row.get('attack_role') == 'target'):
            scans[jid].add(row['frame'])
            fragments[jid].add((row['id'], row['epoch']))
    limits = config['data_support']
    minimum = limits['min_distinct_labelled_fake_query_scans_for_counted_entity']
    entities = {jid: dict(parent=j['parent'], family=j['family'], attack_k=j['attack_k'],
                         distinct_false_query_scans=len(scans[jid]),
                         query_fragments=len(fragments[jid]), counted=len(scans[jid]) >= minimum)
                for jid, j in planned.items()}
    families = {}
    for family in ('F1', 'F2'):
        group = [e for e in entities.values() if e['family'] == family]
        counted = [e for e in group if e['counted']]
        nonempty = [e for e in group if e['distinct_false_query_scans']]
        k_support = {'1': any(e['attack_k'] == 1 for e in nonempty),
                     'at_least_2': any(e['attack_k'] >= 2 for e in nonempty)}
        parents = sorted({e['parent'] for e in counted})
        reasons = []
        if len(counted) < limits['per_fit_family_min_injected_entities']:
            reasons.append('insufficient_counted_entities')
        if len(parents) < limits['per_fit_family_min_parents']:
            reasons.append('insufficient_counted_parents')
        if not all(k_support[k] for k in limits['required_attack_k_support']):
            reasons.append('missing_attack_k_support')
        families[family] = dict(attempts=len(group), nonempty_entities=len(nonempty),
                                counted_entities=len(counted), counted_parents=len(parents),
                                counted_parent_ids=parents, attack_k_support=k_support,
                                data_support_met=not reasons, reasons=reasons)
    regimes = {name: dict(fit_false=spec['fit_false'],
                          data_support_met=all(families[f]['data_support_met'] for f in spec['fit_false']),
                          unsupported_families=[f for f in spec['fit_false'] if not families[f]['data_support_met']])
               for name, spec in config['regimes'].items()}
    return dict(entities=entities, families=families, regimes=regimes,
                planned_attempts=len(planned),
                short_nonempty_entities=sum(0 < len(s) < minimum for s in scans.values()),
                empty_entities=sum(not s for s in scans.values()),
                any_regime_supported=any(r['data_support_met'] for r in regimes.values()),
                keep_short_trajectories_in_fit_and_eval=True,
                gate_meaning=limits['gate_meaning'])


def _legacy_scans(packets, gt_frames, source_ids, expected_frames):
    byframe = {f['frame']: f for f in gt_frames}
    if len(byframe) != len(gt_frames):
        raise ValueError('duplicate offline GT frame')
    scans = []
    for index, (packet, expected) in enumerate(zip(packets, expected_frames)):
        if (any(packet[k] != expected[k] for k in ('frame', 'index', 'timestamp'))
                or packet['index'] != index
                or abs(packet['timestamp'] - index*.1) > 1e-6
                or [m['source_id'] for m in packet['messages']] != source_ids):
            raise ValueError('sender source/frame/index/timestamp mismatch')
        if packet['frame'] not in byframe:
            raise ValueError('missing offline GT frame '+str(packet['frame']))
        messages = []
        for msg in packet['messages']:
            if msg['frame'] != packet['frame'] or msg['timestamp'] != packet['timestamp']:
                raise ValueError('message/frame mismatch')
            messages.append({k: msg[k] for k in MESSAGE_FIELDS})
        scans.append(dict(frame=packet['frame'], index=index, timestamp=packet['timestamp'],
                          messages=messages, gt=byframe[packet['frame']], echo={}))
    if len(scans) != len(packets) or len(scans) != len(expected_frames):
        raise ValueError('sender/expected frame count mismatch')
    return scans


def _public(scans):
    for scan in scans:
        messages = [{k: msg[k] for k in MESSAGE_FIELDS} for msg in scan['messages']]
        for message in messages:
            if message['fov_boundary'] is None:
                # Empty FOV keeps both native containment and source eligibility false.
                message['fov_boundary'] = []
        yield dict(frame=scan['frame'], index=scan['index'], timestamp=scan['timestamp'], messages=messages)


@contextmanager
def _lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _verify_sources(config):
    records = [config[k] for k in ('source_manifest', 'source_models', 'protocol', 'construction_code')]
    records += config['frozen_normal_code']
    for record in records:
        if data.source_record(record['path'])['sha256'] != record['sha256']:
            raise ValueError('frozen source changed '+record['path'])
    # Validate what this checkout actually imports, not only the historical paths.
    for record in config['frozen_normal_code'] + [config['construction_code']]:
        local = REPO/'scripts/rq1_temporal'/Path(record['path']).name
        if data.source_record(local)['sha256'] != record['sha256']:
            raise ValueError('local frozen implementation changed '+str(local))


def _parent_inputs(out, config, source):
    old_root = Path(config['source_manifest']['path']).parent
    old_jobs = {j['job_id']: j for j in source['jobs']}
    parents = {}
    ground = None
    for job in config['planned_fit_attacks']:
        parent = job['parent']
        if parent in parents:
            continue
        clean = old_jobs[job['source_clean_job_id']]
        if clean['parent'] != parent or clean['kind'] != 'clean' or clean['split'] != 'fit':
            raise ValueError('source clean binding mismatch')
        old_parent = old_root/'parents'/parent.replace('/', '__')
        if clean['origin'] == 'native':
            provenance_path = old_parent/'provenance.json'
            spec = json.loads(provenance_path.read_text())['spec']
            scan_path = old_parent/'scans.jsonl.gz'
            scans = list(itertools.islice(data.read_rows(scan_path), config['construction']['scans']))
            provenance = dict(origin='old_native_scan_reference', source=data.source_record(provenance_path))
        else:
            if ground is None:
                ground = {r['recording']: r['frames'] for r in json.loads(LEGACY_GT.read_text())['recordings']}
            old_config = json.loads(Path(clean['config']).read_text())
            n = config['construction']['scans']
            packets = list(itertools.islice(data.read_rows(old_config['sender_path']), n))
            if len(packets) != n or old_config['source_ids'] != job['source_ids']:
                raise ValueError('legacy sender horizon/source mismatch '+parent)
            scans = _legacy_scans(packets, ground[parent], job['source_ids'], old_config['expected_frames'][:n])
            spec = dict(parent=parent, source_ids=job['source_ids'], detections=str(LEGACY_DETECTIONS/parent),
                        frames=[s['frame'] for s in scans])
            dest = out/'parents'/parent.replace('/', '__')
            scan_path = dest/'scans.jsonl.gz'
            provenance_path = dest/'provenance.json'
            provenance = dict(origin='legacy_sender_frame_join', spec=spec,
                              sender=data.source_record(old_config['sender_path']),
                              clean_config=data.source_record(clean['config']), offline_gt=str(LEGACY_GT),
                              echo_supervision='empty; old clean rows and Z remain the normal training source')
        if (spec['parent'] != parent or spec['source_ids'] != job['source_ids']
                or len(scans) != 80 or [s['frame'] for s in scans] != spec['frames'][:80]):
            raise ValueError('parent scan/spec/source mismatch '+parent)
        for index, scan in enumerate(scans):
            if (scan['index'] != index or abs(scan['timestamp'] - index*.1) > 1e-6
                    or [m['source_id'] for m in scan['messages']] != job['source_ids']):
                raise ValueError('scan metadata mismatch '+parent)
            for sid in job['source_ids']:
                cache = Path(spec['detections'])/('%06d_%s.npz' % (scan['frame'], sid))
                if not cache.is_file():
                    raise FileNotFoundError(str(cache))
        # This is one correspondence check per parent, before any attack job.
        by_index = {s['index']: s for s in scans[:20]}
        for row in data.read_rows(old_root/'jobs'/clean['job_id']/'rows.jsonl.gz'):
            if row['index'] >= 20:
                break
            scan = by_index[row['index']]
            if (row['frame'] != scan['frame'] or row['timestamp'] != scan['timestamp']
                    or row['source_ids'] != job['source_ids']):
                raise ValueError('old clean/scan correspondence mismatch '+parent)
        if clean['origin'] != 'native':
            if not scan_path.exists():
                with data.atomic_rows(scan_path) as write:
                    for scan in scans:
                        write(scan)
            else:
                if list(data.read_rows(scan_path)) != scans:
                    raise ValueError('resumed parent scan cache differs '+parent)
            if not provenance_path.exists():
                data.atomic_json(provenance_path, provenance)
        parents[parent] = dict(scan_path=str(scan_path.resolve()),
                               provenance_path=str(provenance_path.resolve()), spec=spec,
                               source_clean_job_id=clean['job_id'], binding=provenance)
    return parents


def _manifest(out, config):
    path = out/'manifest.json'
    code = data.source_record(__file__)
    if path.exists():
        manifest = json.loads(path.read_text())
        if manifest['config'] != config or manifest['prepare_code']['sha256'] != code['sha256']:
            raise ValueError('frozen preparation config/code changed; use a new output')
        return manifest
    _verify_sources(config)
    old_root = Path(config['source_manifest']['path']).parent.resolve()
    if out == old_root or old_root in out.parents or out in old_root.parents:
        raise ValueError('output must be isolated from source run')
    source = json.loads(Path(config['source_manifest']['path']).read_text())
    if (len(source['jobs']) != 70 or source['parent_splits'] != config['parent_splits']
            or {j['job_id'] for j in source['jobs'] if j['split'] in ('cal', 'eval')}
            != set(config['fixed_cal_eval_job_ids'])):
        raise ValueError('frozen source task/split mismatch')
    jobs = []
    for old in source['jobs']:
        status_path = old_root/'jobs'/old['job_id']/'complete.json'
        status = json.loads(status_path.read_text())
        if status['status'] not in ('COMPLETE', 'UNREALIZABLE'):
            raise ValueError('source task not complete '+old['job_id'])
        jobs.append(dict(old, source_origin=old['origin'], origin='reference',
                         rows_path=str(old_root/'jobs'/old['job_id']/'rows.jsonl.gz'),
                         status_path=str(status_path)))
    parents = _parent_inputs(out, config, source)
    for planned in config['planned_fit_attacks']:
        jobs.append(dict(planned, kind='attack', origin='score_revision',
                         rows_path=str(out/'jobs'/planned['job_id']/'rows.jsonl.gz'),
                         status_path=str(out/'jobs'/planned['job_id']/'complete.json')))
    if len({j['job_id'] for j in jobs}) != 96:
        raise ValueError('new/source job collision')
    manifest = dict(schema='rq1_score_revision_prepare_v1', config=config, prepare_code=code,
                    source_manifest=config['source_manifest'], source_models=config['source_models'],
                    parent_splits=config['parent_splits'], parents=parents, jobs=jobs)
    data.atomic_json(path, manifest)
    return manifest


def _worker(out, job_id):
    out = Path(out)
    manifest = json.loads((out/'manifest.json').read_text())
    job = next(j for j in manifest['jobs'] if j['job_id'] == job_id)
    if job['origin'] != 'score_revision':
        raise ValueError('worker may only prepare new attacks')
    dest = out/'jobs'/job_id
    with _lock(dest/'.prepare.lock'):
        if (dest/'complete.json').exists():
            return
        try:
            binding = manifest['parents'][job['parent']]
            scans = list(itertools.islice(data.read_rows(binding['scan_path']), 80))
            attack_path = dest/'attack.json'
            if attack_path.exists():
                attack = json.loads(attack_path.read_text())
            else:
                attack = native.construct_attack(job, scans)
                data.atomic_json(attack_path, attack)
            if attack['status'] == 'UNREALIZABLE':
                data.atomic_json(dest/'complete.json', dict(attack, origin='score_revision'))
                return
            if (attack['status'] != 'VALID' or attack['controlled_sources'] != job['controlled_sources']
                    or attack['normal_source'] != job['normal_probe_source']):
                raise ValueError('constructed roles differ from frozen metadata')
            online_path = dest/'online.jsonl.gz'
            if not online_path.exists():
                with data.atomic_rows(online_path) as write:
                    for event in native.replay_online(job, binding['spec'], _public(scans), attack):
                        write(event)
            rows_path = dest/'rows.jsonl.gz'
            coverage_path = dest/'entity_coverage.jsonl.gz'
            diagnostics = Counter()
            diagnostics['public_occlusion_frames'] = set()
            if not rows_path.exists() or not coverage_path.exists():
                with ExitStack() as stack:
                    write = stack.enter_context(data.atomic_rows(rows_path)) if not rows_path.exists() else None
                    coverage_write = stack.enter_context(data.atomic_rows(coverage_path)) if not coverage_path.exists() else None
                    for row in native.attach_labels(data.read_rows(online_path), scans, job, attack, diagnostics, coverage_write):
                        if write is not None:
                            write(row)
            counts = Counter()
            role_counts = Counter(target_query_rows=0)
            n = 0
            for row in data.read_rows(rows_path):
                n += 1
                counts['query_truth_'+str(row['query_truth'])] += 1
                if row['query_truth'] == 0:
                    role_counts[str(row.get('attack_role'))+'_query_rows'] += 1
            for key, value in role_counts.items():
                diagnostics[key] = value
            diagnostics['public_occlusion_frames'] = len(diagnostics['public_occlusion_frames'])
            coverage = native.coverage_summary(data.read_rows(coverage_path))
            data.atomic_json(dest/'complete.json', dict(status='COMPLETE', rows=n, counts=dict(counts),
                             origin='score_revision', attack_constructed=True,
                             actual_construction=dict(diagnostics), entity_coverage=coverage))
        except Exception as exc:
            if not (dest/'error.json').exists():
                data.atomic_json(dest/'error.json', dict(error=type(exc).__name__+': '+str(exc),
                                 traceback=traceback.format_exc()))
            raise


def prepare(out, workers=8, config_path=None):
    """Run only independent frozen jobs in the established native runtime."""
    if not 1 <= workers <= 8:
        raise ValueError('workers must be between 1 and 8')
    out = Path(out).resolve()
    config = read_config(config_path)
    source_root = Path(config['source_manifest']['path']).parent.resolve()
    if out == source_root or source_root in out.parents or out in source_root.parents:
        raise ValueError('output must be isolated from source run')
    with _lock(out/'.prepare.lock'):
        manifest = _manifest(out, config)
        if (out/'prepare.complete.json').exists():
            return json.loads((out/'prepare.complete.json').read_text())
        pending = [j for j in manifest['jobs'] if j['origin'] == 'score_revision'
                   and not Path(j['status_path']).exists()]
        failures = []
        def run(job):
            with (out/'jobs'/job['job_id']/'worker.log').open('a') as stream:
                subprocess.run([str(data.RUNTIME), '-m', 'scripts.rq1_score_revision.prepare',
                                '--out', str(out), '--_worker', job['job_id']], cwd=str(REPO),
                               env=os.environ.copy(), stdout=stream, stderr=subprocess.STDOUT, check=True)
        for j in pending:
            (out/'jobs'/j['job_id']).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run, j): j['job_id'] for j in pending}
            for future in as_completed(futures):
                try:
                    future.result()
                    print('prepared', futures[future], flush=True)
                except Exception as exc:
                    error = dict(job_id=futures[future], error=type(exc).__name__+': '+str(exc))
                    error_path = out/'jobs'/futures[future]/'error.json'
                    if not error_path.exists():
                        data.atomic_json(error_path, error)
                    failures.append(error)
        if failures:
            raise RuntimeError('preparation failed; preserve errors and resume: '+json.dumps(failures))
        statuses = {j['job_id']: json.loads(Path(j['status_path']).read_text()) for j in manifest['jobs']}
        if any(s['status'] not in ('COMPLETE', 'UNREALIZABLE') for s in statuses.values()):
            raise RuntimeError('nonterminal job status')
        support = support_summary(iter_rows(out, 'fit'), config)
        if (out/'support.json').exists():
            if json.loads((out/'support.json').read_text()) != support:
                raise ValueError('resumed support summary differs')
        else:
            data.atomic_json(out/'support.json', support)
        result = dict(status='COMPLETE', jobs=statuses, attempted_attacks=26,
                      unrealizable_new=sum(statuses[j['job_id']]['status'] == 'UNREALIZABLE'
                                           for j in manifest['jobs'] if j['origin'] == 'score_revision'),
                      support='support.json', prepare_code=manifest['prepare_code'])
        data.atomic_json(out/'prepare.complete.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--_worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._worker:
        if args.out is None:
            parser.error('--_worker requires --out')
        _worker(args.out, args._worker)
    else:
        config = read_config(args.config)
        prepare(args.out or config['new_output_root'], args.workers, args.config)


if __name__ == '__main__':
    main()
