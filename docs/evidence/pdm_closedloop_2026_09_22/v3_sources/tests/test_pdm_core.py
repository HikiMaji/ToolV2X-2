"""Real upstream PDM core, synthetic geometry only; no model-effect evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def scene():
    return dict(version='toolv2x_pdm_scene_v1', coordinate_frame='ego_rear_axle_rh',
        timestamp_us=1000000, speed_mps=4., acceleration_mps2=0., steering_angle_rad=0.,
        vehicle=dict(width=1.9, front_length=3.6, rear_length=1., wheel_base=2.8,
                     cog_position_from_rear_axle=1.4, height=1.5),
        centerline=[[float(x), 0., 0.] for x in range(-10, 101)],
        drivable_lanes={'lane0': [[-20., -3.5], [110., -3.5], [110., 3.5], [-20., 3.5]]},
        route_lane_ids=['lane0'], intersections=[], speed_limit_mps=8.,
        map_identity=dict(name='synthetic_test_map', revision='v1', route='straight'),
        objects=[], signal_constraints=[], input_kind='synthetic_contract')


class PDMModuleTests(unittest.TestCase):
    def test_core_exists(self):
        self.assertTrue((ROOT / 'src/planning/pdm_core.py').is_file(),
                        'original PDM adapter not implemented')


@unittest.skipUnless(importlib.util.find_spec('nuplan'), 'optional original PDM environment required')
class PDMCoreTests(unittest.TestCase):
    def setUp(self):
        from planning.pdm_core import PDMCore, PDMExecutionSpec
        self.core = PDMCore(PDMExecutionSpec())

    def test_original_cv_equivalence_and_same_time_repeat(self):
        data=scene(); before=copy.deepcopy(data)
        reference=self.core.plan(data, original_cv=True)
        result=self.core.plan(data)
        for key in ('waypoints', 'waypoint_headings_rad', 'proposal_scores', 'simulated_proposals'):
            np.testing.assert_allclose(result[key], reference[key], atol=1e-9, rtol=0)
            np.testing.assert_array_equal(result[key], self.core.plan(data)[key])
        self.assertEqual(data, before)
        self.assertEqual(len(result['waypoints']), 6)
        self.assertGreater(result['waypoints'][-1][0], 8.)

    @unittest.skipUnless(os.environ.get('TOOLV2X_PDM_REFERENCE_ROOT'), 'pristine upstream snapshot required')
    def test_pristine_upstream_modules_match_adapted_cv(self):
        data=scene()
        data['objects']=[dict(token='peer:7',box=[15.,0.,0.,4.5,2.,1.5,0.],
                             velocity=[2.,0.],forecast=None,parent_refs=[])]
        env=dict(os.environ,TOOLV2X_PDM_SOURCE_ROOT=os.environ['TOOLV2X_PDM_REFERENCE_ROOT'],
                 PYTHONPATH=str(ROOT/'src'))
        code='import json,sys; from planning.pdm_core import PDMCore; print(json.dumps(PDMCore().plan(json.load(sys.stdin),original_cv=True)))'
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps(data),text=True,
                              env=env,capture_output=True,check=True)
        reference=json.loads(result.stdout)
        actual=self.core.plan(data)
        for key in ('waypoints','waypoint_headings_rad','proposal_scores','simulated_proposals'):
            np.testing.assert_allclose(actual[key],reference[key],rtol=0,atol=1e-9)

    def test_stationary_clear_road_has_positive_control_speed(self):
        from planning.pdm_control import control_target
        data=scene();data['speed_mps']=0.
        result=self.core.plan(data)
        target=control_target(result['waypoints'],np.eye(4),1.4,
            result['waypoint_headings_rad'],result['times'])
        self.assertGreater(target['speed_kmh'],0.)
        self.assertEqual(target['mode'],'track')

    def test_state_and_future_path_change_actual_plan(self):
        clear=scene(); baseline=self.core.plan(clear)
        blocked=copy.deepcopy(clear)
        blocked['objects']=[dict(token='peer:7', box=[12., 0., 0., 4.5, 2., 1.5, 0.],
            velocity=[0.,0.], forecast=None, parent_refs=['synthetic-P'])]
        p=self.core.plan(blocked)
        self.assertLess(p['waypoints'][-1][0], baseline['waypoints'][-1][0])
        predicted=copy.deepcopy(blocked)
        predicted['objects'][0]['forecast']=dict(times=[0.,1.,2.,3.],
            xy=[[12.,0.],[20.,0.],[28.,0.],[36.,0.]])
        predicted['objects'][0]['parent_refs'].append('synthetic-F')
        f=self.core.plan(predicted)
        self.assertGreater(f['waypoints'][-1][0], p['waypoints'][-1][0])
        self.assertEqual(f['forecast_tokens'], ['peer:7'])

    def test_forecast_state_geometry_velocity_are_time_consistent(self):
        from planning.pdm_core import actor_at
        obj=dict(token='turn', box=[10.,0.,0.,4.,2.,1.5,0.], velocity=[0.,0.],
            forecast=dict(times=[0.,1.,2.,3.], xy=[[10.,0.],[10.,2.],[10.,4.],[10.,6.]]),parent_refs=[])
        actor=actor_at(obj,1.)
        np.testing.assert_allclose([actor.center.x,actor.center.y,actor.center.heading],
                                   [10.,2.,np.pi/2])
        np.testing.assert_allclose([actor.velocity.x,actor.velocity.y],[0.,2.])

    def test_turn_then_stop_keeps_last_motion_heading(self):
        from planning.pdm_core import actor_at
        obj=dict(token='stop',box=[10.,0.,0.,4.,2.,1.5,0.],velocity=[0.,0.],
            forecast=dict(times=[0.,1.,2.,3.],xy=[[10.,0.],[10.,2.],[10.,2.],[10.,2.]]),parent_refs=[])
        result=actor_at(obj,2.5)
        self.assertAlmostEqual(result.center.heading,np.pi/2)
        self.assertAlmostEqual(result.velocity.magnitude(),0.)

    def test_unknown_fields_and_insufficient_horizon_fail_closed(self):
        data=scene();data['world']={}
        with self.assertRaises(ValueError):self.core.plan(data)
        data=scene();data['objects']=[dict(token='short',box=[12.,0.,0.,4.,2.,1.5,0.],
            velocity=[0.,0.],forecast=dict(times=[0.,1.],xy=[[12.,0.],[13.,0.]]),parent_refs=[])]
        with self.assertRaises(ValueError):self.core.plan(data)

    def test_receipted_p_f_use_existing_association_and_no_private_bypass(self):
        from planning.pdm_core import scene_from_ledger
        from planning.evidence import new_ledger, apply_response
        from tools.vehicle import VehicleTools
        from test_structured_inputs import empty_window, one_track, predictor_for, request
        from test_task_spec import provenance
        from test_vehicle_tools import fixture_prediction
        def forward_prediction(w):
            result=fixture_prediction(w)
            result['means'][:]=w['states'][:,None,-1:,:2]
            result['means'][:,:,:,0]+=np.arange(1,51)[None,None,:]*.8
            return result
        predictor=predictor_for(forward_prediction)
        local=empty_window('ego');peer=one_track('peer',12.)
        ledger=new_ledger(local,predictor(local),predictor=predictor,local_provenance=provenance(),
                          include_local_history=True,p_processing='observations_only')
        motion=dict(speed_mps=4.,yaw_rate_rps=0.)
        initial,audit=scene_from_ledger(scene(),ledger,motion,rear_from_evidence=np.eye(3))
        self.assertFalse(initial['objects'])
        tools=VehicleTools(lambda:peer,predictor,peer['scene'],peer['g'],provider='peer',task_provenance=provenance())
        p_reply=tools.query_task(request('P'))
        p_ledger=apply_response(ledger,p_reply,predictor)
        p_scene,p_audit=scene_from_ledger(scene(),p_ledger,motion,rear_from_evidence=np.eye(3))
        self.assertEqual(len(p_scene['objects']),1)
        self.assertIsNone(p_scene['objects'][0]['forecast'])
        f_reply=tools.query_task(request('F','q1'))
        f_ledger=apply_response(p_ledger,f_reply,predictor)
        f_scene,f_audit=scene_from_ledger(scene(),f_ledger,motion,rear_from_evidence=np.eye(3))
        self.assertEqual(len(f_scene['objects']),1)
        self.assertIsNotNone(f_scene['objects'][0]['forecast'])
        self.assertGreater(self.core.plan(f_scene)['waypoints'][-1][0],self.core.plan(p_scene)['waypoints'][-1][0])
        self.assertTrue(f_audit['scene_construction_refs'])
        self.assertTrue(f_audit['acquired_field_refs'])
        tampered=copy.deepcopy(f_ledger);tampered['receipts']=[]
        with self.assertRaises(ValueError):scene_from_ledger(scene(),tampered,motion,rear_from_evidence=np.eye(3))


if __name__ == '__main__':
    unittest.main()
