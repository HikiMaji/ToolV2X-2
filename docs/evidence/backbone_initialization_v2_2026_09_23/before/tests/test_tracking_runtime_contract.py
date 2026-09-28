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
        target = m.control_reference(ref, .5, [0., 0.])
        self.assertAlmostEqual(target['position_time'], .9)
        self.assertAlmostEqual(target['speed_time'], .6)
        self.assertAlmostEqual(target['actor_local_xy'][0], .9)
        self.assertAlmostEqual(target['speed_kmh'], 1.36*3.6)


if __name__ == '__main__':
    unittest.main()
