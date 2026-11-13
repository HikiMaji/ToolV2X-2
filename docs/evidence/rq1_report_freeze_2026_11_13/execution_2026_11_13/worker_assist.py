from pathlib import Path
import json,sys,time
from scripts.rq1_report_freeze.prepare import worker
out=Path(sys.argv[1]);ids=sys.argv[2:]
started=time.monotonic()
for job_id in ids:
    result=worker(out,job_id)
    print(json.dumps({'job_id':job_id,'status':result['status'],'elapsed_seconds':time.monotonic()-started}),flush=True)
