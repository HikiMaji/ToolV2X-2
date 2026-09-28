"""Independent checks for the frozen low-speed tracking gate."""
import math
import json
import tempfile
import sys
from pathlib import Path
import unittest

import numpy as np
from shapely.geometry import Polygon, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def case(duration=2., **updates):
    value = dict(name='fixture', V=2., duration=duration,
        segments=[dict(kind='C', start=0., end=duration, v0=2., v1=2., turn=0)],
        stops=[], accels=[], turn_end=None)
    value.update(updates)
    return value


def straight_reference(duration=2., speed=2.):
    return [dict(t=round(i * .1, 10), x=speed * i * .1, y=0., yaw=0., v=speed,
        a=0., jerk=0., kappa=0., kappa_rate=0.)
        for i in range(round((duration + .4) / .1) + 1)]


def body(x, y):
    return [[x - .5, y - .25], [x + .5, y - .25],
            [x + .5, y + .25], [x - .5, y + .25]]


def frames_from_reference(reference, duration):
    count = round(duration / .1) + 1
    rows = []
    for i, ref in enumerate(reference[:count]):
        velocity = [ref['v'] * math.cos(ref['yaw']), ref['v'] * math.sin(ref['yaw']), 0.]
        rows.append(dict(i=i, frame=100 + i, timestamp=20. + ref['t'], t=ref['t'],
            actor_xy=[ref['x'], ref['y']], rear_xy=[ref['x'], ref['y']], yaw=ref['yaw'],
            last_control=dict(throttle=0., brake=0., steer=0.),
            actor_velocity=velocity, angular_velocity=[0., 0., ref['v'] * ref['kappa']],
            body_polygon_xy=body(ref['x'], ref['y']), wheel_steer_rad=[0., 0.], gear=1,
            control=None if i == count - 1 else dict(throttle=.1, brake=0., steer=0.,
                hand_brake=False, reverse=False, manual_gear_shift=False), collision_events=[]))
    return rows


CORRIDOR = Polygon([(-10., -10.), (100., -10.), (100., 100.), (-10., 100.)])


def checks(result):
    return set(result['failures'])


