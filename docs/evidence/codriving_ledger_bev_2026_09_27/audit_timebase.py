"""Offline own-measurement clock consistency; no planner or target labels."""
import json
from pathlib import Path
import numpy as np
root=Path('/root/autodl-tmp/toolv2x_backbone_research_2026_09_19/V2Xverse_official')
route=root/'dataset/weather-0/data/routes_town05_11_w0_04_30_23_14_33'
result=dict(version='codriving_route_time_audit_v1',route=route.name,
    logged_collection_arguments=json.loads((route/'log/args.json').read_text()),
    configured_simulator_hz=20.,configured_save_skip_frames=4,
    nominal_saved_dt_seconds=.2,future_times_seconds=(np.arange(1,11)*.2).tolist(),
    status='configuration_binding_supported_by_own_motion_not_timestamp_measurement',
    selection=dict(min_mean_speed_mps=2.,max_endpoint_speed_change_mps=.5,consecutive_saved_indices=True),vehicles=[])
for vehicle in [0,1]:
    files=sorted((route/('ego_vehicle_%d/measurements'%vehicle)).glob('*.json'))
    # JSON contains offline labels too; only x/y/speed are selected. No online use.
    rows=[json.loads(p.read_text()) for p in files]
    a=np.array([[r[k] for k in ('x','y','speed')] for r in rows])
    speed=(a[:-1,2]+a[1:,2])/2
    mask=(speed>2)&(np.abs(np.diff(a[:,2]))<.5)&(np.diff([int(p.stem) for p in files])==1)
    ratios=np.linalg.norm(np.diff(a[:,:2],axis=0),axis=1)[mask]/speed[mask]
    result['vehicles'].append(dict(vehicle=vehicle,measurements=len(files),selected_pairs=int(mask.sum()),
        dt_quantiles_05_50_95=np.percentile(ratios,[5,50,95]).tolist()))
Path(__file__).with_name('timebase.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
