"""Native-time protocol contracts; fixture forecast is NOT model evidence."""
import copy
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_task_spec import task_request,provenance
from test_vehicle_tools import window
from tools.vehicle import VehicleTools,decode_task_response
from tools.task_spec import FrozenPredictor
from planning.evidence import new_ledger,apply_response,known_field_manifest
from planning.codriving_ledger_bev import records_from_ledger
from planning.codriving_pf_bev import rasterize_pf

def native_window(source='peer'):
    w=window(source);w['time_seconds']=np.arange(-10,1)*.2
    w['states'][0,:,0]=2+3*w['time_seconds']
    return w

def prediction(w):
    times=np.arange(1,11)*.2
    return dict(track_ids=w['track_ids'].copy(),states=w['states'][:,-1].copy(),
        means=np.repeat(w['states'][:,None,-1:,:2],10,axis=2),
        scores=np.ones((len(w['track_ids']),1)),model_used=w['valid'].sum(axis=1)>=2,
        forecast_times=times)

def request(tool='P',**kw):
    r=task_request(tool=tool,max_request_bytes=30000,max_response_bytes=30000,max_episode_bytes=100000)
    r.update(version='toolv2x_task_v3',times=(np.arange(1,11)*.2).tolist(),tau_new=[[0.,0.]]*10,
             frame_binding=dict(version='ego_actor_time_v1',decision_time=5.,axes='x_forward_y_left',
                 origin='ego_actor',time_binding='synthetic_native_0.2s'))
    r.update(kw);return r

class NativeTaskTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def run(w):self.calls.append(len(w['track_ids']));return prediction(w)
        self.predictor=FrozenPredictor(run,provenance()['prediction'],dict(adapter='native_fixture'))
        self.service=VehicleTools(native_window,self.predictor,'scene',10,'peer',task_provenance=provenance(),task_frame_binding=request()['frame_binding'])

    def ledger(self):
        w=native_window('ego')
        return new_ledger(w,prediction(w),predictor=self.predictor,local_provenance=provenance(),
            p_processing='observations_only',task_version='toolv2x_task_v3',frame_binding=request()['frame_binding'])

    def test_p_native_history_and_motion_no_predictor(self):
        r=request();response=self.service.query_task(r);p=decode_task_response(response['wire'],r)
        self.assertEqual(self.calls,[])
        h=next(x['value'] for x in p['records'] if x['ref']['field_kind']=='history')
        np.testing.assert_allclose(h['history_times'],np.arange(-10,1)*.2)
        a=next(x['value'] for x in p['records'] if x['ref']['field_kind']=='anchor')
        np.testing.assert_allclose(a['motion']['velocity'],[3,0],atol=1e-6)

    def test_standalone_f_receipt_to_bev_no_free_history(self):
        r=request('F');response=self.service.query_task(r)
        ledger=apply_response(self.ledger(),response,self.predictor)
        binding=dict(request()['frame_binding'],scene='scene',g=10,coordinate_frame='ego_at_t')
        p,f=records_from_ledger(ledger,binding)
        self.assertEqual(p,[]);self.assertEqual(len(f),2);self.assertEqual(self.calls,[2])
        self.assertEqual({ref['field_kind'] for ref in f[0]['refs']},{'anchor','forecast'})
        raster=rasterize_pf(p,f,np.eye(3),future_times=r['times'],time_binding=binding['time_binding'],decision_time=5.)
        self.assertEqual(raster['F'].shape,(10,192,96));self.assertGreater(raster['F_CV'].sum(),0)
        self.assertEqual(response['cost']['response_bytes'],len(response['wire']))

    def test_f_full_context_before_cap_and_receipt_dedup(self):
        r=request();first=self.service.query_task(r);ledger=apply_response(self.ledger(),first,self.predictor)
        r=request('F',request_id='q1');r['execution_spec']['max_targets']=4
        r['acquired_field_manifest']=known_field_manifest(ledger)
        packet=decode_task_response(self.service.query_task(r)['wire'],r)
        self.assertEqual(self.calls,[2]);self.assertEqual(len(packet['references']),2)
        self.assertTrue(all(x['ref']['field_kind']=='forecast' for x in packet['records']))

    def test_full_context_before_one_target_cap(self):
        r=request('F');r['execution_spec']['max_targets']=1
        p=decode_task_response(self.service.query_task(r)['wire'],r)
        self.assertEqual(self.calls,[2]);self.assertEqual(len(p['ranking']),1)

    def test_native_current_change_changes_ranking(self):
        from tools.task_spec import rank_targets
        w=native_window();w['states'][0,:,0]=2.
        current=request();current['execution_spec']['max_plan_acceleration_mps2']=100.;current['tau_new']=[[2.,0.]]*10
        change=copy.deepcopy(current);change.update(mode='change',tau_old=[[0.,0.]]*10)
        self.assertNotEqual(rank_targets(w,current)[0]['score'],rank_targets(w,change)[0]['score'])

    def test_unsupported_forecast_horizon_rejected(self):
        r=request('F');r['times'][-1]=3.
        with self.assertRaisesRegex(ValueError,'no extrapolation'):self.service.query_task(r)

    def test_anchor_and_history_dedup_both_orders(self):
        first=self.service.query_task(request('F'));ledger=apply_response(self.ledger(),first,self.predictor)
        r=request('P',request_id='q1');r['acquired_field_manifest']=known_field_manifest(ledger)
        second=self.service.query_task(r);ledger=apply_response(ledger,second,self.predictor)
        self.assertEqual(len(decode_task_response(second['wire'],r)['references']),2)
        with self.assertRaises(ValueError):self.service.query_task(request(request_id='q2'))

    def test_native_unknown_velocity_is_marked_not_invented(self):
        w=native_window();w['valid'][:,:-1]=False
        self.service._load=lambda:w
        r=request('P');p=decode_task_response(self.service.query_task(r)['wire'],r)
        for item in p['records']:
            if item['ref']['field_kind']=='anchor':self.assertFalse(item['value']['motion']['valid'])

    def test_forged_receipt_rejected_before_loading(self):
        r=request();r['acquired_field_manifest']=[dict(receipt_id='fake',ref=dict(provider='peer',scene='scene',g=10,
            track_handle=7,field_kind='anchor',producer_version=provenance()['tracking'],context_version=provenance()['context']))]
        self.service._load=lambda:(_ for _ in ()).throw(AssertionError('private read'))
        with self.assertRaises(ValueError):self.service.query_task(r)

    def test_time_axis_change_rejected_before_prediction(self):
        first=self.service.query_task(request('F'));ledger=apply_response(self.ledger(),first,self.predictor)
        r=request('F',request_id='q1');r['times']=(np.arange(1,11)*.1).tolist()
        r['acquired_field_manifest']=known_field_manifest(ledger)
        with self.assertRaises(ValueError):self.service.query_task(r)
        self.assertEqual(self.calls,[2])
        other=VehicleTools(native_window,self.predictor,'scene',10,'peer',task_provenance=provenance(),task_frame_binding=request()['frame_binding'])
        r['acquired_field_manifest']=[]
        response=other.query_task(r)
        with self.assertRaises(ValueError):apply_response(ledger,response,self.predictor)

    def test_time_binding_cannot_change_within_episode(self):
        self.service.query_task(request())
        r=request('F',request_id='q1');r['frame_binding']['decision_time']=6.
        with self.assertRaises(ValueError):self.service.query_task(r)

if __name__=='__main__':unittest.main()
