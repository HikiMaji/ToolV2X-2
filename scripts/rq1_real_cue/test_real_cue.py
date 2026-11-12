"""Bounded contract tests; no AVstack, GPU or research batch."""
import copy
import contextlib
import io
import gzip
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np

try:
    from . import geometry as geo, model, run
except ImportError:
    import geometry as geo
    import model
    import run


def box(i, xyz, half=(1, 1, 1), yaw=0):
    signs = np.array([[1,1,1],[-1,1,1],[-1,-1,1],[1,-1,1],
                      [1,1,-1],[-1,1,-1],[-1,-1,-1],[1,-1,-1]])
    rot = np.array([[np.cos(yaw),-np.sin(yaw),0],
                    [np.sin(yaw),np.cos(yaw),0],[0,0,1]])
    center = np.array(xyz) + [0,0,half[2]]
    return {'id': i, 'xyz': list(xyz), 'corners': (signs * half @ rot.T + center).tolist()}


def row(parent='p', job='j', u=(1,0), cue=(.5,.5), truth=1, kind='clean'):
    return dict(parent=parent, job_id=job, key=[job,1,0], query_present=True,
                U=list(u), X=[[i,0,1,0,0] for i in range(len(u))],
                C=list(cue), C_missing=[0]*len(u), groups=[list(range(len(u)))],
                source_ids=list(range(len(u))), query_truth=truth, kind=kind,
                split='fit', newborn=False, output_present=True, native_adopted=False)


class GeometryTests(unittest.TestCase):
    def test_bottom_rotated_obb_and_invalid(self):
        b=box(1,[3,4,5],(2,1,.7),.4)
        center,axes,half=geo.obb_from_corners(b['corners'])
        np.testing.assert_allclose(center,[3,4,5.7])
        np.testing.assert_allclose(sorted(half),[.7,1,2])
        np.testing.assert_allclose(axes @ axes.T,np.eye(3),atol=1e-12)
        b['corners'][2][0]+=.1
        with self.assertRaises(ValueError):geo.obb_from_corners(b['corners'])

    def test_slab_parallel_inside_and_behind(self):
        c,a,h=geo.obb_from_corners(box(1,[5,0,-1])['corners'])
        t,hit=geo.segment_box_interval([0,0,0],np.array([[10,0,0],[10,3,0],[-10,0,0],[0,0,0]]),[c],[a],[h])
        self.assertEqual(hit[:,0].tolist(),[True,False,False,False])
        self.assertAlmostEqual(t[0,0],.4)
        t,hit=geo.segment_box_interval([5,0,0],[[0,0,0]],[c],[a],[h])
        self.assertTrue(hit[0,0]); self.assertEqual(t[0,0],0)

    def test_cue_exclusions_deleted_and_no_target_extent(self):
        q=box(100,[10,0,0]); blocks=[box(2,[5,0,0],(1,2,2)),box(1,[5,0,0],(1,2,2)),
                                       box(0,[0,0,0],(1,2,2)),box(9,[12,0,0]),box(8,[20,0,0])]
        cue,stats=geo.frame_cues([q]+blocks,{7:[0,0,.75]})
        self.assertEqual(cue[100][7]['C'],1)
        self.assertEqual(cue[100][7]['main_id'],1)
        self.assertEqual(cue[100][7]['ray_ids'],[1]*9)
        self.assertEqual(cue[0][7]['C_missing'],1)
        changed=copy.deepcopy(q);changed.update(hwl=[999]*3,yaw=999,corners=[[0]*3]*8)
        other,_=geo.frame_cues([changed]+blocks,{7:[0,0,.75]})
        self.assertEqual(cue[100],other[100])
        near,_=geo.frame_cues([q,box(2,[8,0,0],(1,2,2))],{7:[0,0,.75]})
        self.assertEqual(near[100][7]['C'],0)

    def test_group_before_event_mask_and_chunk_scalar(self):
        cue={9:dict(C=1,C_missing=0,main_id=2),3:dict(C=.5,C_missing=0,main_id=2),
             4:dict(C=0,C_missing=0,main_id=None)}
        self.assertEqual(geo.groups_from_cues([9,4,3],cue),[[3,9],[4]])
        rng=np.random.default_rng(3)
        bs=[box(i,[float(i*4+4),float(rng.normal()),0],(1,.8,1),float(rng.normal())) for i in range(70)]
        c1,_=geo.frame_cues(bs,{1:[0,0,1]},chunk_size=64)
        c2,_=geo.frame_cues(bs,{1:[0,0,1]},chunk_size=1)
        self.assertEqual(c1,c2)


    def test_vectorized_rays_match_scalar_reference(self):
        origin=np.array([0.,0.,.75])
        bs=[box(i,[4+3*i,(-1)**i*.8,0],(1,1.2,1.2),.13*i) for i in range(7)]
        cues,_=geo.frame_cues(bs,{1:origin})
        def interval(center,axes,half,direction):
            lo,hi=0.,1.
            for axis,h in zip(axes,half):
                o=float((origin-center)@axis);d=float(direction@axis)
                if abs(d)<=1e-12:
                    if abs(o)>h+1e-8:return math.inf
                else:
                    a,b=sorted([(-h-o)/d,(h-o)/d]);lo=max(lo,a);hi=min(hi,b)
            return lo if lo<=hi+1e-8 else math.inf
        for query in bs:
            xyz=np.asarray(query['xyz']);pc=xyz+[0,0,.75];expected=[]
            for offset in geo.PROBE_OFFSETS:
                direction=pc+offset-origin
                probe=interval(pc,np.eye(3),[.5]*3,direction)
                candidates=[]
                for b in bs:
                    if b['id']==query['id'] or np.linalg.norm(np.asarray(b['xyz'])[:2]-xyz[:2])<=3+1e-8:continue
                    c,a,h=geo.obb_from_corners(b['corners'])
                    if np.all(np.abs((origin-c)@a.T)<=h+1e-8):continue
                    t=interval(c,a,h,direction)
                    if t<probe-1e-8:candidates.append((t,b['id']))
                expected.append(min(candidates)[1] if candidates else None)
            self.assertEqual(cues[query['id']][1]['ray_ids'],expected)


