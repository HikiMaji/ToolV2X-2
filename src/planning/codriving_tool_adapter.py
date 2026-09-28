"""Small residual adapter that makes admitted P/F affect waypoint planning.

The official CoDriving planner remains the base module. This adapter does not
replace its occupancy or feature branches: it adds a separately trained,
zero-initialized, empty-content-centered residual on the ToolV2X BEV sidecar.
F future maps are never treated as the original five historical frames.
"""
try:
    import torch
    from torch import nn
except ImportError:  # resource-independent contract tests can import the package
    torch = None
    nn = None


ADAPTER_ARCHITECTURE_VERSION = 2


def _require_torch():
    if torch is None:
        raise RuntimeError('the ToolV2X planner adapter requires the torch model environment')


if nn is not None:
    class _EvidenceEncoder(nn.Module):
        def __init__(self, in_channels, hidden):
            super().__init__()
            self.register_buffer('_architecture_version',
                                 torch.tensor(ADAPTER_ARCHITECTURE_VERSION, dtype=torch.int64))
            self.body = nn.Sequential(
                nn.Conv2d(in_channels, hidden, kernel_size=5, stride=4, padding=2),
                nn.LeakyReLU(negative_slope=.1, inplace=True),
                nn.Conv2d(hidden, hidden, kernel_size=5, stride=4, padding=2),
                nn.LeakyReLU(negative_slope=.1, inplace=True),
                nn.AdaptiveAvgPool2d(1),
            )
            self.head = nn.Sequential(
                nn.Linear(hidden + 2, hidden), nn.LeakyReLU(negative_slope=.1, inplace=True),
                nn.Linear(hidden, 20),
            )
            # Ego behavior is exactly preserved before adapter training.
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict,
                                  missing_keys, unexpected_keys, error_msgs):
            # Activation/centering changes cannot reinterpret old adapter.pt weights.
            # This hook also guards full-wrapper loads and strict=False callers.
            version = state_dict.get(prefix + '_architecture_version')
            if (not torch.is_tensor(version) or version.shape != torch.Size([])
                    or version.dtype != torch.int64
                    or version.item() != ADAPTER_ARCHITECTURE_VERSION):
                raise RuntimeError(
                    'unsupported evidence adapter architecture version; expected {}. '
                    'Replay legacy adapter.pt with its original implementation; '
                    'do not relabel old weights as v2.'.format(ADAPTER_ARCHITECTURE_VERSION))
            super()._load_from_state_dict(state_dict, prefix, local_metadata, strict,
                                          missing_keys, unexpected_keys, error_msgs)

        def forward(self, evidence, target, forecast_variant):
            required = {'P', 'F', 'F_CV', 'F_valid'}
            if not isinstance(evidence, dict) or not required <= set(evidence):
                raise ValueError('P/F/F_CV/F_valid sidecar is required')
            p, f = evidence['P'], evidence[forecast_variant]
            valid = evidence['F_valid']
            device = target.device
            p = p if torch.is_tensor(p) else torch.as_tensor(p, device=device)
            f = f if torch.is_tensor(f) else torch.as_tensor(f, device=device)
            valid = valid if torch.is_tensor(valid) else torch.as_tensor(valid, device=device)
            if (p.ndim != 4 or p.shape[1] != 5 or f.ndim != 4 or f.shape[1] != 10
                    or p.shape[2:] != (192, 96) or f.shape[2:] != (192, 96) or valid.ndim != 2):
                raise ValueError('invalid P/F sidecar rank or channel count')
            if p.shape[0] != f.shape[0] or f.shape[0] != valid.shape[0] or f.shape[1] != valid.shape[1]:
                raise ValueError('P/F batch and horizon mismatch')
            if p.shape[2:] != f.shape[2:]:
                raise ValueError('P/F grids must match')
            if target.shape != (p.shape[0], 2):
                raise ValueError('target shape must match sidecar batch')
            # P: occupancy/history/valid are binary; velocity remains m/s.
            p = p.float().clone()
            p[:, 2:4] = p[:, 2:4].clamp(-20., 20.) / 20.
            f = f.float() * valid.float().unsqueeze(-1).unsqueeze(-1)
            valid_map = valid.float().unsqueeze(-1).unsqueeze(-1).expand_as(f)
            x = torch.cat((p, f, valid_map), dim=1)
            # All five P channels are content, including spatial velocity support.
            # Retain only the global F_valid metadata in the matched null input.
            empty = torch.cat((torch.zeros_like(p), torch.zeros_like(f), valid_map), dim=1)
            pooled = self.body(x).flatten(1)
            empty_pooled = self.body(empty).flatten(1)
            output = self.head(torch.cat((pooled, target.float()), dim=1))
            reference = self.head(torch.cat((empty_pooled, target.float()), dim=1))
            return (output - reference).view(-1, 10, 2)


    class ToolEvidencePlanner(nn.Module):
        """Wrap an official waypoint planner with a trainable P/F residual.

        `base_planner` is kept intact and may be frozen. Missing sidecar means
        exact base behavior. Empty content also gives exact base behavior after
        updates: h(content, target) - h(empty, target), with matched F_valid.
        The `F`/`F_CV` switch changes only the forecast evidence branch and is
        recorded for paired evaluation.
        """
        def __init__(self, base_planner, *, hidden=32, forecast_variant='F', freeze_base=True):
            super().__init__()
            if type(freeze_base) is not bool:
                raise ValueError('freeze_base must be boolean')
            if not isinstance(base_planner, nn.Module):
                raise ValueError('base planner module required')
            if forecast_variant not in ('F', 'F_CV'):
                raise ValueError('forecast_variant must be F or F_CV')
            self.base_planner = base_planner
            self.freeze_base = freeze_base
            if freeze_base:
                for parameter in self.base_planner.parameters():
                    parameter.requires_grad_(False)
                self.base_planner.eval()
            self.adapter = _EvidenceEncoder(5 + 10 + 10, hidden)
            self.forecast_variant = forecast_variant

        def train(self, mode=True):
            super().train(mode)
            if self.freeze_base:
                self.base_planner.eval()
            return self

        def forward(self, input_data):
            if not isinstance(input_data, dict):
                raise ValueError('planner input dictionary required')
            result = self.base_planner(input_data)
            if not isinstance(result, dict) or 'future_waypoints' not in result:
                raise ValueError('base planner must return future_waypoints')
            evidence = input_data.get('toolv2x_pf_bev')
            if evidence is None:
                return result
            residual = self.adapter(evidence, input_data['target'], self.forecast_variant)
            output = dict(result)
            output['future_waypoints'] = result['future_waypoints'] + residual
            return output
else:
    class ToolEvidencePlanner:  # pragma: no cover - only an importable stub without torch
        def __init__(self, *args, **kwargs):
            _require_torch()
