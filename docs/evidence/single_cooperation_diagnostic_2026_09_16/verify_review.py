"""Recompute frozen diagnostic metrics from saved points with only stdlib."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def close(left, right):
    if left is None or right is None:
        assert left is right, (left, right)
    else:
        assert math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-10), (left, right)


def verify(directory):
    root = Path(directory)
    config = json.loads((root/'run.json').read_text())
    rows = [json.loads(line) for line in (root/'predictions.jsonl').read_text().splitlines()]
    summary = json.loads((root/'summary.json').read_text())
    audit = json.loads((root/'audit.json').read_text())
    assert audit['state']=='completed' and audit['model_parameters_unchanged'] and audit['checkpoint_files_unchanged']
    assert len(rows)==config['frames']*len(config['checkpoints'])
    assert len({(r['sample_id'],r['checkpoint_step']) for r in rows})==len(rows)
    outputs_checked = 0
    for row in rows:
        assert row['role']=='validation' and row['label']['times_seconds']==[.5,1.,1.5,2.,2.5,3.]
        assert all(row['label']['valid']), 'This verification requires the declared complete labels'
        for value in row['outputs'].values():
            distances = [math.hypot(p[0]-q[0], p[1]-q[1]) for p,q in
                         zip(value['waypoints'],row['label']['waypoints'])]
            assert len(distances)==6
            computed = dict(ADE3=sum(distances)/6,FDE3=distances[-1],
                got_prefix_L2_avg=(sum(distances[:2])/2+sum(distances[:4])/4+sum(distances)/6)/3)
            for name, number in computed.items():
                close(value['metrics'][name], number)
            points = value['waypoints']
            speeds = [math.hypot(b[0]-a[0],b[1]-a[1])/.5 for a,b in
                      zip([[0.,0.]]+points[:-1],points)]
            # The production validator uses vector acceleration, not scalar speed differences.
            velocities = [[(b[0]-a[0])/.5,(b[1]-a[1])/.5] for a,b in
                          zip([[0.,0.]]+points[:-1],points)]
            accels = [math.hypot(b[0]-a[0],b[1]-a[1])/.5 for a,b in zip(velocities,velocities[1:])]
            finite = all(math.isfinite(x) for p in points for x in p)
            expected_valid = (finite and max(speeds)<=config['execution_spec']['max_plan_speed_mps'] and
                max(accels)<=config['execution_spec']['max_plan_acceleration_mps2'])
            assert expected_valid==value['valid_plan']
            outputs_checked += 1
        for arm in ('P','F','PF'):
            for suffix,ref_name,new_name in (
                ('shared_evidence','Ego_shared_prior',arm+'_shared_prior'),
                ('once_evidence','Ego_once',arm+'_once'),
                ('remote_removal',arm+'_shared_prior',arm+'_without_remote'),
                ('stripped_vs_ego','Ego_shared_prior',arm+'_without_remote')):
                ref,new = row['outputs'][ref_name],row['outputs'][new_name]
                saved=row['pairs'][arm+'_'+suffix]
                if not ref['valid_plan'] or not new['valid_plan']:
                    assert saved['outcome']=='invalid_pair'; continue
                delta=new['metrics']['ADE3']-ref['metrics']['ADE3']
                ds=[math.hypot(a[0]-b[0],a[1]-b[1]) for a,b in zip(ref['waypoints'],new['waypoints'])]
                close(saved['ade_delta_m'],delta)
                close(saved['trajectory_mean_delta_m'],sum(ds)/6)
                close(saved['trajectory_max_delta_m'],max(ds))
                expected='improved' if delta < -config['threshold_m'] else (
                    'harmed' if delta > config['threshold_m'] else 'within_threshold')
                assert saved['outcome']==expected
    for step,groups in summary.items():
        cohort=[r for r in rows if r['checkpoint_step']==int(step)]
        assert len(cohort)==config['frames']
        named={'all':cohort,
            'obstacle_interaction_proxy':[r for r in cohort if any(r['content'][a]['obstacle_interaction_proxy'] for a in ('P','F','PF'))],
            'no_obstacle_interaction_proxy':[r for r in cohort if not any(r['content'][a]['obstacle_interaction_proxy'] for a in ('P','F','PF'))]}
        named.update({'recording:'+k:[r for r in cohort if r['recording']==k] for k in groups['recordings']})
        for name,subset in named.items():
            saved=groups['recordings'][name[10:]] if name.startswith('recording:') else groups[name]
            assert len(subset)==saved['frames']
            for arm,value in saved['outputs'].items():
                selected=[r['outputs'][arm] for r in subset]
                assert value['invalid']==sum(not r['valid_plan'] for r in selected)
                for metric in ('ADE3','FDE3','got_prefix_L2_avg'):
                    vals=[r['metrics'][metric] for r in selected if r['valid_plan']]
                    close(value[metric],sum(vals)/len(vals) if vals else None)
            for pair, value in saved['pairs'].items():
                selected=[r['pairs'][pair] for r in subset]
                assert dict(Counter(r['outcome'] for r in selected))==value['outcomes']
                for metric in ('ade_delta_m','trajectory_mean_delta_m','trajectory_max_delta_m'):
                    vals=[r[metric] for r in selected if r[metric] is not None]
                    close(value[metric],sum(vals)/len(vals) if vals else None)
    return dict(state='verified',rows=len(rows),outputs_checked=outputs_checked,
        metric_implementation='stdlib hypot; independent of production trajectory_metrics',
        grouping_and_primary_evidence_pairs_verified=True,
        scope='Verifies saved numeric results, not dataset completeness or new online calls.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args=parser.parse_args()
    print(json.dumps(verify(args.directory),indent=2))
