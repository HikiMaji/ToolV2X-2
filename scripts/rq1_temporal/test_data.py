"""Small deterministic fixtures. These establish contracts, not research effects."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np
from . import data, run, native_adapter


def row(index=0,truth=1,parent='p',family='clean',k=0):
    return dict(key=[parent,index,1],job_id=parent,id=1,epoch=0,parent=parent,split='cal',kind='clean' if truth else 'attack',family=family,
                attack_k=k,attack_role=None if truth else 'target',frame=index,index=index,timestamp=.1*index,source_ids=[1,2],
                U=[index%2,(index//2)%2],X=[[1.,0.,1.,1.,1.],[2.,1.,0.,1.,1.]],C=[.2,.3],C_missing=[0,0],groups=[[0,1]],
                query_present=True,newborn=False,output_present=True,identity_ok=True,native_adopted=False,native_mean=None,
                query_truth=truth,query_gt_id=1 if truth else None,output_truth=truth,Z=[index%2,(index//3)%2],
                scores={m:float(index-10) for m in run.METHODS},normal_loglik={m:-1. for m in run.kernel.METHODS},
                method_status={},finite=True,accept_eligible=True,reject_eligible=True,m=2,supports=2,common_group=True,C_positive=True)


class DataTests(unittest.TestCase):
    def test_full_pose_obb_and_missing_identity(self):
        from scipy.spatial.transform import Rotation
        rotation=Rotation.from_euler('xyz',[.3,.5,.7]).as_matrix();center=np.array([4.,-3.,2.]);local=np.array([[0,0,0],[1,.5,.25],[3,0,0]])
        box=dict(gt_id=7,xyz=center.tolist(),hwl=[1,2,4],rotation=rotation.tolist())
        self.assertEqual(data.obb_counts(local@rotation.T+center,[box]),{7:2})
        pose=[1.,2.,3.,11.,22.,33.]
        def rot(angles):
            roll,yaw,pitch=np.radians(angles)
            return Rotation.from_euler('xyz',[roll,pitch,yaw]).as_matrix()
        world=data.points_world(np.array([[.2,.3,.4]]),pose,rot)
        np.testing.assert_allclose(world,(np.array([[.2,.3,.4]])@rot(pose[3:]).T+pose[:3])@np.diag([1,-1,1]))
        r=row();r['query_gt_id']=None;r['output_gt_id']=7
        self.assertEqual(next(data.attach_z([r],{(0,1,7):1}))['Z'],[-1,-1])

    def test_legacy_join_metadata_and_eof(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);r=row();r['job_id']='j';r['key']=['j',0,1]
            feature={k:r[k] for k in data.FIELDS if k in r};label=dict(r,native_mean=None)
            jobs={'j':dict(parent='p',kind='clean',split='fit',family='clean',attack_k=0)}
            with data.atomic_rows(d/'f.gz') as write:write(feature)
            with data.atomic_rows(d/'l.gz') as write:write(label)
            joined=list(data.join_legacy(d/'l.gz',{'j':d/'f.gz'},jobs))
            self.assertIsNone(joined[0]['native_mean']);self.assertEqual(joined[0]['query_gt_id'],1)
            label['source_ids']=[2,1]
            with data.atomic_rows(d/'bad.gz') as write:write(label)
            with self.assertRaisesRegex(ValueError,'source_ids'):list(data.join_legacy(d/'bad.gz',{'j':d/'f.gz'},jobs))
            raw=(d/'f.gz').read_bytes();(d/'cut.gz').write_bytes(raw[:-5])
            with self.assertRaises((EOFError,OSError)):list(data.join_legacy(d/'l.gz',{'j':d/'cut.gz'},jobs))

    def test_epochs_do_not_read_labels(self):
        rows=[row(i) for i in range(4)];rows[1]['query_truth']=0;rows[2]['newborn']=True;rows[2]['query_present']=False
        result=list(data.assign_epochs(rows));self.assertEqual([r['epoch'] for r in result],[0,0,1,2])
        rows[1]['query_truth']=-1
        self.assertEqual([r['epoch'] for r in data.assign_epochs(rows)],[0,0,1,2])
        data.validate_splits(data.SPLITS)
        bad=dict(data.SPLITS);bad['train/2021_08_22_06_43_37']=bad.pop('train/2021_08_23_22_31_01')
        with self.assertRaises(ValueError):data.validate_splits(bad)

    def test_atomic_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.gz'
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                with data.atomic_rows(p) as write:write({'a':1});raise RuntimeError('fixture')
            self.assertFalse(p.exists())
            with data.atomic_rows(p) as write:write({'b':2})
            with self.assertRaises(FileExistsError):
                with data.atomic_rows(p):pass
            self.assertEqual(list(data.read_rows(p)),[{'b':2}])

    def test_primary_target_and_weights(self):
        a=row(0,0,'a','F3',3);b=row(1,0,'b','F1',1);c=row(2,0,'b','F1',1)
        oc=dict(a,attack_role='occluder');self.assertFalse(run.primary(oc,0))
        np.testing.assert_allclose(run.weights([a,b,c],0),[.5,.25,.25])
        self.assertTrue(run.primary(dict(a,accept_eligible=False,reject_eligible=False),0))

    def test_calibration_ties_and_common_denominator(self):
        rows=[]
        for i in range(40):
            r=row(i,0,'fake','F1',1);r['scores']={m:2. if i<3 else -1. for m in run.METHODS};rows.append(r)
        rows += [row(i,1,'true') for i in range(40)]
        policy=run.calibrate(rows,'J',{('F1',1),('F2',2)})
        self.assertGreater(policy['A'],2.);self.assertEqual(policy['status'],'not_calibrated_for_missing_layers')
        # Two of forty may be accepted, including 38 ineligible records in the denominator.
        rows[2]['scores']['J']=1.;rows[2]['accept_eligible']=False
        policy=run.calibrate(rows,'J',{('F1',1)})
        self.assertEqual(policy['A'],0.)
        self.assertEqual(sum(run.decide(r,'J',policy)=='accept' for r in rows if run.primary(r,0)),2)
        for r in rows:r['decisions']={m:run.decide(r,m,policy) for m in run.METHODS}
        self.assertEqual(run.six_cells(rows,'J')['false']['n'],40)

    def test_calibration_matches_bruteforce(self):
        rng=np.random.RandomState(8);rows=[]
        for i in range(140):
            truth=int(i%2);r=row(i,truth,'p'+str(i%5),'clean' if truth else 'F'+str(i%3),0 if truth else i%2+1)
            r['scores']['J']=float(rng.randint(-8,9));r['accept_eligible']=bool(i%3);r['reject_eligible']=bool(i%4);rows.append(r)
        actual=run.calibrate(rows,'J')
        for branch,truth,positive in [('A',0,True),('R',1,False)]:
            subset=[r for r in rows if run.primary(r,truth)];groups=[subset]
            groups += [[r for r in subset if (r['family'],r['attack_k'])==layer] for layer in {(r['family'],r['attack_k']) for r in subset}]
            candidates=sorted({0.}|{r['scores']['J'] for r in rows if r['scores']['J']>0 if positive}) if positive else sorted({0.}|{r['scores']['J'] for r in rows if r['scores']['J']<0},reverse=True)
            best=None
            for threshold in candidates:
                trial={'A':threshold if positive else None,'R':None if positive else threshold};decision='accept' if positive else 'reject'
                if all(sum(w for r,w in zip(g,run.weights(g,truth)) if run.decide(r,'J',trial)==decision)<=.05+1e-12 for g in groups):
                    best=threshold;break
            self.assertEqual(actual[branch],best)

    def test_trajectory_keeps_unknown_history_and_nonadopters(self):
        rows=[row(i) for i in range(4)]
        rows[0]['query_truth']=-1
        for r in rows:r['decisions']={m:'unknown' for m in run.METHODS}
        rows[2]['decisions']['J']='accept'
        result=run.trajectories(rows,'J',1)
        self.assertAlmostEqual(result['rows'][0]['first_accept_delay'],.2)
        self.assertEqual(result['rows'][0]['n'],4)
        self.assertEqual(run.trajectories(rows,'D',1)['never_accepted'],1)

    def test_structural_and_numeric_failure_predictions(self):
        r=row();result=dict(scores={m:None for m in run.kernel.METHODS},normal_loglik={m:None for m in run.kernel.METHODS},
                method_status={m:dict(status='unestimable') for m in run.kernel.METHODS},finite=True,n_frames=1,
                accept_eligible=True,reject_eligible=True,opportunity_union=[0,1],support_union=[0,1],window={})
        p=run.prediction(r,result);self.assertTrue(p['finite']);self.assertEqual(p['method_status']['D']['status'],'unestimable')
        r['native_mean']=.7;result['finite']=False
        self.assertIsNone(run.prediction(r,result)['scores']['MATE_policy'])

    def test_small_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);jobs=[]
            for split in ('fit','cal','eval'):
                for p in range(2):
                    jid=split+str(p);job=dict(job_id=jid,parent=jid,split=split,kind='clean',family='clean',attack_k=0);jobs.append(job)
                    with data.atomic_rows(out/'jobs'/jid/'rows.jsonl.gz') as write:
                        for i in range(16):
                            r=row(i,parent=jid);r.update(split=split)
                            r['U']=[(i+p)%2,(i//2+p)%2];r['X'][0][0]=i/5;r['X'][1][0]=i/3
                            write(data.compact(r))
                    data.atomic_json(out/'jobs'/jid/'complete.json',dict(status='COMPLETE'))
                if split!='fit':
                    jid=split+'fake';jobs.append(dict(job_id=jid,parent=split+'0',split=split,kind='attack',family='F1',attack_k=1))
                    with data.atomic_rows(out/'jobs'/jid/'rows.jsonl.gz') as write:
                        for i in range(12):
                            r=row(i,0,split+'0','F1',1);r.update(job_id=jid,key=[jid,i,1],split=split);write(data.compact(r))
                    data.atomic_json(out/'jobs'/jid/'complete.json',dict(status='COMPLETE'))
            data.atomic_json(out/'manifest.json',dict(jobs=jobs));data.atomic_json(out/'prepare.complete.json',{})
            run.fit(out);run.score(out);run.report(out)
            self.assertTrue((out/'report/six_cells.png').exists());metrics=json.loads((out/'report/metrics.json').read_text())
            self.assertEqual(metrics['variants']['main']['metrics']['eval']['system_query']['J']['false']['n'],12)
            self.assertEqual(len(list(data.read_rows(out/'report/predictions.jsonl.gz'))),120)
            with self.assertRaises(FileExistsError):run.fit(out)
            with self.assertRaises(FileExistsError):run.score(out)
            with self.assertRaises(FileExistsError):run.report(out)


class LabelFixtureTests(unittest.TestCase):
    def test_frozen_attack_and_fresh_coast_contract(self):
        import importlib.util
        from types import SimpleNamespace
        modules=[]
        for name,path in [('fixture_recording',native_adapter.OLD/'recording_inputs.py'),('fixture_extract',native_adapter.STATIC/'extract.py')]:
            spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules.append(module)
        recording,static=modules;counts={};track=SimpleNamespace(ID=1,n_updates=1,t=.1,dt_coast=0.)
        self.assertEqual(len(static.fresh_tracks([track],counts,.1)[0]),1)
        self.assertEqual(len(static.fresh_tracks([track],counts,.1)[0]),0)
        track.n_updates=2;track.dt_coast=.1
        self.assertEqual(len(static.fresh_tracks([track],counts,.1)[0]),0)
        blocker=dict(gt_id=1,xyz=[0,0,1],hwl=[2,2,4],rotation=np.eye(3).tolist(),yaw=0.)
        scans=[dict(gt=dict(available=True,boxes=[blocker]),timestamp=i*.1,messages=[dict(source_id=sid,pose_xyz=[-20,sid,1]) for sid in (1,2,3,4)]) for i in range(80)]
        stub=SimpleNamespace(source_features=lambda *args:([0]*5,None,True))
        job=dict(family='F1',attack_k=2)
        with mock.patch.object(native_adapter,'imports',return_value=(None,None,recording,stub)):
            one=native_adapter.construct_attack(job,scans);two=native_adapter.construct_attack(job,scans)
        self.assertEqual(one,two);self.assertEqual(one['status'],'VALID');self.assertLessEqual(one['attempted'],64)
        self.assertEqual(one['controlled_sources'],[1,2]);self.assertEqual(one['normal_source'],3)
        self.assertEqual(one['entities'][20],one['entities'][79])
        stub.source_features=lambda *args:([0]*5,None,False)
        with mock.patch.object(native_adapter,'imports',return_value=(None,None,recording,stub)):
            failed=native_adapter.construct_attack(job,scans)
        self.assertEqual(failed['status'],'UNREALIZABLE');self.assertLessEqual(failed['attempted'],64)

    def test_stopped_fake_bound_and_gt_independent_cues(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('fixture_recording_inputs',native_adapter.OLD/'recording_inputs.py')
        recording=importlib.util.module_from_spec(spec);spec.loader.exec_module(recording)
        entity=native_adapter.entity_box([12,0,.8]);events=[];scans=[]
        job=dict(job_id='fixture',parent='p',kind='attack',family='F1',attack_k=1,split='cal')
        for index in range(20,81):
            r=row(index,0,'p','F1',1);r.update(job_id='fixture',key=['fixture',index,1],query_geometry=dict(entity,id=1),output_geometry=dict(entity,id=1),C=[.3,.4])
            events.append(r);scans.append(dict(frame=index,index=index,gt=dict(available=True,boxes=[]),echo={}))
        attack=dict(entities=[[entity] for _ in range(81)],normal_source=2)
        with mock.patch.object(native_adapter,'imports',return_value=(None,None,recording,None)):
            labelled=list(native_adapter.attach_labels(events,scans,job,attack))
            self.assertTrue(all(r['query_truth']==0 and r['attack_role']=='target' for r in labelled[:-1]))
            self.assertEqual(labelled[-1]['query_truth'],-1)
            self.assertTrue(all(r['C']==[.3,.4] for r in labelled))
            scans[1]['gt']=dict(available=False,boxes=[])
            changed=list(native_adapter.attach_labels(events,scans,job,attack))
            self.assertEqual(changed[1]['query_truth'],-1)
            self.assertEqual(changed[1]['C'],labelled[1]['C'])
            # An unseen central epoch in the stopped interval may not inherit false identity.
            stopped=list(native_adapter.attach_labels(events[40:60],scans,job,attack))
            self.assertTrue(all(r['query_truth']==-1 for r in stopped))

    def test_injection_schedule(self):
        target=native_adapter.entity_box([12,0,.8]);oc=native_adapter.entity_box([6,0,.8],role='occluder')
        attack=dict(status='VALID',entities=[[target,oc] for _ in range(80)])
        self.assertEqual(native_adapter.injection_at(attack,14),[])
        self.assertEqual([e['role'] for e in native_adapter.injection_at(attack,15)],['occluder'])
        self.assertEqual(len(native_adapter.injection_at(attack,20)),2)
        self.assertEqual(native_adapter.injection_at(attack,60),[])


class NativeFixtureTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').version_info >= (3,10),'native runtime is Python 3.10')
    def test_native_four_five_source_messages(self):
        # Synthetic NPZ only. No real scan, fitted policy or attack-effect selection.
        for n in (4,5):
            with tempfile.TemporaryDirectory() as d:
                d=Path(d);ids=list(range(1,n+1));spec=dict(source_ids=ids,detections=str(d));scans=[]
                for i in range(5):
                    messages=[]
                    for sid in ids:
                        pose=np.array([sid*.1,0,0,0,0,0.]);box=np.array([[10-sid*.1,0,0,4.5,1.8,1.6,0.]])
                        np.savez(d/('%06d_%s.npz'%(i,sid)),boxes=box,scores=np.array([.9]),lidar_pose=pose)
                        messages.append(dict(source_id=sid,frame=i,timestamp=i*.1,pose_xyz=pose[:3].tolist(),yaw=0.,tracks=[],fov_boundary=[[-100,-100],[100,-100],[100,100],[-100,100]]))
                    scans.append(dict(frame=i,index=i,timestamp=i*.1,messages=messages))
                rows=list(native_adapter.replay_online(dict(job_id='fixture'),spec,scans))
                self.assertTrue(rows);self.assertTrue(any(r['newborn'] for r in rows))
                self.assertTrue(all(len(r['U'])==n and len(r['X'])==n and len(r['C'])==n for r in rows))
                self.assertTrue(all(r['query_geometry'] is None for r in rows if r['newborn']))


if __name__=='__main__':unittest.main()
