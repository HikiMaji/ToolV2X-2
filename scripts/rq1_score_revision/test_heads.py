"""Small, deterministic checks of the revised head research contracts."""
import copy
import unittest
import numpy as np
from scripts.rq1_score_revision import heads


def normal_models():
    def model(n, intercept=0., coef=None):
        return dict(mean=[0.]*n, scale=[1.]*n, coef=coef or [0.]*n, intercept=intercept)
    return dict(D=model(7), h_B=model(5), h_C=model(6),
                emission=model(6, -1., [0.,0.,0.,0.,0.,2.]),
                transition=model(7, -1., [0.,0.,0.,0.,0.,0.,2.]),
                pi=.5, T_base=[[.8,.2],[.2,.8]])


def row(index=0, **kw):
    result=dict(job_id='j', id=1, epoch=0, parent='p', split='fit', kind='clean',
                family='clean', attack_k=0, attack_role=None, key=['j',index,1],
                index=index, frame=index, timestamp=index*.1, source_ids=[11,22,33],
                U=[1,0,-1], X=[[0.]*5]*3, C=[0.]*3, C_missing=[False]*3,
                groups=[[0,1],[2]], query_present=True, newborn=False,
                output_present=True, identity_ok=True, query_truth=1,
                output_truth=1, native_mean=.7, native_adopted=True, Z=[1,0,1])
    result.update(kw)
    return result


class HeadsContracts(unittest.TestCase):
    def test_source_features_group_average_and_permutation(self):
        window=[row(0),row(1,U=[1,1,0])]
        result=heads.window_features(window,normal_models(),.5)
        self.assertEqual(result['context'], [2,3,2])
        expected=np.array([[2*np.log(.5),0,2],[np.log(.5),np.log(.5),1],[0,np.log(.5),0]])
        np.testing.assert_allclose(result['sources']['D_head'],expected)
        np.testing.assert_allclose(result['features']['D_head'],np.r_[expected.sum(0),[2,3,2]])
        np.testing.assert_allclose(np.asarray(result['sources']['G'])[:2],np.asarray(result['sources']['I_Jmargin'])[:2]/2)
        perm=[2,0,1];other=copy.deepcopy(window)
        for r in other:
            for field in ('source_ids','U','X','C','C_missing'):
                r[field]=[r[field][i] for i in perm]
            r['groups']=[[1,2],[0]]
        changed=heads.window_features(other,normal_models(),.5)
        for m in ('D_head','T_head','I_Jmargin','G'):
            np.testing.assert_allclose(result['features'][m],changed['features'][m])
        self.assertAlmostEqual(result['delta_T'], changed['delta_T'])
        self.assertTrue(result['accept_eligible'])

    def test_online_features_ignore_labels_and_common_numeric_unknown(self):
        original=heads.window_features([row()],normal_models(),.5)
        changed=heads.window_features([row(query_truth=0, family='F2',attack_k=3,Z=[999]*3)],normal_models(),.5)
        self.assertEqual(original,changed)
        bad=row(U=[7,0,1])
        result=heads.window_features([bad],normal_models(),.5)
        self.assertFalse(result['finite'])
        self.assertTrue(all(v is None for v in result['features'].values()))
        unavailable=heads.window_features([row()],normal_models(),None)
        self.assertIsNotNone(unavailable['features']['D_head'])
        self.assertIsNone(unavailable['features']['I_Jmargin'])
        self.assertFalse(heads.window_features([row(newborn=True)],normal_models(),.5)['accept_eligible'])

    def test_constants_fixed_zero_direct_miss_nonpositive_and_decomposition(self):
        X=np.array([[i, -i, i%2,1,3,2] for i in range(8)],float)
        model=heads.fit_base(X, [0,0,0,0,1,1,1,1], np.ones(8)/8)
        self.assertEqual(model['coef'][3:],[0.,0.,0.])
        self.assertGreaterEqual(model['coef'][0],0.)
        self.assertGreaterEqual(model['coef'][1],0.)
        contribution=heads.decompose(model, [[-1.,-2.,1.],[-3.,-4.,2.]], [2,2,2])
        self.assertLessEqual(contribution['source_scores'][0]-heads.raw_parameters(model)['coef'][0]*-1.-heads.raw_parameters(model)['coef'][2],0.)
        self.assertAlmostEqual(contribution['score'],heads.base_score(model,[-4.,-6.,3.,2,2,2]))
        self.assertAlmostEqual(sum(contribution['source_scores'])+contribution['global_score'],contribution['score'])

    def test_fixed_offset_increment_has_no_intercept_and_delta_support_gate(self):
        x=np.array([-2.,-1.,1.,2.,-2.,-1.,1.,2.,-2.,-1.,1.,2.])
        y=(x>0).astype(int);w=np.ones(12)/12;offset=np.linspace(-.2,.2,12)
        model=heads.fit_increment(x,y,w,offset,['a']*4+['b']*4+['c']*4, joint=True)
        self.assertTrue(model['delta_informative'])
        self.assertNotIn('intercept',model)
        self.assertAlmostEqual(model['rms'],np.sqrt(w@(x*x)))
        self.assertAlmostEqual(heads.increment_score(model,3.,0.),3.)
        self.assertAlmostEqual(model['coefficient'],model['coef_std']/model['rms'])
        flat=heads.fit_increment(np.ones(12),y,w,offset,['a']*4+['b']*4+['c']*4,joint=True)
        self.assertEqual(flat['status'],'delta_uninformative')
        self.assertEqual(flat['coefficient'],0.)
        self.assertFalse(flat['delta_informative'])


if __name__=='__main__':
    unittest.main()
