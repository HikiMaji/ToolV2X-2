import sys,unittest,tempfile,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

class DetectorProbeTests(unittest.TestCase):
    def test_native_rotation_height_and_intensity(self):
        from probe_v2xverse_detector import native_points
        raw=np.array([[1.,2.,3.,.4]],dtype=np.float32)
        actual=native_points(raw,1.85)
        np.testing.assert_allclose(actual,[[2.,-1.,4.85,.4]],atol=1e-6)
        np.testing.assert_allclose(raw,[[1.,2.,3.,.4]])
    def test_invalid_point_or_height_rejected(self):
        from probe_v2xverse_detector import native_points
        for raw,z in [(np.ones((2,3)),1.),(np.ones((2,4)),float('nan')),(np.full((1,4),np.inf),1.)]:
            with self.assertRaises(ValueError):native_points(raw,z)
    def test_single_vehicle_reader_never_needs_peer_or_labels(self):
        from probe_v2xverse_detector import load_local_input
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);v=root/'ego_vehicle_0'
            (v/'lidar').mkdir(parents=True);(v/'measurements').mkdir()
            np.save(v/'lidar/0010.npy',np.ones((2,4),dtype=np.float32))
            (v/'measurements/0010.json').write_text(json.dumps({'lidar_pose_z':1.85,'future_waypoints':'forbidden_sentinel'}))
            raw,z,paths=load_local_input(root,0,10)
            self.assertEqual(z,1.85);self.assertEqual(raw.shape,(2,4));self.assertEqual(len(paths),2)
            with self.assertRaises(ValueError):load_local_input(root,'../peer',10)
