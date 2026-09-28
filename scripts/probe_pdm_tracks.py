#!/usr/bin/env python3
"""Fixed-time local PDM sensitivity replay, never a cooperative-effect benchmark."""
import argparse,copy,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from planning.pdm_core import PDMCore

p=argparse.ArgumentParser();p.add_argument('--tracks',required=True);p.add_argument('--output',required=True)
a=p.parse_args();dest=Path(a.output)
if dest.exists():raise ValueError('new output path required')
rows=json.loads(Path(a.tracks).read_text());results=[];core=PDMCore()
for row in rows:
    if row['vehicle']!=0:continue
    scene=row['scene'];actual=core.plan(scene);empty=copy.deepcopy(scene);empty['objects']=[]
    baseline=core.plan(empty)
    results.append(dict(frame=row['frame'],index=row['index'],actual=actual,empty_obstacle_diagnostic=baseline,
        mean_waypoint_difference_m=float(np.linalg.norm(np.asarray(actual['waypoints'])-np.asarray(baseline['waypoints']),axis=1).mean())))
dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(dict(
    scope='fixed-time local evidence sensitivity; empty arm is NOT ego baseline; no closed-loop or cooperative claim',
    real_pdm_calls=2*len(results),results=results),indent=2)+'\n')
