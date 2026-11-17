"""Vehicle support and sampled ray traversal in a fixed reference vehicle box.

xyz is the native track's bottom anchor, yaw is native Box3D.yaw (radians).
F measures volumes of ray-traversed cells, not fully observed free volumes.
"""
import numpy as np
from shapely.geometry import Polygon

CELL = .25
VEHICLES = {'car', 'vehicle', 'truck', 'bus', 'van'}


def valid_shape(shape_hwl):
    shape = np.asarray(shape_hwl, float)
    if shape.shape != (3,) or not np.isfinite(shape).all() or (shape <= 0).any():
        raise ValueError('reference hwl must be three finite positive values')
    return shape


def _geometry(geometry):
    xyz = np.asarray(geometry['xyz'], float)
    yaw = float(geometry['yaw'])
    if xyz.shape != (3,) or not np.isfinite(xyz).all() or not np.isfinite(yaw):
        raise ValueError('invalid geometry')
    c, s = np.cos(yaw), np.sin(yaw)
    return xyz, np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])


def _polygon(geometry, hwl):
    xyz, rotation = _geometry(geometry)
    h, w, l = valid_shape(hwl)
    vertices = np.array([[l/2, w/2, 0], [-l/2, w/2, 0],
                         [-l/2, -w/2, 0], [l/2, -w/2, 0]])
    return Polygon((vertices @ rotation.T + xyz)[:, :2])


def _compatibility(queries, fresh_boxes, shape):
    scores = np.zeros((len(queries), len(fresh_boxes)))
    invalid = False
    ids = []
    for j, box in enumerate(fresh_boxes):
        try:
            # Validate before filtering so corrupt geometry cannot silently be absence.
            _geometry(box)
            polygon = _polygon(box, box['hwl'])
            ids.append(box['id'])
            if not box['fresh'] or str(box['obj_type']).lower() not in VEHICLES:
                continue
            for i, q in enumerate(queries):
                if q is None:
                    continue
                try:
                    xyz, _ = _geometry(q)
                    if abs(float(box['timestamp'])-float(q['timestamp'])) > 1e-8:
                        continue
                    if not np.isfinite(float(box['timestamp'])) or not np.isfinite(float(q['timestamp'])):
                        raise ValueError('invalid timestamp')
                    if str(q.get('obj_type', 'car')).lower() not in VEHICLES:
                        continue
                    if np.linalg.norm(xyz[:2]-np.asarray(box['xyz'])[:2]) > 3.:
                        continue
                    reference = _polygon(q, shape)
                    area = reference.intersection(polygon).area
                    if area > 0:
                        scores[i, j] = area/(reference.area+polygon.area-area)
                except (KeyError, TypeError, ValueError):
                    continue
        except (KeyError, TypeError, ValueError):
            invalid = True
    # Repeated track identities are an invalid association, even if geometries differ.
    duplicates = len(ids) != len(set(ids))
    return scores, invalid, duplicates


