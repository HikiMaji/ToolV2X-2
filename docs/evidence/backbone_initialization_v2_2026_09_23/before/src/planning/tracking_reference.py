"""Frozen analytic references and 2-D geometry for the first tracking gate."""
from functools import lru_cache
import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon


CASES = ["S2", "L2", "R2", "SR2", "S4", "L4", "R4", "SR4"]
_ROW_KEYS = ("t", "x", "y", "yaw", "v", "a", "jerk", "kappa", "kappa_rate")


def _segment(kind, start, end, v0, v1=None, turn=0):
    return {"kind": kind, "start": float(start), "end": float(end),
            "v0": float(v0), "v1": float(v0 if v1 is None else v1), "turn": int(turn)}


_SEGMENTS = {
    "S2": [_segment("H", 0, 1, 0), _segment("A", 1, 5, 0, 2),
           _segment("C", 5, 9, 2), _segment("D", 9, 13, 2, 0), _segment("H", 13, 15, 0)],
    "L2": [_segment("H", 0, 1, 0), _segment("A", 1, 5, 0, 2),
           _segment("C", 5, 7, 2), _segment("K", 7, 19, 2, turn=1),
           _segment("C", 19, 21, 2), _segment("D", 21, 25, 2, 0), _segment("H", 25, 27, 0)],
    "R2": [_segment("H", 0, 1, 0), _segment("A", 1, 5, 0, 2),
           _segment("C", 5, 7, 2), _segment("K", 7, 19, 2, turn=-1),
           _segment("C", 19, 21, 2), _segment("D", 21, 25, 2, 0), _segment("H", 25, 27, 0)],
    "SR2": [_segment("H", 0, 1, 0), _segment("A", 1, 5, 0, 2),
            _segment("C", 5, 9, 2), _segment("D", 9, 13, 2, 0), _segment("H", 13, 16, 0),
            _segment("A", 16, 20, 0, 2), _segment("C", 20, 24, 2),
            _segment("D", 24, 28, 2, 0), _segment("H", 28, 30, 0)],
    "S4": [_segment("H", 0, 1, 0), _segment("A", 1, 9, 0, 4),
           _segment("C", 9, 11, 4), _segment("D", 11, 19, 4, 0), _segment("H", 19, 21, 0)],
    "L4": [_segment("H", 0, 1, 0), _segment("A", 1, 9, 0, 4),
           _segment("C", 9, 10, 4), _segment("K", 10, 16, 4, turn=1),
           _segment("C", 16, 17, 4), _segment("D", 17, 25, 4, 0), _segment("H", 25, 27, 0)],
    "R4": [_segment("H", 0, 1, 0), _segment("A", 1, 9, 0, 4),
           _segment("C", 9, 10, 4), _segment("K", 10, 16, 4, turn=-1),
           _segment("C", 16, 17, 4), _segment("D", 17, 25, 4, 0), _segment("H", 25, 27, 0)],
    "SR4": [_segment("H", 0, 1, 0), _segment("A", 1, 9, 0, 4),
            _segment("C", 9, 11, 4), _segment("D", 11, 19, 4, 0), _segment("H", 19, 22, 0),
            _segment("A", 22, 30, 0, 4), _segment("C", 30, 32, 4),
            _segment("D", 32, 40, 4, 0), _segment("H", 40, 42, 0)],
}


def case_spec(name):
    """Return the frozen, JSON-shaped timing contract for one case."""
    if name not in CASES:
        raise ValueError("unknown tracking case: " + str(name))
    segments = [dict(segment) for segment in _SEGMENTS[name]]
    turns = [segment for segment in segments if segment["kind"] == "K"]
    return {
        "name": name,
        "V": float(name[-1]),
        "duration": segments[-1]["end"],
        "segments": segments,
        "stops": [{"start": segment["start"], "end": segment["end"]}
                  for segment in segments if segment["kind"] == "H"],
        "accels": [{key: segment[key] for key in ("start", "end", "v0", "v1")}
                   for segment in segments if segment["kind"] == "A"],
        "turn_end": turns[0]["end"] if turns else None,
    }


def _smooth(u):
    return 10 * u**3 - 15 * u**4 + 6 * u**5


def _smooth_d1(u):
    return 30 * u**2 - 60 * u**3 + 30 * u**4


