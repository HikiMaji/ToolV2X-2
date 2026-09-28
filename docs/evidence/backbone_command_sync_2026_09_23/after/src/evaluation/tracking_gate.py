"""Independent offline audit for the frozen reference-tracking gate."""
import argparse
import json
import math
from pathlib import Path
import re

import numpy as np
from shapely.geometry import Polygon, shape

DT = .1


_CASE_SEGMENTS = {
    'S2': (2., [('H', 0, 1, 0., 0., 0), ('A', 1, 5, 0., 2., 0), ('C', 5, 9, 2., 2., 0),
                  ('D', 9, 13, 2., 0., 0), ('H', 13, 15, 0., 0., 0)]),
    'L2': (2., [('H', 0, 1, 0., 0., 0), ('A', 1, 5, 0., 2., 0), ('C', 5, 7, 2., 2., 0),
                  ('K', 7, 19, 2., 2., 1), ('C', 19, 21, 2., 2., 0),
                  ('D', 21, 25, 2., 0., 0), ('H', 25, 27, 0., 0., 0)]),
    'R2': (2., [('H', 0, 1, 0., 0., 0), ('A', 1, 5, 0., 2., 0), ('C', 5, 7, 2., 2., 0),
                  ('K', 7, 19, 2., 2., -1), ('C', 19, 21, 2., 2., 0),
                  ('D', 21, 25, 2., 0., 0), ('H', 25, 27, 0., 0., 0)]),
    'SR2': (2., [('H', 0, 1, 0., 0., 0), ('A', 1, 5, 0., 2., 0), ('C', 5, 9, 2., 2., 0),
                   ('D', 9, 13, 2., 0., 0), ('H', 13, 16, 0., 0., 0),
                   ('A', 16, 20, 0., 2., 0), ('C', 20, 24, 2., 2., 0),
                   ('D', 24, 28, 2., 0., 0), ('H', 28, 30, 0., 0., 0)]),
    'S4': (4., [('H', 0, 1, 0., 0., 0), ('A', 1, 9, 0., 4., 0), ('C', 9, 11, 4., 4., 0),
                  ('D', 11, 19, 4., 0., 0), ('H', 19, 21, 0., 0., 0)]),
    'L4': (4., [('H', 0, 1, 0., 0., 0), ('A', 1, 9, 0., 4., 0), ('C', 9, 10, 4., 4., 0),
                  ('K', 10, 16, 4., 4., 1), ('C', 16, 17, 4., 4., 0),
                  ('D', 17, 25, 4., 0., 0), ('H', 25, 27, 0., 0., 0)]),
    'R4': (4., [('H', 0, 1, 0., 0., 0), ('A', 1, 9, 0., 4., 0), ('C', 9, 10, 4., 4., 0),
                  ('K', 10, 16, 4., 4., -1), ('C', 16, 17, 4., 4., 0),
                  ('D', 17, 25, 4., 0., 0), ('H', 25, 27, 0., 0., 0)]),
    'SR4': (4., [('H', 0, 1, 0., 0., 0), ('A', 1, 9, 0., 4., 0), ('C', 9, 11, 4., 4., 0),
                   ('D', 11, 19, 4., 0., 0), ('H', 19, 22, 0., 0., 0),
                   ('A', 22, 30, 0., 4., 0), ('C', 30, 32, 4., 4., 0),
                   ('D', 32, 40, 4., 0., 0), ('H', 40, 42, 0., 0., 0)]),
}
CASE_NAMES = tuple(_CASE_SEGMENTS)


def _frozen_case_spec(name):
    speed, rows = _CASE_SEGMENTS[name]
    segments = [dict(kind=kind, start=float(start), end=float(end), v0=v0, v1=v1, turn=turn)
                for kind, start, end, v0, v1, turn in rows]
    return dict(name=name, V=speed, duration=float(rows[-1][2]), segments=segments,
        stops=[dict(start=row['start'], end=row['end']) for row in segments if row['kind'] == 'H'],
        accels=[dict(start=row['start'], end=row['end'], v0=row['v0'], v1=row['v1'])
                for row in segments if row['kind'] == 'A'],
        turn_end=next((row['end'] for row in segments if row['kind'] == 'K'), None))


def _derivative(points):
    """Same-time finite difference, including second-order endpoints."""
    value = np.empty_like(points, dtype=float)
    value[1:-1] = (points[2:] - points[:-2]) / (2 * DT)
    value[0] = (-3 * points[0] + 4 * points[1] - points[2]) / (2 * DT)
    value[-1] = (3 * points[-1] - 4 * points[-2] + points[-3]) / (2 * DT)
    return value


