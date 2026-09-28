"""Regression cases for the audited native-to-planner coordinate/time errors."""
import copy
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from planning.codriving_native_inputs import (
    NativeInputSpec, sensor_boxes_to_world, world_boxes_to_actor,
    source_to_receiver_transform, sample_binding, resolve_planner_sample,
    validate_context_binding, filter_source_self)


def pose(x=0., y=0., yaw=0.):
    return dict(x=x, y=y, theta=yaw+np.pi/2,
                lidar_pose_x=x+1.3*np.cos(yaw), lidar_pose_y=y+1.3*np.sin(yaw))


class NativeInputTests(unittest.TestCase):
    def test_sensor_offset_is_applied_once_and_y_not_reflected_in_world(self):
        m=pose(10.,20.,np.pi/2)
        raw=np.array([[4.,2.,1.,4.,2.,1.5,.3]])
        before=raw.copy()
        world=sensor_boxes_to_world(raw,m)
        np.testing.assert_allclose(world[0,:2],[8.,25.3],atol=1e-9)
        local=world_boxes_to_actor(world,m)
        np.testing.assert_allclose(local[0,:2],[5.3,-2.],atol=1e-9)
        self.assertAlmostEqual(local[0,6],-.3)
        np.testing.assert_array_equal(raw,before)

    def test_route28_receiver_box_is_near_origin_not_third_party(self):
        source=dict(x=-68.00894165039062,y=6.212459087371826,
                    theta=1.5819659233093262,lidar_pose_x=-66.70924377441406,lidar_pose_y=6.226705074310303)
        receiver=dict(x=-56.16424560546875,y=9.09587287902832,
                      theta=2.2758326530456543,lidar_pose_x=-55.15510559082031,lidar_pose_y=9.901524543762207)
        raw=[[10.60546875,2.66796875,1.,4.8,2.1,1.5,.6]]
        xy=world_boxes_to_actor(sensor_boxes_to_world(raw,source),receiver)[0,:2]
        self.assertLess(np.linalg.norm(xy),.1)
        np.testing.assert_allclose(xy,[-.031,.083],atol=.002)

    def test_proper_source_receiver_transform_matches_world_projection(self):
        a,b=pose(5.,7.,.8),pose(-3.,2.,-1.2)
        world=np.array([[8.,-2.,1.,4.,2.,2.,-.5]])
        src=world_boxes_to_actor(world,a);dst=world_boxes_to_actor(world,b)
        t=source_to_receiver_transform(a,b)
        np.testing.assert_allclose(t[:2,:2]@src[0,:2]+t[:2,2],dst[0,:2],atol=1e-9)
        self.assertAlmostEqual(np.linalg.det(t[:2,:2]),1.)

    def test_source_self_filter_preserves_neighbor_and_empty(self):
        m=pose(0,0,.4);spec=NativeInputSpec()
        boxes=np.array([[0.,0.,1.,4.,2.,2.,.4],[0.,3.,1.,4.,2.,2.,.4]])
        mask=filter_source_self(boxes,m,spec)
        self.assertEqual(mask.tolist(),[False,True])
        self.assertEqual(sensor_boxes_to_world([],m).shape,(0,7))

    def test_start_and_decision_have_distinct_keys_and_physical_time(self):
        sample=sample_binding('route28','ego_vehicle_0',26,NativeInputSpec())
        self.assertEqual(sample['decision_frame'],30)
        self.assertEqual(sample['input_frames'],[26,27,28,29,30])
        self.assertEqual(sample['label_frames'],list(range(31,41)))
        self.assertAlmostEqual(sample['decision_time'],6.)

    def test_nested_subset_resolves_real_identity_without_torch(self):
        dataset=SimpleNamespace(route_frames=[({'ego':'/data/route28/ego_vehicle_0'},26),
                                             ({'ego':'/data/route11/ego_vehicle_1'},66)])
        subset=SimpleNamespace(dataset=dataset,indices=[1,0])
        nested=SimpleNamespace(dataset=subset,indices=[1])
        actual=resolve_planner_sample(nested,0,NativeInputSpec())
        self.assertEqual((actual['scene'],actual['receiver'],actual['decision_frame']),('route28','ego_vehicle_0',30))
        with self.assertRaises((ValueError,IndexError)):resolve_planner_sample(nested,2,NativeInputSpec())

    def test_stale_scene_epoch_axis_and_time_context_rejected(self):
        spec=NativeInputSpec();sample=sample_binding('route28','ego_vehicle_0',26,spec)
        context=dict(scene='route28',receiver='ego_vehicle_0',source='ego_vehicle_1',g=30,
                     decision_time=6.,coordinate_frame='source_actor_at_t',axes='x_forward_y_left',
                     execution_spec=spec.to_dict())
        validate_context_binding(sample,context)
        for key,value in [('scene','route11'),('g',26),('receiver','ego_vehicle_1'),
                          ('decision_time',30.),('axes','x_forward_y_right')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_context_binding(sample,dict(context,**{key:value}))

    def test_invalid_geometry_and_spec_fail_closed(self):
        for m in [dict(pose(),theta=float('nan')),dict(pose(),x=float('inf'))]:
            with self.assertRaises(ValueError):sensor_boxes_to_world([[0,0,1,4,2,2,0]],m)
        for values in [dict(dt_seconds=0.),dict(history_steps=1),dict(receiver_self_radius_m=-1.),dict(version='unknown')]:
            with self.assertRaises(ValueError):NativeInputSpec(**values)
        with self.assertRaises(ValueError):sample_binding('route','ego_vehicle_0',-1,NativeInputSpec())


if __name__=='__main__':unittest.main()