class TrackingGateTests(unittest.TestCase):
    def test_exact_straight_trial_passes(self):
        from evaluation.tracking_gate import audit_trial
        spec = case()
        reference = straight_reference()
        result = audit_trial(spec, reference, frames_from_reference(reference, 2.), CORRIDOR)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['passed'])
        self.assertEqual(result['failures'], [])
        self.assertAlmostEqual(result['metrics']['max_abs_e_long_m'], 0.)

    def test_delayed_start_is_not_time_shifted_to_pass(self):
        from evaluation.tracking_gate import audit_trial
        spec = case(accels=[dict(start=0., end=2., v0=0., v1=2.)])
        reference = straight_reference()
        frames = frames_from_reference(reference, 2.)
        for row in frames:
            x = max(0., 2. * (row['t'] - 1.5))
            row['rear_xy'] = row['actor_xy'] = [x, 0.]
            row['body_polygon_xy'] = body(x, 0.)
        result = audit_trial(spec, reference, frames, CORRIDOR)
        self.assertIn('start_midpoint_speed', checks(result))

    def test_stop_uses_accumulated_path_not_net_displacement(self):
        from evaluation.tracking_gate import audit_trial
        spec = case(3., segments=[dict(kind='H', start=0., end=3., v0=0., v1=0., turn=0)],
                    stops=[dict(start=0., end=3.)])
        reference = straight_reference(3., 0.)
        frames = frames_from_reference(reference, 3.)
        for row in frames:
            x = .02 if row['i'] >= 10 and row['i'] % 2 else 0.
            row['rear_xy'] = row['actor_xy'] = [x, 0.]
            row['body_polygon_xy'] = body(x, 0.)
            row['actor_velocity'] = [0., 0., 0.]
        result = audit_trial(spec, reference, frames, CORRIDOR)
        self.assertIn('stop_path', checks(result))
        self.assertAlmostEqual(result['metrics']['stops'][0]['net_displacement_m'], 0.)
        self.assertGreater(result['metrics']['stops'][0]['path_m'], .1)

    def test_terminal_sample_is_evaluated_and_has_no_control(self):
        from evaluation.tracking_gate import audit_trial
        spec = case()
        reference = straight_reference()
        frames = frames_from_reference(reference, 2.)
        frames[-1]['rear_xy'][1] = frames[-1]['actor_xy'][1] = .5
        frames[-1]['body_polygon_xy'] = body(frames[-1]['rear_xy'][0], .5)
        result = audit_trial(spec, reference, frames, CORRIDOR)
        self.assertIn('lateral_max', checks(result))
        frames = frames_from_reference(reference, 2.)
        frames[-1]['control'] = dict(throttle=0., brake=0., steer=0.)
        self.assertIn('terminal_control', checks(audit_trial(spec, reference, frames, CORRIDOR)))

    def test_turn_native_velocity_point_mismatch_fails(self):
        from evaluation.tracking_gate import audit_trial
        duration, radius, speed = 8., 20., 2.
        reference = []
        for i in range(round((duration + .4) / .1) + 1):
            t, yaw = i * .1, i * .1
            reference.append(dict(t=t, x=radius * math.sin(yaw), y=radius * (1 - math.cos(yaw)),
                yaw=yaw, v=speed, a=0., jerk=0., kappa=.05 if t <= duration else 0., kappa_rate=0.))
        spec = case(duration, segments=[dict(kind='K', start=0., end=duration,
            v0=speed, v1=speed, turn=1)], turn_end=duration)
        frames = frames_from_reference(reference, duration)
        for row in frames:
            row['actor_velocity'][0] += .2
        result = audit_trial(spec, reference, frames, CORRIDOR)
        self.assertIn('native_velocity_vector', checks(result))

    def test_wrong_time_and_missing_terminal_sample_fail_closed(self):
        from evaluation.tracking_gate import audit_trial
        spec = case()
        reference = straight_reference()
        frames = frames_from_reference(reference, 2.)
        frames[5]['t'] += .1
        self.assertIn('time_alignment', checks(audit_trial(spec, reference, frames, CORRIDOR)))
        self.assertIn('sample_count', checks(audit_trial(spec, reference, frames[:-1], CORRIDOR)))




    def test_lateral_speed_and_steer_slew_cannot_hide_in_forward_speed(self):
        from evaluation.tracking_gate import audit_trial
        spec = case(.2, segments=[dict(kind='H', start=0., end=.2, v0=0., v1=0., turn=0)])
        reference = straight_reference(.2, 0.)
        frames = frames_from_reference(reference, .2)
        for row, y in zip(frames, [0., .25, 0.]):
            row['rear_xy'] = row['actor_xy'] = [0., y]
            row['body_polygon_xy'] = body(0., y)
        self.assertIn('max_speed', checks(audit_trial(spec, reference, frames, CORRIDOR)))
        spec = case(); reference = straight_reference(); frames = frames_from_reference(reference, 2.)
        frames[1]['control']['steer'] = .2
        self.assertIn('steer_slew', checks(audit_trial(spec, reference, frames, CORRIDOR)))

    def test_recorder_parser_rejects_truncated_positions_and_collision(self):
        from evaluation.tracking_gate import parse_recorder_info
        def recorder(last_position=True, collision=False):
            frames = []
            for i in range(1, 4):
                create = (' Create 10: vehicle.lincoln.mkz_2017 (1) at (0, 0, 0)\n'
                          ' Create 20: sensor.other.collision (0) at (0, 0, 0)\n') if i == 1 else ''
                positions = '  Id: 10 Location: (0, 0, 0) Rotation: (0, 0, 0)\n' if i < 3 or last_position else ''
                positions += '  Id: 20 Location: (0, 0, 0) Rotation: (0, 0, 0)\n'
                hit = ' Collision id 1 between 10 with 99\n' if collision and i == 2 else ''
                frames.append('Frame %d at %.1f seconds\n%s%s Positions: 2\n%s' %
                              (i, (i - 1) * .1, create, hit, positions))
            return 'Version: 1\nMap: pad\nDate: now\n\n' + ''.join(frames) + '\nFrames: 3\nDuration: 0.2 seconds\n'
        valid = parse_recorder_info(recorder(), 3, 10, 20)
        self.assertTrue(valid['complete'])
        self.assertEqual(valid['collision_count'], 0)
        truncated = parse_recorder_info(recorder(last_position=False), 3, 10, 20)
        self.assertFalse(truncated['complete'])
        self.assertIn('recorder_ego_position', truncated['failures'])
        collided = parse_recorder_info(recorder(collision=True), 3, 10, 20)
        self.assertFalse(collided['complete'])
        self.assertEqual(collided['collision_count'], 1)

    def test_case_directory_requires_raw_recorder_info(self):
        from evaluation.tracking_gate import audit_case_dir
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); refs = root / 'references'; run = root / 'fixture'
            refs.mkdir(); run.mkdir()
            spec = case(); reference = straight_reference(); frames = frames_from_reference(reference, 2.)
            (refs / 'fixture.json').write_text(json.dumps(dict(case_spec=spec, rows=reference)))
            (refs / 'fixture_corridor.json').write_text(json.dumps(mapping(CORRIDOR)))
            (run / 'frames.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in frames))
            (run / 'collision_events.json').write_text(json.dumps(dict(all_events=[], driving_events=[],
                initial_frame=100, recorder=dict(expected_frames=20, actual_ticks=20, ego_id=10,
                    sensor_id=20, initial_timestamp=20., complete=True, collision_count=0, failures=[]))))
            result = audit_case_dir(run)
            self.assertFalse(result['passed'])
            self.assertIn('missing_audit_input', result['failures'])



    def test_batch_pass_requires_complete_eight_case_replay(self):
        from planning.tracking_reference import CASES, case_spec, corridor, generate_reference
        from evaluation.tracking_gate import audit_batch, audit_case_dir
        def recorder_text(count, ego=10, sensor=20):
            blocks = []
            for i in range(1, count + 1):
                create = (' Create %d: vehicle.lincoln.mkz_2017 (1) at (0, 0, 0)\n'
                          ' Create %d: sensor.other.collision (0) at (0, 0, 0)\n' % (ego, sensor)) if i == 1 else ''
                blocks.append('Frame %d at %.1f seconds\n%s Positions: 2\n'
                    '  Id: %d Location: (0, 0, 0) Rotation: (0, 0, 0)\n'
                    '  Id: %d Location: (0, 0, 0) Rotation: (0, 0, 0)\n' %
                    (i, (i - 1) * .1, create, ego, sensor))
            return 'Version: 1\nMap: pad\nDate: now\n\n' + ''.join(blocks) + ('\nFrames: %d\nDuration: %.1f seconds\n' % (count, (count - 1) * .1))

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); refs = root / 'references'; refs.mkdir()
            checks_by_case, outcomes = {}, []
            (root / 'vehicle_geometry.json').write_text(json.dumps(dict(failures=[], parsed=dict(rear_offset_lh=[0., 0., 0.]))))
            for name in CASES:
                spec = case_spec(name); reference = generate_reference(name); n = round(spec['duration'] / .1)
                xy = np.array([[row['x'], row['y']] for row in reference[:n + 1]])
                velocity = np.gradient(xy, .1, axis=0, edge_order=2)
                rows = []
                for i, row in enumerate(reference[:n + 1]):
                    x, y = row['x'], row['y']
                    rows.append(dict(i=i, frame=100 + i, timestamp=20. + i * .1, t=i * .1,
                        actor_xy=[x, y], rear_xy=[x, y], yaw=row['yaw'], last_control=dict(steer=0.),
                        actor_velocity=[*velocity[i], 0.], angular_velocity=[0., 0., row['v'] * row['kappa']],
                        body_polygon_xy=body(x, y), wheel_steer_rad=[0., 0.], gear=1,
                        control=None if i == n else dict(throttle=0., brake=0., steer=0.),
                        collision_events=[]))
                (refs / (name + '.json')).write_text(json.dumps(dict(case_spec=spec, rows=reference)))
                (refs / (name + '_corridor.json')).write_text(json.dumps(mapping(corridor(reference))))
                case_dir = root / name; case_dir.mkdir()
                (case_dir / 'frames.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
                parsed = dict(expected_frames=n, actual_ticks=n, ego_id=10, sensor_id=20,
                    initial_timestamp=20., complete=True, collision_count=0, failures=[])
                (case_dir / 'collision_events.json').write_text(json.dumps(dict(all_events=[], driving_events=[],
                    initial_frame=100, recorder=parsed)))
                (case_dir / 'recorder_info.txt').write_text(recorder_text(n))
                pose = np.eye(4).tolist()
                initialization = [dict(phase='settle' if i < 20 else 'preload', frame=i,
                    raw=dict(pose_lh=pose)) for i in range(30)]
                (case_dir / 'initialization.json').write_text(json.dumps(initialization))
                preload = dict(net=0., max_from_start=0., cumulative=0., passed=True)
                (case_dir / 'initialization_check.json').write_text(json.dumps(dict(
                    passed=True, failures=[], preload_motion=preload, state=rows[0])))
                audit = audit_case_dir(case_dir)
                self.assertTrue(audit['passed'], (name, audit['failures']))
                (case_dir / 'audit.json').write_text(json.dumps(audit))
                outcomes.append(dict(case=name, **audit)); checks_by_case[name] = dict(passed=True)
            (root / 'reference_checks.json').write_text(json.dumps(checks_by_case))
            summary = dict(status='TRACKING_COMPLETE_PENDING_AUDIT', physical_trials_started=8,
                completed_cases=list(CASES), outcomes=outcomes)
            (root / 'summary.json').write_text(json.dumps(summary))
            result = audit_batch(root)
            self.assertTrue(result['passed'], result['failures'])
            self.assertTrue((root / 'independent_audit.json').is_file())
            init_path = root / 'S2' / 'initialization.json'; original = init_path.read_text(); _json = json.loads(original)
            _json[-1]['raw']['pose_lh'][0][3] = .03; init_path.write_text(json.dumps(_json))
            self.assertIn('initialization_recompute_S2', audit_batch(root)['failures'])
            init_path.write_text(original)
            frame_path = root / 'S2' / 'frames.jsonl'; original_frames = frame_path.read_text()
            frame_rows = [json.loads(line) for line in original_frames.splitlines()]
            frame_rows[0].pop('last_control'); frame_path.write_text(''.join(json.dumps(row) + '\n' for row in frame_rows))
            self.assertIn('steer_slew_reference_missing', audit_batch(root)['cases']['S2']['failures'])
            frame_path.write_text(original_frames)
            summary['status'] = 'FAIL'; (root / 'summary.json').write_text(json.dumps(summary))
            failed = audit_batch(root)
            self.assertFalse(failed['passed'])
            self.assertIn('run_summary_status', failed['failures'])

            # The same complete fixture must also be independently auditable with v2 startup.
            from evaluation.tracking_gate import audit_initialization
            summary['status']='TRACKING_COMPLETE_PENDING_AUDIT'
            (root/'summary.json').write_text(json.dumps(summary))
            for name in CASES:
                initialization,g=initialization_fixture()
                for row in initialization:row['raw']['pose_lh'][0][3]=50.
                check=audit_initialization(initialization,{'rear_offset_lh':[0.,0.,0.]})
                self.assertTrue(check['passed'])
                (root/name/'initialization.json').write_text(json.dumps(initialization))
                (root/name/'initialization_check.json').write_text(json.dumps(check))
            self.assertTrue(audit_batch(root)['passed'])
            # Keep the saved PASS intact while corrupting an actual automatic-gear readback.
            init_path=root/'S2/initialization.json';bad=json.loads(init_path.read_text())
            bad[25]['readback_control']['gear']=0;init_path.write_text(json.dumps(bad))
            self.assertIn('initialization_recompute_S2',audit_batch(root)['failures'])

            # Modern transport evidence must never silently fall back to legacy auditing.
            self.assertTrue(audit_case_dir(root/'S2')['passed'])
            journal=root/'S2/command_submissions.jsonl';manifest=root/'spec.json'
            for evidence in ['journal','embedded','v3','unknown']:
                frame_path.write_text(original_frames)
                if journal.exists():journal.unlink()
                if manifest.exists():manifest.unlink()
                if evidence=='journal':journal.write_text('')
                elif evidence=='embedded':
                    modern=[json.loads(line) for line in original_frames.splitlines()]
                    modern[0]['command_submission']={'accepted':False}
                    frame_path.write_text(''.join(json.dumps(row)+'\n' for row in modern))
                elif evidence=='v3':manifest.write_text(json.dumps({'version':'toolv2x_backbone_tracking_gate_v3'}))
                else:manifest.write_text(json.dumps({'command_submission_version':'unknown'}))
                self.assertFalse(audit_case_dir(root/'S2')['passed'],evidence)


def initialization_fixture():
    import copy
    geometry={'rear_offset_lh':[-1.4,0.,.3]}
    rows=[]
    for i in range(30):
        phase='settle' if i<20 else ('engage_drive' if i==20 else 'verify_automatic')
        command=dict(throttle=0.,brake=1.,steer=0.,reverse=False,hand_brake=False,
                     manual_gear_shift=i==20,gear=1 if i==20 else 0)
        actual=dict(command,gear=0 if i<20 else 1)
        pose=np.eye(4);pose[:3,3]=[51.4,0.,.03]
        rows.append(dict(phase=phase,frame=100+i,timestamp=10.+i*.1,
            requested_control=command,readback_control=actual,wheel_steer_rad=[0.,0.],
            raw=dict(pose_lh=pose.tolist(),velocity_lh_mps=[0.,0.,0.],gear=actual['gear'])))
    return rows,geometry


class InitializationV2Tests(unittest.TestCase):
    def test_complete_initialization_requires_actual_gear_and_auto_handover(self):
        from evaluation.tracking_gate import audit_initialization
        rows,g=initialization_fixture()
        result=audit_initialization(rows,g)
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['status'],'INITIALIZATION_PASS')
        self.assertEqual(result['version'],'toolv2x_backbone_initialization_v2')

    def test_wrong_readback_does_not_pass_with_correct_request(self):
        import copy
        from evaluation.tracking_gate import audit_initialization
        for index,field,value in [(20,'gear',0),(23,'gear',0),(29,'manual_gear_shift',True),(25,'brake',0.)]:
            rows,g=initialization_fixture();rows[index]['readback_control'][field]=value
            self.assertFalse(audit_initialization(rows,g)['passed'],(index,field))

    def test_time_phase_and_partial_records_cannot_pass(self):
        from evaluation.tracking_gate import audit_initialization
        for change in ['partial','frame','timestamp','phase','command']:
            rows,g=initialization_fixture()
            if change=='partial':rows=rows[:21]
            elif change=='frame':rows[22]['frame']+=1
            elif change=='timestamp':rows[22]['timestamp']+=.1
            elif change=='phase':rows[22]['phase']='engage_drive'
            else:rows[20]['requested_control']['manual_gear_shift']=False
            self.assertFalse(audit_initialization(rows,g)['passed'],change)
        rows,g=initialization_fixture()
        self.assertEqual(audit_initialization(rows[:21],g,complete=False)['status'],'INITIALIZATION_IN_PROGRESS')

    def test_motion_and_final_pose_must_be_recomputed(self):
        from evaluation.tracking_gate import audit_initialization
        for change in ['excursion','speed','final_pose','wheel','vertical','nonfinite']:
            rows,g=initialization_fixture()
            if change=='excursion':rows[22]['raw']['pose_lh'][0][3]+=.03
            elif change=='speed':rows[22]['raw']['velocity_lh_mps'][1]=.06
            elif change=='final_pose':
                for row in rows:row['raw']['pose_lh'][0][3]+=.03
            elif change=='wheel':rows[-1]['wheel_steer_rad'][0]=.02
            elif change=='vertical':rows[-2]['raw']['pose_lh'][2][3]+=.02
            else:rows[-1]['raw']['velocity_lh_mps'][0]=float('nan')
            self.assertFalse(audit_initialization(rows,g)['passed'],change)

