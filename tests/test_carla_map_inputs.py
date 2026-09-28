import unittest
import numpy as np

class CarlaMapInputsTests(unittest.TestCase):
    def test_route_world_to_rear_axle_and_handedness(self):
        from planning.carla_map_inputs import route_geometry
        pose=np.eye(4);pose[:2,:2]=[[0,-1],[1,0]];pose[:2,3]=[10,20]
        samples=[dict(x=10,y=y,yaw=90,width=4,road_id=1,section_id=0,lane_id=-1) for y in [18,20,22]]
        result=route_geometry(samples,pose)
        np.testing.assert_allclose(result['centerline'],[[-2,0,0],[0,0,0],[2,0,0]],atol=1e-9)
        polygon=result['drivable_lanes']['1:0:-1']
        self.assertAlmostEqual(max(p[1] for p in polygon),2)
        self.assertAlmostEqual(min(p[1] for p in polygon),-2)
    def test_rejects_non_rigid_calibration(self):
        from planning.carla_map_inputs import route_geometry
        pose=np.eye(4);pose[0,0]=2
        with self.assertRaises(ValueError):route_geometry([],pose)
    def test_first_adapter_rejects_multi_lane_route(self):
        from planning.carla_map_inputs import route_geometry
        samples=[dict(x=x,y=0,yaw=0,width=4,road_id=x,section_id=0,lane_id=-1) for x in [0,1]]
        with self.assertRaises(ValueError):route_geometry(samples,np.eye(4))