def _smooth_d2(u):
    return 60 * u - 180 * u**2 + 120 * u**3


def _smooth_integral(u):
    return 2.5 * u**4 - 3 * u**5 + u**6


def _segment_distance(segment, elapsed=None):
    duration = segment["end"] - segment["start"]
    elapsed = duration if elapsed is None else min(max(float(elapsed), 0.0), duration)
    if segment["kind"] in ("A", "D"):
        u = elapsed / duration
        return segment["v0"] * elapsed + (segment["v1"] - segment["v0"]) * duration * _smooth_integral(u)
    return segment["v0"] * elapsed


def _profile(spec, t):
    t = float(t)
    if t >= spec["duration"]:
        return 0.0, 0.0, 0.0, sum(_segment_distance(segment) for segment in spec["segments"])
    distance = 0.0
    for segment in spec["segments"]:
        if t >= segment["end"]:
            distance += _segment_distance(segment)
            continue
        elapsed = max(0.0, t - segment["start"])
        distance += _segment_distance(segment, elapsed)
        if segment["kind"] in ("A", "D"):
            duration = segment["end"] - segment["start"]
            u = elapsed / duration
            delta = segment["v1"] - segment["v0"]
            return (segment["v0"] + delta * _smooth(u),
                    delta * _smooth_d1(u) / duration,
                    delta * _smooth_d2(u) / duration**2,
                    distance)
        return segment["v0"], 0.0, 0.0, distance
    raise RuntimeError("case segments do not cover their duration")


def _turn_geometry(spec):
    distance = 0.0
    for segment in spec["segments"]:
        if segment["kind"] == "K":
            return distance, segment["turn"], segment["v0"]
        distance += _segment_distance(segment)
    return None


def _curvature(turn, distance, speed):
    if turn is None:
        return 0.0, 0.0
    start, sign, turn_speed = turn
    s = distance - start
    if s < 0.0 or s > 24.0:
        return 0.0, 0.0
    if s < 8.0:
        u = s / 8.0
        return sign * 0.05 * _smooth(u), sign * 0.05 * _smooth_d1(u) / 8.0 * speed
    if s < 16.0:
        return sign * 0.05, 0.0
    u = (s - 16.0) / 8.0
    return sign * 0.05 * (1.0 - _smooth(u)), -sign * 0.05 * _smooth_d1(u) / 8.0 * speed


def _integrate_pose(targets, turn, ds):
    pose = np.zeros(3, dtype=float)
    current = 0.0
    result = []

    def derivative(s, yaw):
        kappa, _ = _curvature(turn, s, turn[2] if turn else 0.0)
        return np.array((math.cos(yaw), math.sin(yaw), kappa))

    for target in targets:
        while target - current > 1e-12:
            step = min(ds, target - current)
            k1 = derivative(current, pose[2])
            k2 = derivative(current + step / 2, pose[2] + step * k1[2] / 2)
            k3 = derivative(current + step / 2, pose[2] + step * k2[2] / 2)
            k4 = derivative(current + step, pose[2] + step * k3[2])
            pose += step * (k1 + 2 * k2 + 2 * k3 + k4) / 6
            current += step
        result.append(tuple(float(value) for value in pose))
    return result


@lru_cache(maxsize=32)
def _generate_cached(name, ds):
    spec = case_spec(name)
    count = int(round((spec["duration"] + 0.4) * 10)) + 1
    times = [index / 10 for index in range(count)]
    profiles = [_profile(spec, t) for t in times]
    turn = _turn_geometry(spec)
    poses = _integrate_pose([profile[3] for profile in profiles], turn, ds)
    rows = []
    for t, (v, a, jerk, distance), (x, y, yaw) in zip(times, profiles, poses):
        kappa, kappa_rate = _curvature(turn, distance, v)
        rows.append((t, x, y, yaw, v, a, jerk, kappa, kappa_rate))
    return tuple(rows)


def generate_reference(name, ds=0.001):
    """Generate the rear-axle reference on exact 0.1 s ticks through T+0.4."""
    if isinstance(ds, bool) or not isinstance(ds, (int, float)) or not math.isfinite(ds) or ds <= 0:
        raise ValueError("ds must be a positive finite number")
    return [dict(zip(_ROW_KEYS, row)) for row in _generate_cached(name, float(ds))]


