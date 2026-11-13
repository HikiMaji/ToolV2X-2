"""Bounded re5 formula audit; no fitting, calibration, or experiment mutation."""
import gzip
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/root/autodl-tmp/ToolV2X')
WORK = ROOT / '.worktrees/rq1-temporal-2026-11-12'
sys.path.insert(0, str(WORK))
from scripts.rq1_temporal.kernel import false_window


def proposed_mcs(events, pi=.1, eps=.001, s=.9):
    u = np.asarray(events, dtype=int)
    candidates = []
    for size in range(u.shape[1] + 1):
        for subset in itertools.combinations(range(u.shape[1]), size):
            other = [i for i in range(u.shape[1]) if i not in subset]
            control = false_window(u[:, list(subset)], s)['loglik'] if subset else 0.
            honest = int(np.sum(u[:, other] == 1)) * math.log(eps)
            honest += int(np.sum(u[:, other] == 0)) * math.log1p(-eps)
            likelihood = control + honest
            candidates.append(dict(S=list(subset), m=size, selected_loglik=likelihood,
                                   loglik=size * math.log(pi) + likelihood))
    return max(candidates, key=lambda item: item['loglik'])


def main():
    run = ROOT / 'docs/evidence/rq1_temporal_2026_11_12/run_001'
    source = ROOT / 'docs/CC_re/re5.md'
    report = dict(scope='Finite formula/case audit; not MCS effectiveness experiment',
                  re5_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  kernel_sha256=hashlib.sha256((WORK/'scripts/rq1_temporal/kernel.py').read_bytes()).hexdigest())
    q = [math.exp(proposed_mcs([[event]])['loglik']) for event in (0, 1)]
    report['normalization'] = dict(q0=q[0], q1=q[1], total=sum(q))
    silent = proposed_mcs([[0, 0]] * 10)
    report['all_silent'] = dict(p=.0001, eps=.001, pi=.1, sources=2, frames=10,
                               normal_loglik=20*math.log1p(-.0001), false=silent,
                               score=20*math.log1p(-.0001)-silent['loglik'])
    previous = json.loads((run.parent/'execution_2026_11_13/adoption_decomposition.json').read_text())
    case = previous['false_accepted_J'][0]
    with gzip.open(run/'jobs'/case['job_id']/'rows.jsonl.gz', 'rt') as stream:
        row = next(json.loads(line) for line in stream
                   if (lambda x: x['id'] == case['id'] and x['frame'] == case['frame'])(json.loads(line)))
    u = [row['U']]
    old = false_window(u)['loglik']
    new = proposed_mcs(u)
    normal = case['J_score'] + old
    report['frozen_first_window'] = dict(key=row['key'], U=u, old_false_loglik=old,
        old_J=case['J_score'], normal_loglik=normal, mcs=new,
        new_uncalibrated_J=normal-new['loglik'], shift=old-new['loglik'],
        interpretation='Same frozen normal likelihood; new thresholds not calibrated. Two-support-frame gate blocks this first frame by definition.')
    report['pi_axis_same_window'] = []
    for pi in (.3, .1, .03):
        value = proposed_mcs(u, pi=pi)
        report['pi_axis_same_window'].append(dict(pi=pi, m_star=value['m'],
                                                score=normal-value['loglik']))
    prefix, full = [[1, 0]], [[1, 0], [1, 1]]
    pstar, fstar = proposed_mcs(prefix), proposed_mcs(full)
    report['retrospective_selection'] = dict(prefix=prefix, full=full,
        prefix_S=pstar['S'], full_S=fstar['S'],
        source_1_first_q_prefix=.001 if 1 not in pstar['S'] else .225,
        source_1_first_q_full=.001 if 1 not in fstar['S'] else .225,
        explanation='At the later decision this uses only available history, but reconstructed past q is selected using the whole window; it is not the original causal predictive marginal.')
    report['omitted_penalty'] = dict(selected_likelihood_sum=new['selected_loglik'],
        declared_total=new['loglik'], difference=new['loglik']-new['selected_loglik'])
    report['mstar_depends_on_prior'] = [dict(pi=pi, **proposed_mcs([[1]], pi=pi, eps=.01))
                                       for pi in (.03, .3)]
    manifest = json.loads((run/'manifest.json').read_text())
    report['fit_task_counts'] = {kind: sum(j['split']=='fit' and j['kind']==kind for j in manifest['jobs'])
                                 for kind in ('clean', 'attack')}
    assert report['normalization']['total'] > 1
    assert report['all_silent']['score'] > 0
    assert new['S'] == [0, 1, 2]
    assert pstar['S'] == [0] and fstar['S'] == [0, 1]
    report['audit_status'] = 'Specified re5 universal properties and unchanged probability decomposition do not hold'
    destination = Path(__file__).with_name('results.json')
    with destination.open('x') as output:
        json.dump(report, output, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
