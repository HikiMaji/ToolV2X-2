"""Geometry and information-equivalent controls, no planner/model training."""
import copy
import unittest
import numpy as np


def target():
    return dict(source='peer',track='7',box=[10.,0.,4.,2.,0.],velocity=[2.,0.],
                velocity_valid=True,history=[dict(time=-.2,box=[9.6,0.,4.,2.,0.],valid=True)],
                refs=['test-receipt:anchor','test-receipt:history'])


class PFBEVTests(unittest.TestCase):
    def build(self,p=(),f=(),transform=None):
        from planning.codriving_pf_bev import rasterize_pf
        return rasterize_pf(p,f,np.eye(3) if transform is None else transform,
                            future_times=[.2,.4],time_binding='test fixture: 5Hz',decision_time=1.)

    def test_grid_forward_up_left_left_and_box_extent(self):
        r=self.build([target()]);p=r['P']
        self.assertEqual(p.shape,(5,192,96));self.assertEqual(p.dtype,np.float32)
        self.assertEqual(int(p[0].sum()),16*8)
        self.assertEqual(p[0,104,48],1.)
        t=target();t['box'][1]=4.;r=self.build([t]);self.assertEqual(r['P'][0,104,32],1.)
        self.assertEqual(r['P'][0,104,64],0.)

    def test_rigid_rotation_transforms_velocity_and_history(self):
        t=target();T=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
        r=self.build([t],transform=T);mask=r['P'][4]>0
        np.testing.assert_allclose(r['P'][2][mask],0.,atol=1e-6)
        np.testing.assert_allclose(r['P'][3][mask],2.)
        self.assertGreater(r['P'][1].sum(),0)

    def test_top1_and_cv_share_targets_anchor_shape_and_time_grid(self):
        t=target();f=copy.deepcopy(t);f['forecast_times']=[.2,.4]
        f['forecast']=[[[11.,0.],[12.,0.]],[[10.4,0.],[10.8,0.]]];f['forecast_scores']=[.1,.9]
        f['model_used']=True;r=self.build(f=[f]);np.testing.assert_array_equal(r['F'],r['F_CV'])
        self.assertEqual(r['audit']['selected_modes'],[1]);self.assertEqual(r['F'].shape,(2,192,96))
        self.assertEqual(r['audit']['f_targets'],['peer:7'])
        self.assertEqual(r['F_valid'].tolist(),[True,True])

    def test_no_extrapolation_or_fabricated_velocity(self):
        f=target();f.update(forecast_times=[.5,1.],forecast=[[[11.,0.],[12.,0.]]],forecast_scores=[1.],model_used=True)
        r=self.build(f=[f]);self.assertEqual(r['F_valid'].tolist(),[True,True]) # anchor -> .5 interpolation
        from planning.codriving_pf_bev import rasterize_pf
        r=rasterize_pf([], [f],np.eye(3),future_times=[.5,2.],time_binding='fixture',decision_time=1.)
        self.assertEqual(r['F_valid'].tolist(),[True,False]);self.assertEqual(r['F'][1].sum(),0.)
        f['velocity_valid']=False
        with self.assertRaises(ValueError):self.build(f=[f])

    def test_future_history_rejected_and_input_not_mutated(self):
        t=target();original=copy.deepcopy(t);self.build([t]);self.assertEqual(t,original)
        t['history'][0]['time']=.1
        with self.assertRaises(ValueError):self.build([t])

    def test_overlap_is_order_invariant_and_invalid_velocity_has_mask(self):
        a=target();b=target();b['track']='8';b['velocity']=[-3.,1.]
        np.testing.assert_array_equal(self.build([a,b])['P'],self.build([b,a])['P'])
        a['velocity_valid']=False;r=self.build([a]);self.assertEqual(r['P'][4].sum(),0.)
        self.assertGreater(r['P'][0].sum(),0.)

    def test_missing_refs_and_wrong_transform_rejected(self):
        t=target();t['refs']=[]
        with self.assertRaises(ValueError):self.build([t])
        with self.assertRaises(ValueError):self.build([target()],transform=np.diag([2.,1.,1.]))

    def test_stationary_cv_and_negative_velocity_keep_signed_values(self):
        t=target();t['velocity']=[-2.,1.];r=self.build([t]);mask=r['P'][4]>0
        self.assertTrue(np.all(r['P'][2][mask]==-2.));self.assertTrue(np.all(r['P'][3][mask]==1.))

    def test_empty_unknown_and_partial_forecast_are_distinguishable(self):
        empty=self.build();self.assertFalse(empty['audit']['evidence_presence']['F'])
        self.assertEqual(empty['F'].sum(),0.)
        f=target();f.update(forecast_times=[.2,.4],forecast=[[[11.,0.],[12.,0.]]],forecast_scores=[1.],model_used=False)
        r=self.build(f=[f]);self.assertEqual(r['audit']['model_used'],[False])

    def test_f_cv_differs_when_selected_prediction_turns(self):
        f=target();f.update(forecast_times=[.2,.4],forecast=[[[10.,2.],[10.,4.]]],forecast_scores=[1.],model_used=True)
        r=self.build(f=[f]);self.assertGreater(np.abs(r['F']-r['F_CV']).sum(),0.)

    def test_sidecar_preserves_original_planner_inputs(self):
        from planning.codriving_pf_bev import attach_pf_sidecar, rasterize_pf
        occupancy=np.zeros((1,5,6,192,96),np.float32)
        batch=dict(occupancy=occupancy,feature_warpped_list=['unchanged'],target=np.zeros((1,2)))
        raster=rasterize_pf([target()],[],np.eye(3),future_times=np.arange(1,11)*.2,time_binding='synthetic fixture',decision_time=1.)
        result=attach_pf_sidecar(batch,[raster])
        with self.assertRaises(ValueError):attach_pf_sidecar(batch,[self.build()])
        self.assertIs(result['occupancy'],occupancy)
        self.assertNotIn('toolv2x_pf_bev',batch)
        self.assertEqual(result['toolv2x_pf_bev']['P'].shape,(1,5,192,96))
        with self.assertRaises(ValueError):attach_pf_sidecar(dict(batch,occupancy=np.zeros((1,5,6,96,192))),[self.build()])