def state_at(reference, t):
    """Return an exact 0.1 s row; interpolation and out-of-range access are forbidden."""
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
        raise ValueError("time must be finite")
    index = int(round(float(t) * 10))
    if abs(float(t) - index / 10) > 1e-9 or index < 0 or index >= len(reference):
        raise ValueError("time is outside the reference or not on the 0.1 s grid")
    row = reference[index]
    if abs(float(row.get("t", math.nan)) - index / 10) > 1e-9:
        raise ValueError("reference time grid is invalid")
    return row


def actor_target(row, rear_to_actor_xy):
    """Convert one rear-axle state to actor-origin position and rigid-body speed."""
    offset = np.asarray(rear_to_actor_xy, dtype=float)
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError("rear_to_actor_xy must contain two finite values")
    yaw, speed, kappa = (float(row[key]) for key in ("yaw", "v", "kappa"))
    rotation = np.array(((math.cos(yaw), -math.sin(yaw)),
                         (math.sin(yaw), math.cos(yaw))))
    world_offset = rotation @ offset
    rear_velocity = speed * np.array((math.cos(yaw), math.sin(yaw)))
    omega = speed * kappa
    actor_velocity = rear_velocity + omega * np.array((-world_offset[1], world_offset[0]))
    return {"x": float(row["x"] + world_offset[0]),
            "y": float(row["y"] + world_offset[1]),
            "speed_mps": float(np.linalg.norm(actor_velocity))}


def corridor(reference, case_name=None):
    """Build the corridor; frozen cases use an analytic 0.01 m centerline."""
    if not reference:
        raise ValueError("reference is empty")
    if case_name is None:
        points = []
        for row in reference:
            point = (float(row["x"]), float(row["y"]))
            if not points or point != points[-1]:
                points.append(point)
        first_yaw, last_yaw = float(reference[0]["yaw"]), float(reference[-1]["yaw"])
    else:
        spec = case_spec(case_name)
        total_distance = _profile(spec, spec["duration"])[3]
        count = int(math.floor(total_distance / 0.01 + 1e-9))
        distances = [index * 0.01 for index in range(count + 1)]
        if total_distance - distances[-1] > 1e-9:
            distances.append(total_distance)
        poses = _integrate_pose(distances, _turn_geometry(spec), 0.001)
        points = [(x, y) for x, y, _ in poses]
        first_yaw, last_yaw = poses[0][2], poses[-1][2]
    if len(points) < 2:
        raise ValueError("reference has no moving path")
    start = (points[0][0] - 10 * math.cos(first_yaw), points[0][1] - 10 * math.sin(first_yaw))
    end = (points[-1][0] + 10 * math.cos(last_yaw), points[-1][1] + 10 * math.sin(last_yaw))
    polygon = LineString([start, *points, end]).buffer(1.75, resolution=16, cap_style=2, join_style=1)
    if not polygon.is_valid or polygon.is_empty:
        raise ValueError("reference corridor is invalid")
    return polygon


def body_polygon(rear_xy, yaw, geometry):
    """Return the full bounding-box polygon from a rear-axle pose."""
    required = {"front", "rear", "width", "box_center_y", "box_yaw"}
    if not isinstance(geometry, dict) or not required <= set(geometry):
        raise ValueError("incomplete vehicle geometry")
    values = {key: float(geometry[key]) for key in required}
    if (not all(math.isfinite(value) for value in values.values()) or
            values["front"] <= 0 or values["rear"] <= 0 or values["width"] <= 0):
        raise ValueError("invalid vehicle geometry")
    rear_xy = np.asarray(rear_xy, dtype=float)
    if rear_xy.shape != (2,) or not np.isfinite(rear_xy).all() or not math.isfinite(float(yaw)):
        raise ValueError("invalid rear pose")

    half_length = (values["front"] + values["rear"]) / 2
    half_width = values["width"] / 2
    center = np.array(((values["front"] - values["rear"]) / 2, values["box_center_y"]))
    box_rotation = np.array(((math.cos(values["box_yaw"]), -math.sin(values["box_yaw"])),
                             (math.sin(values["box_yaw"]), math.cos(values["box_yaw"]))))
    world_rotation = np.array(((math.cos(yaw), -math.sin(yaw)),
                               (math.sin(yaw), math.cos(yaw))))
    corners = []
    for longitudinal, lateral in ((half_length, half_width), (half_length, -half_width),
                                  (-half_length, -half_width), (-half_length, half_width)):
        corners.append(tuple(rear_xy + world_rotation @ (center + box_rotation @ (longitudinal, lateral))))
    return Polygon(corners)


