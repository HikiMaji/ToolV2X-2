import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


class V2XverseInputTests(unittest.TestCase):
    def test_module_exists(self):
        self.assertTrue((ROOT/'src/planning/v2xverse_inputs.py').exists())

    def test_reader_excludes_expert_and_peer_fields_and_does_not_invent_time(self):
        from planning.v2xverse_inputs import load_vehicle_observation
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vehicle=root/'ego_vehicle_0'
            (vehicle/'measurements').mkdir(parents=True);(vehicle/'lidar').mkdir()
            fields=dict(x=1.,y=2.,theta=.3,speed=4.,lidar_pose_x=1.,lidar_pose_y=2.,
                lidar_pose_z=3.,x_command=10.,y_command=20.,command=4,
                future_waypoints=[[99.,99.]],should_brake=True,gt_command=5,other_vehicle={'x':9.})
            (vehicle/'measurements/0010.json').write_text(json.dumps(fields))
            np.save(vehicle/'lidar/0010.npy',np.array([[1.,2.,3.,.5]],dtype=np.float32))
            result=load_vehicle_observation(root,'ego_vehicle_0',10)
            self.assertNotIn('future_waypoints',result['measurement'])
            self.assertNotIn('should_brake',result['measurement'])
            self.assertNotIn('other_vehicle',result['measurement'])
            self.assertIsNone(result['timestamp_seconds'])
            self.assertEqual(result['measurement']['command'],4)
            with self.assertRaises(ValueError):load_vehicle_observation(root,'rsu_0',10)

    def test_sensor_to_rear_axle_and_handedness(self):
        from planning.v2xverse_inputs import lidar_to_rear_axle
        sensor=np.eye(4);sensor[0,3]=1.3
        body=np.eye(4)
        actual=lidar_to_rear_axle(np.array([[1.,2.,3.,.5]]),sensor,body)
        np.testing.assert_allclose(actual,[[2.3,-2.,3.,.5]])
        bad=body.copy();bad[0,0]=2.
        with self.assertRaises(ValueError):lidar_to_rear_axle(np.zeros((1,4)),sensor,bad)


if __name__=='__main__':unittest.main()
