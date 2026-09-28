"""Export expanded real collection using the existing supervision contract."""
from pathlib import Path
from collections import Counter
import json, math, shutil
from common.audit_protocol import recording
from planning.adaptation_data import ego_label
from planning.train_structured_driver import prepare_training_rows, _config
from planning.structured_validation import frame_condition_weights

BASE = Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text())
def save(name, value):
    (BASE/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')

selected = read(BASE/'selected_frames.json')
manifest = [json.loads(x) for x in (BASE/'collection/tasks.jsonl').read_text().splitlines()]
by_sample = {}
for ref in manifest: by_sample.setdefault(ref['sample_id'], []).append(ref)
eligible, labels, excluded = [], [], []
task_bytes = 0
for row in selected:
    refs = by_sample[row['sample_id']]
    assert len(refs) == 4 and {x['arm'] for x in refs} == {'Ego','P','F','PF'}
    failures = []
    for ref in refs:
        path = BASE/'collection'/ref['path']
        task = read(path)
        if task['status'] != 'completed' or task['episode']['status'] != 'completed':
            failures.append(dict(arm=ref['arm'], reason='collection_failure'))
        task_bytes += path.stat().st_size
    if failures:
        excluded.append(dict(sample_id=row['sample_id'], role=row['role'], failures=failures))
        continue
    label = dict(ego_label('train', row['g']), **{k:row[k] for k in ('sample_id','scene','g','role')})
    if not all(label['valid']):
        excluded.append(dict(sample_id=row['sample_id'], role=row['role'], failures=['incomplete_offline_label']))
        continue
    labels.append(label)
    eligible.extend(dict(ref, path='collection/'+ref['path']) for ref in refs)
save('excluded_frames.json', excluded)
counts = Counter(x['role'] for x in labels)
assert counts['train'] >= 144 and counts['validation'] >= 36, 'under 90% full-frame coverage; retained failures'
assert {(x['role'],recording(x['scene'])) for x in labels} == {(x['role'],recording(x['scene'])) for x in selected}
assert shutil.disk_usage(BASE).free > 6*1024**3 + task_bytes//2 + 1024**3, 'insufficient reserved training snapshot/checkpoint space'
(BASE/'eligible_tasks.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in eligible))
(BASE/'labels.jsonl').write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in labels))
rows = prepare_training_rows(BASE/'eligible_tasks.jsonl', labels)
assert len(rows) == 8*len(labels)
config = _config(read(BASE/'training_config.json'))
coverage = dict(frames=dict(counts), excluded_frame_count=len(excluded), intended_frames={'train':160,'validation':40})
for role in ('train','validation'):
    _, detail = frame_condition_weights(rows,role)
    assert all(not x['conditions'] for x in detail['missing_conditions'])
    coverage[role] = detail
    coverage[role]['recordings'] = sorted({r['recording'] for r in rows if r['role']==role})
assert not set(coverage['train']['recordings']) & set(coverage['validation']['recordings'])
coverage['train_rows'] = sum(r['role']=='train' for r in rows)
coverage['validation_rows'] = sum(r['role']=='validation' for r in rows)
coverage['optimizer_steps'] = config['epochs']*math.ceil(coverage['train_rows']/config['batch_size'])
assert coverage['optimizer_steps'] <= 3200
(BASE/'rows.jsonl').write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in rows))
save('coverage.json',coverage)
print(json.dumps({k:v for k,v in coverage.items() if k not in ('train','validation')}),flush=True)
