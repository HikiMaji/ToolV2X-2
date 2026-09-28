"""Offline orchestration contracts; fixture predictions are not model evidence."""
import copy
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from planning.codriving_native_inputs import NativeInputSpec,sample_binding


class ProbePipelineTests(unittest.TestCase):
    def setUp(self):
        from test_codriving_causal_context import frames
        from planning.codriving_causal_context import build_context
        rows=frames()
        for row in rows:row['frame']+=4
        self.context=build_context(rows,scene='route05',source='ego_vehicle_1',receiver='ego_vehicle_0',decision_frame=6,spec=NativeInputSpec())
        self.sample=sample_binding('route05','ego_vehicle_0',2,NativeInputSpec())
        self.calls=[]

    def predictor(self,window):
        self.calls.append(window['track_ids'].tolist())
        n=len(window['track_ids']);xy=window['states'][:,-1,:2]
        return dict(track_ids=window['track_ids'].copy(),states=window['states'][:,-1].copy(),
            means=np.tile(xy[:,None,None,:],(1,6,50,1)),scores=np.tile([1.,0.,0.,0.,0.,0.],(n,1)),
            model_used=np.ones(n,bool))

    def test_p_never_runs_predictor_and_binds_to_actual_decision(self):
        from planning.codriving_native_inputs import raster_for_sample
        r=raster_for_sample(self.sample,self.context,tool='P',target_ids=[1],predictor=self.predictor)
        self.assertEqual(self.calls,[])
        self.assertEqual(r['sample_key'],dict(scene='route05',receiver='ego_vehicle_0',decision_frame=6))
        self.assertGreater(np.count_nonzero(r['P']),0)
        self.assertEqual(np.count_nonzero(r['F']),0)
        self.assertAlmostEqual(r['decision_time'],1.2)

    def test_f_predicts_all_context_before_selecting_returned_targets(self):
        from planning.codriving_native_inputs import raster_for_sample
        before=copy.deepcopy(self.context)
        r=raster_for_sample(self.sample,self.context,tool='F',target_ids=[1],predictor=self.predictor,
                            predictor_version=dict(name='fixture',revision='contract_only'))
        self.assertEqual(self.calls,[[1,2,3]])
        self.assertEqual(r['audit']['f_targets'],['ego_vehicle_1:1'])
        self.assertGreater(np.count_nonzero(r['F']),0)
        self.assertEqual(np.count_nonzero(r['P']),0)
        self.assertEqual(self.context,before)

    def test_mismatched_binding_and_predictor_target_arrays_rejected(self):
        from planning.codriving_native_inputs import raster_for_sample
        wrong=dict(self.context,g=2)
        with self.assertRaises(ValueError):raster_for_sample(self.sample,wrong,tool='P',target_ids=[1])
        def bad(w):
            r=self.predictor(w);r['track_ids']=r['track_ids'][::-1];return r
        with self.assertRaises(ValueError):raster_for_sample(self.sample,self.context,tool='F',target_ids=[1],predictor=bad,predictor_version=dict(name='fixture',revision='test'))

    def test_batch_connector_uses_subset_identity_and_preserves_original_inputs(self):
        from types import SimpleNamespace
        from planning.codriving_native_inputs import attach_context_batch
        dataset=SimpleNamespace(route_frames=[({'ego':'/data/route05/ego_vehicle_0'},2)])
        subset=SimpleNamespace(dataset=dataset,indices=[0])
        batch={'occupancy':np.zeros((1,5,6,192,96)), 'target':np.zeros((1,2))}
        linked=attach_context_batch(batch,subset,[0],[self.context],tool='P',target_ids=[[1]])
        self.assertIs(linked['occupancy'],batch['occupancy'])
        self.assertNotIn('toolv2x_pf_bev',batch)
        self.assertEqual(linked['toolv2x_sample_keys'][0]['decision_frame'],6)
        self.assertEqual(linked['toolv2x_pf_bev']['P'].shape,(1,5,192,96))
        with self.assertRaises(ValueError):attach_context_batch(batch,subset,[0],[],tool='P',target_ids=[[1]])

    def test_recording_split_rejects_adjacent_windows_and_shared_ego_recording(self):
        from planning.codriving_native_inputs import validate_recording_split
        with self.assertRaises(ValueError):validate_recording_split([self.sample],[dict(self.sample,start_frame=3)])
        with self.assertRaises(ValueError):validate_recording_split([self.sample],[dict(self.sample,receiver='ego_vehicle_1')])
        validate_recording_split([self.sample],[dict(self.sample,scene='independent_recording')])

    def test_forged_sample_start_and_labels_rejected(self):
        from planning.codriving_native_inputs import raster_for_sample
        for key,value in [('start_frame',200),('input_frames',[200,201,202,203,204]),('label_frames',[999])]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                raster_for_sample(dict(self.sample,**{key:value}),self.context,tool='P',target_ids=[1])

    def test_predictor_cannot_shrink_input_then_self_validate_output(self):
        from planning.codriving_native_inputs import raster_for_sample
        def shrinking(window):
            for key in ('track_ids','states','valid','scores','eligible'):
                window[key]=window[key][:1]
            return self.predictor(window)
        with self.assertRaises(ValueError):
            raster_for_sample(self.sample,self.context,tool='F',target_ids=[1],predictor=shrinking,
                              predictor_version=dict(name='fixture',revision='contract_only'))

    def test_empty_target_set_stays_empty_and_receiver_cannot_be_bought(self):
        from planning.codriving_native_inputs import raster_for_sample
        r=raster_for_sample(self.sample,self.context,tool='P',target_ids=[])
        self.assertEqual(np.count_nonzero(r['P']),0)
        with self.assertRaises(ValueError):raster_for_sample(self.sample,self.context,tool='P',target_ids=[2])

if __name__=='__main__':unittest.main()
