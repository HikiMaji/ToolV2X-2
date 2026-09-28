import unittest
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

class ControlTests(unittest.TestCase):
    def test_startup_requires_stable_ego_and_observed_tracks(self):
        from planning.pdm_control import StartupGate
        g=StartupGate(min_frames=3,max_acceleration=1.,min_track_hits=3)
        self.assertFalse(g.update(80.,[{'hits':3,'detector_hit':True}]))
        self.assertFalse(g.update(0.,[{'hits':1,'detector_hit':True}]))
        self.assertFalse(g.update(0.,[{'hits':3,'detector_hit':True}]))
        self.assertFalse(g.update(0.,[{'hits':3,'detector_hit':True}]))
        self.assertTrue(g.update(0.,[{'hits':3,'detector_hit':True}]))
    def test_controller_uses_ahead_of_body_waypoint_and_kmh(self):
        from planning.pdm_control import control_target
        pose=np.eye(4);pose[:2,:2]=[[0,-1],[1,0]];pose[:2,3]=[10,20]
        result=control_target([[.1,0],[.6,0],[1.4,0],[2.6,0],[4,0],[5.5,0]],pose,1.4,[0]*6,[.5,1,1.5,2,2.5,3])
        self.assertAlmostEqual(result['speed_kmh'],3.6)
        np.testing.assert_allclose(result['world_xy'],[10,22.])
    def test_backward_or_nonfinite_plan_is_not_silently_clipped(self):
        from planning.pdm_control import control_target
        for points in [[[-.2,0],[0,0]],[[np.nan,0],[1,0]]]:
            with self.assertRaises(ValueError):control_target(points,np.eye(4),1.4,[0,0],[.5,1.])
    def test_zero_path_holds_brake(self):
        from planning.pdm_control import control_target
        r=control_target([[0,0],[0,0]],np.eye(4),1.4,[0,0],[.5,1.])
        self.assertEqual(r['speed_kmh'],0.)
        self.assertEqual(r['mode'],'hold_no_forward_target')

    def test_short_forward_rear_path_does_not_force_brake(self):
        from planning.pdm_control import control_target
        r=control_target([[.1,0],[.4,0]],np.eye(4),1.4,[0,0],[.5,1.])
        self.assertEqual(r['mode'],'track')
        self.assertAlmostEqual(r['speed_kmh'],2.16)
        np.testing.assert_allclose(r['world_xy'],[1.8,0])

    def test_future_heading_rotates_rear_to_actor_offset(self):
        from planning.pdm_control import control_target
        r=control_target([[2.,1.],[3.,2.]],np.eye(4),1.4,[np.pi/2,np.pi/2],[.5,1.])
        np.testing.assert_allclose(r['world_xy'],[2.,-2.4])

    def test_missing_nonfinite_or_nonincreasing_times_rejected(self):
        from planning.pdm_control import control_target
        for headings,times in [([0],[.5,1]),([0,np.nan],[.5,1]),([0,0],[1,.5]),([0,0],[.5,.5])]:
            with self.assertRaises(ValueError):control_target([[1,0],[2,0]],np.eye(4),1.4,headings,times)
