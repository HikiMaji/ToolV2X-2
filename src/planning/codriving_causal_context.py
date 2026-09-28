"""Causal, complete CoDriving peer context; no tracking or model execution.

Tracker rows are world-frame FixedRateTracker outputs with source self already
removed. All history is expressed in the source actor frame at decision time.
Receiver and out-of-ROI tracks remain predictor context; purchases are separate.
"""
from dataclasses import asdict
import hashlib
import json

import numpy as np

from planning.codriving_native_inputs import world_boxes_to_actor, source_to_receiver_transform
from tools.native_time import motion

VERSION = 'codriving_causal_context_v1'
PRODUCER = 'fixed_rate_ab3dmot_causal_world_v1'


def _identifiers(ids):
    if any(type(i) is not int or i < 0 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique nonnegative integer track IDs required')


def _measurement(value):
    # Only observed pose fields belong in this context; never copy a whole log.
    return {k: float(value[k]) for k in ('x', 'y', 'theta', 'lidar_pose_x', 'lidar_pose_y')}


def _context_version(context):
    payload = {k: v for k, v in context.items() if k != 'context_version'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                      allow_nan=False).encode('utf-8')).hexdigest()[:16]
    return '%s:%s:%s:%s:g%d:%s' % (VERSION, context['scene'], context['source'],
                                  context['receiver'], context['g'], digest)


def build_context(frames, *, scene, source, receiver, decision_frame, spec):
    """Build JSON native history of every track active at the decision frame.

    A maintained tracker state is valid even on a detector miss. A missing track
    in a frame is invalid, never padded using a past/future box. The caller owns
    FixedRateTracker and must pass its contiguous same-recording causal output.
    """
    spec_record = asdict(spec)
    dt = spec_record['dt_seconds']; steps = spec_record['history_steps']
    radius = spec_record['receiver_self_radius_m']
    if (not np.isfinite(dt) or dt <= 0 or type(steps) is not int or steps < 2
            or not np.isfinite(radius) or radius <= 0):
        raise ValueError('valid native history and self-exclusion specification required')
    if (any(not isinstance(s, str) or not s.strip() or s.startswith('/') for s in (scene, source, receiver))
            or source == receiver or type(decision_frame) is not int or decision_frame < 0):
        raise ValueError('explicit scene/source/receiver/decision binding required')
    frames = list(frames)
    if not frames or frames[-1]['frame'] != decision_frame:
        raise ValueError('decision frame must be present and last')
    previous = None
    indexed = []
    for frame in frames:
        g = frame['frame']
        if (type(g) is not int or g < 0 or g > decision_frame
                or (previous is not None and g != previous + 1)):
            raise ValueError('contiguous ordered causal frames required')
        previous = g
        if (frame['scene'], frame['source'], frame['receiver']) != (scene, source, receiver):
            raise ValueError('mixed scene/source/receiver context')
        # Validate both same-frame poses even when a frame has no emitted tracks.
        source_to_receiver_transform(frame['source_measurement'], frame['receiver_measurement'])
        rows = frame['tracks']; ids = [row['id'] for row in rows]; _identifiers(ids)
        for row in rows:
            box = np.asarray(row['box'], dtype=float)
            if (box.shape != (7,) or not np.isfinite(box).all() or (box[3:6] <= 0).any()
                    or type(row['detector_hit']) is not bool or not np.isfinite(row['score'])
                    or not 0 <= row['score'] <= 1):
                raise ValueError('finite tracker geometry, score and detector-hit mask required')
            refs = row['parent_refs']
            if (not isinstance(refs, list) or any(not isinstance(r, str) or not r.strip()
                                                or r.startswith('/') for r in refs)):
                raise ValueError('stable relative tracker parent references required')
        indexed.append({row['id']: row for row in rows})
    current = frames[-1]
    ids = sorted(indexed[-1]); n = len(ids)
    states = np.zeros((n, steps, 7), dtype=float)
    valid = np.zeros((n, steps), dtype=bool)
    hits = np.zeros_like(valid); scores = np.zeros((n, steps), dtype=float)
    refs = [[[] for _ in range(steps)] for _ in ids]
    first = decision_frame - steps + 1
    source_pose = current['source_measurement']
    for frame, rows in zip(frames, indexed):
        slot = frame['frame'] - first
        if slot < 0:
            continue
        for i, ident in enumerate(ids):
            if ident not in rows:
                continue
            row = rows[ident]
            states[i, slot] = world_boxes_to_actor(np.asarray([row['box']], dtype=float), source_pose)[0]
            valid[i, slot] = True; hits[i, slot] = row['detector_hit']; scores[i, slot] = row['score']
            refs[i][slot] = list(row['parent_refs'])
    receiver_xy = np.array([current['receiver_measurement'][k] for k in ('x', 'y')])
    receiver_ids = [ident for ident in ids
                    if np.linalg.norm(np.asarray(indexed[-1][ident]['box'])[:2] - receiver_xy) <= radius]
    context = dict(version=VERSION, scene=scene, source=source, receiver=receiver, g=decision_frame,
        decision_time=float(decision_frame * dt), coordinate_frame='source_actor_at_t',
        axes='x_forward_y_left', execution_spec=spec_record, source_measurement=_measurement(source_pose),
        receiver_measurement=_measurement(current['receiver_measurement']),
        time_seconds=(np.arange(1-steps, 1) * dt).tolist(), track_ids=ids,
        states=states.tolist(), valid=valid.tolist(), detector_hit=hits.tolist(), scores=scores.tolist(),
        receiver_track_ids=receiver_ids, parent_refs=refs, producer_version=PRODUCER,
        model_history_binding=dict(version='cmp_causal_resampling_v1', dt_seconds=.1, history_steps=11,
            semantics='adjacent valid maintained states in fixed source actor frame at decision',
            detector_hit='native observation mask only; interpolated slots are not detector hits',
            missing='invalid zero; no extrapolation or gap bridging'))
    context['context_version'] = _context_version(context)
    return context


