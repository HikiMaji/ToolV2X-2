import unittest
import numpy as np
from evaluation.evidence_quality import match_anchors, score_forecast

class EvidenceQualityTest(unittest.TestCase):
    def test_source_matches_independently_and_rejects_tie(self):
        gt = np.array([[10.,0,0,4,2,2,0],[20.,0,0,4,2,2,0]])
        pred = gt.copy(); pred[:,0] += .3
        self.assertEqual([r['gt_id'] for r in match_anchors(pred,gt,[7,8])], [7,8])
        tied = np.array([[9.9,0,0,4,2,2,0],[10.1,0,0,4,2,2,0]])
        self.assertEqual(match_anchors(gt[:1],tied,[7,8])[0]['status'],'ambiguous')
    def test_score_is_not_oracle_and_missing_labels_stay_masked(self):
        paths = np.array([[[1.,0],[100.,0]], [[0.,0],[0.,0]]])
        r=score_forecast(paths,[.8,.2],np.zeros((2,2)),[True,False])
        self.assertEqual(r['top_ADE'],1.)
        self.assertEqual(r['minADE'],0.)
        self.assertEqual(r['valid_steps'],1)
        self.assertIsNone(score_forecast(paths,[.8,.2],np.zeros((2,2)),[False,False]))
if __name__=='__main__': unittest.main()