def _nearest_rank_99(values):
    values = np.sort(np.abs(values))
    return float(values[max(0, math.ceil(.99 * len(values)) - 1)]) if len(values) else None


def audit_trial(case_spec, reference, frames, corridor_polygon):
    """Recompute one fixed 0.1 s trial without smoothing or time alignment."""
    failures, metrics = [], {}

    def fail(check):
        if check not in failures:
            failures.append(check)

    def finish():
        passed = not failures
        return {'status': 'PASS' if passed else 'FAIL', 'passed': passed,
                'failures': failures, 'metrics': metrics}

    try:
        required = {'name', 'V', 'duration', 'segments', 'stops', 'accels', 'turn_end'}
        if not isinstance(case_spec, dict) or set(case_spec) != required:
            fail('case_spec'); return finish()
        duration = float(case_spec['duration'])
        if (not np.isfinite(duration) or duration <= 0 or
                not np.isclose(duration / DT, round(duration / DT)) or
                case_spec['V'] not in (2, 4) or
                not all(isinstance(case_spec[k], list) for k in ('segments', 'stops', 'accels'))):
            fail('case_spec'); return finish()
        count = round(duration / DT) + 1
        metrics.update(expected_samples=count, observed_samples=len(frames), expected_controls=count - 1, observed_controls=sum(row.get('control') is not None for row in frames))
        if len(frames) != count:
            fail('sample_count')
        if len(reference) < count + 4:
            fail('reference_count')
        if len(frames) < count or len(reference) < count:
            return finish()
        frames, evaluated = frames[:count], reference[:count]
        reference_fields = {'t', 'x', 'y', 'yaw', 'v', 'a', 'jerk', 'kappa', 'kappa_rate'}
        frame_fields = {'i', 'frame', 'timestamp', 't', 'actor_xy', 'rear_xy', 'yaw',
            'actor_velocity', 'angular_velocity', 'body_polygon_xy', 'wheel_steer_rad',
            'gear', 'control', 'collision_events'}
        for i, row in enumerate(reference):
            if not isinstance(row, dict) or not reference_fields <= set(row):
                fail('reference_fields'); return finish()
            if not np.isfinite([row[k] for k in reference_fields]).all():
                fail('nonfinite'); return finish()
            if not np.isclose(row['t'], i * DT, atol=1e-8):
                fail('time_alignment')
        for i, row in enumerate(frames):
            if not isinstance(row, dict) or not frame_fields <= set(row):
                fail('frame_fields'); return finish()
            values = np.concatenate([np.asarray(row[k], dtype=float).reshape(-1)
                for k in ('actor_xy', 'rear_xy', 'actor_velocity', 'angular_velocity',
                          'body_polygon_xy', 'wheel_steer_rad')]
                + [np.asarray([row['timestamp'], row['t'], row['yaw'], row['gear']], dtype=float)])
            if not np.isfinite(values).all():
                fail('nonfinite'); return finish()
            if type(row['i']) is not int or row['i'] != i:
                fail('frame_index')
            if type(row['frame']) is not int or (i and row['frame'] != frames[i - 1]['frame'] + 1):
                fail('frame_continuity')
            if (not np.isclose(row['t'], i * DT, atol=1e-8) or
                    not np.isclose(row['t'], evaluated[i]['t'], atol=1e-8)):
                fail('time_alignment')
            if i and not np.isclose(row['timestamp'] - frames[i - 1]['timestamp'], DT, atol=1e-5):
                fail('timestamp_continuity')
            if row['gear'] < 0:
                fail('reverse_gear')
            if row['collision_events']:
                fail('collision')
            if row.get('abort_reason'):
                fail(str(row['abort_reason']))
            control = row['control']
            if i == count - 1:
                if control is not None:
                    fail('terminal_control')
            elif not isinstance(control, dict):
                fail('missing_control')
            else:
                try:
                    throttle, brake, steer = (float(control[k]) for k in ('throttle', 'brake', 'steer'))
                except (KeyError, TypeError, ValueError):
                    fail('illegal_control')
                else:
                    if (not np.isfinite([throttle, brake, steer]).all() or
                            not 0 <= throttle <= .75 or not 0 <= brake <= .3 or abs(steer) > .8 or
                            control.get('hand_brake', False) or control.get('reverse', False) or
                            control.get('manual_gear_shift', False)):
                        fail('illegal_control')

        steer_slew = []
        for i, row in enumerate(frames[:-1]):
            previous = row.get('last_control') if i == 0 else frames[i - 1]['control']
            if isinstance(previous, dict) and 'steer' in previous and isinstance(row['control'], dict):
                steer_slew.append(abs(float(row['control']['steer']) - float(previous['steer'])))
        metrics['max_steer_command_change'] = max(steer_slew) if steer_slew else None
        if steer_slew and metrics['max_steer_command_change'] > .1 + 1e-12:
            fail('steer_slew')

        rear = np.asarray([row['rear_xy'] for row in frames], dtype=float)
        actor = np.asarray([row['actor_xy'] for row in frames], dtype=float)
        yaw = np.asarray([row['yaw'] for row in frames], dtype=float)
        ref_xy = np.asarray([[row['x'], row['y']] for row in evaluated], dtype=float)
        ref_yaw = np.asarray([row['yaw'] for row in evaluated], dtype=float)
        ref_speed = np.asarray([row['v'] for row in evaluated], dtype=float)
        tangent = np.column_stack((np.cos(ref_yaw), np.sin(ref_yaw)))
        normal = np.column_stack((-np.sin(ref_yaw), np.cos(ref_yaw)))
        delta = rear - ref_xy
        e_long = np.sum(delta * tangent, axis=1)
        e_lat = np.sum(delta * normal, axis=1)
        e_yaw = np.arctan2(np.sin(yaw - ref_yaw), np.cos(yaw - ref_yaw))
        rear_velocity, actor_velocity = _derivative(rear), _derivative(actor)
        heading = np.column_stack((np.cos(yaw), np.sin(yaw)))
        lateral = np.column_stack((-np.sin(yaw), np.cos(yaw)))
        speed = np.sum(rear_velocity * heading, axis=1)
        rear_rate = np.linalg.norm(rear_velocity, axis=1)
        speed_error = speed - ref_speed
        metrics.update(max_abs_e_long_m=float(np.max(np.abs(e_long))),
            rmse_e_long_m=float(np.sqrt(np.mean(e_long ** 2))),
            max_abs_e_lat_m=float(np.max(np.abs(e_lat))),
            rmse_e_lat_m=float(np.sqrt(np.mean(e_lat ** 2))),
            max_abs_e_yaw_rad=float(np.max(np.abs(e_yaw))),
            min_forward_speed_mps=float(np.min(speed)), max_forward_speed_mps=float(np.max(speed)),
            max_rear_speed_mps=float(np.max(rear_rate)))
        for check, key, limit in (
                ('longitudinal_max', 'max_abs_e_long_m', .75),
                ('longitudinal_rmse', 'rmse_e_long_m', .40),
                ('lateral_max', 'max_abs_e_lat_m', .30),
                ('lateral_rmse', 'rmse_e_lat_m', .15),
                ('yaw_max', 'max_abs_e_yaw_rad', .10)):
            if metrics[key] > limit + 1e-12:
                fail(check)
        if metrics['min_forward_speed_mps'] < -.02 - 1e-12:
            fail('reverse_motion')
        if metrics['max_rear_speed_mps'] > 4.25 + 1e-12:
            fail('max_speed')
        moving = ref_speed > 0
        metrics['moving_speed_rmse_mps'] = float(np.sqrt(np.mean(speed_error[moving] ** 2))) if moving.any() else None
        metrics['max_abs_moving_speed_error_mps'] = float(np.max(np.abs(speed_error[moving]))) if moving.any() else None
        if moving.any() and metrics['moving_speed_rmse_mps'] > .35 + 1e-12:
            fail('moving_speed_rmse')
        if moving.any() and metrics['max_abs_moving_speed_error_mps'] > .75 + 1e-12:
            fail('moving_speed_max')
        metrics['initial_position_error_m'] = float(np.linalg.norm(rear[0] - ref_xy[0]))
        metrics['initial_yaw_error_rad'] = float(abs(e_yaw[0]))
        metrics['initial_wheel_steer_max_rad'] = float(np.max(np.abs(frames[0]['wheel_steer_rad'])))
        if metrics['initial_position_error_m'] > .02 + 1e-12: fail('initial_position')
        if metrics['initial_yaw_error_rad'] > .005 + 1e-12: fail('initial_yaw')
        if metrics['initial_wheel_steer_max_rad'] > .01 + 1e-12: fail('initial_wheel_steer')

        corridor = corridor_polygon if getattr(corridor_polygon, 'geom_type', None) == 'Polygon' else Polygon(corridor_polygon)
        margins = []
        for row in frames:
            polygon = Polygon(row['body_polygon_xy'])
            if not polygon.is_valid or polygon.is_empty or not corridor.covers(polygon):
                fail('geometry_containment'); margins.append(0.)
            else:
                margins.append(float(polygon.distance(corridor.boundary)))
        metrics['min_geometry_margin_m'] = min(margins)
        if metrics['min_geometry_margin_m'] < .15 - 1e-12:
            fail('geometry_margin')

        acceleration = np.diff(rear_velocity, axis=0) / DT
        a_long = np.sum(acceleration * heading[1:], axis=1)
        a_lat = np.sum(acceleration * lateral[1:], axis=1)
        jerk = np.diff(a_long) / DT
        metrics.update(max_abs_a_long_mps2=float(np.max(np.abs(a_long))),
            max_abs_a_lat_mps2=float(np.max(np.abs(a_lat))),
            p99_abs_j_long_mps3=_nearest_rank_99(jerk),
            max_abs_j_long_mps3=float(np.max(np.abs(jerk))) if len(jerk) else None)
        if metrics['max_abs_a_long_mps2'] > 2. + 1e-12: fail('longitudinal_acceleration')
        if metrics['max_abs_a_lat_mps2'] > 1.2 + 1e-12: fail('lateral_acceleration')
        if metrics['p99_abs_j_long_mps3'] is not None and metrics['p99_abs_j_long_mps3'] > 5. + 1e-12:
            fail('longitudinal_jerk_p99')

        metrics['starts'] = []
        for segment in case_spec['accels']:
            mid = round(((float(segment['start']) + float(segment['end'])) / 2) / DT)
            end = round(float(segment['end']) / DT)
            target = float(segment['v1'])
            result = dict(start=float(segment['start']), end=float(segment['end']),
                midpoint_speed_mps=float(speed[mid]), end_speed_mps=float(speed[end]))
            metrics['starts'].append(result)
            if result['midpoint_speed_mps'] < target / 2 - .40 - 1e-12: fail('start_midpoint_speed')
            if result['end_speed_mps'] < target - .30 - 1e-12: fail('start_end_speed')

        metrics['stops'] = []
        for stop in case_spec['stops']:
            strict, end = round((float(stop['start']) + 1.) / DT), round(float(stop['end']) / DT)
            if strict > end:
                fail('case_spec'); continue
            positions = rear[strict:end + 1]
            result = dict(start=float(stop['start']), end=float(stop['end']), strict_start=float(stop['start']) + 1.,
                max_speed_mps=float(np.max(rear_rate[strict:end + 1])),
                path_m=float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum()),
                net_displacement_m=float(np.linalg.norm(positions[-1] - positions[0])),
                end_abs_e_long_m=float(abs(e_long[end])))
            metrics['stops'].append(result)
            if result['max_speed_mps'] > .10 + 1e-12: fail('stop_speed')
            if result['path_m'] > .10 + 1e-12: fail('stop_path')
            if result['end_abs_e_long_m'] > .50 + 1e-12: fail('stop_end_longitudinal')

        turn_segments = [segment for segment in case_spec['segments'] if segment['kind'] == 'K']
        turn_mask = np.zeros(count, dtype=bool)
        ticks = np.arange(count) * DT
        for segment in turn_segments:
            turn_mask |= ((ticks >= float(segment['start']) - 1e-8) &
                          (ticks <= float(segment['end']) + 1e-8))
        turn_mask &= moving
        native = np.asarray([row['actor_velocity'][:2] for row in frames], dtype=float)
        vector_diff = np.linalg.norm(native - actor_velocity, axis=1)
        rate_diff = np.abs(np.linalg.norm(native, axis=1) - np.linalg.norm(actor_velocity, axis=1))
        metrics['native_velocity_vector_diff_max_mps'] = float(np.max(vector_diff[turn_mask])) if turn_mask.any() else None
        metrics['native_speed_diff_max_mps'] = float(np.max(rate_diff[turn_mask])) if turn_mask.any() else None
        if turn_mask.any() and metrics['native_velocity_vector_diff_max_mps'] > .10 + 1e-12: fail('native_velocity_vector')
        if turn_mask.any() and metrics['native_speed_diff_max_mps'] > .05 + 1e-12: fail('native_velocity_rate')
        metrics['turn'] = None
        if case_spec['turn_end'] is not None:
            if len(turn_segments) != 1:
                fail('case_spec')
            else:
                segment = turn_segments[0]
                start, end = round(float(segment['start']) / DT), round(float(case_spec['turn_end']) / DT)
                unwrapped = np.unwrap(yaw)
                actual = float(unwrapped[end] - unwrapped[start])
                expected = .8 * int(segment['turn'])
                error = abs(actual - expected)
                metrics['turn'] = dict(start=float(segment['start']), end=float(case_spec['turn_end']),
                    actual_heading_change_rad=actual, expected_heading_change_rad=expected,
                    absolute_error_rad=error)
                if error > .08 + 1e-12: fail('turn_heading')
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        metrics['input_error'] = '%s: %s' % (type(exc).__name__, exc)
        fail('input_contract')
    return finish()



