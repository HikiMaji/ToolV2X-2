"""Synthetic contract tests; fixture forecasts are not model evidence."""
import copy
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_evidence_ledger import LedgerFixture
from planning.codriving_ledger_bev import records_from_ledger
from planning.codriving_pf_bev import rasterize_pf

class LedgerBevTests(LedgerFixture):
    def setUp(self):
        super().setUp()
        self.ledger['p_processing']='observations_only'
        self.binding=dict(scene='scene',g=10,decision_time=1.,coordinate_frame='ego_at_t',
            axes='x_forward_y_left',origin='ego_actor',time_binding='synthetic_0.1s')

    def acquired(self, both=False):
        service=self.service()
        ledger=self.apply(service.query_task(self.request()))
        if both:
            request=self.request(tool='F',request_id='q1')
            request['acquired_field_manifest']=self.e.known_field_manifest(ledger)
            ledger=self.apply(service.query_task(request),ledger)
        return ledger

    def test_paid_pf_to_ten_channels_and_dependency_refs(self):
        ledger=self.acquired(True);before=copy.deepcopy(ledger)
        p,f=records_from_ledger(ledger,self.binding)
        self.assertEqual(len(p),2);self.assertEqual(len(f),2)
        self.assertEqual({r['field_kind'] for r in f[0]['refs']},{'anchor','history','forecast'})
        raster=rasterize_pf(p,f,np.eye(3),future_times=np.arange(1,11)*.2,
            time_binding=self.binding['time_binding'],decision_time=1.)
        self.assertEqual(raster['F'].shape,(10,192,96));self.assertTrue(raster['F_valid'].all())
        self.assertEqual(ledger,before)

    def test_velocity_uses_valid_paid_history_actual_time_gap(self):
        from test_vehicle_tools import window
        w=window();w['valid'][0,:]=False;w['valid'][0,[-4,-1]]=True
        w['states'][0,-4,0]=-1.;w['states'][0,-1,0]=2.
        ledger=self.apply(self.service(w).query_task(self.request()))
        p,_=records_from_ledger(ledger,self.binding)
        target=next(r for r in p if r['track']=='7')
        np.testing.assert_allclose(target['velocity'],[10.,0.])
        self.assertEqual(sum(h['valid'] for h in target['history']),2)

    def test_p_never_predicts(self):
        def forbidden(w): raise AssertionError('P must not predict')
        self.predictor._predict=forbidden
        p,f=records_from_ledger(self.acquired(),self.binding)
        self.assertEqual(len(p),2);self.assertEqual(f,[])

    def test_f_without_paid_velocity_is_rejected(self):
        ledger=self.apply(self.service().query_task(self.request(tool='F')))
        with self.assertRaisesRegex(ValueError,'paid causal history'):
            records_from_ledger(ledger,self.binding)

    def test_tampering_and_epoch_mismatch_rejected(self):
        ledger=self.acquired()
        for mutate in [lambda x:x['acquired_fields'][0]['value']['box'].__setitem__(0,999),
                       lambda x:x['receipts'][0].__setitem__('wire_text','{}')]:
            bad=copy.deepcopy(ledger);mutate(bad)
            with self.assertRaises(ValueError):records_from_ledger(bad,self.binding)
        for k,v in [('g',11),('scene','other'),('origin','rear_axle'),('axes','x_right_y_forward')]:
            with self.assertRaises(ValueError):records_from_ledger(ledger,dict(self.binding,**{k:v}))

    def test_derived_forecasts_do_not_become_paid_f(self):
        ledger=self.acquired();ledger['derived_fields']=[{'untrusted':'ignored'}]
        self.assertEqual(records_from_ledger(ledger,self.binding)[1],[])

if __name__=='__main__':unittest.main()
