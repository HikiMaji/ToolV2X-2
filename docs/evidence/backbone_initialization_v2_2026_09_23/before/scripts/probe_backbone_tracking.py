#!/usr/bin/env python3
"""Frozen CARLA 0.9.15 tracking gate. Default mode prepares, never drives.

No detector, tracker, planner, predictor or LLM is imported. --execute requires
the 0.9.15 server package. It starts and owns an isolated local server process group.
"""
import argparse
import json
import math
import os
import pwd
import signal
import socket
import subprocess
from contextlib import contextmanager
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
DT = .1
ORIGIN = np.array([50., 0.])  # right-handed world XY
NOMINAL = dict(front=3.848486, rear=1.053197, width=2.128324,
               box_center_y=0., box_yaw=0.)
SPEC = dict(version='toolv2x_backbone_tracking_gate_v1',
            carla_version='0.9.15', python_version='3.10',
            blueprint='vehicle.lincoln.mkz_2017', dt=DT,
            lateral_pid=dict(K_P=1.95, K_I=.05, K_D=.2, dt=DT),
            longitudinal_pid=dict(K_P=1., K_I=.05, K_D=0., dt=DT),
            max_throttle=.75, max_brake=.3, max_steering=.8,
            position_preview=.4, speed_preview=.1,
            settling_ticks=20, preload_ticks=10, preload_throttle=.1,
            origin_xy=ORIGIN.tolist(), seed=0, max_effective_control_ticks=2160,
            reference_contract='RH rear axle; actor point position/derivative targets',
            scope='Given-reference independent tracking only; no planner or P/F')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def validate_versions(server, client, python_version):
    if server != '0.9.15' or client != '0.9.15' or tuple(python_version[:2]) != (3, 10):
        raise ValueError('gate requires CARLA server/client 0.9.15 and Python 3.10')


def fixture_opendrive():
    return '''<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
<header revMajor="1" revMinor="4" name="ToolV2X_tracking_pad_v1" version="1.0" north="60" south="-60" east="600" west="0"/>
<road name="tracking_pad" length="600" id="0" junction="-1">
<link/><type s="0" type="town"><speed max="4" unit="m/s"/></type>
<planView><geometry s="0" x="0" y="0" hdg="0" length="600"><line/></geometry></planView>
<elevationProfile><elevation s="0" a="0" b="0" c="0" d="0"/></elevationProfile><lateralProfile/>
<lanes><laneOffset s="0" a="60" b="0" c="0" d="0"/>
<laneSection s="0"><center><lane id="0" type="none" level="false"><roadMark sOffset="0" type="none" weight="standard" color="standard" width="0"/></lane></center>
<right><lane id="-1" type="driving" level="false"><link/><width sOffset="0" a="120" b="0" c="0" d="0"/><roadMark sOffset="0" type="none" weight="standard" color="standard" width="0"/></lane></right>
</laneSection></lanes><objects/><signals/>
</road></OpenDRIVE>\n'''


def vehicle_geometry(pose_lh, wheel_world_cm, box):
    pose = np.asarray(pose_lh, dtype=float)
    wheels = np.asarray(wheel_world_cm, dtype=float)
    if pose.shape != (4, 4) or wheels.shape != (4, 3) or not np.isfinite(pose).all() or not np.isfinite(wheels).all():
        raise ValueError('invalid pose or wheel geometry')
    if not np.allclose(pose[3], [0, 0, 0, 1]) or not np.allclose(pose[:3, :3].T @ pose[:3, :3], np.eye(3), atol=1e-5):
        raise ValueError('pose is not rigid')
    local = (wheels / 100. - pose[:3, 3]) @ pose[:3, :3]
    rear = local[2:].mean(axis=0)
    front = local[:2].mean(axis=0)
    wheelbase = float(front[0] - rear[0])
    if not 1.5 < wheelbase < 5. or np.max(np.abs(local)) > 6.:
        raise ValueError('wheel units or world/local frame mismatch')
    center = np.asarray(box['location'], dtype=float) - rear
    extent = np.asarray(box['extent'], dtype=float)
    if not np.isfinite(center).all() or not np.isfinite(extent).all() or (extent <= 0).any():
        raise ValueError('invalid bounding box')
    geom = dict(front=float(center[0] + extent[0]), rear=float(extent[0] - center[0]),
                width=float(2*extent[1]), box_center_y=float(-center[1]), box_yaw=-float(box['yaw']))
    return dict(geometry=geom, wheelbase=wheelbase, wheel_local_lh_m=local.tolist(),
                rear_offset_lh=rear.tolist(), rear_to_actor_xy=[float(-rear[0]), float(rear[1])],
                box=box)


