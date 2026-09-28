#!/usr/bin/env python3
"""Local JSON-line IPC only, bridging existing Python 3.7/3.9 environments."""
import contextlib,json,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
mode=sys.argv[1]
with contextlib.redirect_stdout(sys.stderr):
    if mode=='track':
        from tracking.lidar_tracks import FixedRateTracker
        from probe_lidar_tracking import tracking_step,calibration
        tracker=FixedRateTracker(dt=.05)
    elif mode=='pdm':
        from planning.pdm_core import PDMCore
        planner=PDMCore()
    else:raise ValueError('unknown mode')
for line in sys.stdin:
    try:
        request=json.loads(line)
        with contextlib.redirect_stdout(sys.stderr):
            if mode=='track':
                if request.get('reset'):
                    tracker=FixedRateTracker(dt=.05);result={'reset':True}
                else:
                    result=tracking_step(request['record'],request['state'],tracker,request['spec'])
                    result['world_from_rear']=calibration(request['state'],request['spec']['max_tilt_rad'])[0].tolist()
            else:
                result=planner.plan(request['scene']);result.pop('simulated_proposals',None)
        print(json.dumps({'result':result}),flush=True)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr);print(json.dumps({'error':str(exc)}),flush=True)
