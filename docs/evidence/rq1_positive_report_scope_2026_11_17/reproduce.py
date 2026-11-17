"""Describe saved positive evidence; no fitting, thresholds or changed decisions.

Run from the execution worktree. Prints JSON; redirect to a new file to preserve
the archived result. Weights are formed on each complete main class first.
"""
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.rq1_evidence_scope_audit import primary, weights, quantiles, auc, ep

RUN = Path('/root/autodl-tmp/ToolV2X/docs/evidence/rq1_joint_supplement_2026_11_17/run_002')


def rows(path):
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def summary(records):
    return dict(n=len(records), parents=len({r['parent'] for r in records}),
                entities=len({ep(r) for r in records}),
                mass=math.fsum(r['mass'] for r in records),
                mean_report_probability=quantiles([(r['positive_p_geomean'], r['mass']) for r in records]),
                mean_positive_surprise=quantiles([(r['R_ind'], r['mass']) for r in records]))


def main():
    records = [r for r in rows(RUN / 'predictions/additional/mixed/eval.jsonl.gz') if primary(r)]
    for truth in (0, 1):
        subset = [r for r in records if r['query_truth'] == truth]
        for row, weight in zip(subset, weights(subset)):
            row['mass'] = weight
    selected = {tuple(r['key']): r for r in records
                if r['decisions']['Count'] == 'accept' and sum(r['n_minus']) == 0}
    for path in sorted((RUN / 'features/additional').glob('*.gz')):
        for feature in rows(path):
            row = selected.get(tuple(feature['key']))
            if row is not None:
                x = feature['features']['D_head']
                assert x[2] > 0
                # Reuse the audit's generic ranking helper; R_ind here is Splus.
                row['R_ind'] = -x[0] / x[2]
                row['positive_p_geomean'] = math.exp(x[0] / x[2])
                row['source_evidence'] = feature['sources']['D_head']
    assert all('R_ind' in r for r in selected.values())
    cells = defaultdict(lambda: {0: [], 1: []})
    for row in selected.values():
        key = (row['parent'], *row['Count_inputs'], row['accept_eligible'], row['reject_eligible'])
        cells[key][row['query_truth']].append(row)
    common = []
    for key, cell in cells.items():
        if cell[0] and cell[1]:
            common.append(dict(stratum=list(key),
                weight=min(math.fsum(r['mass'] for r in cell[y]) for y in (0, 1)),
                auc=auc(cell[1], cell[0]), true=summary(cell[1]), false=summary(cell[0])))
    overlap = math.fsum(c['weight'] for c in common)
    example = selected[('748caf659d7d990e', 117, 98)]
    out = dict(scope='additional mixed Count-accepted no-effective-miss records only; descriptive; no fit, thresholds or new decisions',
        score='Splus=-sum(U=1)log(p_D)/n_plus; larger means more surprising reports under normal model',
        source=str(RUN),
        selection={str(y): summary([r for r in selected.values() if r['query_truth'] == y]) for y in (0, 1)},
        matched=dict(cells=len(common), overlap_mass=overlap,
            false_larger_surprise_auc=math.fsum(c['weight']*c['auc'] for c in common)/overlap if overlap else None,
            details=common),
        example={k: example[k] for k in ('key', 'Count_inputs', 'positive_p_geomean', 'source_evidence')})
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
