import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scripts.rq1_temporal import data
from scripts.rq1_trusted_receiver import run


class SidecarTests(unittest.TestCase):
    def test_shape_parent_track_time_balancing(self):
        # A has one long small track and one short large track. B has one large track.
        samples = [dict(parent='A', id=1, hwl=[1, 1, 1]) for _ in range(100)]
        samples += [dict(parent='A', id=2, hwl=[3, 3, 3]), dict(parent='B', id=1, hwl=[3, 3, 3])]
        self.assertEqual(run.fit_shape(samples)['shape_hwl'], [3., 3., 3.])
        with self.assertRaises(ValueError):
            run.fit_shape([])

    def test_clean_fit_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = dict(parents=[dict(parent='A', split='cal', receiver_id=7, root=tmp,
                detections=tmp, frames=[2, 4])], jobs=[])
            with self.assertRaises(ValueError):
                run.prepare(config, Path(tmp)/'out')

    def test_two_jobs_share_scan_not_matching_and_faults_keep_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            jobs = []
            for name, ids in [('a', [1, 2]), ('b', [1])]:
                path = tmp/(name+'.jsonl.gz')
                with data.atomic_rows(path) as write:
                    for frame, t in [(2, 0.), (4, .1)]:
                        for tid in ids:
                            write(dict(key=[name, frame, tid], job_id=name, frame=frame,
                                index=int(t*10), timestamp=t, id=tid, source_ids=[7],
                                newborn=False, query_geometry=dict(xyz=[0, 0, 0], yaw=0)))
                        write(dict(key=[name, frame, 9], job_id=name, frame=frame,
                            index=int(t*10), timestamp=t, id=9, source_ids=[7],
                            newborn=True, query_geometry=None))
                jobs.append(dict(job_id=name, parent='A', kind='clean', online_path=str(path)))
            parents = [dict(parent=p, split=split, receiver_id=7, root=str(tmp),
                            detections=str(tmp), frames=[2, 4]) for p, split in [('A', 'cal'), ('FIT', 'fit')]]
            jobs.append(dict(job_id='fit', parent='FIT', kind='clean', online_path=jobs[0]['online_path']))
            config = dict(parents=parents, jobs=jobs)
            def frames(spec):
                for frame, t in [(2, 0.), (4, .1)]:
                    yield dict(frame=frame, index=int(t*10), timestamp=t,
                        boxes=[dict(id=100, xyz=[0, 0, 0], yaw=0., hwl=[1, 1, 1],
                            fresh=True, obj_type='car', timestamp=t)])
            calls = []
            def scan(spec, frame, t, pose):
                calls.append(frame)
                if frame == 4:
                    raise FileNotFoundError('missing PCD')
                return np.array([-2, 0, .125]), np.empty((0, 3))
            out = tmp/'out'
            with patch.object(run, 'receiver_frames', frames), patch.object(run, 'load_scan', scan):
                result = run.prepare(config, out)
            self.assertEqual(calls, [2, 4])
            a = list(data.read_rows(out/'jobs/a/local.jsonl.gz'))
            b = list(data.read_rows(out/'jobs/b/local.jsonl.gz'))
            self.assertEqual(len(a)+len(b), 10)
            self.assertTrue(all(r['I'] is None for r in a[:2]))
            self.assertEqual(b[0]['I'], 1.)
            self.assertEqual(b[1]['status'], 'no_query')
            self.assertTrue(all(r['input_fault'] for r in a[3:]+b[2:]))
            self.assertFalse(any('truth' in k or 'label' in k for r in a+b for k in r))
            self.assertEqual(result['jobs']['a']['rows'], 6)
            self.assertEqual(result['jobs']['fit']['status'], 'SHAPE_ONLY')
            self.assertFalse((out/'jobs/fit/local.jsonl.gz').exists())
            self.assertEqual(json.loads((out/'shape.json').read_text())['shape_hwl'], [1., 1., 1.])

    def test_public_reader_rejects_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'online.jsonl.gz'
            with data.atomic_rows(path) as write:
                write(dict(frame=2, query_truth=1))
            with self.assertRaises(ValueError):
                list(run.public_frames(dict(online_path=str(path), job_id='a')))

    def test_time_fault_cannot_create_ambiguity_for_valid_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp/'online.jsonl.gz'
            with data.atomic_rows(path) as write:
                for tid, index in [(1, 0), (2, 1)]:
                    write(dict(frame=2, index=index, timestamp=0., id=tid, source_ids=[7],
                        key=['a', 2, tid], job_id='a', newborn=False,
                        query_geometry=dict(xyz=[0, 0, 0], yaw=0)))
            spec = dict(parent='A', split='cal', receiver_id=7, root=str(tmp),
                        detections=str(tmp), frames=[2])
            config = dict(parents=[spec, dict(spec, parent='FIT', split='fit')], jobs=[
                dict(job_id='a', parent='A', kind='clean', online_path=str(path)),
                dict(job_id='fit', parent='FIT', kind='clean', online_path=str(path))])
            packet = dict(frame=2, index=0, timestamp=0., pose=[0]*6,
                boxes=[dict(id=100, xyz=[0, 0, 0], yaw=0., hwl=[1, 1, 1],
                            fresh=True, obj_type='car', timestamp=0.)])
            with patch.object(run, 'receiver_frames', side_effect=lambda spec: iter([packet])), \
                    patch.object(run, 'load_scan', return_value=(np.array([-2, 0, .125]), np.empty((0, 3)))):
                run.prepare(config, tmp/'out')
            rows = list(data.read_rows(tmp/'out/jobs/a/local.jsonl.gz'))
            self.assertEqual(rows[0]['I'], 1.)
            self.assertTrue(rows[1]['input_fault'])
            self.assertIsNone(rows[1]['I'])

    def test_raw_zero_one_and_missing_pcd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp/'7'
            path.mkdir()
            spec = dict(root=str(tmp), receiver_id=7)
            pose = [10., 5., 2., 7., 33., -3.]
            # Only receiver raw endpoints, original nonzero rotation and y flip.
            for frame, body, n in [(2, '', 0), (4, '1 2 3 0.5\n', 1)]:
                (path/('%06d.pcd' % frame)).write_text('FIELDS x y z intensity\nPOINTS %d\nDATA ascii\n'%n+body)
                origin, points = run.load_scan(spec, frame, 0., pose)
                self.assertEqual(points.shape, (n, 3))
                np.testing.assert_allclose(origin, [10, -5, 2])
                if n:
                    _, original, _, _ = run.native_adapter.imports()
                    expected = (np.array([[1., 2., 3.]]) @ original.rot(*np.radians(pose[3:])).T
                                +pose[:3]) @ original.S
                    np.testing.assert_allclose(points, expected)
            with self.assertRaises(FileNotFoundError):
                run.load_scan(spec, 6, 0., pose)
            (path/'000008.pcd').write_text('POINTS 0\n')
            with self.assertRaises(ValueError):
                run.load_scan(spec, 8, 0., pose)
            for text in ['FIELDS x y z\nPOINTS 1\nDATA ascii\n',
                         'FIELDS x y z\nPOINTS 0\nDATA binary\n']:
                (path/'000008.pcd').write_text(text)
                with self.assertRaises(ValueError):
                    run.load_scan(spec, 8, 0., pose)

    def test_points_header_requires_one_nonnegative_integer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'malformed.pcd'
            for field in ['', 'POINTS\n', 'POINTS 0 1\n', 'POINTS invalid\n',
                          'POINTS -1\n', 'POINTS 1.0\n']:
                with self.subTest(field=field):
                    path.write_text('FIELDS x y z\n'+field+'DATA ascii\n')
                    with self.assertRaises(ValueError):
                        run.load_raw_points(path)

    def test_bad_points_header_preserves_prepare_fault_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'7').mkdir()
            (tmp/'7/000002.pcd').write_text('FIELDS x y z\nPOINTS\nDATA ascii\n')
            path = tmp/'online.jsonl.gz'
            with data.atomic_rows(path) as write:
                write(dict(frame=2, index=0, timestamp=0., id=1, source_ids=[7],
                    key=['a', 2, 1], job_id='a', newborn=False,
                    query_geometry=dict(xyz=[0, 0, 0], yaw=0)))
            spec = dict(parent='A', split='cal', receiver_id=7, root=str(tmp),
                        detections=str(tmp), frames=[2])
            config = dict(parents=[spec, dict(spec, parent='FIT', split='fit')], jobs=[
                dict(job_id='a', parent='A', kind='clean', online_path=str(path)),
                dict(job_id='fit', parent='FIT', kind='clean', online_path=str(path))])
            packet = dict(frame=2, index=0, timestamp=0., pose=[0]*6,
                boxes=[dict(id=100, xyz=[0, 0, 0], yaw=0., hwl=[1, 1, 1],
                            fresh=True, obj_type='car', timestamp=0.)])
            with patch.object(run, 'receiver_frames', side_effect=lambda spec: iter([packet])):
                result = run.prepare(config, tmp/'out')
            rows = list(data.read_rows(tmp/'out/jobs/a/local.jsonl.gz'))
            self.assertEqual(result['status'], 'COMPLETE')
            self.assertEqual([row['key'] for row in rows], [['a', 2, 1]])
            self.assertTrue(rows[0]['input_fault'])
            self.assertEqual(rows[0]['status'], 'input_fault')
            self.assertIsNone(rows[0]['I'])
            self.assertIsNone(rows[0]['F'])
            self.assertFalse(rows[0]['I_eligible'])
            self.assertFalse(rows[0]['F_eligible'])

    def test_native_receiver_only_uses_declared_frozen_ego(self):
        with tempfile.TemporaryDirectory() as tmp:
            for frame in [2, 4, 6]:
                np.savez(Path(tmp)/('%06d_7.npz'%frame),
                    lidar_pose=np.array([10., 5., 2., 0., 33., 0.]),
                    boxes=np.array([[5., 0., -1., 4., 2., 1.5, .2]]),
                    scores=np.array([.9]), checkpoint_sha256=np.array(run.native_adapter.CHECKPOINT))
            spec = dict(detections=tmp, receiver_id=7, frames=[2, 4, 6])
            packets = list(run.receiver_frames(spec))
            self.assertEqual(len(packets), 3)
            self.assertTrue(all(p['fault'] is None for p in packets))
            self.assertGreater(sum(len(p['boxes']) for p in packets), 0)
            for p in packets:
                for box in p['boxes']:
                    self.assertTrue(box['fresh'])
                    # Confirm geometry reconstruction agrees with native corners,
                    # including native yaw sign and bottom anchor.
                    from scripts.rq1_trusted_receiver.local import _polygon
                    from shapely.geometry import MultiPoint
                    native_polygon = MultiPoint(np.array(box['corners'])[:, :2]).convex_hull
                    self.assertAlmostEqual(_polygon(box, box['hwl']).intersection(native_polygon).area,
                                           native_polygon.area, places=6)


if __name__ == '__main__':
    unittest.main()