def rear_local_xy(pose_lh, geometry):
    pose = np.asarray(pose_lh, dtype=float)
    point = pose[:3, 3] + pose[:3, :3] @ np.asarray(geometry['rear_offset_lh'])
    return np.array([point[0], -point[1]]) - ORIGIN


def control_reference(reference, t, rear_to_actor_xy):
    from planning.tracking_reference import actor_target, state_at
    position = actor_target(state_at(reference, round(t + .4, 8)), rear_to_actor_xy)
    speed = actor_target(state_at(reference, round(t + .1, 8)), rear_to_actor_xy)
    return dict(position_time=round(t+.4, 8), speed_time=round(t+.1, 8),
                actor_local_xy=[position['x'], position['y']],
                speed_mps=speed['speed_mps'], speed_kmh=3.6*speed['speed_mps'])


def archive_sources(out):
    paths = ['scripts/probe_backbone_tracking.py', 'src/planning/tracking_reference.py',
             'src/evaluation/tracking_gate.py', 'docs/backbone_decision_and_tracking_spec_2026_09_22.md',
             'vendor/carla_agents_0_9_15/agents/navigation/controller.py',
             'vendor/carla_agents_0_9_15/agents/tools/misc.py', 'vendor/carla_agents_0_9_15/PROVENANCE.json']
    for name in paths:
        dest = out / 'source' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)


def prepare_references(out, geometry):
    from planning.tracking_reference import CASES, case_spec, corridor, generate_reference, validate_reference
    from shapely.geometry import mapping
    refs, corridors, checks = {}, {}, {}
    folder = out / 'references'; folder.mkdir()
    for name in CASES:
        refs[name] = generate_reference(name)
        corridors[name] = corridor(refs[name], name)
        checks[name] = validate_reference(name, refs[name], geometry)
        write_json(folder / (name+'.json'), dict(case_spec=case_spec(name), rows=refs[name]))
        write_json(folder / (name+'_corridor.json'), mapping(corridors[name]))
    write_json(out / 'reference_checks.json', checks)
    if not all(item['passed'] for item in checks.values()):
        raise ValueError('analytic reference preflight failed; physical trials forbidden')
    return refs, corridors


def xyz(obj):
    return [float(obj.x), float(obj.y), float(obj.z)]


