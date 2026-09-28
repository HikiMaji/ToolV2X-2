"""Causal input contracts only: no detector, tracker, or MTR model is run."""
import copy
import importlib
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def measurement(x, y=0., theta=math.pi / 2):
    return dict(x=x, y=y, theta=theta, lidar_pose_x=x-1.3, lidar_pose_y=y)


def track(ident, x, y=0., yaw=0., hit=True):
    return dict(id=ident, box=[x, y, 0., 4., 2., 1.5, yaw],
                velocity=[0., 0.], velocity_observed=True, detector_hit=hit,
                score=.8, parent_refs=['local_detection_frame:0'])


def frames():
    return [dict(frame=i, scene='route05', source='ego_vehicle_1', receiver='ego_vehicle_0',
                 source_measurement=measurement(float(i)), receiver_measurement=measurement(20.),
                 tracks=[track(1, 10., hit=i != 1), track(2, 20.), track(3, 100.)])
            for i in range(3)]


class CausalContextTests(unittest.TestCase):
    def setUp(self):
        name = 'planning.codriving_causal_context'
        self.assertIsNotNone(importlib.util.find_spec(name), 'causal context implementation is absent')
        self.module = importlib.import_module(name)
        self.spec = importlib.import_module('planning.codriving_native_inputs').NativeInputSpec()

    def build(self, values=None, **kwargs):
        return self.module.build_context(frames() if values is None else values,
            scene='route05', source='ego_vehicle_1', receiver='ego_vehicle_0',
            decision_frame=2, spec=self.spec, **kwargs)

    def test_fixed_current_source_frame_does_not_create_ego_motion(self):
        values = frames(); before = copy.deepcopy(values)
        context = self.build(values)
        np.testing.assert_allclose(np.asarray(context['states'])[0, -3:, :2], [[8., 0.]] * 3, atol=1e-10)
        self.assertEqual(values, before)
        self.assertEqual(context['coordinate_frame'], 'source_actor_at_t')
        self.assertEqual(context['axes'], 'x_forward_y_left')
        self.assertEqual(context['decision_time'], .4)
        self.assertEqual(context['execution_spec']['history_steps'], 11)
        self.assertEqual(json.loads(json.dumps(context)), context)

    def test_complete_context_retains_receiver_unselected_and_distant_tracks(self):
        context = self.build()
        self.assertEqual(context['track_ids'], [1, 2, 3])
        self.assertEqual(context['receiver_track_ids'], [2])
        window = self.module.to_mtr_window(context)
        self.assertEqual(window['track_ids'].tolist(), [1, 2, 3])
        self.assertEqual(window['states'].shape, (3, 11, 7))
        self.assertAlmostEqual(window['states'][2, -1, 0], 98.)
        p = self.module.records_for_targets(context, [1])
        self.assertEqual([row['track'] for row in p], ['1'])
        self.assertEqual(context['track_ids'], [1, 2, 3])
        from tools.task_spec import _check_window
        _check_window(window)

    def test_tracker_state_validity_differs_from_detector_hit(self):
        context = self.build()
        self.assertEqual(context['valid'][0], [False] * 8 + [True] * 3)
        self.assertEqual(context['detector_hit'][0], [False] * 8 + [True, False, True])
        np.testing.assert_array_equal(np.asarray(context['states'])[0, :8], np.zeros((8, 7)))
        self.assertEqual(context['scores'][0][:8], [0.] * 8)
        p = self.module.records_for_targets(context, [1])[0]
        self.assertTrue(p['velocity_valid'])
        np.testing.assert_allclose(p['velocity'], [0., 0.], atol=1e-10)

    def test_actual_missing_track_slot_is_not_interpolated(self):
        values = frames(); values[1]['tracks'] = values[1]['tracks'][1:]
        context = self.build(values); window = self.module.to_mtr_window(context)
        self.assertEqual(window['valid'][0].tolist(), [False] * 6 + [True, False, False, False, True])
        np.testing.assert_array_equal(window['states'][0, 7:10], np.zeros((3, 7)))
        self.assertTrue(window['valid'][1, -5:].all())

    def test_adjacent_native_states_interpolate_wrapped_yaw_without_extrapolation(self):
        values = frames()[1:]
        values[0]['tracks'][0] = track(1, 10., yaw=math.radians(179.))
        values[1]['tracks'][0] = track(1, 12., yaw=math.radians(-179.))
        window = self.module.to_mtr_window(self.build(values))
        self.assertEqual(window['valid'][0].tolist(), [False] * 8 + [True] * 3)
        np.testing.assert_allclose(window['states'][0, -3:, 0], [8., 9., 10.])
        self.assertAlmostEqual(abs(window['states'][0, -2, 6]), math.pi)
        np.testing.assert_allclose(window['time_seconds'], np.arange(-10, 1) * .1)
        self.assertEqual(window['scores'][0, -2], .8)

    def test_current_only_track_has_invalid_velocity_and_keeps_current_mtr_slot(self):
        values = frames(); values[0]['tracks'] = []; values[1]['tracks'] = []
        context = self.build(values)
        p = self.module.records_for_targets(context, [1])[0]
        self.assertFalse(p['velocity_valid'])
        self.assertEqual(p['velocity'], [0., 0.])
        window = self.module.to_mtr_window(context)
        self.assertEqual(window['valid'][0].tolist(), [False] * 10 + [True])
        self.assertFalse(window['eligible'].any())

    def test_rejects_future_missing_decision_frame_holes_and_out_of_order(self):
        cases = [frames()[:2], frames()[::2], list(reversed(frames())), frames() + [dict(frames()[-1], frame=3)]]
        for values in cases:
            with self.subTest(frames=[v['frame'] for v in values]), self.assertRaises(ValueError):
                self.build(values)

    def test_rejects_mixed_scene_source_receiver_and_duplicate_ids(self):
        for key, value in [('scene', 'other'), ('source', 'ego_vehicle_4'), ('receiver', 'ego_vehicle_4')]:
            values = frames(); values[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.build(values)
        values = frames(); values[1]['tracks'].append(copy.deepcopy(values[1]['tracks'][0]))
        with self.assertRaises(ValueError): self.build(values)

    def test_rejects_receiver_unknown_or_duplicate_purchases(self):
        context = self.build()
        for targets in [[2], [99], [1, 1]]:
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                self.module.records_for_targets(context, targets)

    def test_provenance_is_bound_to_actual_scene_source_epoch_and_context(self):
        context = self.build(); record = self.module.records_for_targets(context, [1])[0]
        self.assertEqual({r['field_kind'] for r in record['refs']}, {'anchor', 'history'})
        for ref in record['refs']:
            self.assertEqual((ref['scene'], ref['provider'], ref['g'], ref['track_handle']),
                             ('route05', 'ego_vehicle_1', 2, 1))
            self.assertEqual(ref['context_version'], context['context_version'])
            self.assertTrue(ref['producer_version'])
            self.assertNotIn('/root', json.dumps(ref))
        self.assertIn('route05', context['context_version'])
        self.assertEqual(len(record['history']), 11)
        self.assertEqual(record['history'][-1]['box'], record['box'])

    def test_changed_scene_or_history_cannot_keep_stale_provenance(self):
        context = self.build()
        for change in [lambda c: c.update(scene='route11'),
                       lambda c: c.update(decision_time=.8),
                       lambda c: c['states'][0][-1].__setitem__(0, 99.)]:
            bad = copy.deepcopy(context); change(bad)
            with self.assertRaises(ValueError): self.module.to_mtr_window(bad)
            with self.assertRaises(ValueError): self.module.records_for_targets(bad, [1])

    def test_velocity_uses_native_seconds_across_missing_slots(self):
        values = frames(); values[1]['tracks'] = values[1]['tracks'][1:]
        values[-1]['tracks'][0]['box'][0] = 12.
        record = self.module.records_for_targets(self.build(values), [1])[0]
        self.assertTrue(record['velocity_valid'])
        np.testing.assert_allclose(record['velocity'], [5., 0.], atol=1e-10)

    def test_no_current_tracks_produces_empty_evidence_without_old_track_resurrection(self):
        values = frames(); values[-1]['tracks'] = []
        context = self.build(values)
        self.assertEqual(context['track_ids'], [])
        self.assertEqual(self.module.records_for_targets(context, []), [])
        window = self.module.to_mtr_window(context)
        self.assertEqual(window['states'].shape, (0, 11, 7))
        from tools.task_spec import _check_window
        _check_window(window)


if __name__ == '__main__':
    unittest.main()
