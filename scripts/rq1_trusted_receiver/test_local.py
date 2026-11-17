import unittest
import numpy as np

from scripts.rq1_trusted_receiver.local import measure_local, measure_frame


def query(x=0., y=0., yaw=0., tid=1):
    return dict(id=tid, xyz=[x, y, 0.], yaw=yaw, timestamp=0., obj_type='car')


def box(x=0., y=0., tid=10, **kwargs):
    return dict(query(x, y, tid=tid), hwl=[1., 1., 1.], fresh=True, **kwargs)


class LocalGeometryTests(unittest.TestCase):
    def measure(self, points, origin=(-2., 0., .125), q=None, boxes=(), shape=(1., 1., 1.)):
        return measure_local(query() if q is None else q, boxes, origin, points, shape)

    def test_before_inside_after(self):
        self.assertEqual(self.measure([[-1., 0., .125]])['F'], 0.)
        inside = self.measure([[0., 0., .125]])
        self.assertEqual(inside['n_free'], 2)
        self.assertEqual(inside['n_occupied'], 1)
        after = self.measure([[2., 0., .125]])
        self.assertEqual(after['n_free'], 4)
        self.assertAlmostEqual(after['F'], 4 / 64)

    def test_empty_is_valid_but_missing_is_fault(self):
        empty = self.measure(np.empty((0, 3)))
        self.assertEqual(empty['F'], 0.)
        self.assertTrue(empty['F_eligible'])
        self.assertEqual(empty['F_status'], 'no_coverage')
        missing = self.measure(None)
        self.assertIsNone(missing['F'])
        self.assertTrue(missing['input_fault'])
        self.assertTrue(self.measure([[float('nan'), 0, 0]])['input_fault'])

    def test_occupied_wins_across_rays_and_endpoint_boundary(self):
        r = self.measure([[2., 0., .125], [0., 0., .125]])
        self.assertEqual((r['n_free'], r['n_occupied']), (3, 1))
        outer = self.measure([[.5, 0., .125]])
        self.assertEqual((outer['n_free'], outer['n_occupied']), (3, 1))

    def test_truncated_last_cell_uses_actual_volume(self):
        r = self.measure([[2., .125, .125]], origin=(-2., .125, .125), shape=(.3, .3, .6))
        self.assertEqual(r['n_free'], 3)
        self.assertAlmostEqual(r['F'], .6 * .05 * .25 / (.3 * .3 * .6))

    def test_rotation_translation_invariance(self):
        base = self.measure([[2., 0., .125]])
        angle = .73
        c, s = np.cos(angle), np.sin(angle)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        offset = np.array([17., -6., 2.])
        q = query(yaw=angle)
        q['xyz'] = offset.tolist()
        actual = self.measure(np.array([[2., 0., .125]]) @ rot.T + offset,
            origin=np.array([-2., 0., .125]) @ rot.T + offset, q=q)
        self.assertEqual(base['n_free'], actual['n_free'])
        self.assertAlmostEqual(base['F'], actual['F'])

    def test_corner_graze_and_sparse_ray(self):
        r = self.measure([[0., 1., .125]], origin=(-1., 0., .125))
        self.assertEqual(r['n_free'], 0)
        sparse = self.measure([[2., .01, .125]])
        self.assertLessEqual(sparse['n_free'], 5)

    def test_support_requires_fresh_compatible_unique_match(self):
        self.assertEqual(self.measure([], boxes=[box()])['I'], 1.)
        self.assertIsNone(self.measure([], boxes=[dict(box(), fresh=False)])['I'])
        self.assertIsNone(self.measure([], boxes=[dict(box(), obj_type='pedestrian')])['I'])
        self.assertIsNone(self.measure([], boxes=[box(), box(tid=11)])['I'])
        self.assertIsNone(self.measure([], boxes=[box(x=3.1)])['I'])
        self.assertIsNone(self.measure([], boxes=[dict(box(), timestamp=.1)])['I'])

    def test_bidirectional_ambiguity_is_per_job_frame(self):
        r = measure_frame([query(tid=1), query(x=.1, tid=2)], [box()],
            [-2, 0, .125], [], [1, 1, 1])
        self.assertTrue(all(v['I'] is None for v in r))
        self.assertTrue(all(v['I_status'] == 'ambiguous' for v in r))

    def test_cached_free_score_does_not_cache_job_matching(self):
        cache = {}
        args = ([box()], [-2, 0, .125], [[2, 0, .125]], [1, 1, 1])
        a = measure_frame([query(tid=1), query(tid=2)], *args, free_cache=cache)
        b = measure_frame([query(tid=1)], *args, free_cache=cache)
        self.assertEqual(len(cache), 1)
        self.assertIsNone(a[0]['I'])
        self.assertEqual(b[0]['I'], 1.)
        self.assertEqual(a[0]['F'], b[0]['F'])

    def test_no_query_unknown_and_invalid_shape_stops(self):
        self.assertEqual(self.measure([], q={})['status'], 'input_fault')
        self.assertEqual(measure_local(None, [], [-2, 0, 0], [], [1, 1, 1])['status'], 'no_query')
        with self.assertRaises(ValueError):
            self.measure([], shape=None)


if __name__ == '__main__':
    unittest.main()
