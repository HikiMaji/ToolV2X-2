"""Small contracts for the new preparation boundary, without research jobs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.rq1_temporal import data, native_adapter as native
from scripts.rq1_score_revision import prepare


def job(jid='new', parent='p', family='F1', k=1):
    return dict(job_id=jid, source_clean_job_id='old', parent=parent, split='fit',
                kind='attack', family=family, attack_k=k, seed=0,
                source_ids=[1, 2, 3], controlled_sources=list(range(1, k+1)),
                normal_probe_source=k+1, origin='score_revision')


def row(j, frame, **kw):
    return dict(dict(j, id=frame % 3, epoch=frame % 2, frame=frame,
                     index=frame, timestamp=frame*.1, query_truth=0,
                     query_present=True, newborn=False, attack_role='target'), **kw)


class PrepareContracts(unittest.TestCase):
    def test_entity_fragments_and_duplicate_frames_do_not_inflate_support(self):
        config=prepare.read_config(); jobs=[]; rows=[]
        for family in ('F1', 'F2'):
            for i in range(6):
                j=job(family+str(i), 'p'+str(i//2), family, 1 if i%2 else 2)
                jobs.append(j)
                rows += [row(j, f) for f in range(10)]
                rows += [row(j, 0, id=99, epoch=9)]
        short=job('short', 'p9'); jobs.append(short)
        rows += [row(short, f) for f in range(9)]
        config['planned_fit_attacks']=jobs
        rows += [row(short, 99, query_present=False), row(short, 100, newborn=True),
                 row(short, 101, attack_role='occluder'), row(short, 102, query_truth=-1)]
        result=prepare.support_summary(iter(rows), config)
        self.assertEqual(result['families']['F1']['counted_entities'], 6)
        self.assertEqual(result['families']['F1']['counted_parents'], 3)
        self.assertEqual(result['entities']['short']['distinct_false_query_scans'], 9)
        self.assertEqual(result['entities']['F10']['distinct_false_query_scans'], 10)
        self.assertTrue(result['regimes']['mixed']['data_support_met'])
        self.assertEqual(result['short_nonempty_entities'], 1)

    def test_k_support_uses_short_entities_but_parent_gate_uses_counted_entities(self):
        config=prepare.read_config(); jobs=[]; rows=[]
        for i in range(6):
            j=job('long'+str(i), 'p'+str(i%2));jobs.append(j)
            rows += [row(j, f) for f in range(10)]
        j=job('short', 'p3', k=2);jobs.append(j);rows.append(row(j, 0))
        config['planned_fit_attacks']=jobs
        result=prepare.support_summary(rows, config)
        f=result['families']['F1']
        self.assertTrue(f['attack_k_support']['at_least_2'])
        self.assertEqual(f['counted_parents'], 2)
        self.assertFalse(result['regimes']['F1_only']['data_support_met'])
        self.assertFalse(result['regimes']['F2_only']['data_support_met'])

    def test_legacy_frame_join_strips_private_message_fields(self):
        packets=[]; ground=[]
        for index in range(2):
            messages=[dict(source_id=s, frame=10+2*index, timestamp=index*.1,
                           pose_xyz=[0, 0, 0], yaw=0, tracks=[], fov_boundary=[],
                           gt={'secret': 1}, echo={'secret': 2}) for s in (1, 2, 3)]
            packets.append(dict(frame=10+2*index,index=index,timestamp=index*.1,messages=messages))
            ground.append(dict(frame=10+2*index,available=True,boxes=[]))
        scans=prepare._legacy_scans(packets, ground, [1,2,3], packets)
        self.assertEqual([s['gt']['frame'] for s in scans], [10,12])
        self.assertEqual(scans[0]['echo'], {})
        self.assertNotIn('gt', scans[0]['messages'][0])
        with self.assertRaises(ValueError):
            prepare._legacy_scans(packets, ground[:1], [1,2,3], packets)
        wrong=copy.deepcopy(packets);wrong[0]['messages'].reverse()
        with self.assertRaises(ValueError):
            prepare._legacy_scans(wrong, ground, [1,2,3], packets)
        wrong=copy.deepcopy(packets);wrong[1]['frame']=99
        with self.assertRaises(ValueError):
            prepare._legacy_scans(wrong, ground, [1,2,3], packets)

    def test_iter_rows_preserves_clean_z_and_requires_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp); old=out/'old'; new=out/'jobs/new'
            old.mkdir();new.mkdir(parents=True)
            jobs=[dict(job('old'), origin='reference',kind='clean',family='clean',attack_k=0,
                       rows_path=str(old/'rows.jsonl.gz'),status_path=str(old/'complete.json')),
                  dict(job(), rows_path=str(new/'rows.jsonl.gz'),status_path=str(new/'complete.json')),
                  dict(job('absent'), origin='reference',rows_path=str(out/'absent.gz'),
                       status_path=str(out/'unrealizable.json'))]
            data.atomic_json(out/'manifest.json', dict(jobs=jobs))
            data.atomic_json(old/'complete.json', dict(status='COMPLETE'))
            data.atomic_json(out/'unrealizable.json', dict(status='UNREALIZABLE'))
            with data.atomic_rows(old/'rows.jsonl.gz') as write:
                write(dict(row(jobs[0],2),Z=[1,0,-1]))
            with data.atomic_rows(new/'rows.jsonl.gz') as write:
                write(row(jobs[1],3))
            with self.assertRaises(RuntimeError):
                list(prepare.iter_rows(out))
            data.atomic_json(new/'complete.json', dict(status='COMPLETE'))
            result=list(prepare.iter_rows(out,'fit'))
            self.assertEqual([r['job_id'] for r in result], ['old','new'])
            self.assertEqual(result[0]['Z'],[1,0,-1])

    def test_worker_failure_keeps_error_and_resumes_atomic_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);j=job();scan_path=out/'scans.jsonl.gz'
            with data.atomic_rows(scan_path) as write:
                write(dict(frame=0,index=0,timestamp=0.,messages=[],gt={'available':True},echo={}))
            manifest=dict(jobs=[j], parents={'p':dict(scan_path=str(scan_path),spec={'source_ids':[1,2,3]})})
            data.atomic_json(out/'manifest.json', manifest)
            attack=dict(status='VALID', controlled_sources=[1], normal_source=2, entities=[[]])
            def broken(*args):
                yield dict(frame=0, job_id='new')
                raise ValueError('interrupted replay')
            def online(_job, _spec, scans, _attack):
                self.assertEqual(set(next(iter(scans))), {'frame','index','timestamp','messages'})
                yield dict(frame=0,job_id='new')
            def labelled(events, scans, j, attack, diagnostics, coverage_writer):
                list(events)
                coverage_writer(dict(role='target',phase='active',frame=0,job_id='new',index=0,query_present=True))
                yield row(j,0)
            with patch.object(native,'construct_attack',return_value=attack), patch.object(native,'replay_online',side_effect=broken):
                with self.assertRaises(ValueError):
                    prepare._worker(out,'new')
            dest=out/'jobs/new'
            self.assertTrue((dest/'error.json').exists())
            self.assertFalse((dest/'complete.json').exists())
            self.assertFalse((dest/'online.jsonl.gz').exists())
            self.assertTrue((dest/'online.jsonl.gz.partial').exists())
            with patch.object(native,'construct_attack',side_effect=AssertionError('must reuse attack')), patch.object(native,'replay_online',side_effect=online), patch.object(native,'attach_labels',side_effect=labelled):
                prepare._worker(out,'new')
            status=json.loads((dest/'complete.json').read_text())
            self.assertEqual(status['rows'],1)
            self.assertEqual(status['entity_coverage']['target']['active']['query_present'],1)
            before=(dest/'complete.json').read_bytes()
            with patch.object(native,'construct_attack',side_effect=AssertionError('completed job reran')):
                prepare._worker(out,'new')
            self.assertEqual((dest/'complete.json').read_bytes(),before)
            self.assertTrue((dest/'error.json').exists())

    def test_label_recovery_reuses_online_and_rebuilds_missing_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);dest=out/'jobs/new';dest.mkdir(parents=True)
            scan_path=out/'scans.jsonl.gz'
            with data.atomic_rows(scan_path) as write:
                write(dict(frame=0,index=0,timestamp=0.,messages=[],gt={},echo={}))
            data.atomic_json(out/'manifest.json',dict(jobs=[job()],parents={'p':dict(scan_path=str(scan_path),spec={})}))
            data.atomic_json(dest/'attack.json',dict(status='VALID',controlled_sources=[1],normal_source=2))
            with data.atomic_rows(dest/'online.jsonl.gz') as write:
                write(dict(frame=0))
            with data.atomic_rows(dest/'rows.jsonl.gz') as write:
                write(row(job(),0))
            original=(dest/'rows.jsonl.gz').read_bytes()
            def labelled(events, scans, j, attack, diagnostics, coverage_writer):
                list(events)
                coverage_writer(dict(role='target',phase='active',frame=0,job_id='new',index=0,query_present=True))
                yield row(j,0)
            with patch.object(native,'replay_online',side_effect=AssertionError('must reuse online')), patch.object(native,'attach_labels',side_effect=labelled):
                prepare._worker(out,'new')
            self.assertEqual((dest/'rows.jsonl.gz').read_bytes(),original)
            self.assertEqual(json.loads((dest/'complete.json').read_text())['rows'],1)
            self.assertTrue((dest/'entity_coverage.jsonl.gz').exists())

    def test_source_run_is_rejected_before_any_lock_write(self):
        config=prepare.read_config()
        with tempfile.TemporaryDirectory() as temp:
            old=Path(temp)/'old';old.mkdir()
            config['source_manifest']['path']=str(old/'manifest.json')
            with patch.object(prepare,'read_config',return_value=config):
                with self.assertRaises(ValueError):
                    prepare.prepare(old)
            self.assertEqual(list(old.iterdir()),[])

    def test_unrealizable_attempt_is_terminal_without_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);path=out/'scans.jsonl.gz'
            with data.atomic_rows(path) as write:
                write(dict(frame=0))
            data.atomic_json(out/'manifest.json',dict(jobs=[job()],parents={'p':dict(scan_path=str(path),spec={})}))
            with patch.object(native,'construct_attack',return_value=dict(status='UNREALIZABLE',reason='fixed proposals exhausted')), patch.object(native,'replay_online',side_effect=AssertionError('unrealizable replayed')):
                prepare._worker(out,'new')
            self.assertEqual(json.loads((out/'jobs/new/complete.json').read_text())['status'],'UNREALIZABLE')
            self.assertEqual(list(prepare.iter_rows(out)),[])


if __name__=='__main__':
    unittest.main()
