"""Tensor interventions are diagnostics; these tests are not driving evidence."""
import sys
from pathlib import Path
import unittest

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from evaluation.structured_evidence import with_prior, without_evidence, paired_effect


def batch():
    return dict(previous_plan=torch.full((1, 6, 2), 99.),
        previous_plan_valid=torch.ones((1, 6), dtype=torch.bool),
        observations=torch.ones((1, 2, 2, 11, 10)),
        observation_mask=torch.tensor([[[[True]*11, [True]*11],
                                        [[False]*11, [True]*11]]]),
        observation_sources=torch.tensor([[[0, 1], [0, 1]]]),
        forecasts=torch.ones((1, 2, 2, 6, 6, 5)),
        forecast_mask=torch.ones((1, 2, 2, 6, 6), dtype=torch.bool),
        forecast_context=torch.tensor([[[[1., 1.], [0., 1.]], [[0., 1.], [0., 1.]]]]),
        entity_mask=torch.ones((1, 2), dtype=torch.bool),
        scene_patches=torch.ones((1, 2, 220, 320)),
        scene_mask=torch.ones((1, 2, 220), dtype=torch.bool),
        ego_motion=torch.ones((1, 4)), ego_history=torch.ones((1, 11, 4)),
        ego_history_mask=torch.ones((1, 11), dtype=torch.bool))


class EvidenceDiagnosticTests(unittest.TestCase):
    def test_prior_is_replaced_without_mutating_archive_batch(self):
        original = batch()
        clean = with_prior(original, None)
        self.assertEqual(clean['previous_plan'].count_nonzero().item(), 0)
        self.assertFalse(clean['previous_plan_valid'].any())
        self.assertEqual(original['previous_plan'][0, 0, 0].item(), 99.)
        prior = torch.arange(12.).reshape(1, 6, 2)
        changed = with_prior(original, prior)
        prior.fill_(0)
        self.assertEqual(changed['previous_plan'][0, -1, -1].item(), 11.)

    def test_remote_removal_keeps_local_and_removes_remote_only_entity(self):
        original = batch()
        stripped = without_evidence(original, 'remote')
        self.assertTrue(torch.equal(stripped['observation_mask'][0, 0, 0],
                                    original['observation_mask'][0, 0, 0]))
        self.assertFalse(stripped['observation_mask'][0, :, 1].any())
        self.assertTrue(stripped['forecast_mask'][0, 0, 0].all())
        self.assertFalse(stripped['forecast_mask'][0, 0, 1].any())
        self.assertFalse(stripped['entity_mask'][0, 1])
        self.assertTrue(original['entity_mask'].all())
        self.assertTrue(torch.equal(stripped['previous_plan'], original['previous_plan']))

    def test_environment_removal_preserves_motion_and_prior(self):
        original = batch()
        stripped = without_evidence(original, 'environment')
        for key in ('scene_mask', 'entity_mask', 'observation_mask', 'forecast_mask'):
            self.assertFalse(stripped[key].any(), key)
        for key in ('ego_history', 'ego_motion', 'previous_plan'):
            self.assertTrue(torch.equal(stripped[key], original[key]))

    def test_equal_average_error_does_not_mean_equal_trajectories(self):
        a = dict(waypoints=[[1., 0.]]*6, metrics={'ADE3': 1.}, valid_plan=True)
        b = dict(waypoints=[[-1., 0.]]*6, metrics={'ADE3': 1.}, valid_plan=True)
        result = paired_effect(a, b, .01)
        self.assertEqual(result['ade_delta_m'], 0.)
        self.assertEqual(result['trajectory_mean_delta_m'], 2.)
        self.assertEqual(result['outcome'], 'within_threshold')

    def test_invalid_output_is_not_silently_a_pair(self):
        a = dict(waypoints=[[1., 0.]]*6, metrics={'ADE3': 1.}, valid_plan=False)
        b = dict(waypoints=[[1., 0.]]*6, metrics={'ADE3': 1.}, valid_plan=True)
        self.assertEqual(paired_effect(a, b, .01)['outcome'], 'invalid_pair')


if __name__ == '__main__':
    unittest.main()