def parse_recorder_info(text, expected_frames, ego_id, sensor_id):
    """Parse CARLA 0.9.15 QueryInfo(show_all=True) without recorder APIs."""
    failures = []
    def fail(name):
        if name not in failures:
            failures.append(name)
    if (not isinstance(text, str) or type(expected_frames) is not int or expected_frames < 1 or
            type(ego_id) is not int or type(sensor_id) is not int or ego_id == sensor_id):
        return {'complete': False, 'collision_count': 0, 'failures': ['recorder_contract']}
    pattern = re.compile(r'^Frame (\d+) at ([0-9.eE+-]+) seconds$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    ids, elapsed = [], []
    for match in matches:
        ids.append(int(match.group(1)))
        try:
            elapsed.append(float(match.group(2)))
        except ValueError:
            fail('recorder_elapsed')
    if len(matches) != expected_frames:
        fail('recorder_frame_count')
    if ids != list(range(1, expected_frames + 1)):
        fail('recorder_frame_ids')
    if len(elapsed) == expected_frames and any(
            not np.isclose(value, i * DT, atol=1e-4) for i, value in enumerate(elapsed)):
        fail('recorder_elapsed')
    blocks = [text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
              for i, match in enumerate(matches)]
    if not blocks or re.search(r'^ Create %d: vehicle\.lincoln\.mkz_2017 \(\d+\) at '\
            % ego_id, blocks[0], re.MULTILINE) is None:
        fail('recorder_ego_create')
    if not blocks or re.search(r'^ Create %d: sensor\.other\.collision \(\d+\) at '\
            % sensor_id, blocks[0], re.MULTILINE) is None:
        fail('recorder_sensor_create')
    position_counts = []
    for block_text in blocks:
        position_ids, in_positions, saw_positions = set(), False, False
        for line in block_text.splitlines():
            if re.fullmatch(r' Positions: \d+', line):
                saw_positions, in_positions = True, True
                continue
            match = re.match(r'^  Id: (\d+) Location: ', line) if in_positions else None
            if match:
                position_ids.add(int(match.group(1)))
            elif in_positions and not line.startswith('  '):
                in_positions = False
        position_counts.append(len(position_ids))
        if not saw_positions:
            fail('recorder_positions')
        if ego_id not in position_ids:
            fail('recorder_ego_position')
    collisions = re.findall(r'^\s*Collision id\b.*$', text, re.MULTILINE)
    if collisions:
        fail('recorder_collision')
    footer_frames = re.search(r'^Frames: (\d+)$', text, re.MULTILINE)
    footer_duration = re.search(r'^Duration: ([0-9.eE+-]+) seconds$', text, re.MULTILINE)
    if footer_frames is None or int(footer_frames.group(1)) != expected_frames:
        fail('recorder_footer_frames')
    expected_duration = (expected_frames - 1) * DT
    try:
        duration = float(footer_duration.group(1)) if footer_duration else None
    except ValueError:
        duration = None
    if duration is None or not np.isclose(duration, expected_duration, atol=1e-4):
        fail('recorder_footer_duration')
    return dict(complete=not failures, expected_frames=expected_frames, actual_frames=len(matches),
        frame_ids=ids, elapsed_seconds=elapsed, footer_frames=(int(footer_frames.group(1)) if footer_frames else None),
        footer_duration_seconds=duration, position_counts=position_counts,
        collision_count=len(collisions), failures=failures)

def _read_json(path):
    return json.loads(Path(path).read_text())



def control_echo_matches(requested, readback):
    """Transport equality in CARLA float32 fields; auto gear is simulator-owned."""
    try:
        a=np.array([requested[k] for k in ('throttle','brake','steer')],dtype=np.float32)
        b=np.array([readback[k] for k in ('throttle','brake','steer')],dtype=np.float32)
        return bool(np.isfinite(a).all() and np.isfinite(b).all() and np.array_equal(a,b)
            and all(requested[k]==readback[k] for k in ('hand_brake','reverse','manual_gear_shift'))
            and (not requested['manual_gear_shift'] or requested['gear']==readback['gear']))
    except (KeyError,TypeError,ValueError,OverflowError):return False


def audit_control_delivery(frames, submissions, *, actor_id=None):
    """Validate acknowledged commands against the next physical-frame readback."""
    failures=[];observed=0
    def fail(name):
        if name not in failures:failures.append(name)
    selected=[a for a in submissions if a.get('stage')=='tracking']
    embedded=[r.get('command_submission') for r in frames if r.get('control') is not None]
    if selected!=embedded:fail('submission_journal_mismatch')
    for i,row in enumerate(frames):
        if row.get('control') is None:continue
        try:
            ack=row['command_submission']
            if (ack['version']!='toolv2x_control_submission_v1' or ack['accepted'] is not True
                    or ack['error'] is not None or ack['do_tick_cue'] is not False
                    or ack['source_frame']!=row['frame'] or ack['expected_next_frame']!=row['frame']+1
                    or ack['stage']!='tracking' or ack['request']!=row['control']
                    or (actor_id is not None and ack['actor_id']!=actor_id)):
                fail('command_ack_contract')
            following=frames[i+1]
            if (type(row['frame']) is not int or type(following['frame']) is not int
                    or following['frame']!=row['frame']+1
                    or not np.isfinite([row['timestamp'],following['timestamp']]).all()
                    or abs(following['timestamp']-row['timestamp']-DT)>1e-6):
                fail('command_tick_binding')
            if not control_echo_matches(row['control'],following['last_control']):fail('control_echo_mismatch')
            observed+=1
        except (KeyError,IndexError,TypeError,ValueError):fail('command_delivery_incomplete')
    if not embedded:fail('no_tracking_commands')
    return dict(version='toolv2x_control_delivery_audit_v1',passed=not failures,failures=failures,
                observed_transitions=observed,attempted_commands=len(embedded))


def audit_case_dir(case_dir):
    """Fail-closed independent replay of one runner output directory."""
    case_dir = Path(case_dir).resolve()
    name, references = case_dir.name, case_dir.parent / 'references'
    required = [case_dir / 'frames.jsonl', case_dir / 'collision_events.json', case_dir / 'recorder_info.txt',
                references / (name + '.json'), references / (name + '_corridor.json')]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        return {'status': 'FAIL', 'passed': False, 'failures': ['missing_audit_input'],
                'metrics': {'missing_paths': missing}}
    bundle, collision = _read_json(required[3]), _read_json(required[1])
    frames = [json.loads(line) for line in required[0].read_text().splitlines() if line.strip()]
    collision_fields = {'all_events', 'driving_events', 'initial_frame', 'recorder'}
    recorder_fields = {'expected_frames', 'actual_ticks', 'ego_id', 'sensor_id', 'initial_timestamp',
                       'complete', 'collision_count', 'failures'}
    if (not isinstance(collision, dict) or not collision_fields <= set(collision) or
            not isinstance(collision['recorder'], dict) or not recorder_fields <= set(collision['recorder'])):
        return {'status': 'FAIL', 'passed': False, 'failures': ['collision_sidecar_contract'], 'metrics': {}}
    if collision['driving_events'] and frames:
        frames[-1]['collision_events'] = collision['driving_events']
    result = audit_trial(bundle['case_spec'], bundle['rows'], frames, shape(_read_json(required[4])))
    recorder = collision['recorder']
    expected = round(float(bundle['case_spec']['duration']) / DT)
    parsed = parse_recorder_info(required[2].read_text(), expected, recorder['ego_id'], recorder['sensor_id'])
    result['metrics']['recorder'] = parsed
    sidecar_mismatch = (recorder['expected_frames'] != expected or recorder['actual_ticks'] != expected or
        recorder['complete'] != parsed['complete'] or recorder['collision_count'] != parsed['collision_count'] or
        list(recorder['failures']) != parsed['failures'])
    additions = list(parsed['failures'])
    if parsed['collision_count']:
        additions.append('collision')
    if not parsed['complete']:
        additions.append('recorder_incomplete')
    if not frames or not isinstance(frames[0].get('last_control'), dict) or 'steer' not in frames[0]['last_control']:
        additions.append('steer_slew_reference_missing')
    if sidecar_mismatch:
        additions.append('recorder_sidecar_mismatch')
    if collision['driving_events']:
        additions.append('collision')
    run_spec=case_dir.parent/'spec.json'
    metadata=_read_json(run_spec) if run_spec.is_file() else {}
    journal=case_dir/'command_submissions.jsonl'
    modern=(journal.exists() or any('command_submission' in row for row in frames)
            or metadata.get('version')=='toolv2x_backbone_tracking_gate_v3'
            or 'command_submission_version' in metadata)
    if modern:
        if (metadata.get('version')!='toolv2x_backbone_tracking_gate_v3'
                or metadata.get('command_submission_version')!='toolv2x_control_submission_v1'):
            additions.append('command_submission_metadata')
        if not journal.is_file():additions.append('submission_journal_missing')
        else:
            delivery=audit_control_delivery(frames,[json.loads(line) for line in journal.read_text().splitlines()],actor_id=recorder['ego_id'])
            result['metrics']['command_delivery']=delivery
            additions.extend(delivery['failures'])
    result['failures'] = list(dict.fromkeys(result['failures'] + additions))
    result['passed'] = not result['failures']
    result['status'] = 'PASS' if result['passed'] else 'FAIL'
    return result


def audit_initialization(records, geometry, *, complete=True):
    """Recompute the fixed v2 startup contract from requests AND actual readbacks."""
    failures=[];motion=None
    def fail(reason):
        if reason not in failures:failures.append(reason)
    try:
        if not 1<=len(records)<=30 or (complete and len(records)!=30):fail('initialization_count')
        offset=np.asarray(geometry['rear_offset_lh'],dtype=float)
        if offset.shape!=(3,) or not np.isfinite(offset).all():raise ValueError('rear calibration')
        phases=['settle']*20+['engage_drive']+['verify_automatic']*9
        positions=[];heights=[]
        for i,row in enumerate(records):
            if i>=30:break
            if row['phase']!=phases[i]:fail('initialization_phase')
            if row['frame']!=records[0]['frame']+i:fail('initialization_frame')
            if not np.isfinite(row['timestamp']) or abs(row['timestamp']-records[0]['timestamp']-i*DT)>1e-6:fail('initialization_time')
            requested=row['requested_control'];readback=row['readback_control']
            expected=dict(throttle=0.,brake=1.,steer=0.,hand_brake=False,reverse=False,
                          manual_gear_shift=i==20,gear=1 if i==20 else 0)
            for key,value in expected.items():
                if requested[key]!=value:fail('requested_control')
                if key!='gear' and readback[key]!=value:fail('readback_control')
            if readback['gear']!=row['raw']['gear']:fail('gear_readback_mismatch')
            if i>=20 and readback['gear']!=1:fail('gear_not_one')
            pose=np.asarray(row['raw']['pose_lh'],dtype=float)
            velocity=np.asarray(row['raw']['velocity_lh_mps'],dtype=float)
            wheels=np.asarray(row['wheel_steer_rad'],dtype=float)
            if (pose.shape!=(4,4) or velocity.shape!=(3,) or wheels.shape!=(2,)
                    or not all(np.isfinite(v).all() for v in (pose,velocity,wheels))):
                raise ValueError('nonfinite or malformed state')
            point=pose[:3,3]+pose[:3,:3]@offset
            positions.append(point[:2]);heights.append(pose[2,3])
            if i>=20 and np.linalg.norm(velocity)>.05:fail('not_stationary')
        if len(positions)>=20:
            xy=np.asarray(positions[19:]);maximum=float(np.linalg.norm(xy-xy[0],axis=1).max())
            motion=dict(net=float(np.linalg.norm(xy[-1]-xy[0])),max_from_start=maximum,
                        cumulative=float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum()),passed=maximum<=.02)
            if maximum>.02:fail('preload_moved')
        if complete and len(records)==30:
            if max(heights[-5:])-min(heights[-5:])>.01:fail('vertical_settling_incomplete')
            if np.linalg.norm(positions[-1]-np.array([50.,0.]))>.02 or abs(math.atan2(pose[1,0],pose[0,0]))>.005:fail('wrong_initial_pose')
            if np.max(np.abs(wheels))>.01:fail('nonzero_initial_steering')
    except (KeyError,IndexError,TypeError,ValueError,OverflowError):fail('initialization_input_contract')
    passed=complete and len(records)==30 and not failures
    status='INITIALIZATION_PASS' if passed else ('INITIALIZATION_FAIL' if failures else 'INITIALIZATION_IN_PROGRESS')
    return dict(version='toolv2x_backbone_initialization_v2',status=status,passed=passed,
                failures=failures,record_count=len(records),preload_motion=motion)