class CommandDeliveryTests(unittest.TestCase):
    @staticmethod
    def fixture():
        command=dict(throttle=.3,brake=0.,steer=.1,hand_brake=False,reverse=False,manual_gear_shift=False,gear=0)
        echo=dict(command,throttle=float(np.float32(.3)),steer=float(np.float32(.1)),gear=1)
        ack=dict(version='toolv2x_control_submission_v1',stage='tracking',actor_id=7,source_frame=10,
                 expected_next_frame=11,accepted=True,error=None,do_tick_cue=False,request=command)
        rows=[dict(frame=10,timestamp=1.,control=command,command_submission=ack),
              dict(frame=11,timestamp=1.1,control=None,last_control=echo)]
        return rows,[ack]

    def test_echo_compares_float32_and_does_not_require_auto_requested_gear(self):
        from evaluation.tracking_gate import audit_control_delivery,control_echo_matches
        rows,acks=self.fixture()
        self.assertTrue(control_echo_matches(rows[0]['control'],rows[1]['last_control']))
        result=audit_control_delivery(rows,acks)
        self.assertTrue(result['passed'],result)
        self.assertEqual(result['observed_transitions'],1)

    def test_old_control_missing_ack_or_extra_tick_cannot_pass(self):
        from evaluation.tracking_gate import audit_control_delivery
        for kind in ['stale','frame','error','missing','journal','request','actor','nan']:
            rows,acks=self.fixture()
            if kind=='stale':rows[1]['last_control']['throttle']=.1
            elif kind=='frame':rows[1]['frame']=12
            elif kind=='error':rows[0]['command_submission']['accepted']=False
            elif kind=='missing':rows[0].pop('command_submission')
            elif kind=='journal':acks=[]
            elif kind=='actor':rows[0]['command_submission']['actor_id']=8
            elif kind=='nan':rows[1]['timestamp']=float('nan')
            else:rows[0]['control']=dict(rows[0]['control'],throttle=.7)
            self.assertFalse(audit_control_delivery(rows,acks,actor_id=7)['passed'],kind)

if __name__ == '__main__':
    unittest.main()
