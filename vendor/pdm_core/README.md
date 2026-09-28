# Original PDM core

Source: autonomousvision/tuplan_garage, local upstream snapshot dated 2026-09-19. Apache-2.0 license is included. SOURCE.json lists the 26 retained files and three adaptations; exact diff is in docs/evidence/pdm_core_2026_09_22/upstream_diff.patch.

The original IDM, proposal generator, simulator, scoring and emergency brake are retained. Observation exposes time-indexed object_at; generator/scorer use it for future velocity, collision state and heading. Open/Hybrid models are not included.

Runtime verified with Python 3.9.25 and official nuplan-devkit v1.2 (package 1.2.0). Full installed dependency versions are in docs/evidence/pdm_core_2026_09_22/environment.txt. Local interpreter: /root/autodl-tmp/conda-envs/pdm39/bin/python. This is a numerical core adapter, not a complete CARLA planner deployment.

Run from repository root:

```bash
PYTHONPATH=src:tests /root/autodl-tmp/conda-envs/pdm39/bin/python -m unittest test_pdm_core test_v2xverse_inputs -v
```

Set TOOLV2X_PDM_REFERENCE_ROOT to a pristine tuplan_garage source root to enable the additional independent upstream equivalence check. TOOLV2X_PDM_SOURCE_ROOT locates alternate source code; neither path is a model or context semantic identity.