def sampled_free(query, origin_world, points_world, shape_hwl):
    shape = valid_shape(shape_hwl)
    xyz, rotation = _geometry(query)
    origin = np.asarray(origin_world, float)
    if points_world is None:
        raise ValueError('point cloud unavailable')
    points = np.asarray(points_world, float)
    if points.size == 0 and points.shape in ((0,), (0, 3)):
        points = points.reshape(0, 3)
    if (origin.shape != (3,) or points.ndim != 2 or points.shape[1] != 3
            or not np.isfinite(origin).all() or not np.isfinite(points).all()):
        raise ValueError('invalid point cloud or sensor origin')
    # Bottom anchor: x/y centered, z in [0,h]. Native yaw is body-to-world heading.
    size = shape[[2, 1, 0]]
    lower = np.array([-size[0]/2, -size[1]/2, 0.])
    o = (origin-xyz) @ rotation-lower
    endpoints = (points-xyz) @ rotation-lower
    edges = [np.r_[np.arange(0., d, CELL), d] for d in size]
    counts = np.array([len(e)-1 for e in edges])
    traversed = np.zeros(tuple(counts), bool)
    occupied = np.zeros_like(traversed)

    def indices(coords):
        # Half-open cells; an endpoint on the external maximum belongs to last cell.
        return np.minimum(np.floor(coords/CELL).astype(int), counts-1)

    in_box = ((endpoints >= 0) & (endpoints <= size)).all(axis=1)
    if in_box.any():
        occupied[tuple(indices(endpoints[in_box]).T)] = True
    directions = endpoints-o
    parallel = np.abs(directions) < 1e-14
    a = np.full_like(directions, -np.inf)
    b = np.full_like(directions, np.inf)
    np.divide(-o, directions, out=a, where=~parallel)
    np.divide(size-o, directions, out=b, where=~parallel)
    entry = np.maximum(0., np.minimum(a, b).max(axis=1))
    exit_ = np.minimum(1., np.maximum(a, b).min(axis=1))
    outside = (parallel & ((o < 0) | (o > size))).any(axis=1)
    hits = np.flatnonzero((exit_ > entry) & ~outside & (np.linalg.norm(directions, axis=1) > 0))
    for k in hits:
        d = directions[k]
        times = [np.array([entry[k], exit_[k]])]
        for axis, e in enumerate(edges):
            if not parallel[k, axis]:
                t = (e[1:-1]-o[axis])/d[axis]
                times.append(t[(t > entry[k]) & (t < exit_[k])])
        t = np.unique(np.concatenate(times))
        # Discard numerical zero segments at plane/corner coincidences.
        mid = (t[:-1]+t[1:])/2
        mid = mid[(t[1:]-t[:-1])*np.linalg.norm(d) > 1e-12]
        if mid.size:
            cells = indices(np.clip(o+mid[:, None]*d, 0, size))
            traversed[tuple(cells.T)] = True
    free = traversed & ~occupied
    volumes = (np.diff(edges[0])[:, None, None] * np.diff(edges[1])[None, :, None]
               * np.diff(edges[2])[None, None, :])
    return dict(F=float(volumes[free].sum()/np.prod(size)), F_eligible=True,
                F_status='covered' if (traversed | occupied).any() else 'no_coverage',
                n_points=len(points), n_intersecting_rays=len(hits), n_voxels=int(np.prod(counts)),
                n_free=int(free.sum()), n_occupied=int(occupied.sum()),
                n_covered=int((traversed | occupied).sum()))


def measure_frame(queries, fresh_boxes, origin_world, points_world, shape_hwl, free_cache=None):
    """Match all queries of ONE job/frame together, then measure each reference box."""
    shape = valid_shape(shape_hwl)
    scores, invalid_boxes, duplicate_ids = _compatibility(queries, fresh_boxes, shape)
    relation = scores > 0
    result = []
    for i, q in enumerate(queries):
        r = dict(I=None, F=None, I_eligible=False, F_eligible=False,
                 I_status='no_support', F_status='unavailable', input_fault=False,
                 n_compatible=int(relation[i].sum()), matched_local_id=None)
        if q is None:
            r.update(status='no_query', I_status='no_query', F_status='no_query')
            result.append(r)
            continue
        try:
            _geometry(q)
            if not np.isfinite(float(q['timestamp'])):
                raise ValueError('invalid query time')
            cache_key = tuple(q['xyz'])+(float(q['yaw']),)+tuple(shape)
            if free_cache is not None and cache_key in free_cache:
                free = free_cache[cache_key]
            else:
                free = sampled_free(q, origin_world, points_world, shape)
                if free_cache is not None:
                    free_cache[cache_key] = free
            r.update(free)
            if invalid_boxes:
                raise ValueError('invalid local detection geometry')
            candidates = np.flatnonzero(relation[i])
            if len(candidates):
                j = candidates[0]
                if len(candidates) != 1 or relation[:, j].sum() != 1 or duplicate_ids:
                    r['I_status'] = 'ambiguous'
                else:
                    r.update(I=float(scores[i, j]), I_eligible=True, I_status='matched',
                             matched_local_id=fresh_boxes[j]['id'])
            r['status'] = 'ok'
        except (KeyError, ValueError, TypeError) as exc:
            r.update(I=None, F=None, I_eligible=False, F_eligible=False,
                     input_fault=True, status='input_fault', fault=str(exc))
        result.append(r)
    return result


def measure_local(query, fresh_boxes, origin_world, points_world, shape_hwl):
    """Single-query helper. Multi-query callers MUST use measure_frame for uniqueness."""
    return measure_frame([query], fresh_boxes, origin_world, points_world, shape_hwl)[0]
