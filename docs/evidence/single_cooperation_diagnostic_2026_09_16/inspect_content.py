"""Post-hoc source-content comparison; no new driver output or parameter updates."""
from pathlib import Path
from collections import Counter
import json
import sys

import numpy as np
import torch

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'src/planning/structured_driver.py').is_file())
sys.path.insert(0,str(ROOT/'src'))
from planning.structured_driver import _masked_point_max
from planning.train_structured_driver import load_structured_planner

BASE=Path(__file__).resolve().parent
records=[json.loads(l) for l in (BASE/'predictions.jsonl').read_text().splitlines()]
records=[r for r in records if r['checkpoint_step']==500]
torch.set_num_threads(1)
models={s:load_structured_planner(ROOT/'outputs/structured_driver_expanded_2026_09_15_v1/training'/
    ('checkpoint_%06d.pt'%s)).model.eval().requires_grad_(False) for s in [0,500,3200]}
result=[]
for row in records:
 for arm in ['P','F','PF']:
  task=json.loads(Path(row['source_tasks'][arm]['source_task']).read_text())
  p=task['episode']['plans'][-1]['prepared']; raw=p['tensor_inputs']
  assert all(p['driver_spec']==model.spec.to_dict() for model in models.values())
  position_scale=p['driver_spec']['position_scale_m']
  obs=np.asarray(raw['observations']); om=np.asarray(raw['observation_mask'])
  fs=np.asarray(raw['forecasts']); fm=np.asarray(raw['forecast_mask']); fc=np.asarray(raw['forecast_context'])
  weights={}
  if arm in ('P','PF'):
   for step,model in models.items():
    with torch.inference_mode():
     encoded,valid=_masked_point_max(torch.tensor(obs,dtype=torch.float32),torch.tensor(om),
         model.observation_encoder,model.null_observation)
     encoded=model.observation_post(encoded)+model.source_role(torch.tensor(raw['observation_sources']))
     safe=valid.clone();safe[:,0] |= ~safe.any(dim=1)
     encoded=torch.where(valid.unsqueeze(-1),encoded,model.null_observation.reshape(1,1,-1))
     query=model.source_query.reshape(1,1,-1).expand(len(obs),1,-1)
     _,attention=model.source_attention(query,encoded,encoded,key_padding_mask=~safe,need_weights=True)
     weights[step]=attention[:,0,1].cpu().tolist()
  for entity in p['entities']:
   i=entity['tensor_index']
   if i is None:continue
   remote=np.flatnonzero(fm[i].any(axis=(1,2)) & (fc[i,:,0]==0))
   if not om[i,1].any() and not len(remote):continue
   local=np.flatnonzero(fm[i].any(axis=(1,2)) & (fc[i,:,0]==1))
   common=om[i,0] & om[i,1]
   item=dict(sample_id=row['sample_id'],recording=row['recording'],arm=arm,
       entity_id=entity['entity_id'],role=entity['role'],aliases=entity['aliases'],
       common_history_points=int(common.sum()),remote_history_points=int(om[i,1].sum()),
       local_history_points=int(om[i,0].sum()),
       history_xy_difference_m=float(np.linalg.norm((obs[i,1,common,:2]-obs[i,0,common,:2])*position_scale,axis=-1).mean())
          if common.any() else None,
       remote_attention={str(s):w[i] for s,w in weights.items()}
          if om[i,0].any() and om[i,1].any() else {},forecast_differences=[])
   for a in local:
    lm=int(np.argmax(fs[i,a,:,0,3]))
    for b in remote:
     rm=int(np.argmax(fs[i,b,:,0,3]))
     item['forecast_differences'].append(dict(local_slot=int(a),remote_slot=int(b),
        local_mode=lm,remote_mode=rm,
        top_mode_path_distance_m=float(np.linalg.norm((fs[i,a,lm,:,:2]-fs[i,b,rm,:,:2])*position_scale,axis=-1).mean()),
        same_index_all_modes_distance_m=float(np.linalg.norm((fs[i,a,:,:,:2]-fs[i,b,:,:,:2])*position_scale,axis=-1).mean())))
   result.append(item)
print('records',len(result),flush=True)
summary={}
def stats(values):
 return dict(n=len(values),mean=float(np.mean(values)),median=float(np.median(values)),
     min=float(np.min(values)),max=float(np.max(values))) if values else dict(n=0)
for arm in ['P','F','PF']:
 rows=[r for r in result if r['arm']==arm]
 summary[arm]=dict(roles=dict(Counter(r['role'] for r in rows)),
    history_xy_difference_m=stats([r['history_xy_difference_m'] for r in rows if r['history_xy_difference_m'] is not None]),
    matched_forecast_top_mode_path_distance_m=stats([p['top_mode_path_distance_m'] for r in rows for p in r['forecast_differences']]),
    remote_attention={str(s):stats([r['remote_attention'][str(s)] for r in rows if str(s) in r['remote_attention']]) for s in models})
out=dict(scope='Post-hoc content and observation-fusion explanation. Attention is module-level, not attribution of final driving quality. '
    'Forecast comparisons require no future labels and do not establish which source is more accurate. '
    'No new complete driver forwards, provider calls, or optimizer steps.',summary=summary,records=result)
(BASE/'content_comparison.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
print(json.dumps(summary,indent=2))
