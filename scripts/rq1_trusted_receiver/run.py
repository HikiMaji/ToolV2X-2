"""Extract label-free receiver sidecars without replaying other cars or fusion."""
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
        declared = int(header['POINTS'][0])
        if declared < 0:
            raise ValueError('negative PCD count')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['prepare'], default='prepare')
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    prepare(json.loads(Path(args.config).read_text()), args.out)


if __name__ == '__main__':
    main()
