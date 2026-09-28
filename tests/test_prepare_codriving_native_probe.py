"""Offline reader guards; no model/checkpoint access."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


class NativeProbeReaderTests(unittest.TestCase):
    def test_reader_loads_only_requested_causal_localization(self):
        from prepare_codriving_native_probe import read_localization
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'ego_vehicle_1'/'measurements';p.mkdir(parents=True)
            values=dict(x=0.,y=1.,theta=2.,lidar_pose_x=3.,lidar_pose_y=4.,future_waypoints='forbidden')
            (p/'0004.json').write_text(json.dumps(values))
            m=read_localization(Path(root),'ego_vehicle_1',4)
            self.assertEqual(set(m),{'x','y','theta','lidar_pose_x','lidar_pose_y'})
            with self.assertRaises(ValueError):read_localization(Path(root),'../ego_vehicle_1',4)

    def test_detector_provenance_rejects_cross_route_or_wrong_vehicle(self):
        from prepare_codriving_native_probe import check_detection
        root=Path('/data/route05')
        r=dict(vehicle=1,frame_index=4,record_len=[1],coordinate_frame='original_v2xverse_rotated_sensor_xy_world_height',
               read_paths=[str(root/'ego_vehicle_1/lidar/0004.npy'),str(root/'ego_vehicle_1/measurements/0004.json')])
        check_detection(r,root,'ego_vehicle_1')
        with self.assertRaises(ValueError):check_detection(r,Path('/data/other'),'ego_vehicle_1')
        with self.assertRaises(ValueError):check_detection(r,root,'ego_vehicle_0')

if __name__=='__main__':unittest.main()
