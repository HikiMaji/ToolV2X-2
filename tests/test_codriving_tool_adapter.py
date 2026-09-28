"""Contract tests for the optional torch evidence adapter."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    import torch
except Exception:
    torch = None


@unittest.skipUnless(torch is not None, 'torch model environment required')
class ToolEvidenceAdapterTests(unittest.TestCase):
    def setUp(self):
        from planning.codriving_tool_adapter import ToolEvidencePlanner

        class Base(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.offset = torch.nn.Parameter(torch.tensor(.125))

            def forward(self, inputs):
                return {'future_waypoints': inputs['base'] + self.offset}

        torch.manual_seed(7)
        self.base = Base()
        self.model = ToolEvidencePlanner(self.base, hidden=8, freeze_base=True)
        self.base_y = torch.full((2, 10, 2), .125)
        self.batch = {'base': torch.zeros(2, 10, 2), 'target': torch.zeros(2, 2)}
        self.side = {
            'P': torch.zeros(2, 5, 192, 96),
            'F': torch.zeros(2, 10, 192, 96),
            'F_CV': torch.zeros(2, 10, 192, 96),
            'F_valid': torch.ones(2, 10, dtype=torch.bool),
        }

    def test_frozen_base_stays_eval_when_adapter_trains(self):
        self.model.train()
        self.assertFalse(self.model.base_planner.training)
        self.assertTrue(self.model.adapter.training)

    def test_freeze_base_is_explicit_and_adapter_remains_trainable(self):
        self.assertTrue(all(not p.requires_grad for p in self.base.parameters()))
        self.assertTrue(any(p.requires_grad for p in self.model.adapter.parameters()))
        self.batch['toolv2x_pf_bev'] = self.side
        self.model(self.batch)['future_waypoints'].sum().backward()
        self.assertTrue(all(p.grad is None for p in self.base.parameters()))
        self.assertTrue(any(p.grad is not None for p in self.model.adapter.parameters()))

    def test_missing_evidence_is_exact_base(self):
        y = self.model(self.batch)['future_waypoints']
        torch.testing.assert_close(y, self.base_y, rtol=0, atol=0)

    def test_zero_initialized_evidence_is_exact_base(self):
        self.batch['toolv2x_pf_bev'] = self.side
        self.side['P'][:, 0, 40:60, 20:40] = 1.
        self.side['F'][:, :, 80:100, 10:30] = 1.
        y = self.model(self.batch)['future_waypoints']
        torch.testing.assert_close(y, self.base_y, rtol=0, atol=0)

    def test_synthetic_updates_learn_content_with_null_and_shuffle_controls(self):
        # Target and validity are shared: only P/F content can distinguish rows.
        # These tiny synthetic fits test dependency, not driving effectiveness.
        for branch in ('P', 'F', 'F_CV'):
            with self.subTest(branch=branch):
                self.setUp()
                self.model.forecast_variant = 'F_CV' if branch == 'F_CV' else 'F'
                self.batch['target'].fill_(.5)
                channels = slice(0, 1) if branch == 'P' else slice(None)
                self.side[branch][0, channels, 16:40, 8:28] = 1.
                self.side[branch][1, channels, 70:134, 24:80] = 1.
                if branch != 'P':
                    other = 'F' if branch == 'F_CV' else 'F_CV'
                    self.side[other] = self.side[branch].flip(0)
                self.batch['toolv2x_pf_bev'] = self.side
                expected = self.base_y + torch.tensor([-.5, .5]).view(2, 1, 1)
                before = {k: v.clone() for k, v in self.base.state_dict().items()}
                initial = self.model(self.batch)['future_waypoints']
                torch.testing.assert_close(initial, self.base_y, rtol=0, atol=0)
                self.model.train()
                optimizer = torch.optim.Adam(self.model.parameters(), lr=.02)
                for _ in range(20):
                    optimizer.zero_grad()
                    output = self.model(self.batch)['future_waypoints']
                    loss = torch.nn.functional.mse_loss(output, expected)
                    loss.backward()
                    optimizer.step()
                self.model.eval()
                with torch.no_grad():
                    actual = self.model(self.batch)['future_waypoints']
                    null = {k: v.clone() for k, v in self.side.items()}
                    for key in ('P', 'F', 'F_CV'):
                        null[key].zero_()
                    empty = self.model(dict(self.batch, toolv2x_pf_bev=null))['future_waypoints']
                    shuffled = dict(self.side, **{branch: self.side[branch].flip(0)})
                    swapped = self.model(dict(self.batch, toolv2x_pf_bev=shuffled))['future_waypoints']
                    if branch != 'P':
                        self.model.forecast_variant = other
                        switched = self.model(self.batch)['future_waypoints']
                        torch.testing.assert_close(switched, swapped, rtol=0, atol=0)
                torch.testing.assert_close(empty, self.base_y, rtol=0, atol=0)
                torch.testing.assert_close(swapped, actual.flip(0), rtol=0, atol=0)
                mse = torch.nn.functional.mse_loss
                self.assertLess(float(mse(actual, expected)), float(mse(empty, expected)))
                self.assertLess(float(mse(actual, expected)), float(mse(swapped, expected)))
                self.assertFalse(torch.equal(actual, empty))
                self.assertFalse(self.base.training)
                self.assertTrue(all(p.grad is None for p in self.base.parameters()))
                for key, value in self.base.state_dict().items():
                    torch.testing.assert_close(value, before[key], rtol=0, atol=0)
                torch.testing.assert_close(self.model({'base': self.batch['base']})['future_waypoints'],
                                           self.base_y, rtol=0, atol=0)

    def test_target_and_validity_alone_cannot_generate_residual(self):
        # Arbitrary trained weights/biases must still cancel with matched metadata.
        with torch.no_grad():
            for parameter in self.model.adapter.parameters():
                parameter.uniform_(-.2, .2)
        self.batch['target'] = torch.tensor([[10., -5.], [-4., 2.]])
        self.side['F_valid'][0, 3:] = False
        self.batch['toolv2x_pf_bev'] = self.side
        for training in (True, False):
            self.model.train(training)
            output = self.model(self.batch)['future_waypoints']
            torch.testing.assert_close(output, self.base_y, rtol=0, atol=0)
            self.model.zero_grad()
            output.sum().backward()
            self.assertTrue(all(p.grad is None or torch.count_nonzero(p.grad) == 0
                                for p in self.model.adapter.parameters()))

    def test_negative_evidence_activations_retain_gradient(self):
        # ReLU kills every feature/gradient here, as in the audited checkpoint.
        for layer in (self.model.adapter.body[1], self.model.adapter.body[3],
                      self.model.adapter.head[1]):
            inputs = torch.full((2, 8), -1., requires_grad=True)
            layer(inputs.clone()).sum().backward()
            self.assertTrue(torch.all(inputs.grad > 0))

    def test_checkpoint_architecture_is_checked_for_adapter_and_wrapper_loads(self):
        for module, version_key in ((self.model.adapter, '_architecture_version'),
                                    (self.model, 'adapter._architecture_version')):
            state = module.state_dict()
            # Historical adapter.pt has no architecture marker.
            legacy = {k: v for k, v in state.items() if k != version_key}
            with self.assertRaisesRegex(RuntimeError, 'architecture version'):
                module.load_state_dict(legacy, strict=True)
            with self.assertRaisesRegex(RuntimeError, 'architecture version'):
                module.load_state_dict(legacy, strict=False)
            for invalid in (torch.tensor(1), torch.tensor(3), torch.tensor([2]), torch.tensor(2.)):
                with self.subTest(version=invalid):
                    wrong = dict(state, **{version_key: invalid})
                    with self.assertRaisesRegex(RuntimeError, 'architecture version'):
                        module.load_state_dict(wrong, strict=True)
            module.load_state_dict(state, strict=True)

    def test_numpy_and_tensor_sidecars_on_the_planner_device(self):
        devices = ['cpu'] + (['cuda'] if torch.cuda.is_available() else [])
        for device in devices:
            with self.subTest(device=device):
                self.model.to(device)
                batch = {k: v.to(device) for k, v in self.batch.items()}
                for side in ({k: v.numpy() for k, v in self.side.items()},
                             {k: v.to(device) for k, v in self.side.items()}):
                    batch['toolv2x_pf_bev'] = side
                    y = self.model(batch)['future_waypoints']
                    torch.testing.assert_close(y, self.base_y.to(device), rtol=0, atol=0)

    def test_bad_shapes_and_missing_validity_rejected(self):
        self.batch['toolv2x_pf_bev'] = dict(self.side, P=torch.zeros(2, 4, 192, 96))
        with self.assertRaises(ValueError):
            self.model(self.batch)
        self.batch['toolv2x_pf_bev'] = dict(self.side)
        del self.batch['toolv2x_pf_bev']['F_valid']
        with self.assertRaises(ValueError):
            self.model(self.batch)
        self.batch['toolv2x_pf_bev'] = dict(self.side, F=torch.zeros(2, 9, 192, 96),
                                          F_valid=torch.ones(2, 9, dtype=torch.bool))
        with self.assertRaises(ValueError):
            self.model(self.batch)
        self.batch['toolv2x_pf_bev'] = dict(self.side, P=torch.zeros(2, 5, 20, 96))
        with self.assertRaises(ValueError):
            self.model(self.batch)


if __name__ == '__main__':
    unittest.main()
