"""Execute the one authorized frozen batch and retain per-attempt provenance."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time

work=Path('/root/autodl-tmp/ToolV2X/.worktrees/rq1-score-revision-2026-11-13')
execution=Path(__file__).resolve().parent
out=execution.parent/'run_001'
config=work/'docs/REALLY_MAYBE/rq1_report_freeze_2026_11_13/config.json'
attempt=1
while (execution/('execution.attempt%d.json'%attempt)).exists(): attempt+=1
record_path=execution/('execution.attempt%d.json'%attempt)
log_path=execution/('run.attempt%d.log'%attempt)
command=[sys.executable,'-u','-m','scripts.rq1_report_freeze.run','--stage','all','--config',str(config),'--out',str(out),'--workers','4']
clock=lambda:datetime.now(timezone(timedelta(hours=8))).isoformat()
def save(value):
    temporary=record_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(record_path)
record={'status':'running','attempt':attempt,'started_at':clock(),'command':command,'cwd':str(work),'log':str(log_path),'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=work,text=True).strip()}
environment=os.environ.copy()
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):environment[key]='1'
started=time.monotonic()
with log_path.open('x') as log:
    process=subprocess.Popen(command,cwd=work,env=environment,stdout=log,stderr=subprocess.STDOUT)
    record['pid']=process.pid
    save(record)
    print(json.dumps({'status':'started','attempt':attempt,'pid':process.pid,'log':str(log_path)}),flush=True)
    code=process.wait()
record.update(status='complete' if code==0 else 'technical_failure',exit_code=code,finished_at=clock(),wall_seconds=time.monotonic()-started)
save(record)
print(json.dumps(record,ensure_ascii=False),flush=True)
raise SystemExit(code)
