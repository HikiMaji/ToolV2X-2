"""Describe saved errors and replay old frozen policies; no new policy selection."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from scripts.rq1_temporal import run as original
from scripts import rq1_independent_supplement as supplement


def main(run):
    run = Path(run)
    source = Path('/root/autodl-tmp/ToolV2X/docs/evidence')
    result = dict(scope='descriptive saved-output analysis; old policies are context references without the new local channel', regimes={})
    for regime in ('mixed', 'F1_only', 'F2_only'):
        with gzip.open(run/'predictions'/regime/'eval.jsonl.gz', 'rt') as stream:
            rows = [json.loads(line) for line in stream]
        count_policy = json.loads((source/'rq1_report_freeze_2026_11_13/run_001/calibration'/f'{regime}.json').read_text())['policies']['Count']
        cond_policy = json.loads((source/'rq1_independent_supplement_2026_11_16/run_001/calibration'/f'{regime}.json').read_text())['branches']['Cond']
        for row in rows:
            public = {k: row[k] for k in ('finite', 'accept_eligible', 'reject_eligible')}
            public['scores'] = {'Count': row['C']}
            base = original.decide(public, 'Count', count_policy)
            cond = supplement.decide(base, bool(row['finite']) and supplement.finite(row['C']),
                row['query_present'], row['newborn'], row['reject_eligible'], row['R'], cond_policy)
            row['old_Count'], row['old_Cond'] = base, cond['decision']
        output = dict(old_reference={}, false_accept_entities={})
        for truth in (0, 1):
            selected = [row for row in rows if original.primary(row, truth)]
            weights = original.weights(selected, truth)
            for method in ('old_Count', 'old_Cond'):
                rates = {decision: math.fsum(float(w) for row, w in zip(selected, weights)
                    if row[method] == decision) for decision in ('accept', 'unknown', 'reject')}
                output['old_reference'].setdefault(method, {})['true' if truth else 'false'] = rates
            if truth:
                output['true_message_accept_mass'] = math.fsum(float(w) for row, w in zip(selected, weights)
                    if row['decision_reasons']['LocalCond'] == 'message_support')
                continue
            entities = defaultdict(lambda: dict(n=0, mass=0., zero_R=0, states=Counter(), reasons=Counter(), F=[], I=[]))
            for row, weight in zip(selected, weights):
                if row['decisions']['LocalCond'] != 'accept':
                    continue
                entry = entities[row['job_id']]
                entry.update(parent=row['parent'], family=row['family'], k=row['attack_k'])
                entry['n'] += 1
                entry['mass'] += float(weight)
                entry['zero_R'] += row['R'] == 0
                entry['states'][row['local_state']] += 1
                entry['reasons'][row['decision_reasons']['LocalCond']] += 1
                for field in ('F', 'I'):
                    if row[field] is not None:
                        entry[field].append(row[field])
            for entry in entities.values():
                for field in ('F', 'I'):
                    entry[field] = [min(entry[field]), max(entry[field])] if entry[field] else None
            output['false_accept_entities'] = dict(entities)
        for table in output['old_reference'].values():
            table['CD'] = (table['true']['accept']+table['false']['reject'])/2
        result['regimes'][regime] = output
    path = run/'saved_output_diagnostics.json'
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v['old_reference'] for k, v in result['regimes'].items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    main(parser.parse_args().run)
