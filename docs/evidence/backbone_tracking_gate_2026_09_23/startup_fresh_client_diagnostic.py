import json,os,signal,subprocess,sys,time
from pathlib import Path
import carla
ROOT=Path('/root/autodl-tmp/ToolV2X')
sys.path.insert(0,str(ROOT/'scripts'))
from probe_backbone_tracking import listener_owned_by_group
out=ROOT/'docs/evidence/backbone_tracking_gate_2026_09_23'
command=['runuser','-u','autodl','--','bash','/root/autodl-tmp/CARLA_0.9.15/CarlaUE4.sh','-RenderOffScreen','-nosound','-quality-level=Low','-carla-rpc-port=2015']
import socket
for port in [2015,2016,2017]:
 with socket.socket() as s:s.bind(('0.0.0.0',port))
with (out/'startup_fresh_client_server.log').open('w') as log, (out/'startup_fresh_client_diagnostic.jsonl').open('x') as result:
 p=subprocess.Popen(command,cwd='/root/autodl-tmp/CARLA_0.9.15',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 start=time.monotonic()
 try:
  while time.monotonic()-start<100:
   row={'elapsed':round(time.monotonic()-start,3),'launcher_pid':p.pid,'exit_code':p.poll(),'command':command,'purpose':'read_only_startup_diagnostic_no_driving'}
   row['owned']=listener_owned_by_group(2015,p.pid)
   if row['owned']:
    client=carla.Client('127.0.0.1',2015);client.set_timeout(2.)
    try:
     row['server_version']=client.get_server_version()
     row['map']=client.get_world().get_map().name
    except RuntimeError as e:row['rpc_error']=str(e)
    del client
   result.write(json.dumps(row)+'\n');result.flush();print(json.dumps(row),flush=True)
   if 'server_version' in row or p.poll() is not None:break
   time.sleep(8.)
 finally:
  try:os.killpg(p.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:p.wait(timeout=5.)
  except subprocess.TimeoutExpired:
   try:os.killpg(p.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   p.wait(timeout=5.)
  print('owned process group cleaned',p.pid,flush=True)
