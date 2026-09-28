"""Run the explicit NumPy/SciPy review suite; full integration is a separate command."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'src'))

names = [
    'test_codriving_native_inputs', 'test_codriving_causal_context', 'test_codriving_probe_pipeline', 'test_prepare_codriving_native_probe',
    'test_codriving_pf_bev', 'test_codriving_ledger_bev', 'test_native_task', 'test_codriving_tool_adapter',
    'test_pdm_control',
    'test_lidar_tracks.GeometryTests', 'test_carla_map_inputs', 'test_v2xverse_detector_probe', 'test_v2xverse_inputs', 'test_pdm_core.PDMModuleTests',
    'test_driver_readiness_preparation', 'test_structured_inputs', 'test_structured_admission', 'test_compact_evidence', 'test_planning_inputs', 'test_protocol',
    'test_task_spec', 'test_vehicle_tools', 'test_evidence_ledger', 'test_method_episode', 'test_method_evaluation', 'test_decision_accounting', 'test_method_controls.ControlTests', 'test_control_bundle', 'test_vehicle_probe', 'test_learned_probe',
    'test_review_portability', 'test_saved_review_evidence', 'test_wire_comparison',
    'test_prediction_evaluation', 'test_planning_evaluation',
    'test_evidence_audit', 'test_budget_review', 'test_query_data',
    'test_query_value.FeatureTests', 'test_query_value.DatasetTests',
    'test_query_value.BundleFeatureTests', 'test_query_value.TrainingAuditTests',
    'test_query_value.MetadataBindingTests',
    'test_bundle_data.BundlePrefixTests', 'test_bundle_data.BundleDataTests',
    'test_bundle_data.RuntimeIdentityTests', 'test_method_run_spec', 'test_t9_admission',
    'test_paired_driving.PairedInputTests',
    'test_framework_episode.EpisodeTests', 'test_framework_pipeline',
    'test_direct_planning.DirectPlanningInputTests',
    'test_mtr_supervision.MTRSupervisionTests.test_current_geometry_gates_and_ego_exclusion_leave_targets_in_ledger',
    'test_mtr_supervision.MTRSupervisionTests.test_labels_match_current_only_keep_missing_and_preserve_inputs',
    'test_adaptation_data.AdaptationDataTests.test_native_labels_use_six_future_poses_in_fixed_current_frame',
    'test_adaptation_data.AdaptationDataTests.test_missing_or_cross_record_future_keeps_mask_without_fabricating_label',
    'test_adaptation_data.AdaptationDataTests.test_supervised_q9_uses_generated_parent_even_when_q9_prediction_failed',
]

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if 'torch' in sys.modules or 'transformers' in sys.modules:
        raise RuntimeError('review suite unexpectedly imported a model dependency')
    sys.exit(0 if result.wasSuccessful() else 1)
