"""Physical interface contracts; no simulator or model is started."""
import importlib.util
import math
import sys
import unittest
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import probe_backbone_tracking as runtime
except ModuleNotFoundError:
    runtime = None


class TrackingRuntimeContractTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(runtime, 'tracking runtime implementation is absent')
        return runtime

    def test_rejects_old_server_or_client_before_world_mutation(self):
        m = self.module()
        m.validate_versions('0.9.15', '0.9.15', (3, 10))
        for values in [('0.9.10', '0.9.15', (3, 10)), ('0.9.15', '0.9.10', (3, 10)), ('0.9.15', '0.9.15', (3, 9))]:
            with self.assertRaises(ValueError):
                m.validate_versions(*values)

    def test_geometry_world_cm_and_actor_origin_are_distinct(self):
        m = self.module()
        pose = np.array([[0., -1., 0., 12.], [1., 0., 0., 30.], [0., 0., 1., 1.], [0., 0., 0., 1.]])
        local = np.array([[1.47753, -.8, -.3], [1.47753, .8, -.3], [-1.3936, -.8, -.3], [-1.3936, .8, -.3]])
        world_cm = ((local @ pose[:3, :3].T) + pose[:3, 3]) * 100
        box = {'location': [.0040445, 0., -.1], 'extent': [2.4508415, 1.064162, .75], 'yaw': 0.}
        g = m.vehicle_geometry(pose, world_cm, box)
        self.assertAlmostEqual(g['wheelbase'], 2.87113)
        self.assertAlmostEqual(g['rear_to_actor_xy'][0], 1.3936)
        self.assertAlmostEqual(g['geometry']['front'], 3.848486)
        self.assertAlmostEqual(g['geometry']['rear'], 1.053197)
        np.testing.assert_allclose(m.rear_local_xy(pose, g), [-38., -28.6064], atol=1e-9)
        with self.assertRaises(ValueError):
            m.vehicle_geometry(pose, world_cm / 100., box)

    def test_fixture_is_explicit_flat_road_with_no_traffic(self):
        import xml.etree.ElementTree as ET
        m = self.module()
        root = ET.fromstring(m.fixture_opendrive())
        roads = root.findall('road')
        self.assertEqual(len(roads), 1)
        road = roads[0]
        self.assertEqual(float(road.attrib['length']), 600.)
        self.assertEqual(road.attrib['junction'], '-1')
        self.assertEqual(float(road.find('lanes/laneOffset').attrib['a']), 60.)
        self.assertEqual(float(road.find('lanes/laneSection/right/lane/width').attrib['a']), 120.)
        self.assertIsNotNone(road.find('planView/geometry/line'))
        self.assertFalse(root.findall('junction'))

    def test_owned_server_refuses_an_already_listening_port(self):
        import socket
        import tempfile
        from unittest.mock import patch
        m = self.module()
        self.assertTrue(hasattr(m, 'owned_server'), 'managed server ownership is missing')
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as listener:
            root = Path(tmp)
            (root / 'CarlaUE4.sh').write_text('#!/bin/sh\nexit 0\n')
            listener.bind(('127.0.0.1', 0)); listener.listen()
            with patch('subprocess.Popen', side_effect=AssertionError('must reject before launching')):
                with self.assertRaises(RuntimeError):
                    with m.owned_server(root, listener.getsockname()[1], root):
                        self.fail('foreign server was accepted')

    @unittest.skipUnless(__import__('os').geteuid() == 0, 'cross-user launch requires root')
    def test_managed_nonroot_listener_ownership_is_visible(self):
        import os, pwd, signal, subprocess
        m = self.module()
        try: pwd.getpwnam('autodl')
        except KeyError: self.skipTest('autodl account absent')
        code = "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(10)"
        process=subprocess.Popen(['runuser','-u','autodl','--',sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
        try:
            port=int(process.stdout.readline())
            self.assertTrue(m.listener_owned_by_group(port,process.pid))
        finally:
            try: os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError: pass
            process.wait(timeout=5)
            process.stdout.close()

    def test_preload_excursion_cannot_hide_in_zero_net_displacement(self):
        m = self.module()
        self.assertTrue(hasattr(m, 'preload_motion'), 'preload trajectory check is missing')
        result = m.preload_motion([[0., 0.], [.03, 0.], [0., 0.]])
        self.assertAlmostEqual(result['net'], 0.)
        self.assertAlmostEqual(result['max_from_start'], .03)
        self.assertAlmostEqual(result['cumulative'], .06)
        self.assertFalse(result['passed'])

    def test_client_waits_for_listener_and_cleans_owned_group(self):
        import json, os, shlex, signal, socket, tempfile, types
        from unittest.mock import patch
        m = self.module()
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]

        class EagerClient:
            def __init__(self, host, port):
                try:
                    with socket.create_connection((host, port), timeout=.2): pass
                except OSError as exc:
                    raise AssertionError('client connected before server was listening') from exc
            def set_timeout(self, value): pass
            def get_server_version(self): return '0.9.15'
            def get_client_version(self): return '0.9.15'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); root.chmod(0o755)
            code = ('import socket,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(.2); s=socket.socket(); '
                    f's.bind(("127.0.0.1",{port})); s.listen(); time.sleep(10)')
            (root/'CarlaUE4.sh').write_text(shlex.quote(sys.executable)+' -c '+shlex.quote(code)+'\n')
            try:
                with patch.dict(sys.modules, {'carla': types.SimpleNamespace(Client=EagerClient)}), patch.object(m, 'validate_versions'):
                    with m.owned_server(root, port, root) as client:
                        self.assertEqual(client.get_server_version(), '0.9.15')
                group = json.loads((root/'server_ownership.json').read_text())['process_group']
                self.assertFalse(m.listener_owned_by_group(port, group), 'server child survived launcher exit')
            finally:
                ownership = root/'server_ownership.json'
                if ownership.exists():
                    try: os.killpg(json.loads(ownership.read_text())['process_group'], signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_control_targets_use_distinct_times_and_unit_conversion(self):
        m = self.module()
        ref = [dict(t=i/10., x=i/10., y=0., yaw=0., v=1.+(i/10.)**2, a=0., jerk=0., kappa=0., kappa_rate=0.) for i in range(21)]
        target = m.control_reference(ref, .5, [0., 0.], [.5,0.], 1.)
        self.assertIsNone(target['position_time'])
        self.assertAlmostEqual(target['speed_time'], .6)
        self.assertAlmostEqual(target['actor_local_xy'][0], 1.5)
        self.assertAlmostEqual(target['speed_kmh'], 1.36*3.6)


class InitializationRuntimeTests(unittest.TestCase):
    def run_fake(self, directory, fail=False):
        import types
        from unittest.mock import patch
        from test_tracking_gate import initialization_fixture
        rows,g=initialization_fixture()
        if fail=='nonfinite':rows[20]['raw']['velocity_lh_mps'][0]=float('nan')
        elif fail:rows[20]['raw']['gear']=0;rows[20]['readback_control']['gear']=0
        class World:
            i=-1
            def tick(self):self.i+=1;return 100+self.i
            def get_snapshot(self):return types.SimpleNamespace(frame=100+self.i,timestamp=types.SimpleNamespace(elapsed_seconds=10.+self.i*.1))
        world=World();commands=[]
        actor=types.SimpleNamespace(id=7,
            get_control=lambda:types.SimpleNamespace(**rows[world.i]['readback_control']),get_wheel_steer_angle=lambda w:0.)
        carla=types.SimpleNamespace(command=types.SimpleNamespace(ApplyVehicleControl=lambda actor_id,c:(actor_id,c)),
            VehicleControl=lambda **kw:types.SimpleNamespace(**kw),
            VehicleWheelLocation=types.SimpleNamespace(FL_Wheel=0,FR_Wheel=1))
        def batch(values,do_tick):
            self.assertFalse(do_tick);commands.append(vars(values[0][1]).copy())
            return [types.SimpleNamespace(actor_id=7,error='')]
        client=types.SimpleNamespace(apply_batch_sync=batch)
        with patch.object(runtime,'raw_vehicle',side_effect=lambda a:rows[world.i]['raw']):
            result=runtime.initialize_actor(actor,world,g,Path(directory),carla,client)
        return result,world.i+1,commands

    def test_fixed_three_phase_schedule_and_zero_throttle(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as directory:
            result,ticks,commands=self.run_fake(directory)
            self.assertTrue(result['passed'],result)
            self.assertEqual(ticks,30)
            self.assertEqual([c['manual_gear_shift'] for c in commands],[False,True,False])
            self.assertTrue(all(c['throttle']==0 and c['brake']==1 for c in commands))
            rows=json.loads((Path(directory)/'initialization.json').read_text())
            self.assertEqual([r['phase'] for r in rows],['settle']*20+['engage_drive']+['verify_automatic']*9)

    def test_failed_engagement_stops_and_preserves_partial_evidence(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as directory:
            result,ticks,commands=self.run_fake(directory,fail=True)
            self.assertFalse(result['passed'])
            self.assertEqual(ticks,21)
            self.assertEqual(len(commands),2)
            rows=json.loads((Path(directory)/'initialization.json').read_text())
            self.assertEqual(len(rows),21)
            self.assertEqual(rows[-1]['requested_control']['gear'],1)
            self.assertEqual(rows[-1]['readback_control']['gear'],0)

    def test_nonfinite_failed_tick_is_preserved_as_invalid_json_safe_data(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as directory:
            result,ticks,commands=self.run_fake(directory,fail='nonfinite')
            self.assertFalse(result['passed'])
            self.assertEqual(ticks,21)
            rows=json.loads((Path(directory)/'initialization.json').read_text())
            self.assertEqual(len(rows),21)
            self.assertEqual(rows[-1]['raw']['velocity_lh_mps'][0],'NaN')
            saved=json.loads((Path(directory)/'initialization_check.json').read_text())
            self.assertEqual(saved,result)
            self.assertEqual(saved['status'],'INITIALIZATION_FAIL')

class CommandSubmissionTests(unittest.TestCase):
    def test_ack_is_waited_for_without_advancing_clock(self):
        from types import SimpleNamespace as NS
        import tempfile,json
        events=[]
        world=NS(get_snapshot=lambda:NS(frame=100),tick=lambda:events.append('tick'))
        actor=NS(id=7)
        def batch(commands,do_tick):
            events.append('ack');self.assertFalse(do_tick);self.assertEqual(commands[0][0],7)
            return [NS(actor_id=7,error='')]
        client=NS(apply_batch_sync=batch)
        carla=NS(command=NS(ApplyVehicleControl=lambda actor_id,c:(actor_id,c)))
        control=NS(throttle=.2,brake=0.,steer=.1,hand_brake=False,reverse=False,manual_gear_shift=False,gear=0)
        with tempfile.TemporaryDirectory() as folder:
            ack=runtime.submit_control(client,world,actor,control,carla,Path(folder)/'commands.jsonl','tracking')
            self.assertEqual(events,['ack']);world.tick();self.assertEqual(events,['ack','tick'])
            self.assertTrue(ack['accepted']);self.assertEqual(ack['expected_next_frame'],101)
            self.assertEqual(json.loads((Path(folder)/'commands.jsonl').read_text()),ack)

    def test_rejected_or_wrong_actor_response_is_saved_without_tick(self):
        from types import SimpleNamespace as NS
        import tempfile,json
        for responses in [[NS(actor_id=7,error='rejected')],[],[NS(actor_id=8,error='')]]:
            events=[];world=NS(get_snapshot=lambda:NS(frame=100),tick=lambda:events.append('tick'))
            client=NS(apply_batch_sync=lambda c,t:responses)
            carla=NS(command=NS(ApplyVehicleControl=lambda a,c:(a,c)))
            control=NS(throttle=.2,brake=0.,steer=0.,hand_brake=False,reverse=False,manual_gear_shift=False,gear=0)
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(RuntimeError):runtime.submit_control(client,world,NS(id=7),control,carla,Path(folder)/'commands.jsonl','tracking')
                saved=json.loads((Path(folder)/'commands.jsonl').read_text())
                self.assertFalse(saved['accepted']);self.assertTrue(saved['error']);self.assertEqual(events,[])

class SpatialReferenceTests(unittest.TestCase):
    def test_stationary_pose_noise_does_not_become_large_direction_error(self):
        from planning.tracking_reference import generate_reference
        ref=generate_reference('S2');ego=[1.4-.00002,.00009]
        result=runtime.control_reference(ref,0.,[1.4,0.],ego,0.)
        delta=np.array(result['actor_local_xy'])-ego
        self.assertGreater(delta[0],.99)
        self.assertLess(abs(math.atan2(delta[1],delta[0])),.001)
        self.assertEqual(result['target_kind'],'stationary_tangent')
        self.assertEqual(result['speed_mps'],0.)

    def test_stopped_endpoint_remains_forward_after_small_overshoot(self):
        from planning.tracking_reference import generate_reference
        ref=generate_reference('S2');ego=[17.6,0.]
        result=runtime.control_reference(ref,15.,[1.4,0.],ego,0.)
        self.assertAlmostEqual(result['actor_local_xy'][0],18.6)
        self.assertEqual(result['speed_mps'],0.)

    def test_left_and_right_curves_have_mirrored_spatial_targets(self):
        from planning.tracking_reference import generate_reference,state_at,actor_target
        results=[]
        for case in ['L2','R2']:
            ref=generate_reference(case);state=actor_target(state_at(ref,12.),[1.4,0.])
            result=runtime.control_reference(ref,12.,[1.4,0.],[state['x'],state['y']],2.)
            self.assertEqual(result['target_kind'],'path_arc')
            self.assertAlmostEqual(result['target_path_s']-result['projection_path_s'],1.)
            results.append(result['actor_local_xy'])
        np.testing.assert_allclose(results[0],[results[1][0],-results[1][1]],atol=1e-8)

    def test_speed_time_law_is_unchanged_for_every_sample(self):
        from planning.tracking_reference import generate_reference,state_at,actor_target,case_spec
        for case in ['S2','L2']:
            ref=generate_reference(case)
            for i in range(round(case_spec(case)['duration']/.1)+1):
                t=round(i*.1,8);current=actor_target(state_at(ref,t),[1.4,0.])
                result=runtime.control_reference(ref,t,[1.4,0.],[current['x'],current['y']],3.5)
                old_speed=actor_target(state_at(ref,round(t+.1,8)),[1.4,0.])['speed_mps']
                self.assertEqual(result['speed_mps'],old_speed)
                self.assertAlmostEqual(result['speed_time'],round(t+.1,8))
                self.assertAlmostEqual(result['lookahead_m'],1.4)

if __name__ == '__main__':
    unittest.main()
