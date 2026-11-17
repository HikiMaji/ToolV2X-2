"""Prepare shared receiver evidence and evaluate frozen three-state policies."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import itertools
import json
from pathlib import Path

import numpy as np

from scripts.rq1_temporal import data, native_adapter
from .local import measure_frame, valid_shape, VEHICLES


def validate_config(config):
    parents = {p['parent']: p for p in config['parents']}
    if len(parents) != len(config['parents']):
        raise ValueError('duplicate parent/role')
    for spec in parents.values():
        frames = spec['frames']
        if (spec['split'] not in ('fit', 'cal', 'eval') or not frames
                or any(type(f) is not int for f in frames)
                or any(b-a != 2 for a, b in zip(frames, frames[1:]))
                or type(spec['receiver_id']) is not int):
            raise ValueError('invalid receiver, role or ordered frames')
        if 'source_ids' in spec and spec['receiver_id'] not in spec['source_ids']:
            raise ValueError('receiver outside frozen sources')
        for key in ('root', 'detections'):
            if not Path(spec[key]).is_dir():
                raise ValueError('missing '+key+' '+str(spec[key]))
    jobs = config['jobs']
    if len({j['job_id'] for j in jobs}) != len(jobs):
        raise ValueError('duplicate job ID')
    for job in jobs:
        if job['parent'] not in parents or job['kind'] not in ('clean', 'attack'):
            raise ValueError('unknown job parent or kind')
        if '/' in job['job_id'] or job['job_id'] in ('.', '..'):
            raise ValueError('job ID must be a filename')
        if not Path(job['online_path']).is_file():
            raise ValueError('missing public online path '+job['online_path'])
    clean_fit = {j['parent'] for j in jobs if j['kind'] == 'clean'
                 and parents[j['parent']]['split'] == 'fit'}
    if not clean_fit:
        raise ValueError('no clean fit receiver observations; local model not estimable')
    return parents, clean_fit


def fit_shape(samples):
    """Per-axis weighted median: equal parents, tracks within parent, times per track."""
    grouped = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        shape = valid_shape(sample['hwl'])
        grouped[sample['parent']][sample['id']].append(shape)
    if not grouped:
        raise ValueError('no valid clean fit shape; refusing a default vehicle')
    values, weights = [], []
    for parent, tracks in grouped.items():
        for tid, observations in tracks.items():
            weight = 1./len(grouped)/len(tracks)/len(observations)
            values.extend(observations)
            weights.extend([weight]*len(observations))
    values, weights = np.asarray(values), np.asarray(weights)
    shape = []
    for axis in range(3):
        order = np.argsort(values[:, axis], kind='stable')
        index = np.searchsorted(np.cumsum(weights[order]), weights.sum()/2, side='left')
        shape.append(float(values[order[min(index, len(order)-1)], axis]))
    return dict(shape_hwl=valid_shape(shape).tolist(), parents=len(grouped),
                tracks=sum(len(v) for v in grouped.values()), observations=len(values),
                weighting='equal parent, local track within parent, time within track',
                anchor='native bottom xyz', voxel_m=.25)


def receiver_frames(spec):
    """Exactly one clean local tracker; no central or other-source state is created."""
    native, original, _, static = native_adapter.imports()
    from avstack.modules.tracking.tracks import TrackBase
    TrackBase.ID_counter = 0
    tracker = native.BasicBoxTracker3D(check_reference=False)
    counts = {}
    sid = spec['receiver_id']
    for index, frame in enumerate(spec['frames']):
        t = index*.1
        pose = None
        fault = None
        path = Path(spec['detections'])/('%06d_%s.npz' % (frame, sid))
        try:
            with np.load(path, allow_pickle=False) as cache:
                if index == 0 and str(cache['checkpoint_sha256'].item()) != native_adapter.CHECKPOINT:
                    raise RuntimeError('frozen detector checkpoint mismatch '+str(path))
                pose = np.asarray(cache['lidar_pose'], float)
                boxes, scores = cache['boxes'], cache['scores']
                if (pose.shape != (6,) or not np.isfinite(pose).all()
                        or boxes.ndim != 2 or boxes.shape[1] != 7
                        or scores.shape != (len(boxes),) or not np.isfinite(boxes).all()
                        or not np.isfinite(scores).all() or (boxes[:, 3:6] <= 0).any()):
                    raise ValueError('invalid frozen pose/detections')
                ref = original.ref_from_pose(pose, t)
                detections = original.make_detections(cache, ref, frame, t, sid)
        except (OSError, ValueError, KeyError, AssertionError) as exc:
            fault = type(exc).__name__+': '+str(exc)
            detections = native.DataContainer(frame, t, [], str(sid))
        tracks = tracker(detections=detections, platform=native.GlobalOrigin3D, check_reference=False)
        fresh, _ = static.fresh_tracks(tracks, counts, t)
        boxes = [dict(original.track_json(tr), timestamp=t, fresh=True, obj_type=tr.obj_type)
                 for tr in fresh if str(tr.obj_type).lower() in VEHICLES]
        yield dict(frame=frame, index=index, timestamp=t,
                   pose=None if pose is None else pose.tolist(), boxes=boxes, fault=fault)


def load_scan(spec, frame, timestamp, pose):
    """Use native LiDAR origin and the same raw-axis flip/extrinsics as run_native."""
    _, original, _, _ = native_adapter.imports()
    pose = np.asarray(pose, float)
    if pose.shape != (6,) or not np.isfinite(pose).all():
        raise ValueError('invalid cached receiver pose')
    path = Path(spec['root'])/str(spec['receiver_id'])/('%06d.pcd' % frame)
    points = load_raw_points(path)
    points = np.asarray(points, float).reshape(-1, 3)
    if not np.isfinite(points).all():
        raise ValueError('nonfinite raw returns')
    ref = original.ref_from_pose(pose, timestamp)
    rotation = original.S @ original.rot(*np.radians(pose[3:])) @ original.S
    origin = np.asarray(ref.x, float)
    return origin, (points @ original.S) @ rotation.T+origin


def load_raw_points(path):
    """run_native.load_points ASCII/xyz semantics, with EOF and 0/1-point handling."""
    with Path(path).open('rb') as stream:
        header = {}
        while True:
            line = stream.readline()
            if not line:
                raise ValueError('truncated PCD header')
            fields = line.decode('ascii').split()
            if not fields or fields[0].startswith('#'):
                continue
            header[fields[0]] = fields[1:]
            if fields[0] == 'DATA':
                break
        if header['DATA'] != ['ascii'] or header.get('FIELDS', [])[:3] != ['x', 'y', 'z']:
            raise ValueError('expected native ASCII xyz PCD')
        counts = header.get('POINTS', [])
        if len(counts) != 1 or not counts[0].isdigit():
            raise ValueError('POINTS must contain exactly one nonnegative integer')
        declared = int(counts[0])
        if declared == 0:
            if stream.read().strip():
                raise ValueError('nonempty zero-return PCD')
            return np.empty((0, 3))
        points = np.loadtxt(stream, dtype=np.float32, usecols=(0, 1, 2), ndmin=2)
        if len(points) != declared or not np.isfinite(points).all():
            raise ValueError('PCD return count mismatch')
        return points


def public_frames(job):
    """Reject label-bearing files; never fall back to rows_path or feature paths."""
    previous = None
    rows = data.read_rows(job['online_path'])
    for frame, grouped in itertools.groupby(rows, key=lambda r: r['frame']):
        if previous is not None and frame <= previous:
            raise ValueError('unordered public frames')
        previous = frame
        public = []
        ids = set()
        for row in grouped:
            if any('truth' in k.lower() or 'label' in k.lower() or 'gt_' in k.lower()
                   or k in ('controlled_sources', 'attack_role', 'query_gt_id', 'Z') for k in row):
                raise ValueError('label/attack data in public online file')
            if row['job_id'] != job['job_id'] or row['key'] != [job['job_id'], frame, row['id']]:
                raise ValueError('public key mismatch')
            if row['id'] in ids:
                raise ValueError('duplicate public key')
            ids.add(row['id'])
            public.append({k: row[k] for k in ('key', 'id', 'frame', 'index', 'timestamp',
                          'source_ids', 'newborn', 'query_geometry')})
        yield frame, public


def _frame_fault(status='input_fault', fault=None):
    return dict(I=None, F=None, I_eligible=False, F_eligible=False, input_fault=True,
                status=status, I_status='unavailable', F_status='unavailable', fault=fault)


def prepare(config, out):
    parents, clean_fit = validate_config(config)
    out = Path(out)
    binding = out/'prepare.config.json'
    if binding.exists():
        if json.loads(binding.read_text()) != config:
            raise ValueError('sidecar configuration changed')
    else:
        data.atomic_json(binding, config)
    complete = out/'prepare.complete.json'
    if complete.exists():
        return json.loads(complete.read_text())
    parent_paths = {}
    # Cache fresh local boxes once, before estimating common shape. Pose is read
    # together with detections, then reused when opening each frame's raw PCD.
    for parent, spec in parents.items():
        path = out/'parents'/parent.replace('/', '__')/'receiver.jsonl.gz'
        parent_paths[parent] = path
        if not path.exists():
            with data.atomic_rows(path) as write:
                for packet in receiver_frames(spec):
                    write(packet)
    shape_path = out/'shape.json'
    if not shape_path.exists():
        samples = (dict(parent=p, **box) for p in sorted(clean_fit)
                   for packet in data.read_rows(parent_paths[p]) if not packet.get('fault')
                   for box in packet['boxes'])
        data.atomic_json(shape_path, fit_shape(samples))
    shape = valid_shape(json.loads(shape_path.read_text())['shape_hwl'])
    summary = {}
    for parent, spec in parents.items():
        jobs = [j for j in config['jobs'] if j['parent'] == parent]
        if spec['split'] == 'fit':
            for job in jobs:
                summary[job['job_id']] = dict(rows=0, status='SHAPE_ONLY')
            continue
        if all((out/'jobs'/j['job_id']/'local.jsonl.gz').exists() for j in jobs):
            for job in jobs:
                summary[job['job_id']] = dict(rows=sum(1 for _ in data.read_rows(
                    out/'jobs'/job['job_id']/'local.jsonl.gz')))
            continue
        with ExitStack() as stack:
            states = []
            for job in jobs:
                destination = out/'jobs'/job['job_id']/'local.jsonl.gz'
                if destination.exists():
                    summary[job['job_id']] = dict(rows=sum(1 for _ in data.read_rows(destination)))
                    continue
                iterator = iter(public_frames(job))
                states.append(dict(job=job, iterator=iterator, current=next(iterator, None),
                    write=stack.enter_context(data.atomic_rows(destination)), counts=Counter()))
            for packet in data.read_rows(parent_paths[parent]):
                frame, t, index = packet['frame'], packet['timestamp'], packet['index']
                active = [s for s in states if s['current'] is not None and s['current'][0] == frame]
                if any(s['current'] is not None and s['current'][0] < frame for s in states):
                    raise ValueError('public frame outside declared receiver sequence')
                if not active:
                    continue
                origin = points = None
                fault = packet.get('fault')
                if fault is None:
                    try:
                        origin, points = load_scan(spec, frame, t, packet.get('pose'))
                    except (OSError, ValueError, AssertionError, KeyError, TypeError) as exc:
                        fault = type(exc).__name__+': '+str(exc)
                free_cache = {}
                for state in active:
                    rows = state['current'][1]
                    queries, row_faults = [], []
                    for row in rows:
                        bad = (row['index'] != index or not np.isfinite(row['timestamp'])
                            or abs(row['timestamp']-t) > 1e-8
                            or spec['receiver_id'] not in row['source_ids'])
                        q = row['query_geometry']
                        if q is not None and not row['newborn'] and not bad:
                            q = dict(xyz=q.get('xyz'), yaw=q.get('yaw'), id=row['id'],
                                     timestamp=row['timestamp'], obj_type='car')
                        else:
                            q = None
                        queries.append(q)
                        row_faults.append(bad)
                    measured = ([_frame_fault(fault=fault) for _ in rows] if fault else
                        measure_frame(queries, packet['boxes'], origin, points, shape, free_cache))
                    for row, m, bad in zip(rows, measured, row_faults):
                        if bad:
                            m = _frame_fault(fault='frame/time/receiver mismatch')
                        record = dict(m, key=row['key'], job_id=state['job']['job_id'],
                            parent=parent, id=row['id'], receiver_id=spec['receiver_id'],
                            frame=frame, index=row['index'], timestamp=row['timestamp'],
                            receiver_timestamp=t, query_present=row['query_geometry'] is not None,
                            newborn=row['newborn'])
                        state['write'](record)
                        state['counts']['rows'] += 1
                        state['counts'][m['status']] += 1
                    state['current'] = next(state['iterator'], None)
            if any(s['current'] is not None for s in states):
                raise ValueError('extra public frames outside receiver sequence')
            for state in states:
                summary[state['job']['job_id']] = dict(state['counts'])
    result = dict(status='COMPLETE', jobs=summary, shape_hwl=shape.tolist(),
                  schema='rq1_trusted_receiver_local_v1')
    data.atomic_json(complete, result)
    return result


# These methods share local thresholds; only the message rejection score differs.
METHODS = ('Local', 'LocalCount', 'LocalCond')
PUBLIC_FIELDS = ('query_present', 'newborn', 'input_fault', 'I', 'F', 'I_eligible',
    'F_eligible', 'output_present', 'identity_ok', 'accept_eligible',
    'reject_eligible', 'C', 'R', 'MissCount')


def _finite(value):
    return isinstance(value, (int, float, np.number)) and np.isfinite(value)


def _public(row):
    return {k: row.get(k) for k in PUBLIC_FIELDS}


def _tau(policy, name):
    value = policy[name]
    if value == 'Infinity':
        return float('inf')
    if value is None:
        raise ValueError('missing frozen threshold '+name)
    return float(value)


def _raw(row, field):
    return (not row.get('input_fault') and row.get('query_present')
        and not row.get('newborn') and row.get(field+'_eligible')
        and _finite(row.get(field)) and (field != 'I' or row[field] > 0))


def _local(row, policy):
    if row.get('input_fault'):
        return 'input_fault', 'unknown', 'input_fault'
    if not row.get('query_present') or row.get('newborn'):
        return 'no_query', 'unknown', 'no_causal_query'
    negative = _raw(row, 'F') and row['F'] > _tau(policy, 'tauF')
    positive = _raw(row, 'I') and row['I'] >= _tau(policy, 'tauP')
    if negative and positive:
        return 'conflict', 'unknown', 'local_conflict'
    if negative:
        return 'refutation', 'reject', 'local_refutation'
    if positive:
        if not row.get('output_present'):
            return 'support_no_output', 'unknown', 'local_support_no_output'
        if not row.get('identity_ok'):
            return 'support_identity_unavailable', 'unknown', 'local_support_identity_unavailable'
        return 'support', 'accept', 'local_support'
    return 'unknown', 'unknown', 'local_unknown'


def decide(public_row, policy, mode):
    """Label-free decision. Only ordinary local unknown may use messages."""
    if mode not in METHODS:
        raise ValueError('unknown method '+str(mode))
    if set(public_row)-set(PUBLIC_FIELDS):
        raise ValueError('non-public decision fields '+str(sorted(set(public_row)-set(PUBLIC_FIELDS))))
    state, decision, reason = _local(public_row, policy)
    if policy.get('status') == 'infeasible_local_risk':
        return dict(decision='unknown', reason='infeasible_local_risk', local_state=state)
    if state != 'unknown' or mode == 'Local':
        return dict(decision=decision, reason=reason, local_state=state)
    score = public_row.get('MissCount' if mode == 'LocalCount' else 'R')
    if public_row.get('reject_eligible') and _finite(score) and score > _tau(policy, 'tauR'):
        return dict(decision='reject', reason='message_refutation', local_state=state)
    if (public_row.get('accept_eligible') and public_row.get('output_present')
            and public_row.get('identity_ok') and _finite(public_row.get('C'))
            and public_row['C'] >= _tau(policy, 'tauC')):
        return dict(decision='accept', reason='message_support', local_state=state)
    return dict(decision='unknown', reason='message_undetermined', local_state=state)


def _support(rows):
    from scripts.rq1_temporal import run as original
    entities = {('injected', r['job_id']) if r['kind'] == 'attack' else
        ('true', r['parent'], r['query_gt_id']) if r.get('query_gt_id') is not None
        else ('query_epoch',)+original.epoch(r) for r in rows}
    return dict(rows=len(rows), parents=len({r['parent'] for r in rows}),
        entities=len(entities), epochs=len({original.epoch(r) for r in rows}),
        entity_unit='injected job; true GT within parent, query epoch if GT unavailable')


def _mass(rows, weights, predicate):
    return float(sum(w for r, w in zip(rows, weights) if predicate(r)))


def _tails(rows, weights, field, eligible):
    """Mass at/above and strictly above finite boundaries, on the full denominator."""
    pairs = sorted((float(r[field]), float(w)) for r, w in zip(rows, weights)
                   if eligible(r) and _finite(r.get(field)))
    if not pairs:
        return lambda tau, strict=False: 0.
    scores = np.asarray([p[0] for p in pairs])
    suffix = np.r_[np.cumsum(np.asarray([p[1] for p in pairs])[::-1])[::-1], 0.]
    return lambda tau, strict=False: float(suffix[np.searchsorted(scores, tau,
                                       side='right' if strict else 'left')])


def calibrate(cal_rows, required_layers, mode):
    """Sequential empirical budgets; unknowns stay in each complete primary class."""
    from scripts.rq1_temporal import run as original
    if mode not in METHODS:
        raise ValueError('unknown method '+str(mode))
    if any(r.get('split') != 'cal' for r in cal_rows):
        raise ValueError('calibration may consume only cal rows')
    required = sorted({(str(f), int(k)) for f, k in required_layers})
    if not required:
        raise ValueError('declared false layers required')
    true = [r for r in cal_rows if original.primary(r, 1)]
    false = [r for r in cal_rows if original.primary(r, 0)]
    if any((r['family'], r['attack_k']) not in required for r in false):
        raise ValueError('undeclared false family/k in calibration')
    selected = true+false
    tw = original.weights(true, 1)
    groups = {'overall': (false, original.weights(false, 0))}
    for family, k in required:
        group = [r for r in false if (r['family'], r['attack_k']) == (family, k)]
        groups[family+'/'+str(k)] = (group, original.weights(group, 0))
    missing = [key for key, (group, _) in groups.items() if not group]
    policy = dict(status='active', mode=mode, tauF=float('inf'), tauP=float('inf'),
        tauR=float('inf'), tauC=float('inf'), required_layers=[list(x) for x in required],
        missing_layers=missing, coverage=dict(true=_support(true),
            false={key: _support(group) for key, (group, _) in groups.items()}),
        branches={}, budget=dict(local_limit=.02, total_limit=.05))
    branches, budget = policy['branches'], policy['budget']
    ftail = _tails(true, tw, 'F', lambda r: _raw(r, 'F'))
    fvalues = sorted({float(r['F']) for r in true if _raw(r, 'F')})+[float('inf')]
    if true:
        policy['tauF'] = next(t for t in fvalues if ftail(t, True) <= .02+1e-12)
    budget['raw_F_true_reject'] = ftail(policy['tauF'], True)
    branches['local_reject'] = dict(status='active' if _finite(policy['tauF']) else 'disabled',
        reason=None if true else 'no_normal_primary')
    ivalues = sorted({float(r['I']) for r in selected if _raw(r, 'I')})
    itail = _tails(true, tw, 'I', lambda r: _raw(r, 'I'))
    false_itails = {key: _tails(group, w, 'I', lambda r: _raw(r, 'I'))
                    for key, (group, w) in groups.items()}
    if true and not missing:
        feasible = [t for t in ivalues if all(tail(t) <= .02+1e-12 for tail in false_itails.values())]
        if feasible:
            best = max(itail(t) for t in feasible)
            if best > 0:
                policy['tauP'] = max(t for t in feasible if itail(t) >= best-1e-12)
    branches['local_accept'] = dict(status='active' if _finite(policy['tauP']) else 'disabled',
        reason=None if _finite(policy['tauP']) else 'missing_false_layers' if missing else 'no_positive_quality_region')
    budget['raw_I_false_accept'] = {key: tail(policy['tauP']) if groups[key][0] else None
        for key, tail in false_itails.items()}
    local = {id(r): _local(r, policy) for r in selected}
    budget['local_true_reject'] = _mass(true, tw, lambda r: local[id(r)][1] == 'reject')
    budget['local_false_accept'] = {key: _mass(group, w, lambda r: local[id(r)][1] == 'accept') if group else None
        for key, (group, w) in groups.items()}
    budget['remaining_true_reject'] = .05-budget['local_true_reject']
    budget['remaining_false_accept'] = {key: None if value is None else .05-value
        for key, value in budget['local_false_accept'].items()}
    if budget['remaining_true_reject'] < -1e-12 or any(
            x is not None and x < -1e-12 for x in budget['remaining_false_accept'].values()):
        policy['status'] = 'infeasible_local_risk'
        branches['remote_reject'] = branches['remote_accept'] = dict(status='disabled', reason='local_risk_exceeds_total')
        return policy
    field = 'MissCount' if mode == 'LocalCount' else 'R'
    reject = lambda r: local[id(r)][0] == 'unknown' and bool(r.get('reject_eligible'))
    rtail = _tails(true, tw, field, reject)
    if mode != 'Local' and true:
        values = sorted({float(r[field]) for r in true if reject(r) and _finite(r.get(field))})+[float('inf')]
        policy['tauR'] = next(t for t in values if rtail(t, True) <= budget['remaining_true_reject']+1e-12)
    branches['remote_reject'] = dict(status='active' if _finite(policy['tauR']) else 'disabled',
        reason=None if _finite(policy['tauR']) else 'local_only' if mode == 'Local' else 'no_normal_score_region')
    def accept(r):
        rejected = reject(r) and _finite(r.get(field)) and r[field] > policy['tauR']
        return (local[id(r)][0] == 'unknown' and not rejected and r.get('accept_eligible')
                and r.get('output_present') and r.get('identity_ok'))
    ctail = _tails(true, tw, 'C', accept)
    false_ctails = {key: _tails(group, w, 'C', accept) for key, (group, w) in groups.items()}
    if mode != 'Local' and true and not missing:
        values = sorted({float(r['C']) for r in selected if accept(r) and _finite(r.get('C'))})
        feasible = [t for t in values if all(budget['local_false_accept'][key]+tail(t) <= .05+1e-12
                                           for key, tail in false_ctails.items())]
        if feasible:
            best = max(ctail(t) for t in feasible)
            if best > 0:
                policy['tauC'] = max(t for t in feasible if ctail(t) >= best-1e-12)
    branches['remote_accept'] = dict(status='active' if _finite(policy['tauC']) else 'disabled',
        reason=None if _finite(policy['tauC']) else 'local_only' if mode == 'Local'
            else 'missing_false_layers' if missing else 'no_positive_quality_region')
    budget['final_true_reject'] = budget['local_true_reject']+rtail(policy['tauR'], True)
    budget['final_false_accept'] = {key: None if not group else budget['local_false_accept'][key]+false_ctails[key](policy['tauC'])
        for key, (group, _) in groups.items()}
    if missing:
        policy['status'] = 'not_estimable_false_coverage'
    elif not true:
        policy['status'] = 'not_estimable_normal_coverage'
    return policy


# Explicit online projection before calling the existing window extractor.
WINDOW_FIELDS = ('key', 'job_id', 'id', 'epoch', 'frame', 'index', 'timestamp',
    'source_ids', 'U', 'X', 'C', 'C_missing', 'groups', 'query_present',
    'newborn', 'output_present', 'identity_ok')


def _encode_thresholds(value):
    if isinstance(value, dict):
        return {k: _encode_thresholds(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_thresholds(v) for v in value]
    return 'Infinity' if isinstance(value, float) and value == float('inf') else value


def _event_counts(window):
    """Same valid U/X events and causal W10 as legacy, independent of D prediction."""
    current = window[-1]
    if not current.get('query_present') or current.get('newborn'):
        return dict(Count_inputs=[0.]*5, context=[0, 0, 0], n_minus=[], n_frames=0,
                    accept_eligible=False, reject_eligible=False, finite=True, error=None)
    try:
        effective = []
        n = len(current['source_ids'])
        for row in window:
            u = np.asarray(row['U'])
            if u.shape != (n,) or not np.isin(u, [-1, 0, 1]).all() or len(row['X']) != n:
                raise ValueError('invalid source events')
            valid = []
            for x in row['X']:
                array = None if x is None else np.asarray(x, float)
                valid.append(array is not None and array.shape == (5,) and np.isfinite(array).all())
            effective.append(np.where(valid, u, -1))
        events = np.asarray(effective)
        opportunity, support = np.any(events >= 0, axis=0), np.any(events == 1, axis=0)
        context = [len(window), int(opportunity.sum()), int(support.sum())]
        minus = (events == 0).sum(0).tolist()
        return dict(Count_inputs=[float((events == 1).sum()), float(sum(minus)), *map(float, context)],
            context=context, n_minus=minus, n_frames=len(window), finite=True, error=None,
            accept_eligible=bool(opportunity.sum() >= 2 and support.sum() >= 2
                and current.get('output_present') and current.get('identity_ok')),
            reject_eligible=bool(opportunity.sum() >= 2 and np.any(events == 0)))
    except (TypeError, ValueError, KeyError) as exc:
        return dict(Count_inputs=None, context=[0, 0, 0], n_minus=None, n_frames=0,
            accept_eligible=False, reject_eligible=False, finite=False, error=str(exc))


def _d_only(normal_models):
    model = normal_models.get('D')
    try:
        valid = (isinstance(model, dict) and _finite(model.get('intercept'))
            and all(np.asarray(model.get(k), float).shape == (7,)
                and np.isfinite(np.asarray(model[k], float)).all() for k in ('mean', 'scale', 'coef'))
            and np.all(np.asarray(model['scale'], float) > 0)
            and normal_models.get('component_status', {}).get('D', {}).get('status', 'ok') == 'ok')
    except (TypeError, ValueError, KeyError):
        valid = False
    return {'D': model} if valid else {}


def evaluation_rows(job, out, normal_models, receiver_id):
    """One keyed candidate join; offline metadata is attached after feature extraction."""
    from scripts.rq1_score_revision import heads, run as legacy
    from scripts.rq1_temporal import kernel
    from scripts.rq1_report_freeze import run as freeze
    rows = list(data.read_rows(job['rows_path']))
    expected_local = Path(out)/'jobs'/job['job_id']/'local.jsonl.gz'
    local_path = Path(job.get('local_path') or expected_local)
    if local_path.resolve() != expected_local.resolve():
        raise ValueError('local_path is not the bound prepare product')
    local = list(data.read_rows(local_path))
    public = [{k: r[k] for k in WINDOW_FIELDS if k in r} for r in rows]
    windows = list(kernel.windows(public, 10))
    counts = {tuple(w[-1]['key']): _event_counts(w) for w in windows}
    if job.get('features_path'):
        features = list(data.read_rows(job['features_path']))
    else:
        models = _d_only(normal_models)
        features = [dict({k: w[-1].get(k) for k in WINDOW_FIELDS},
                    **heads.window_features(w, models, 0., W=10)) for w in windows]
    def keyed(records):
        result = {tuple(r['key']): r for r in records}
        if len(result) != len(records):
            raise ValueError('duplicate candidate key '+job['job_id'])
        return result
    by_row, by_local, by_feature = keyed(rows), keyed(local), keyed(features)
    if set(by_row) != set(by_local) or set(by_row) != set(by_feature):
        raise ValueError('candidate key coverage mismatch '+job['job_id'])
    result = []
    for key, row in by_row.items():
        if key != (job['job_id'], row['frame'], row['id']):
            raise ValueError('malformed candidate key')
        for field in ('parent', 'split', 'kind', 'family', 'attack_k'):
            if row[field] != job[field]:
                raise ValueError('frozen role mismatch '+field)
        feature, sidecar = by_feature[key], by_local[key]
        if sidecar.get('receiver_id') != receiver_id or receiver_id not in row['source_ids']:
            raise ValueError('sidecar receiver identity mismatch '+str(key))
        if not sidecar.get('input_fault') and (not _finite(sidecar.get('receiver_timestamp'))
                or not _finite(row['timestamp']) or abs(sidecar['receiver_timestamp']-row['timestamp']) > 1e-8):
            raise ValueError('sidecar receiver timestamp mismatch '+str(key))
        if job.get('features_path') and any(feature.get(k) != row.get(k) for k in
                ('parent', 'split', 'kind', 'family', 'attack_k', 'query_truth', 'attack_role')):
            raise ValueError('feature offline identity mismatch '+str(key))
        for other, fields in ((sidecar, ('job_id', 'id', 'frame', 'index', 'timestamp',
                'parent', 'query_present', 'newborn')),
                (feature, ('job_id', 'id', 'frame', 'index', 'timestamp', 'epoch',
                 'source_ids', 'query_present', 'newborn', 'output_present', 'identity_ok'))):
            if any(other.get(k) != row.get(k) for k in fields):
                raise ValueError('sidecar/feature metadata mismatch '+str(key))
        # The output row keeps only evaluation metadata, local evidence and score inputs.
        merged = {k: row.get(k) for k in legacy.METADATA}
        merged['features'] = feature.get('features', {})
        merged.update(counts[key])
        merged.update({k: sidecar.get(k) for k in ('I', 'F', 'I_eligible', 'F_eligible', 'input_fault')})
        context = merged['context']
        merged.update(w=context[0], d=context[1], m=context[2])
        x = feature.get('features', {}).get('D_head')
        readable = (feature.get('finite', False) and feature.get('method_status', {}).get(
            'D_head', {}).get('status', 'ok') == 'ok')
        merged['R'] = -float(x[1]) if readable and x is not None and len(x) == 6 and _finite(x[1]) and x[1] <= 0 else None
        merged['R_error'] = feature.get('error') if merged['R'] is None else None
        if readable and x is not None and merged['finite']:
            if freeze.count_inputs(feature) != merged['Count_inputs']:
                raise ValueError('public event counts differ from legacy Count inputs '+str(key))
        minus = merged['n_minus']
        merged['MissCount'] = float(sum(minus)) if minus is not None else None
        result.append(merged)
    return result


def _apply_evaluation(rows, policies):
    for row in rows:
        row['scores'] = {m: row['C'] for m in METHODS}
        row['decisions'], row['decision_reasons'] = {}, {}
        for mode in METHODS:
            result = decide(_public(row), policies[mode], mode)
            row['decisions'][mode] = result['decision']
            row['decision_reasons'][mode] = result['reason']
            row['local_state'] = result['local_state']
    return rows


def measurements(rows, layers, domains=None):
    from scripts.rq1_temporal import run as original
    from scripts.rq1_report_freeze import run as freeze
    from scripts.rq1_score_revision import no_miss_constant as zero, run as legacy
    tables = {m: freeze.table(rows, m) for m in METHODS}
    def cells(mask=None):
        return {m: original.six_cells(t if mask is None else t.subset(mask), 'D')
                for m, t in tables.items()}
    def masks(field):
        return {value: np.asarray([r[field] == value for r in rows])
                for value in sorted({r[field] for r in rows})}
    windows = np.asarray([r['w'] for r in rows])
    result = dict(system_query=cells(), coverage=legacy._coverage(rows),
        by_parent={p: cells(mask) for p, mask in masks('parent').items()},
        by_local_state={s: cells(mask) for s, mask in masks('local_state').items()},
        local_unknown=cells(np.asarray([r['local_state'] == 'unknown' for r in rows], dtype=bool)),
        first_windows={name: cells(mask) for name, mask in (
            ('length_1', windows == 1), ('length_2_to_9', (windows >= 2)&(windows < 10)),
            ('length_10', windows == 10))},
        family_k={}, by_domain={},
        paired_timeliness={m: zero._paired(rows, m, 'LocalCount') for m in METHODS if m != 'LocalCount'},
        transitions={m: zero._transitions(rows, m, 'LocalCount') for m in METHODS if m != 'LocalCount'},
        trajectories={m: {str(truth): original.trajectories(t, 'D', truth)
                         for truth in (0, 1)} for m, t in tables.items()},
        decision_reasons={m: dict(Counter(r['decision_reasons'][m] for r in rows)) for m in METHODS},
        score_coverage={field: dict(total=len(rows), available=sum(_finite(r.get(field)) for r in rows))
                        for field in ('I', 'F', 'R', 'MissCount', 'C')})
    for family, k in sorted(set(layers)):
        mask = np.asarray([(r['family'], r['attack_k']) == (family, k) for r in rows], dtype=bool)
        false = [r for r, keep in zip(rows, mask) if keep and original.primary(r, 0)]
        result['family_k'][family+'/'+str(k)] = dict(status='observed' if false else 'not_tested',
            support=_support(false), metrics=cells(mask))
    for name, parents in (domains or {}).items():
        result['by_domain'][name] = cells(np.asarray([r['parent'] in parents for r in rows], dtype=bool))
    return result


def _judge(measured, policies, criteria):
    from scripts.rq1_score_revision import run as legacy
    baseline = measured['system_query']['LocalCount']
    result = {}
    for mode in ('Local', 'LocalCond'):
        current = measured['system_query'][mode]
        paired = measured['paired_timeliness'][mode]
        checks = dict(true_reject=legacy._check(current['true']['weighted']['reject'], criteria.get('max_TR_global', .05)),
            false_accept=legacy._check(current['false']['weighted']['accept'], criteria.get('max_FA_global_and_layer', .05)),
            true_accept_loss=legacy._check(legacy._difference(baseline['true']['weighted']['accept'], current['true']['weighted']['accept']), criteria.get('max_TA_loss_vs_LocalCount', .02)),
            CD_gain=legacy._check(legacy._difference(current['correct_definite'], baseline['correct_definite']), criteria.get('min_CD_gain_vs_LocalCount', .01), 'min'),
            never_adopt_increase=legacy._check(paired['never_difference'], criteria.get('max_never_adopt_increase', .02)),
            paired_median_delay=legacy._check(paired['weighted_median_delay_difference_seconds'], criteria.get('max_paired_median_delay_seconds', .5)),
            calibration=legacy._check(int(policies[mode]['status'] == 'active'), 1, 'min'))
        for layer, group in measured['family_k'].items():
            support = group['support']
            checks['false_accept_'+layer] = legacy._check(group['metrics'][mode]['false']['weighted']['accept'], criteria.get('max_FA_global_and_layer', .05))
            checks['parents_'+layer] = legacy._check(support['parents'], criteria.get('min_eval_parents_per_layer', 3), 'min')
            checks['entities_'+layer] = legacy._check(support['entities'], criteria.get('min_eval_entities_per_layer', 3), 'min')
        result[mode] = dict(status=legacy._verdict(checks), checks=checks)
    return result


def evaluate(config, out):
    """Use a completed shared local sidecar batch; never consume fit features/labels."""
    import time
    from scripts.rq1_score_revision import heads
    from scripts.rq1_report_freeze import run as freeze
    out = Path(out)
    if not (out/'prepare.complete.json').is_file():
        raise RuntimeError('prepare sidecars incomplete')
    complete = freeze.read(out/'prepare.complete.json')
    if complete['status'] != 'COMPLETE':
        raise RuntimeError('prepare sidecars incomplete')
    prepared = freeze.read(out/'prepare.config.json')
    if prepared['parents'] != config['parents']:
        raise ValueError('prepared parent/receiver inputs changed')
    public_jobs = lambda c: {j['job_id']: tuple(j.get(k) for k in
        ('parent', 'kind', 'online_path')) for j in c['jobs']}
    if public_jobs(prepared) != public_jobs(config):
        raise ValueError('prepared public jobs changed')
    parents = {p['parent']: p for p in config['parents']}
    if len(parents) != len(config['parents']) or any(p['split'] not in ('fit', 'cal', 'eval') for p in parents.values()):
        raise ValueError('duplicate or invalid parent roles')
    jobs = []
    if len({j['job_id'] for j in config['jobs']}) != len(config['jobs']):
        raise ValueError('duplicate job IDs')
    for original_job in config['jobs']:
        job = dict(original_job)
        split = parents[job['parent']]['split']
        if job.get('split', split) != split:
            raise ValueError('job/parent split mismatch')
        job['split'] = split
        if split == 'fit':
            continue
        if complete['jobs'].get(job['job_id'], {}).get('status') == 'SHAPE_ONLY':
            raise ValueError('cal/eval cannot consume SHAPE_ONLY')
        jobs.append(job)
    sources = config['model_sources']
    paths = [out/'prepare.config.json', out/'prepare.complete.json', Path(sources['p_D'])]+[Path(p) for p in sources['Count_models'].values()]
    if config.get('batch_path'):
        paths.append(Path(config['batch_path']))
    for job in jobs:
        paths.extend([Path(job['rows_path']), Path(job['online_path']), Path(job.get('local_path') or out/'jobs'/job['job_id']/'local.jsonl.gz')])
        if job.get('features_path'):
            paths.append(Path(job['features_path']))
    binding = dict(config=config, sources=[data.source_record(p) for p in sorted(set(paths))],
        code=[data.source_record(p) for p in (Path(__file__), Path(heads.__file__), Path(freeze.__file__),
            Path(heads.__file__).parent/'run.py', Path(data.__file__),
            Path(data.__file__).with_name('run.py'), Path(data.__file__).with_name('fit.py'),
            Path(data.__file__).with_name('kernel.py'))])
    freeze.save(out/'evaluate.binding.json', binding)
    if (out/'evaluate.complete.json').exists():
        return freeze.read(out/'evaluate.report.json')
    started = time.monotonic()
    normal = freeze.read(sources['p_D'])['models']
    # Omit every other model so the existing extractor executes only D.
    normal = _d_only(normal)
    shared = {job['job_id']: evaluation_rows(job, out, normal,
        receiver_id=parents[job['parent']]['receiver_id']) for job in jobs}
    feature_seconds = time.monotonic()-started
    reports = dict(schema='rq1_trusted_receiver_evaluation_v1', regimes={},
        scope='fixed development comparison; empirical budgets are not population guarantees',
        task_inventory=freeze.read(config['batch_path']) if config.get('batch_path') else dict(jobs=config['jobs']),
        cost=dict(feature_join_seconds=feature_seconds))
    for regime, spec in config['regimes'].items():
        begin = time.monotonic()
        rows = {}
        for split, key in (('cal', 'cal_families'), ('eval', 'eval_families')):
            rows[split] = [dict(row) for job in jobs if job['split'] == split
                and (job['kind'] == 'clean' or job['family'] in spec[key])
                for row in shared[job['job_id']]]
        model = freeze.read(sources['Count_models'][regime])['models']['Count']
        # Recompute only the frozen continuous score; old decisions are not inherited.
        for group in rows.values():
            for row in group:
                row['C'] = None
                try:
                    row['C'] = heads.base_score(model, row['Count_inputs']) if model is not None and row['Count_inputs'] is not None else None
                except (ValueError, FloatingPointError, OverflowError):
                    pass
        required = [(f, k) for f in spec['cal_families'] for k in config['required_k']]
        policies = {mode: calibrate(rows['cal'], required, mode) for mode in METHODS}
        if len({(p['tauF'], p['tauP']) for p in policies.values()}) != 1:
            raise AssertionError('methods must share frozen local thresholds')
        freeze.save(out/'calibration'/(regime+'.json'), _encode_thresholds(policies))
        measured = {}
        for split, group in rows.items():
            _apply_evaluation(group, policies)
            # Keep compact predictions; heavy per-source features remain in their source.
            predictions = [{k: v for k, v in row.items() if k != 'features'} for row in group]
            freeze.rows_once(out/'predictions'/regime/(split+'.jsonl.gz'), predictions)
            layers = [(f, k) for f in spec['cal_families' if split == 'cal' else 'eval_families'] for k in config['required_k']]
            measured[split] = measurements(group, layers, config.get('domains'))
            freeze.save(out/'report'/regime/(split+'.json'), measured[split])
        reports['regimes'][regime] = dict(measured,
            verdict=_judge(measured['eval'], policies, config.get('criteria', {})),
            seconds=time.monotonic()-begin)
        print('evaluated', regime, 'cal', len(rows['cal']), 'eval', len(rows['eval']), flush=True)
    reports['cost']['total_evaluate_seconds'] = time.monotonic()-started
    freeze.save(out/'evaluate.report.json', reports)
    freeze.save(out/'evaluate.complete.json', dict(status='COMPLETE', regimes=list(reports['regimes']),
        report='evaluate.report.json'))
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['prepare', 'evaluate'], default='prepare')
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    stage = prepare if args.stage == 'prepare' else evaluate
    stage(json.loads(Path(args.config).read_text()), args.out)


if __name__ == '__main__':
    main()
