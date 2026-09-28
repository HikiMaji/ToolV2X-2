"""Verify expanded training and independently evaluate the unchanged old development tasks."""
from pathlib import Path
from collections import Counter
import json, math
import torch
from planning import train_structured_driver as T
from planning.structured_validation import evidence_condition, frame_condition_weights, summarize_measurements
BASE=Path(__file__).resolve().parent;ROOT=BASE.parents[1]
def read(p):return json.loads(Path(p).read_text())
rows=[json.loads(x) for x in (BASE/'rows.jsonl').read_text().splitlines()]
trace=[json.loads(x) for x in (BASE/'training_trace.jsonl').read_text().splitlines()]
config=read(BASE/'training_config.json')
coverage=read(BASE/'coverage.json')
N=coverage['optimizer_steps'];epochs=config['epochs']
steps=[r for r in trace if r['kind']=='step'];train=[r for r in trace if r['kind']=='train']
assert len(steps)==N and [r['optimizer_steps'] for r in steps]==list(range(1,N+1))
assert len(train)==coverage['train_rows']*epochs and all(r['role']=='train' and math.isfinite(r['loss']) for r in train)
expected=Counter((r['sample_id'],r['stage'],evidence_condition(r)) for r in rows if r['role']=='train')
actual=Counter((r['sample_id'],r['stage'],r['condition']) for r in train)
assert Counter({k:v*epochs for k,v in expected.items()})==actual
config=read(BASE/'training_config.json')
initial=T._load(BASE/'training/checkpoint_000000.pt');final=T._load(BASE/'training'/('checkpoint_%06d.pt'%N))
assert final['progress']['optimizer_steps']==N and final['progress']['epoch']==epochs
assert final['config']==config and config['save_interval']==config['validation']['interval_batches']==500
assert [x['batches'] for x in final['report']['validation_history']]==sorted(set([0,N]+list(range(500,N+1,500))))
original=T._load(ROOT/'outputs/structured_driver_fix_2026_09_15_v1/acceptance/initialized_seed7.pt')
assert T._same(initial['model_state'],original['model_state'])
changed=sum(not torch.equal(initial['model_state'][k],v) for k,v in final['model_state'].items())
assert changed>0
selected=read(BASE/'training/selection.json');assert selected is not None
T._load(BASE/'training'/selected['checkpoint'])
for path in sorted((BASE/'training').glob('checkpoint_*.pt')):
    T._load(path)
# Re-evaluate final held-out stages using the public checkpoint loader, no optimization.
planner=T.load_structured_planner(BASE/'training'/('checkpoint_%06d.pt'%N),device='cuda')
weights,_=frame_condition_weights(rows,'validation');records=[]
with torch.no_grad():
    for i,row in enumerate(rows):
        if row['role']!='validation':continue
        task=read(row['source_task'])
        _,detail=T.training_loss(planner.model,T._read_features(row['inputs']['feature_path']),row,task=task,
            refinement_depth=config['refinement_depth'],objective=config['objective'],evaluation=True)
        records.extend(dict(m,stage=row['stage'],condition=evidence_condition(row,task),weight=weights[i],
                            label=row['supervision'],execution_spec=task['episode']['limits']['execution_spec'])
                       for m in detail['measurements'])
recomputed=summarize_measurements(records,None)
archived=final['report']['validation_history'][-1]['metrics']
# Preserve any tiny CUDA difference; do not recast allclose as bitwise equivalence.
def max_numeric_diff(a,b):
    if isinstance(a,dict):
        assert a.keys()==b.keys();return max([max_numeric_diff(a[k],b[k]) for k in a]+[0.])
    if isinstance(a,list):
        assert len(a)==len(b);return max([max_numeric_diff(x,y) for x,y in zip(a,b)]+[0.])
    if isinstance(a,(int,float)) and not isinstance(a,bool):
        assert isinstance(b,(int,float)) and math.isfinite(a) and math.isfinite(b)
        return abs(a-b)
    assert a==b;return 0.
difference=max_numeric_diff(archived,recomputed)
for kind in ('selected_stage','refinements'):
    for key in ('rows','valid_plans','invalid_plans','valid_label_points'):
        assert archived[kind][key]==recomputed[kind][key]
unchanged=0
for p in (BASE/'source_snapshot').rglob('*.py'):
    assert p.read_bytes()==(ROOT/p.relative_to(BASE/'source_snapshot')).read_bytes();unchanged+=1
# Full source-task content comparison against retained fit input snapshots.
sources=list(dict.fromkeys(r['source_task'] for r in rows))
for i,p in enumerate(sources):assert read(p)==read(BASE/'training/inputs'/('task_%06d.json'%i))
result=dict(version='toolv2x_structured_driver_small_fit_result_v1',status='completed_expanded_five_epochs',
    optimizer_steps=N,epochs_completed=epochs,train_rows_consumed=len(train),validation_rows=coverage['validation_rows'],
    train_conditions=dict(Counter(r['condition'] for r in train)),changed_parameter_tensors=changed,
    initial_equals_previous_seed7=True,checkpoint_full_load_checks=True,selected_checkpoint=selected,
    validation_history=final['report']['validation_history'],reloaded_final_validation=recomputed,
    reloaded_validation_exact=recomputed==archived,reloaded_validation_max_numeric_difference=difference,
    invalid_prior_masks=final['report']['invalid_prior_masks'],invalid_prior_reasons=final['report']['invalid_prior_reasons'],
    train_mean_raw_row_loss=sum(r['loss'] for r in train)/len(train),
    source_files_byte_identical=unchanged,task_snapshots_equal=len(sources),
    runtime=read(BASE/'training_result.json'),training_phase_new_provider_calls=0,training_phase_new_got_calls=0,training_phase_new_mtr_calls=0,
    scope='Expanded existing development recordings; real collection precedes fixed-evidence driver training; not independent test or sequential method superiority.')
# Compare on the SAME previously archived 32 development rows, independently of cohort expansion.
old_rows=[json.loads(x) for x in (ROOT/'outputs/structured_driver_fit_20ep_2026_09_15_v1/rows.jsonl').read_text().splitlines()]
old_weights,_=frame_condition_weights(old_rows,'validation')
old_summaries={}
for tag,ckpt in [('initial',BASE/'training/checkpoint_000000.pt'),('final',BASE/'training'/('checkpoint_%06d.pt'%N)),('selected',BASE/'training'/selected['checkpoint'])]:
    loaded=T.load_structured_planner(ckpt,device='cuda')
    measurements=[]
    with torch.no_grad():
        for i,row in enumerate(old_rows):
            if row['role']!='validation':continue
            task=read(row['source_task'])
            _,detail=T.training_loss(loaded.model,T._read_features(row['inputs']['feature_path']),row,task=task,
                refinement_depth=config['refinement_depth'],objective=config['objective'],evaluation=True)
            measurements.extend(dict(m,stage=row['stage'],condition=evidence_condition(row,task),weight=old_weights[i],
                label=row['supervision'],execution_spec=task['episode']['limits']['execution_spec']) for m in detail['measurements'])
    old_summaries[tag]=summarize_measurements(measurements,None)
    del loaded
result['old_development_same_archive_comparison']=old_summaries
result['coverage']=coverage
result['collection_progress']=read(BASE/'collection/progress.json')
(BASE/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('validation_history','reloaded_final_validation')},ensure_ascii=False),flush=True)
