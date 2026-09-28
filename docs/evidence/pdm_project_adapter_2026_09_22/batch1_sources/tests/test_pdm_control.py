import unittest
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def rollout_plan(*,end=2.,speed=.5,status='selected_feasible'):
    times=np.arange(0.,2.01,.1)
    if status!='selected_feasible':
        return dict(plan_status=status,selected_index=None,rollout=None,waypoints=[])
    return dict(plan_status=status,selected_index=0,rollout=dict(
        source='selected_scored_simulation',times_s=times.tolist(),
        xy_rear_axle_m=np.column_stack((times/2*end,np.zeros(len(times)))).tolist(),
        headings_rad=np.zeros(len(times)).tolist(),
        speed_mps=np.full(len(times),speed).tolist(),
        acceleration_mps2=np.zeros(len(times)).tolist()))

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

    def test_v2_uses_simulated_half_second_speed_and_spatial_lookahead(self):
        from planning.pdm_control import PDMControlAdapter
        pose=np.eye(4);pose[:2,:2]=[[0,-1],[1,0]];pose[:2,3]=[10,20]
        target=PDMControlAdapter().update(rollout_plan(speed=.7),pose,1.4,current_speed_mps=.3)
        self.assertEqual(target['mode'],'track')
        self.assertAlmostEqual(target['speed_kmh'],2.52)
        np.testing.assert_allclose(target['world_xy'],[10,21.9])

    def test_v2_short_forward_rollout_tracks_endpoint_without_inventing_stop(self):
        from planning.pdm_control import PDMControlAdapter
        target=PDMControlAdapter().update(rollout_plan(end=.2,speed=.1),np.eye(4),1.4,
                                                  current_speed_mps=.3)
        self.assertEqual(target['mode'],'track')
        np.testing.assert_allclose(target['world_xy'],[1.6,0])

    def test_v2_stop_latch_uses_three_entry_conditions_and_hysteretic_release(self):
        from planning.pdm_control import PDMControlAdapter
        adapter=PDMControlAdapter()
        stopped=adapter.update(rollout_plan(end=.2,speed=.1),np.eye(4),1.4,.1)
        self.assertEqual(stopped['mode'],'hold_stopped')
        still=adapter.update(rollout_plan(end=.4,speed=.3),np.eye(4),1.4,.1)
        self.assertEqual(still['mode'],'hold_stopped')
        released=adapter.update(rollout_plan(end=.4,speed=.4),np.eye(4),1.4,.1)
        self.assertEqual(released['mode'],'track')

    def test_v2_stop_distance_is_rear_path_progress_not_rotating_body_offset(self):
        from planning.pdm_control import PDMControlAdapter
        plan=rollout_plan(end=.2,speed=.1)
        plan['rollout']['headings_rad']=np.linspace(0.,.5,21).tolist()
        stopped=PDMControlAdapter().update(plan,np.eye(4),1.4,.1)
        self.assertEqual(stopped['mode'],'hold_stopped')

    def test_v2_stationary_feasible_rollout_enters_stop_before_no_forward_check(self):
        from planning.pdm_control import PDMControlAdapter
        plan=rollout_plan(end=0.,speed=.1)
        stopped=PDMControlAdapter().update(plan,np.eye(4),1.4,.1)
        self.assertEqual(stopped['mode'],'hold_stopped')

    def test_v2_rejects_preview_beyond_dense_horizon(self):
        from planning.pdm_control import PDMControlAdapter
        with self.assertRaises(ValueError):PDMControlAdapter(speed_preview_s=2.1)

    def test_v2_infeasible_and_emergency_plans_hold_explicitly(self):
        from planning.pdm_control import PDMControlAdapter
        adapter=PDMControlAdapter()
        for status,mode in [('no_feasible_candidate','hold_infeasible'),
                            ('emergency_brake','hold_emergency')]:
            self.assertEqual(adapter.update(rollout_plan(status=status),np.eye(4),1.4,0.)['mode'],mode)

    def test_v2_rejects_bad_dense_contract_and_no_forward_rollout(self):
        from planning.pdm_control import PDMControlAdapter
        adapter=PDMControlAdapter();bad=[]
        for field,value in [('times_s',[0.,.1]),('speed_mps',[.5]*20+[-.1]),
                            ('headings_rad',[0.]*20+[np.nan])]:
            plan=rollout_plan();plan['rollout'][field]=value;bad.append(plan)
        plan=rollout_plan();plan['rollout']['xy_rear_axle_m'][0]=[.1,0.];bad.append(plan)
        plan=rollout_plan();plan['rollout']['xy_rear_axle_m']=[[0.,0.]]*21;bad.append(plan)
        for plan in bad:
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):adapter.update(plan,np.eye(4),1.4,.3)

    def test_v2_rejects_unscored_raw_generator_rollout(self):
        from planning.pdm_control import PDMControlAdapter
        plan=rollout_plan()
        plan['rollout']['source']='raw_generator'
        with self.assertRaises(ValueError):
            PDMControlAdapter().update(plan,np.eye(4),1.4,.3)
