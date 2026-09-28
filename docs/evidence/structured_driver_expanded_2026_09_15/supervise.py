"""Run the authorized bounded expansion; preserve artifacts and stop on failure."""
from pathlib import Path
import subprocess, sys, json, datetime
BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
def status(state, **kw):
    temp=BASE/'status.tmp'
    temp.write_text(json.dumps(dict(state=state,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw),indent=2)+'\n')
    temp.replace(BASE/'status.json')
checkpoint=ROOT/'outputs/structured_driver_fix_2026_09_15_v1/acceptance/initialized_seed7.pt'
stages=[('collect.py',['collection',str(checkpoint)],'collection'),
        ('prepare.py',[],'preparing_training'),('run_training.py',[],'training'),
        ('verify_training.py',[],'verifying')]
for script,args,state in stages:
    status(state)
    with (BASE/(state+'.log')).open('x') as log:
        child=subprocess.Popen([sys.executable,'-u',str(BASE/script)]+args,stdout=log,stderr=subprocess.STDOUT)
        status(state,pid=child.pid)
        code=child.wait()
    if code:
        status('failed',script=script,exit_code=code)
        sys.exit(code)
status('completed_verified')
