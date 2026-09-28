import unittest,importlib.util
import numpy as np

class GeometryTests(unittest.TestCase):
    def test_self_filter_keeps_adjacent_vehicle(self):
        from tracking.lidar_tracks import exclude_self
        own=np.array([0,0,1,4,2,2,.4]);boxes=np.array([own,own+[0,3,0,0,0,0,0]])
        keep,audit=exclude_self(boxes,own,.5)
        self.assertEqual(keep.tolist(),[False,True]);self.assertEqual(audit[0]['reason'],'own_vehicle_overlap')
    def test_tracker_box_roundtrip_and_camera_heading(self):
        from tracking.lidar_tracks import to_camera,from_camera
        box=np.array([[2,3,1,4,2,2,.7]])
        camera=to_camera(box);self.assertAlmostEqual(camera[0,6],-.7)
        self.assertAlmostEqual(camera[0,4],0.)
        np.testing.assert_allclose(from_camera(camera),box)
    def test_reflected_plan_frame_has_correct_heading_velocity(self):
        from tracking.lidar_tracks import plan_objects
        tracks=[dict(id=1,box=[12,21,1,4,2,2,np.pi/2],velocity=[0,2],parent_refs=['local:1'])]
        pose=np.eye(4);pose[:2,:2]=[[0,-1],[1,0]];pose[:2,3]=[10,20]
        obj=plan_objects(tracks,pose,'ego0')[0]
        np.testing.assert_allclose(obj['box'][:2],[1,2],atol=1e-9)
        np.testing.assert_allclose(obj['velocity'],[2,0],atol=1e-9);self.assertAlmostEqual(obj['box'][6],0.)

@unittest.skipUnless(importlib.util.find_spec('filterpy'),'AB3DMOT environment required')
class TrackerTests(unittest.TestCase):
    def test_upstream_camera_corners_match_world_box(self):
        from tracking.lidar_tracks import FixedRateTracker,to_camera,footprint
        FixedRateTracker(dt=.05)  # resolve the actual upstream package
        from AB3DMOT_libs.box import Box3D
        from shapely.geometry import Polygon
        box=np.array([2.,3.,1.,4.,2.,2.,.7])
        corners=Box3D.box2corners3d_camcoord(Box3D.array2bbox_raw(to_camera(box[None])[0]))
        world=corners[:,[0,2,1]];world[:,2]*=-1
        np.testing.assert_allclose(world.mean(axis=0),box[:3],atol=1e-9)
        self.assertAlmostEqual(Polygon(world[:4,:2]).symmetric_difference(footprint(box)).area,0.,places=8)

    def test_fixed_rate_prefix_and_velocity_units(self):
        from tracking.lidar_tracks import FixedRateTracker
        tr=FixedRateTracker(dt=.05);rows=[]
        for i in range(8):rows.append(tr.update([[i*.1,0,1,4,2,2,0]],[.9],1+i*.05,i))
        self.assertAlmostEqual(rows[-1][0]['velocity'][0],2.,places=1)
        other=FixedRateTracker(dt=.05)
        for i in range(4):r=other.update([[i*.1,0,1,4,2,2,0]],[.9],1+i*.05,i)
        self.assertEqual(r,rows[3])
        with self.assertRaises(ValueError):other.update([],[],None,4)
        with self.assertRaises(ValueError):other.update([],[],1.3,4)
        # Rejection must not advance valid time or tracker state.
        self.assertEqual(other.frame_count,4)
    def test_late_track_retains_pre_confirmation_detection_refs(self):
        from tracking.lidar_tracks import FixedRateTracker
        tr=FixedRateTracker(dt=.05)
        for i in range(4):tr.update([],[],1+i*.05,i)
        for i in range(4,7):rows=tr.update([[(i-4)*.1,0,1,4,2,2,0]],[.9],1+i*.05,i)
        self.assertEqual(rows[0]['parent_refs'],['local_detection_frame:4','local_detection_frame:5','local_detection_frame:6'])

    def test_missed_frame_is_marked_as_prediction(self):
        from tracking.lidar_tracks import FixedRateTracker
        tr=FixedRateTracker(dt=.05)
        tr.update([[0,0,1,4,2,2,0]],[.9],1.,0)
        rows=tr.update([],[],1.05,1)
        self.assertEqual(rows[0]['time_since_update'],1)
        self.assertFalse(rows[0]['detector_hit'])