def native_attributes(value):
    """Serialize the public data of CARLA physics/vector records, never actors."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [native_attributes(item) for item in value]
    result={}
    for name in dir(value):
        if name.startswith('_'): continue
        item=getattr(value,name)
        if not callable(item): result[name]=native_attributes(item)
    return result


def scalar_attributes(value):
    return {name:getattr(value,name) for name in dir(value) if not name.startswith('_')
            and isinstance(getattr(value,name), (bool,int,float,str,type(None)))}


def finish_recording(client, path, expected_ticks, ego_id, sensor_id, case_dir):
    from evaluation.tracking_gate import parse_recorder_info
    client.stop_recorder()  # asynchronous; query completeness is the barrier
    text='';coverage=dict(complete=False,collision_count=0,failures=['recorder_query_not_complete'])
    deadline=time.monotonic()+2.
    try:
        while time.monotonic()<deadline:
            remaining=deadline-time.monotonic()
            if remaining<=0: break
            client.set_timeout(min(.5,remaining))
            try:
                text=client.show_recorder_file_info(str(path),True)
                coverage=parse_recorder_info(text,expected_ticks,ego_id,sensor_id)
                if coverage['complete']: break
            except RuntimeError as exc:
                coverage=dict(complete=False,collision_count=0,failures=[str(exc)])
            time.sleep(min(.1,max(0.,deadline-time.monotonic())))
    finally:
        client.set_timeout(60.)
        (case_dir/'recorder_info.txt').write_text(text)
    return coverage


def raw_vehicle(actor):
    transform = actor.get_transform(); physics = actor.get_physics_control(); box = actor.bounding_box
    record = dict(pose_lh=transform.get_matrix(), velocity_lh_mps=xyz(actor.get_velocity()),
                  acceleration_lh_mps2=xyz(actor.get_acceleration()),
                  angular_velocity_lh_degrees=xyz(actor.get_angular_velocity()),
                  wheel_world_cm=[xyz(w.position) for w in physics.wheels],
                  box=dict(location=xyz(box.location), extent=xyz(box.extent), yaw=math.radians(box.rotation.yaw)),
                  gear=int(actor.get_control().gear), center_of_mass_as_reported=xyz(physics.center_of_mass),
                  physics=native_attributes(physics))
    return record


def geometry_gate(g):
    failures = []
    for field in ['front', 'rear', 'width']:
        if abs(g['geometry'][field] - NOMINAL[field]) > .01:
            failures.append('changed_'+field)
    if abs(g['wheelbase']-2.87113) > .01 or abs(g['rear_to_actor_xy'][0]-1.39360) > .01:
        failures.append('changed_axle_geometry')
    if abs(g['geometry']['box_yaw']) > .01 or abs(g['geometry']['box_center_y']) > .01:
        failures.append('changed_box_alignment')
    return failures


def control_dict(control):
    return {key: getattr(control, key) for key in
            ['throttle', 'brake', 'steer', 'hand_brake', 'manual_gear_shift', 'reverse', 'gear']}


def observe(actor, world, geometry, initial_frame, initial_timestamp, i, carla):
    from shapely.geometry import MultiPoint
    snap = world.get_snapshot(); pose = actor.get_transform(); velocity = actor.get_velocity()
    native_angular = actor.get_angular_velocity()
    corners = actor.bounding_box.get_world_vertices(pose)
    polygon = MultiPoint([(p.x-ORIGIN[0], -p.y-ORIGIN[1]) for p in corners]).convex_hull
    return dict(i=i, frame=snap.frame, timestamp=snap.timestamp.elapsed_seconds,
                t=round(i*DT, 8), elapsed_sim_time=snap.timestamp.elapsed_seconds-initial_timestamp,
                expected_frame=initial_frame+i,
                actor_xy=[pose.location.x-ORIGIN[0], -pose.location.y-ORIGIN[1]],
                actor_z=pose.location.z, rear_xy=rear_local_xy(pose.get_matrix(), geometry).tolist(),
                yaw=-math.radians(pose.rotation.yaw), roll=math.radians(pose.rotation.roll), pitch=math.radians(pose.rotation.pitch),
                actor_velocity=[velocity.x, -velocity.y, velocity.z],
                angular_velocity=[-math.radians(native_angular.x), math.radians(native_angular.y), -math.radians(native_angular.z)],
                body_polygon_xy=[list(xy) for xy in polygon.exterior.coords[:-1]],
                wheel_steer_rad=[-math.radians(actor.get_wheel_steer_angle(which)) for which in
                                 [carla.VehicleWheelLocation.FL_Wheel, carla.VehicleWheelLocation.FR_Wheel]],
                gear=int(actor.get_control().gear), last_control=control_dict(actor.get_control()),
                target=None, control=None, collision_events=[])


def immediate_failure(row, ref, corridor_polygon, previous=None):
    from planning.tracking_reference import clearance
    from shapely.geometry import Polygon, box
    values = row['rear_xy'] + row['actor_velocity'] + [row['yaw']]
    if not np.isfinite(values).all():
        return 'nonfinite_state'
    body = Polygon(row['body_polygon_xy'])
    if not box(-50, -60, 550, 60).covers(body):
        return 'left_physical_pad'
    if clearance(body, corridor_polygon) < 0:
        return 'left_virtual_corridor'
    delta = np.asarray(row['rear_xy']) - [ref['x'], ref['y']]
    lat = float(delta @ [-math.sin(ref['yaw']), math.cos(ref['yaw'])])
    if abs(lat) > .75:
        return 'large_lateral_error'
    if np.linalg.norm(row['actor_velocity']) > 4.5:
        return 'overspeed_abort'
    if row['gear'] < 0:
        return 'reverse_gear'
    if previous is not None:
        speed = float((np.asarray(row['rear_xy'])-previous['rear_xy']) @ [math.cos(row['yaw']), math.sin(row['yaw'])] / DT)
        if speed < -.02:
            return 'reverse_motion'
    if row['collision_events']:
        return 'collision'
    return None


def preload_motion(points):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError('invalid preload positions')
    maximum = float(np.linalg.norm(points-points[0], axis=1).max())
    return dict(net=float(np.linalg.norm(points[-1]-points[0])), max_from_start=maximum,
                cumulative=float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum()), passed=maximum<=.02)


def listener_owned_by_group(port, group):
    inodes = set()
    for table in ['/proc/net/tcp', '/proc/net/tcp6']:
        for line in Path(table).read_text().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='0A' and int(fields[1].rsplit(':',1)[1],16)==port:
                inodes.add(fields[9])
    if not inodes: return False
    owned=set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            if os.getpgid(int(process.name))!=group: continue
            for fd in (process/'fd').iterdir():
                try:
                    value=os.readlink(fd)
                    if value.startswith('socket:['): owned.add(value[8:-1])
                except OSError: pass
        except (OSError,ProcessLookupError): pass
    if inodes.issubset(owned): return True
    if os.geteuid()==0:
        # This container restricts cross-UID /proc/fd reads even for root.
        # Repeat the same kernel-inode proof as the server's UID, not a weaker port check.
        code=("import sys; sys.path.insert(0,sys.argv[1]); "
              "from probe_backbone_tracking import listener_owned_by_group; "
              "print(int(listener_owned_by_group(int(sys.argv[2]),int(sys.argv[3]))))")
        try:
            proof=subprocess.run(['runuser','-u','autodl','--',sys.executable,'-c',code,
                    str(ROOT/'scripts'),str(port),str(group)],capture_output=True,text=True,timeout=3.)
            return proof.returncode==0 and proof.stdout.strip()=='1'
        except (OSError,subprocess.TimeoutExpired):
            return False
    return False


@contextmanager
def owned_server(carla_root, port, out):
    """Never attach to an existing listener, and only stop our own process group."""
    root=Path(carla_root).resolve(); entry=root/'CarlaUE4.sh'
    if not entry.is_file(): raise FileNotFoundError('CARLA 0.9.15 server package is absent: '+str(entry))
    if not 1024<=port<=65533: raise ValueError('invalid dedicated server port')
    for number in [port,port+1,port+2]:
        try:
            with socket.socket() as check: check.bind(('0.0.0.0',number))
        except OSError as exc:
            raise RuntimeError('refusing an occupied CARLA port: '+str(number)) from exc
    command=['bash',str(entry),'-RenderOffScreen','-nosound','-quality-level=Low','-carla-rpc-port='+str(port)]
    if os.geteuid()==0:
        user=pwd.getpwnam('autodl')
        writable=[root/'CarlaUE4'/'Saved',root/'CarlaUE4/Content/Carla/Maps/Nav',root/'CarlaUE4/Content/Carla/Maps/OpenDrive']
        for folder in writable:
            folder.mkdir(parents=True,exist_ok=True)
            os.chown(folder,user.pw_uid,user.pw_gid)
        for relative in ['CarlaUE4/Content/Carla/Maps/Nav/OpenDriveMap.obj','CarlaUE4/Content/Carla/Maps/OpenDrive/OpenDriveMap.xodr']:
            existing=root/relative
            if existing.exists(): os.chown(existing,user.pw_uid,user.pw_gid)
        command=['runuser','-u','autodl','--']+command
    log=(Path(out)/'server.log').open('w')
    process=subprocess.Popen(command,cwd=str(root),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        start_ticks=Path('/proc/%d/stat'%process.pid).read_text().rsplit(')',1)[1].split()[19]
        write_json(Path(out)/'server_ownership.json',dict(pid=process.pid,process_group=process.pid,
                   process_start_ticks=start_ticks,port=port,package=str(root),command=command))
        import carla
        deadline=time.monotonic()+60.
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('owned CARLA server exited; see server.log')
            if listener_owned_by_group(port,process.pid):
                # Client connects eagerly; a connection made before listen may stay failed.
                client=carla.Client('127.0.0.1',port);client.set_timeout(1.)
                try:
                    server=client.get_server_version()
                except RuntimeError:
                    time.sleep(.1)
                    continue
                validate_versions(server,client.get_client_version(),sys.version_info)
                client.set_timeout(60.)
                yield client
                return
            time.sleep(.5)
        raise TimeoutError('owned CARLA server did not become ready within 60s')
    finally:
        # Popen created this session; no system-wide process matching or shared-server kill.
        try: os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=5.)
        except subprocess.TimeoutExpired: pass
        # runuser/bash can exit before the server child; always finish our group.
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait(timeout=5.)
        log.close()


def execute(out, port, carla_root):
    import carla
    validate_versions('0.9.15',carla.Client('127.0.0.1',port).get_client_version(),sys.version_info)
    with owned_server(carla_root,port,out) as client:
        return execute_connected(out,client)


def execute_connected(out, client):
    import carla
    from planning.tracking_reference import CASES, case_spec
    from evaluation.tracking_gate import audit_trial
    sys.path.insert(0, str(ROOT / 'vendor/carla_agents_0_9_15'))
    from agents.navigation.controller import VehiclePIDController
    import agents.navigation.controller as controller_module
    if Path(controller_module.__file__).resolve() != (ROOT / 'vendor/carla_agents_0_9_15/agents/navigation/controller.py').resolve():
        raise ValueError('unintended agents controller import')
    # Version validation precedes world generation, vehicle spawn, and controls.
    validate_versions(client.get_server_version(), client.get_client_version(), sys.version_info)
    world = client.generate_opendrive_world(fixture_opendrive(), carla.OpendriveGenerationParameters(
        vertex_distance=1., max_road_length=50., wall_height=0., additional_width=0.,
        smooth_junctions=False, enable_mesh_visibility=True, enable_pedestrian_navigation=False))
    actors = []; sensors = []
    summary = dict(status='PREFLIGHT', physical_trials_started=0, completed_cases=[], outcomes=[],
                   server=client.get_server_version(), client=client.get_client_version(), controller=str(controller_module.__file__))
    write_json(out / 'summary.json', summary)
    recording_active=False
    try:
        settings = world.get_settings(); settings.synchronous_mode=True; settings.fixed_delta_seconds=DT
        settings.substepping=True; settings.max_substep_delta_time=.01; settings.max_substeps=10
        world.apply_settings(settings)
        actual=world.get_settings()
        if not actual.synchronous_mode or not actual.substepping or abs(actual.fixed_delta_seconds-DT)>1e-8 or abs(actual.max_substep_delta_time-.01)>1e-8 or actual.max_substeps!=10:
            raise ValueError('world settings readback does not match frozen physics timing')
        weather=carla.WeatherParameters.ClearNoon; weather.wind_intensity=0.; weather.precipitation=0.; weather.precipitation_deposits=0.
        world.set_weather(weather)
        write_json(out/'world_readback.json',dict(settings=scalar_attributes(world.get_settings()),weather=scalar_attributes(world.get_weather()),python=sys.version,numpy=np.__version__))
        blueprint = world.get_blueprint_library().find(SPEC['blueprint'])
        write_json(out/'blueprint.json',dict(id=blueprint.id,attributes={attribute.id:str(attribute) for attribute in blueprint}))
        recordings=out/'recordings';recordings.mkdir()
        if os.geteuid()==0:
            user=pwd.getpwnam('autodl');os.chown(recordings,user.pw_uid,user.pw_gid)
        # One stationary 2-second geometry read, before all scored trials. No PID.
        calibration = world.spawn_actor(blueprint, carla.Transform(carla.Location(x=50., y=0., z=1.)))
        actors.append(calibration); calibration.apply_control(carla.VehicleControl(brake=1.))
        for _ in range(20): world.tick()
        raw=raw_vehicle(calibration); g=vehicle_geometry(raw['pose_lh'],raw['wheel_world_cm'],raw['box'])
        failures=geometry_gate(g)
        write_json(out/'vehicle_geometry.json', dict(raw=raw, parsed=g, failures=failures))
        calibration.destroy(); actors.remove(calibration)
        if failures: raise ValueError('vehicle geometry preflight failed: '+','.join(failures))
        refs, corridors=prepare_references(out,g['geometry'])
        summary['reference_preflight_passed']=True
        for name in CASES:
            case_dir=out/name; case_dir.mkdir(); events=[]; rows=[]; initialization=[]
            spec=case_spec(name); n=round(spec['duration']/DT); begun=False
            actor = world.spawn_actor(blueprint, carla.Transform(carla.Location(
                x=50.+g['rear_to_actor_xy'][0], y=-g['rear_to_actor_xy'][1], z=1.)))
            actors.append(actor)
            sensor=world.spawn_actor(world.get_blueprint_library().find('sensor.other.collision'), carla.Transform(), attach_to=actor)
            sensors.append(sensor); actors.append(sensor)
            sensor.listen(lambda e, sink=events: sink.append(dict(frame=e.frame, timestamp=e.timestamp, other_type=e.other_actor.type_id,
                                                       impulse=float(e.normal_impulse.length()))))
            try:
                for phase,count,throttle in [('settle',20,0.),('preload',10,.1)]:
                    actor.apply_control(carla.VehicleControl(throttle=throttle,brake=1.,steer=0.,manual_gear_shift=False))
                    for _ in range(count):
                        frame=world.tick(); raw=raw_vehicle(actor)
                        initialization.append(dict(phase=phase,frame=frame,raw=raw))
                write_json(case_dir/'initialization.json', initialization)
                initial=world.get_snapshot(); t0=initial.timestamp.elapsed_seconds; f0=initial.frame
                first=observe(actor,world,g,f0,t0,0,carla)
                pre=initialization[19]['raw']['pose_lh']; post=initialization[-1]['raw']['pose_lh']
                preload=preload_motion([rear_local_xy(item['raw']['pose_lh'],g).tolist() for item in initialization[19:]])
                init_fail=[]
                initial_values=first['rear_xy']+first['actor_velocity']+first['wheel_steer_rad']+[first['yaw'],first['actor_z'],first['roll'],first['pitch']]
                if not np.isfinite(initial_values).all(): init_fail.append('nonfinite_initial_state')
                last_z=[item['raw']['pose_lh'][2][3] for item in initialization[-5:]]
                if max(last_z)-min(last_z)>.01: init_fail.append('vertical_settling_incomplete')
                if first['gear']!=1: init_fail.append('gear_not_one')
                if np.linalg.norm(first['actor_velocity'])>.05: init_fail.append('not_stationary')
                if not preload['passed']: init_fail.append('preload_moved')
                if np.linalg.norm(first['rear_xy'])>.02 or abs(first['yaw'])>.005: init_fail.append('wrong_initial_pose')
                if max(abs(v) for v in first['wheel_steer_rad'])>.01: init_fail.append('nonzero_initial_steering')
                write_json(case_dir/'initialization_check.json',dict(passed=not init_fail,failures=init_fail,preload_motion=preload,state=first))
                if init_fail: raise ValueError('initialization failed: '+','.join(init_fail))
                controller=VehiclePIDController(actor,args_lateral=SPEC['lateral_pid'],args_longitudinal=SPEC['longitudinal_pid'],
                                                offset=0.,max_throttle=.75,max_brake=.3,max_steering=.8)
                write_json(case_dir/'controller_initial_state.json',dict(past_steering=controller.past_steering,errors_long=[],errors_lat=[]))
                recorder_path=(recordings/(name+'.rec')).resolve()
                started=client.start_recorder(str(recorder_path),True);recording_active=True
                if not started or Path(started).resolve()!=recorder_path or not recorder_path.is_file():
                    raise RuntimeError('recorder did not synchronously open the requested file')
                recorder_binding=dict(expected_frames=n,ego_id=actor.id,sensor_id=sensor.id,initial_frame=f0,initial_timestamp=t0,file=str(recorder_path))
                write_json(case_dir/'recorder_binding.json',recorder_binding)
                abort=None
                with (case_dir/'frames.jsonl').open('w') as stream:
                    for i in range(n+1):
                        row=first if i==0 else observe(actor,world,g,f0,t0,i,carla)
                        row['collision_events']=[e for e in list(events) if f0<e['frame']<=row['frame']]
                        if row['frame']!=f0+i or abs(row['elapsed_sim_time']-i*DT)>1e-5:
                            abort='frame_or_timestamp_gap'
                        abort=abort or immediate_failure(row,refs[name][i],corridors[name],rows[-1] if rows else None)
                        if i<n and not abort:
                            target=control_reference(refs[name],i*DT,g['rear_to_actor_xy']); row['target']=target
                            local=target['actor_local_xy']; world_target=np.array(local)+ORIGIN
                            waypoint=SimpleNamespace(transform=carla.Transform(carla.Location(x=float(world_target[0]),y=float(-world_target[1]),z=row['actor_z'])))
                            control=controller.run_step(target['speed_kmh'],waypoint)
                            row['control']=control_dict(control)
                            if not np.isfinite([control.throttle,control.brake,control.steer]).all():
                                abort='nonfinite_control'
                        row['abort_reason']=abort; rows.append(row)
                        stream.write(json.dumps(row,allow_nan=False)+'\n');stream.flush()
                        if abort: actor.apply_control(carla.VehicleControl(brake=1.));break
                        if i<n:
                            actor.apply_control(control)
                            if not begun:
                                begun=True;summary['physical_trials_started']+=1
                                write_json(out/'summary.json',summary)
                            world.tick()
                actual_ticks=rows[-1]['i']
                coverage=finish_recording(client,recorder_path,actual_ticks,actor.id,sensor.id,case_dir)
                recording_active=False
                sensor.stop();sensors.remove(sensor)
                driving_events=[e for e in events if f0<e['frame']<=rows[-1]['frame']]
                recorder={**recorder_binding,**coverage,'actual_ticks':actual_ticks,'expected_frames':n}
                write_json(case_dir/'collision_events.json',dict(all_events=events,driving_events=driving_events,initial_frame=f0,recorder=recorder))
                if driving_events: rows[-1]['collision_events']=driving_events
                audit=audit_trial(spec,refs[name],rows,corridors[name])
                audit['metrics']['recorder']=coverage
                extra=([abort] if abort else [])+(['collision'] if driving_events or coverage['collision_count'] else [])
                if not coverage['complete']: extra.append('recorder_incomplete')
                if extra:
                    audit['passed']=False;audit['status']='FAIL'
                    audit['failures']=list(dict.fromkeys(audit.get('failures',[])+extra))
                write_json(case_dir/'audit.json',audit)
                summary['outcomes'].append(dict(case=name,**audit));summary['completed_cases'].append(name)
                summary['status']='RUNNING' if audit['passed'] else 'FAIL'
                write_json(out/'summary.json',summary)
                print(json.dumps(dict(case=name,status=audit['status'],failures=audit['failures'])),flush=True)
                if not audit['passed']: break
            finally:
                client.set_timeout(1.)
                if sensor in sensors:
                    try: sensor.stop()
                    except RuntimeError as exc: summary.setdefault('cleanup_errors',[]).append(str(exc))
                    sensors.remove(sensor)
                for item in [sensor,actor]:
                    if item in actors:
                        try: item.destroy()
                        except RuntimeError as exc: summary.setdefault('cleanup_errors',[]).append(str(exc))
                        actors.remove(item)
                client.set_timeout(60.)
        if len(summary['completed_cases'])==8 and all(x['passed'] for x in summary['outcomes']): summary['status']='TRACKING_COMPLETE_PENDING_AUDIT'
    except Exception as exc:
        summary['status']='FAIL' if summary['physical_trials_started'] else 'PREFLIGHT_FAIL'
        summary['error']=str(exc)
        write_json(out/'summary.json',summary)
        raise
    finally:
        client.set_timeout(1.)
        if recording_active:
            try: client.stop_recorder()
            except RuntimeError as exc: summary.setdefault('cleanup_errors',[]).append(str(exc))
        for sensor in sensors:
            try: sensor.stop()
            except RuntimeError as exc: summary.setdefault('cleanup_errors',[]).append(str(exc))
        for actor in reversed(actors):
            try: actor.destroy()
            except RuntimeError as exc: summary.setdefault('cleanup_errors',[]).append(str(exc))
        # The enclosing context terminates only our server; no shared world is restored.
        write_json(out/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--execute',action='store_true',help='launch a dedicated 0.9.15 server process group; default is offline preparation')
    parser.add_argument('--port',type=int,default=2015)
    parser.add_argument('--carla-root',help='0.9.15 package directory; required only with --execute')
    args=parser.parse_args()
    if args.execute and not args.carla_root: parser.error('--execute requires --carla-root; existing servers are never reused')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    write_json(out/'spec.json',SPEC);(out/'fixture.xodr').write_text(fixture_opendrive());archive_sources(out)
    try:
        if args.execute:
            result=execute(out,args.port,args.carla_root)
        else:
            prepare_references(out,NOMINAL)
            result=dict(status='PREPARED_NOT_EXECUTED',nominal_geometry=NOMINAL,physical_trials_started=0,
                        limitation='Nominal geometry only. Actual server/vehicle geometry/physics and tracking remain unverified.')
            write_json(out/'summary.json',result)
        print(json.dumps(result),flush=True)
        return 0 if result['status'] in ['PASS','PREPARED_NOT_EXECUTED','TRACKING_COMPLETE_PENDING_AUDIT'] else 1
    except Exception as exc:
        if not (out/'summary.json').exists():
            write_json(out/'summary.json',dict(status='PREPARATION_OR_CONNECTION_FAIL',physical_trials_started=0,error=str(exc)))
        print(str(exc),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
