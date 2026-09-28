# v3 diagnosis and v4 bounded retest evidence

Read ../../pdm_closedloop_diagnosis_2026_09_22.md for the result and limits.

- diagnose_v3.py / v3_diagnosis.json / v3_replays.jsonl: 320 exact original PDM replays plus 240 fixed-state interventions. These are not counterfactual closed-loop runs.
- v4_predeclared.json: frozen single-variable change, original stopping point, and secondary criteria.
- verify_control.py / v3_control_red.log / v4_control_check.log: both versions fail the secondary acceleration and sustained-low-speed diagnostics; the script reports both flags before assertions.
- summarize_runs.py / v3_v4_comparison.json / v3_v4_timeseries.csv / v3_v4_control.png: independent raw-frame recomputation and plotting.
- run_v4.sh / v4_run.log: successful finite execution; server must first be started using the existing CARLA runtime instructions, without changing HOME.
- v4_setup_failed.log / setup_failure.json: retained initialization error before any sensor/model/planner execution.
- v4_sources / source_check.json / v4_spec.json / v4_summary.json / v4_detector_metadata.json: actual runtime source and configuration; only probe version and longitudinal Kp differ from v3.
- pdm_tests.log / check_review.log / completion.json: fresh test and cleanup evidence.

Runtime output directories are never reused. The run script is archival: choose a new directory and predeclare scope before rerunning. Source snapshot probe_pdm_closedloop_v4.py and v4_sources are evidence, not independent runnable project roots.

Offline commands, from the ToolV2X root (existing dependencies):

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/conda-envs/pdm39/bin/python docs/evidence/pdm_closedloop_diagnosis_2026_09_22/diagnose_v3.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /root/autodl-tmp/conda-envs/pdm39/bin/python docs/evidence/pdm_closedloop_diagnosis_2026_09_22/summarize_runs.py
python docs/evidence/pdm_closedloop_diagnosis_2026_09_22/verify_control.py outputs/pdm_closedloop_2026_09_22_v4
```

The final command is expected to fail: secondary control diagnostics are not passed. No training or P/F method-effect claim.
