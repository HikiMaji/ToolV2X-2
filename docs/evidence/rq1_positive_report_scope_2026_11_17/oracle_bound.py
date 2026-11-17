"""Posthoc upper bound to reject one candidate, NOT a calibrated policy.

Run from the execution worktree. Evaluation labels are deliberately used to
find the most optimistic scalar threshold. Never deploy the returned cutoffs.
"""
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.rq1_evidence_scope_audit import primary, weights

RUN = Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_joint_supplement_2026_11_17/run_002')


def rows(path):
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def main():
    records = [r for r in rows(RUN/'predictions/additional/mixed/eval.jsonl.gz') if primary(r)]
    for truth in (0, 1):
        subset = [r for r in records if r['query_truth'] == truth]
        for row, weight in zip(subset, weights(subset)):
            row['mass'] = weight
    accepted = {tuple(r['key']): r for r in records if r['decisions']['Cond'] == 'accept'}
    for path in sorted((RUN/'features/additional').glob('*.gz')):
        for feature in rows(path):
            row = accepted.get(tuple(feature['key']))
            if row is not None:
                x = feature['features']['D_head']
                assert x[2] > 0
                row['Splus'] = -x[0]/x[2]
    assert all('Splus' in r and math.isfinite(r['Splus']) for r in accepted.values())
    true = [r for r in accepted.values() if r['query_truth'] == 1]
    false = [r for r in accepted.values() if r['query_truth'] == 0]
    layers = defaultdict(float)
    for row in records:
        if row['query_truth'] == 0:
            layers[row['family'], row['attack_k']] += row['mass']
    base_ta = math.fsum(r['mass'] for r in true)
    cutoffs = [-math.inf] + sorted({r['Splus'] for r in accepted.values()}) + [math.inf]
    points = []
    for cutoff in cutoffs:
        loss = math.fsum(r['mass'] for r in true if r['Splus'] > cutoff)
        remaining = [r for r in false if r['Splus'] <= cutoff]
        layer_fa = {f'{f}/{k}': math.fsum(r['mass'] for r in remaining
                    if (r['family'], r['attack_k']) == (f, k))/mass
                    for (f, k), mass in layers.items()}
        points.append(dict(oracle_cutoff=cutoff if math.isfinite(cutoff) else str(cutoff),
            TA_loss=loss, TA=base_ta-loss, FA=math.fsum(r['mass'] for r in remaining),
            FA_layers=layer_fa, remaining_false_times=len(remaining)))
    within_loss = [p for p in points if p['TA_loss'] <= .02+1e-12]
    within_risk = [p for p in points if p['FA'] <= .05+1e-12
                   and max(p['FA_layers'].values()) <= .05+1e-12]
    result = dict(scope='posthoc optimistic threshold feasibility only; additional mixed; not calibration, new policy, or confirmatory effectiveness',
        score='Splus=-sum(U=1)log(p_D)/n_plus; Cond accepts with Splus>cutoff would become unknown',
        TA_budget=.02, FA_budget=.05,
        base=dict(TA=base_ta, FA=math.fsum(r['mass'] for r in false),
            true_rows=sum(r['query_truth'] == 1 for r in records),
            false_rows=sum(r['query_truth'] == 0 for r in records),
            accepted_true=len(true), accepted_false=len(false)),
        best_FA_at_TA_budget=min(within_loss, key=lambda p: (p['FA'], -p['TA'])),
        minimum_TA_loss_at_global_and_layer_FA_budget=min(within_risk, key=lambda p: p['TA_loss']),
        feasible=any(p['TA_loss'] <= .02+1e-12 for p in within_risk))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