def clearance(polygon, corridor_polygon):
    """Return inside boundary clearance, with a negative sign for any excursion."""
    if corridor_polygon.covers(polygon):
        return float(corridor_polygon.boundary.distance(polygon))
    outside_distance = max(Point(point).distance(corridor_polygon) for point in polygon.exterior.coords)
    return -float(max(outside_distance, 1e-12))


def validate_reference(name, reference, geometry):
    """Independently check the frozen reference, integration and full-body margin."""
    spec = case_spec(name)
    errors = []
    metrics = {}
    expected_count = int(round((spec["duration"] + 0.4) * 10)) + 1
    if not isinstance(reference, list) or len(reference) != expected_count:
        errors.append("time grid length does not cover 0..T+0.4")
        return {"passed": False, "errors": errors, "metrics": metrics}

    valid_rows = True
    for index, row in enumerate(reference):
        if (not isinstance(row, dict) or set(row) != set(_ROW_KEYS) or
                not all(isinstance(row[key], (int, float)) and not isinstance(row[key], bool)
                        and math.isfinite(float(row[key])) for key in _ROW_KEYS) or
                abs(float(row["t"]) - index / 10) > 1e-9):
            valid_rows = False
            break
    if not valid_rows:
        errors.append("invalid row fields, values, or 0.1 s time grid")
        return {"passed": False, "errors": errors, "metrics": metrics}

    expected = generate_reference(name, 0.001)
    refined = generate_reference(name, 0.0005)
    position_deltas = [math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                       for a, b in zip(expected, refined)]
    yaw_deltas = [abs(a["yaw"] - b["yaw"]) for a, b in zip(expected, refined)]
    metrics["half_step_position_max_m"] = max(position_deltas)
    metrics["half_step_yaw_max_rad"] = max(yaw_deltas)
    if metrics["half_step_position_max_m"] > 0.0001 or metrics["half_step_yaw_max_rad"] > 0.00001:
        errors.append("ds/2 integration consistency failed")

    mismatch = max(abs(float(row[key]) - expected[index][key])
                   for index, row in enumerate(reference) for key in _ROW_KEYS)
    metrics["analytic_max_difference"] = mismatch
    if mismatch > 1e-8:
        errors.append("analytic reference does not match the frozen construction")

    metrics.update(
        max_abs_accel_mps2=max(abs(float(row["a"])) for row in reference),
        max_abs_jerk_mps3=max(abs(float(row["jerk"])) for row in reference),
        max_abs_curvature_1pm=max(abs(float(row["kappa"])) for row in reference),
        max_abs_curvature_rate_1pms=max(abs(float(row["kappa_rate"])) for row in reference),
    )
    jerk_bound = 1.4433756729740645 / spec["V"]
    if (min(float(row["v"]) for row in reference) < -1e-12 or
            max(float(row["v"]) for row in reference) > spec["V"] + 1e-12 or
            metrics["max_abs_accel_mps2"] > 0.9375 + 1e-12 or
            metrics["max_abs_jerk_mps3"] > jerk_bound + 1e-12 or
            metrics["max_abs_curvature_1pm"] > 0.05 + 1e-12 or
            metrics["max_abs_curvature_rate_1pms"] > 0.01171875 * spec["V"] + 1e-12):
        errors.append("analytic velocity, acceleration, jerk, or curvature bound failed")
    if any(abs(float(reference[-1][key])) > 1e-12 for key in ("v", "a", "jerk", "kappa", "kappa_rate")):
        errors.append("terminal extension is not stationary")

    try:
        lane = corridor(reference, name)
        clearances = [clearance(body_polygon((row["x"], row["y"]), row["yaw"], geometry), lane)
                      for row in reference]
        metrics["min_body_clearance_m"] = min(clearances)
        if metrics["min_body_clearance_m"] < 0.30:
            errors.append("full-body reference clearance is below 0.30 m")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append("geometry validation failed: " + str(exc))

    return {"passed": not errors, "errors": errors, "metrics": metrics}