def audit_initialization_dir(case_dir):
    case_dir=Path(case_dir)
    result=audit_initialization(_read_json(case_dir/'initialization.json'),
                                _read_json(case_dir.parent/'vehicle_geometry.json')['parsed'])
    saved=_read_json(case_dir/'initialization_check.json')
    if result!=saved:
        result['failures'].append('initialization_saved_result_mismatch')
        result['passed']=False;result['status']='INITIALIZATION_FAIL'
    (case_dir/'independent_initialization_audit.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def audit_batch(output_dir):
    """Re-read all frozen artifacts; this is the only final PASS authority."""
    root = Path(output_dir).resolve()
    failures, cases = [], {}
    def fail(name):
        if name not in failures:
            failures.append(name)
    required = [root / 'summary.json', root / 'reference_checks.json', root / 'vehicle_geometry.json']
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        result = dict(version='toolv2x_tracking_independent_audit_v1', status='FAIL', passed=False,
                      failures=['missing_batch_input'], cases={}, metrics={'missing_paths': missing})
        root.mkdir(parents=True, exist_ok=True)
        (root / 'independent_audit.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        return result
    try:
        summary, reference_checks, geometry = map(_read_json, required)
        if summary.get('status') != 'TRACKING_COMPLETE_PENDING_AUDIT': fail('run_summary_status')
        if summary.get('physical_trials_started') != len(CASE_NAMES): fail('physical_trial_count')
        if summary.get('completed_cases') != list(CASE_NAMES): fail('completed_case_manifest')
        if set(reference_checks) != set(CASE_NAMES) or not all(
                isinstance(reference_checks[name], dict) and reference_checks[name].get('passed') is True
                for name in CASE_NAMES): fail('reference_preflight')
        if not isinstance(geometry, dict) or geometry.get('failures') != []: fail('vehicle_geometry_preflight')
        outcomes = summary.get('outcomes')
        if not isinstance(outcomes, list) or [row.get('case') for row in outcomes] != list(CASE_NAMES):
            fail('summary_outcomes')
            outcomes = []
        outcome_index = {row['case']: row for row in outcomes}
        for name in CASE_NAMES:
            case_dir = root / name
            init_path, raw_init_path, saved_path = (case_dir / 'initialization_check.json',
                case_dir / 'initialization.json', case_dir / 'audit.json')
            reference_path = root / 'references' / (name + '.json')
            if not init_path.is_file() or not raw_init_path.is_file() or not saved_path.is_file() or not reference_path.is_file():
                cases[name] = dict(status='FAIL', passed=False, failures=['missing_audit_input'], metrics={})
                fail('case_' + name); continue
            initialization, raw_initialization = _read_json(init_path), _read_json(raw_init_path)
            if initialization.get('passed') is not True or initialization.get('failures') != []:
                fail('initialization_' + name)
            if initialization.get('version')=='toolv2x_backbone_initialization_v2':
                recomputed=audit_initialization(raw_initialization,geometry['parsed'])
                if not recomputed['passed'] or recomputed!=initialization:
                    fail('initialization_recompute_'+name)
            else:
                try:
                    offset = np.asarray(geometry['parsed']['rear_offset_lh'], dtype=float)
                    if len(raw_initialization) != 30 or [row.get('phase') for row in raw_initialization] != ['settle'] * 20 + ['preload'] * 10:
                        raise ValueError('initialization phase/count mismatch')
                    positions = []
                    for row in raw_initialization[19:]:
                        pose = np.asarray(row['raw']['pose_lh'], dtype=float)
                        if pose.shape != (4, 4) or not np.isfinite(pose).all():
                            raise ValueError('invalid initialization pose')
                        point = pose[:3, 3] + pose[:3, :3] @ offset
                        positions.append(point[:2])
                    positions = np.asarray(positions)
                    measured = dict(net=float(np.linalg.norm(positions[-1] - positions[0])),
                        max_from_start=float(np.linalg.norm(positions - positions[0], axis=1).max()),
                        cumulative=float(np.linalg.norm(np.diff(positions, axis=0), axis=1).sum()))
                    measured['passed'] = measured['max_from_start'] <= .02 + 1e-12
                    claimed = initialization.get('preload_motion')
                    if (not isinstance(claimed, dict) or set(claimed) != set(measured) or
                            any(not np.isclose(claimed[key], measured[key], atol=1e-12) for key in ('net', 'max_from_start', 'cumulative')) or
                            claimed['passed'] is not measured['passed'] or not measured['passed']):
                        fail('initialization_recompute_' + name)
                except (KeyError, TypeError, ValueError):
                    fail('initialization_recompute_' + name)
            bundle = _read_json(reference_path)
            if bundle.get('case_spec') != _frozen_case_spec(name):
                fail('case_spec_' + name)
            recomputed, saved = audit_case_dir(case_dir), _read_json(saved_path)
            cases[name] = recomputed
            if recomputed != saved:
                fail('saved_audit_mismatch_' + name)
            summary_row = outcome_index.get(name)
            if summary_row is not None and {k: v for k, v in summary_row.items() if k != 'case'} != saved:
                fail('summary_audit_mismatch_' + name)
            if not recomputed['passed']:
                fail('case_' + name)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
        fail('batch_input_contract')
        input_error = '%s: %s' % (type(exc).__name__, exc)
    else:
        input_error = None
    passed = not failures
    result = dict(version='toolv2x_tracking_independent_audit_v1', status='PASS' if passed else 'FAIL',
                  passed=passed, failures=failures, cases=cases,
                  metrics=dict(expected_cases=len(CASE_NAMES), audited_cases=len(cases), input_error=input_error))
    (root / 'independent_audit.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--case-dir')
    source.add_argument('--batch')
    source.add_argument('--initialization-dir')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = (audit_initialization_dir(args.initialization_dir) if args.initialization_dir else
              audit_batch(args.batch) if args.batch else audit_case_dir(args.case_dir))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result, allow_nan=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
