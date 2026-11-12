"""Public pre-query geometry only. C is a known-blocker proxy, not visibility truth."""
from collections import Counter
import itertools
import numpy as np

TOL = 1e-8
PROBE_OFFSETS = np.vstack([np.zeros(3), np.array(list(itertools.product([-.5, .5], repeat=3)))])


def obb_from_corners(corners):
    c = np.asarray(corners, dtype=float)
    if c.shape != (8, 3) or not np.isfinite(c).all():
        raise ValueError('invalid corners')
    center = c.mean(axis=0)
    edges = c[[1, 3, 4]] - c[0]
    lengths = np.linalg.norm(edges, axis=1)
    if (lengths <= 1e-6).any():
        raise ValueError('degenerate OBB')
    axes = edges / lengths[:, None]
    if np.max(np.abs(axes @ axes.T - np.eye(3))) > 1e-5:
        raise ValueError('nonorthogonal OBB')
    half = lengths / 2
    local = (c - center) @ axes.T
    if np.max(np.abs(np.abs(local) - half)) > 1e-4:
        raise ValueError('inconsistent OBB corners')
    # Boundary checks alone would accept duplicated corners.
    signs = np.sign(local)
    if len({tuple(s) for s in signs}) != 8:
        raise ValueError('duplicate OBB corners')
    return center, axes, half


def segment_box_interval(origin, directions, centers, axes, half):
    """R directions x B boxes; t parameterizes origin+t*direction on [0,1]."""
    origin = np.asarray(origin, float)
    directions = np.asarray(directions, float).reshape(-1, 3)
    centers = np.asarray(centers, float).reshape(-1, 3)
    axes = np.asarray(axes, float).reshape(-1, 3, 3)
    half = np.asarray(half, float).reshape(-1, 3)
    o = np.einsum('bj,baj->ba', origin - centers, axes)
    d = np.einsum('rj,baj->rba', directions, axes)
    parallel = np.abs(d) <= 1e-12
    lo = np.full_like(d, -np.inf)
    hi = np.full_like(d, np.inf)
    a = np.zeros_like(d)
    b = np.zeros_like(d)
    np.divide(-half[None] - o[None], d, out=a, where=~parallel)
    np.divide(half[None] - o[None], d, out=b, where=~parallel)
    np.minimum(a, b, out=lo, where=~parallel)
    np.maximum(a, b, out=hi, where=~parallel)
    outside = (parallel & (np.abs(o)[None] > half[None] + TOL)).any(axis=-1)
    enter = np.maximum(0., lo.max(axis=-1))
    leave = np.minimum(1., hi.min(axis=-1))
    hit = (~outside) & (enter <= leave + TOL)
    return np.where(hit, enter, np.inf), hit


def frame_cues(query_geometries, source_poses, chunk_size=64):
    """Return {query ID: {source ID: cue}}, diagnostics; no event/label inputs."""
    queries = sorted(query_geometries, key=lambda g: g['id'])
    ids = [g['id'] for g in queries]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate query ID')
    stats = Counter(queries=len(queries))
    result = {i: {} for i in ids}
    valid = []
    for g in queries:
        try:
            c, a, h = obb_from_corners(g['corners'])
            xy = np.asarray(g['xyz'], float)
            if xy.shape != (3,) or not np.isfinite(xy).all():
                raise ValueError('invalid bottom')
            valid.append((g['id'], xy, c, a, h))
        except (ValueError, KeyError, TypeError):
            stats['invalid_obb'] += 1
    bid = [b[0] for b in valid]
    bottoms = np.array([b[1] for b in valid]).reshape(-1, 3)
    centers = np.array([b[2] for b in valid]).reshape(-1, 3)
    axes = np.array([b[3] for b in valid]).reshape(-1, 3, 3)
    half = np.array([b[4] for b in valid]).reshape(-1, 3)
    for sid in sorted(source_poses):
        try:
            origin = np.asarray(source_poses[sid], float)
            source_ok = origin.shape == (3,) and np.isfinite(origin).all()
        except (TypeError, ValueError):
            source_ok = False
        if source_ok:
            contains = (np.abs(np.einsum('bj,baj->ba', origin - centers, axes)) <= half + TOL).all(axis=-1)
            stats['source_inside_obb'] += int(contains.sum())
        for start in range(0, len(queries), chunk_size):
            chunk = queries[start:start + chunk_size]
            xyz = np.full((len(chunk), 3), np.nan)
            for k, g in enumerate(chunk):
                try:
                    v = np.asarray(g['xyz'], float)
                    if v.shape == (3,):
                        xyz[k] = v
                except (TypeError, ValueError, KeyError):
                    pass
            pc = xyz + [0, 0, .75]
            good = np.isfinite(pc).all(axis=1)
            if source_ok:
                inside_probe = (np.abs(origin - pc) <= .5 + TOL).all(axis=1)
                good &= ~inside_probe
                stats['source_inside_probe'] += int(inside_probe.sum())
            else:
                good[:] = False
            for k, g in enumerate(chunk):
                result[g['id']][sid] = dict(C=0., C_missing=int(not good[k]), main_id=None, ray_ids=[None] * 9)
            stats['cue_missing'] += int((~good).sum())
            if not good.any() or not bid:
                continue
            ix = np.flatnonzero(good)
            directions = (pc[ix, None] + PROBE_OFFSETS[None] - origin).reshape(-1, 3)
            # Each ray's own probe entry; all other probes are irrelevant.
            probe_t, _ = segment_box_interval(origin, directions, pc[ix], np.tile(np.eye(3), (len(ix), 1, 1)), np.full((len(ix), 3), .5))
            own_t = probe_t[np.arange(len(ix) * 9), np.repeat(np.arange(len(ix)), 9)]
            t, hit = segment_box_interval(origin, directions, centers, axes, half)
            same = np.array([[chunk[q]['id'] == b for b in bid] for q in ix])
            near = np.linalg.norm(xyz[ix, None, :2] - bottoms[None, :, :2], axis=-1) <= 3 + TOL
            excluded = same | near | contains[None]
            stats['near_duplicate_pairs'] += int((near & ~same).sum())
            hit &= ~np.repeat(excluded, 9, axis=0)
            hit &= t < own_t[:, None] - TOL
            t = np.where(hit, t, np.inf)
            nearest = t.min(axis=1)
            # IDs were sorted. The first within the fixed tie tolerance wins.
            tied = np.isfinite(t) & (t <= nearest[:, None] + TOL)
            best = tied.argmax(axis=1)
            for j, q in enumerate(ix):
                ray_ids = [bid[int(best[j*9+r])] if np.isfinite(nearest[j*9+r]) else None for r in range(9)]
                counts = Counter(v for v in ray_ids if v is not None)
                main = min(counts, key=lambda v: (-counts[v], v)) if counts else None
                result[chunk[q]['id']][sid] = dict(C=sum(v is not None for v in ray_ids) / 9., C_missing=0, main_id=main, ray_ids=ray_ids)
                stats['cue_positive'] += int(bool(counts))
    return result, dict(stats)


def groups_from_cues(source_ids, cue):
    groups = {}
    for sid in sorted(source_ids):
        c = cue[sid]
        token = ('blocker', c['main_id']) if c['C'] > 0 and not c['C_missing'] else ('singleton', sid)
        groups.setdefault(token, []).append(sid)
    return sorted(groups.values(), key=lambda g: tuple(g))