class ModelTests(unittest.TestCase):
    def test_all_patterns_normalize_and_unknown_marginal(self):
        p=np.array([.2,.7,.5]); groups=[[0,1],[2]]
        for rho in [0,.6,.95]:
            total=sum(math.exp(model.normal_logprob(p,u,groups,rho)) for u in itertools.product([0,1],repeat=3))
            self.assertAlmostEqual(total,1)
        self.assertAlmostEqual(sum(math.exp(model.false_logprob(u)) for u in itertools.product([0,1],repeat=3)),1)
        self.assertAlmostEqual(math.exp(model.false_logprob([1])),.225)
        self.assertAlmostEqual(math.exp(model.false_logprob([0,0,0])),(.9**3+.8**3+.6**3+.8)/4)
        lhs=math.exp(model.normal_logprob(p,[1,-1,0],groups,.6))
        rhs=sum(math.exp(model.normal_logprob(p,[1,u,0],groups,.6)) for u in [0,1])
        self.assertAlmostEqual(lhs,rhs)
        self.assertEqual(model.normal_logprob([],[],[],.5),0)
        self.assertEqual(model.false_logprob([]),0)

    def test_weights_constraint_oof_and_rho(self):
        rows=[]
        for p in range(5):
            for i in range(8):
                r=row(str(p),str(p),u=(i%2,(i//2)%2),cue=(i/8,i/8))
                r['X']=[[p*10+i,0,1,0,0]]*2; rows.append(r)
        w=model.query_weights(rows);self.assertAlmostEqual(sum(w),1)
        fit=model.fit_margin(rows,True);self.assertLessEqual(fit['coef'][5],0)
        oof,folds=model.crossfit_cue_margin(rows)
        self.assertEqual(len(oof),len(rows));self.assertEqual(len(folds),5)
        self.assertNotIn('0',folds['0']['train_parents'])
        self.assertGreater(folds['0']['model']['mean'][0],fit['mean'][0])
        tiny=[dict(row(),p_C=[.5,.5],groups=[[0],[1]])]
        rho=model.fit_rho(tiny);self.assertEqual(rho['rho'],0)
        self.assertEqual(rho['status'],'structurally_unidentified')
        informative=[dict(row(u=(1,1)),p_C=[.5,.5]) for _ in range(3)]
        self.assertGreater(model.fit_rho(informative)['rho'],.9)

    def test_score_no_k_gate_or_output_dependence(self):
        r=row(u=(0,0)); r['p_B']=[.1,.2];r['p_C']=[.15,.25]
        a=model.score_query(r,{'rho':.5})
        self.assertTrue(a['eligible']);self.assertEqual(a['k'],0)
        r.update(query_truth=0,output_present=False,identity_ok=False)
        b=model.score_query(r,{'rho':.5})
        self.assertEqual(a,b)
        r['U']=[1,-1];self.assertFalse(model.score_query(r,{'rho':.5})['eligible'])
        r['C_missing']=[1,0];self.assertEqual(model.margin_features(r,True)[0].shape[1],7)

    def test_score_decomposition_rho_zero_and_permutation(self):
        r=row(u=(1,0,1),cue=(.2,.5,0))
        r['p_B']=[.2,.5,.7];r['p_C']=[.1,.4,.8];r['groups']=[[0,1],[2]]
        score=model.score_query(r,{'rho':.6})
        self.assertAlmostEqual(score['raw_scores']['J'],sum(score['e'])+sum(score['delta'])+score['gamma'])
        zero=model.score_query(r,{'rho':0.})
        self.assertEqual(zero['scores']['J'],zero['scores']['C'])
        permutation=[2,0,1];rr=copy.deepcopy(r)
        for field in ['U','X','C','C_missing','p_B','p_C','source_ids']:rr[field]=[r[field][i] for i in permutation]
        rr['groups']=[[permutation.index(i) for i in g] for g in r['groups']]
        self.assertEqual(model.score_query(rr,{'rho':.6})['scores'],score['scores'])

    def test_unidentifiable_margin_and_missing_cal_class(self):
        with self.assertRaisesRegex(ValueError,'both report outcomes'):
            model.fit_margin([row(u=(1,1))],True)
        r=row();r.update(eligible=True,scores={'C':1.})
        policy=model.calibrate([r],'C')
        self.assertEqual(policy['status'],'not_estimable')
        self.assertIsNone(policy['accept']['error'])
        self.assertFalse(policy['reject']['enabled'])

    def test_calibration_budget_and_ties(self):
        rs=[]
        for truth,kind in [(1,'clean'),(0,'attack')]:
            for i in range(100):
                r=row(u=(0,0),truth=truth,kind=kind); r['eligible']=True
                r['scores']={'C': float(i if truth else i-95)};rs.append(r)
        policy=model.calibrate(rs,'C')
        for truth in [0,1]:
            selected=[r for r in rs if r['query_truth']==truth]
            errors=sum(model.decide(r['scores']['C'],True,policy)==('accept' if truth==0 else 'reject') for r in selected)/len(selected)
            self.assertLessEqual(errors,.05+1e-12)
        self.assertEqual(model.decide(0,True,policy),'unknown')


class ExtractionTests(unittest.TestCase):
    def test_frame_join_and_label_boundary(self):
        q=box(100,[10,0,0]); b=box(1,[5,0,0],(1,2,2))
        events=[]
        for i,g in enumerate([q,b,None]):
            r=row();r.update(id=i,query_geometry=g,key=['j',2,i],frame=2,index=1,timestamp=.1,
                            source_ids=[0,1],output_present=(i!=1),newborn=(g is None))
            if g:r['id']=g['id'];r['key'][-1]=g['id']
            events.append(r)
        sender={'frame':2,'index':1,'timestamp':.1,'messages':[dict(source_id=s,frame=2,timestamp=.1,pose_xyz=[0,0,.75]) for s in [0,1]]}
        features,stats=run.extract_frame(events,sender,[0,1])
        self.assertEqual(features[0]['C'],[1,1]);self.assertFalse(features[-1]['query_present'])
        altered=copy.deepcopy(events)
        for r in altered:r.update(U=[0,0],query_truth=0,output_present=False,identity_ok=False)
        again,_=run.extract_frame(altered,sender,[0,1])
        self.assertEqual(features[0]['C'],again[0]['C'])
        sender['timestamp']=.2
        with self.assertRaises(ValueError):run.extract_frame(events,sender,[0,1])

    def test_full_tiny_cli_stages_and_background_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); old=root/'old';old.mkdir();(old/'events').mkdir()
            jobs=[]; labels=[]
            specs=[('p'+str(i),'clean','fit') for i in range(5)]
            specs += [('a'+str(i),'clean','cal') for i in range(4)] + [('e','clean','eval')]
            specs += [('a'+str(i%4),'attack','cal') for i in range(28)] + [('e','attack','eval')]
            for n,(parent,kind,split) in enumerate(specs):
                jid='job'+str(n); config_path=old/(jid+'.json');sender_path=old/(jid+'.sender.gz')
                frames=[dict(frame=1,index=0,timestamp=0.),dict(frame=2,index=1,timestamp=.1)]
                senders=[dict(f,messages=[dict(source_id=s,frame=f['frame'],timestamp=f['timestamp'],pose_xyz=[0,s,.75]) for s in [0,1]]) for f in frames]
                run.write_jsonl(sender_path,senders)
                run.dump_json(config_path,dict(job_id=jid,source_ids=[0,1],sender_path=str(sender_path),expected_frames=frames))
                jobs.append(dict(job_id=jid,parent=parent,kind=kind,split=split,config=str(config_path)))
                events=[]
                for i,g in enumerate([box(100,[10,0,0]),box(1,[5,0,0],(1,2,2)),box(2,[20,0,0]),None]):
                    r=row(parent,jid,u=(i%2,(n+i)%2),kind=kind);ident=g['id'] if g else 200
                    r.update(id=ident,key=[jid,2,ident],frame=2,index=1,timestamp=.1,query_geometry=g,
                             source_ids=[0,1],newborn=g is None,identity_ok=True,output_present=ident!=1)
                    if g is None:r.update(U=[-1,-1],X=[None,None])
                    events.append(r)
                    lab=dict(r,split=split,query_truth=-1 if g is None else 0 if kind=='attack' and ident==100 else 1,
                             query_label_reason='fixture',output_truth=1)
                    labels.append(lab)
                run.write_jsonl(old/'events'/(jid+'.jsonl.gz'),events)
            run.dump_json(old/'manifest.json',dict(jobs=jobs))
            run.write_jsonl(old/'labelled.jsonl.gz',labels)
            out=root/'out'
            with contextlib.redirect_stdout(io.StringIO()):
                run.extract(old/'manifest.json',out);run.fit(out);run.report(out)
            metrics=json.loads((out/'metrics.json').read_text())
            self.assertEqual(metrics['by_split']['eval']['n_all'],8)
            self.assertEqual(metrics['by_split']['eval']['system_query']['J']['true']['n'],3)
            self.assertEqual(metrics['by_split']['eval']['attack_true_background']['n'],2)
            self.assertEqual(metrics['by_split']['eval']['attack_true_background']['by_parent']['e']['n'],2)
            self.assertEqual(metrics['by_split']['eval']['unknown_label']['n'],2)
            self.assertIn('<svg', (out/'six_cells.svg').read_text())
            self.assertEqual((out/'six_cells.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            with self.assertRaises(FileExistsError):run.report(out)
            png_only=root/'png_only';png_only.mkdir()
            (png_only/'six_cells.png').write_bytes(b'existing')
            with self.assertRaisesRegex(FileExistsError,'six_cells.png'):run.report(png_only)

    def test_parent_split(self):
        jobs=[dict(parent='e',kind='attack',split='eval')]
        jobs += [dict(parent='a'+str(i),kind='attack',split='fit') for i in range(4)]
        jobs += [dict(parent='p'+str(i),kind='clean',split='fit') for i in range(5)]
        split=run.parent_splits(jobs)
        self.assertEqual(list(split.values()).count('fit'),5)
        self.assertEqual(split['e'],'eval');self.assertEqual(split['a0'],'cal')


if __name__=='__main__':unittest.main()