def _arrays(context):
    """Validate the exported JSON boundary before deriving a window or purchase."""
    if context['context_version'] != _context_version(context):
        raise ValueError('context contents differ from bound provenance')
    if context['decision_time'] != context['g'] * context['execution_spec']['dt_seconds']:
        raise ValueError('context decision time differs from native capture binding')
    ids = context['track_ids']; _identifiers(ids)
    times = np.asarray(context['time_seconds'], dtype=float)
    n = len(ids); steps = context['execution_spec']['history_steps']
    states = np.asarray(context['states'], dtype=float)
    valid = np.asarray(context['valid'])
    scores = np.asarray(context['scores'], dtype=float)
    if not n:
        states = states.reshape(0, steps, 7); valid = valid.astype(bool).reshape(0, steps)
        scores = scores.reshape(0, steps)
    if (context['version'] != VERSION or context['coordinate_frame'] != 'source_actor_at_t'
            or context['axes'] != 'x_forward_y_left' or times.shape != (steps,)
            or not np.allclose(times, np.arange(1-steps, 1) * context['execution_spec']['dt_seconds'])
            or states.shape != (n, steps, 7) or valid.shape != (n, steps)
            or valid.dtype != np.dtype(bool) or scores.shape != (n, steps)
            or not valid[:, -1].all() or not np.isfinite(states).all() or not np.isfinite(scores).all()
            or (states[valid, 3:6] <= 0).any() or (scores < 0).any() or (scores > 1).any()
            or not np.all(states[~valid] == 0) or not np.all(scores[~valid] == 0)):
        raise ValueError('invalid native causal context')
    return states, valid, scores, times


def to_mtr_window(context):
    """Full context at -1..0 s / .1 s, interpolating adjacent valid slots only.

    This prepares the existing CMP interface. It does not execute MTR. No ROI,
    purchase cap, receiver-self filter, extrapolation, or missing-slot bridging
    is allowed here. Heading follows the shortest wrapped angular difference.
    """
    native, valid, scores, times = _arrays(context)
    n = len(context['track_ids']); target_times = np.arange(-10, 1) * .1
    states = np.zeros((n, 11, 7)); mask = np.zeros((n, 11), dtype=bool)
    confidence = np.zeros((n, 11))
    for j, stamp in enumerate(target_times):
        exact = np.flatnonzero(np.isclose(times, stamp, rtol=0., atol=1e-9))
        if len(exact):
            k = int(exact[0]); good = valid[:, k]
            states[good, j] = native[good, k]; confidence[good, j] = scores[good, k]; mask[good, j] = True
            continue
        b = int(np.searchsorted(times, stamp)); a = b - 1
        if a < 0 or b >= len(times):
            continue
        good = valid[:, a] & valid[:, b]
        weight = (stamp - times[a]) / (times[b] - times[a])
        states[good, j] = native[good, a] + weight * (native[good, b] - native[good, a])
        delta = np.arctan2(np.sin(native[good, b, 6] - native[good, a, 6]),
                           np.cos(native[good, b, 6] - native[good, a, 6]))
        angle = native[good, a, 6] + weight * delta
        states[good, j, 6] = np.arctan2(np.sin(angle), np.cos(angle))
        confidence[good, j] = scores[good, a] + weight * (scores[good, b] - scores[good, a])
        mask[good, j] = True
    return dict(source=context['source'], scene=context['scene'], g=context['g'],
        track_ids=np.asarray(context['track_ids'], dtype=np.int64), states=states, valid=mask,
        scores=confidence, time_seconds=target_times, eligible=mask.sum(axis=1) >= 2)


def records_for_targets(context, target_ids):
    """Normalize selected native P histories, excluding the receiver as a target.

    These records carry input provenance, not a paid receipt or claim that an F
    prediction was executed. The service/orchestrator owns billing and F order.
    """
    states, valid, _, times = _arrays(context)
    target_ids = list(target_ids); _identifiers(target_ids)
    index = {ident: i for i, ident in enumerate(context['track_ids'])}
    if any(ident not in index or ident in context['receiver_track_ids'] for ident in target_ids):
        raise ValueError('unknown or receiver-self purchased target')
    result = []
    for ident in target_ids:
        i = index[ident]; anchor = motion(states[i], valid[i], times)
        refs = [dict(provider=context['source'], scene=context['scene'], g=context['g'], track_handle=ident,
                     field_kind=kind, producer_version=context['producer_version'],
                     context_version=context['context_version']) for kind in ('anchor', 'history')]
        result.append(dict(source=context['source'], track=str(ident),
            box=states[i, -1, [0, 1, 3, 4, 6]].tolist(), velocity=anchor['velocity'],
            velocity_valid=anchor['valid'], refs=refs,
            history=[dict(time=float(t), box=b[[0, 1, 3, 4, 6]].tolist(), valid=bool(v))
                     for t, b, v in zip(times, states[i], valid[i])]))
    return result
