#!/usr/bin/env python3
"""Bounded synchronous local-perception PDM control test; no remote acquisition."""
import argparse,json,math,os,queue,selectors,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from planning.pdm_control import StartupGate,control_target
from probe_v2xverse_detector import load_detector


def rpc(process,request):
    process.stdin.write(json.dumps(request)+'\n');process.stdin.flush()
    with selectors.DefaultSelector() as poll:
        poll.register(process.stdout,selectors.EVENT_READ)
        if not poll.select(30):raise TimeoutError('local worker deadline exceeded')
    line=process.stdout.readline()
    if not line:raise RuntimeError('local worker exited')
    result=json.loads(line)
    if 'error' in result:raise RuntimeError(result['error'])
    return result['result']


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    carla_root=Path(args.carla_root)
    sys.path.insert(0,str(carla_root/'PythonAPI/carla/dist/carla-0.9.10-py3.7-linux-x86_64.egg'))
    sys.path.insert(0,str(carla_root/'PythonAPI/carla'))
    import carla
    from agents.navigation.controller import VehiclePIDController
    spec=dict(version='toolv2x_pdm_closedloop_probe_v1',dt=.05,steps=160,settling_ticks=30,
        min_stable_frames=10,max_start_acceleration=1.,min_track_hits=3,max_warmup_frames=60,
        self_iou=.5,max_tilt_rad=.05,planning_speed_cap_mps=4.,lead_distance_m=15.,
        lateral_pid=dict(K_P=1.95,K_D=.2,K_I=.07,dt=.05),longitudinal_pid=dict(K_P=1.,K_D=0.,K_I=.05,dt=.05),
        max_throttle=.75,max_brake=.3,max_steering=.8,velocity_proxy_min_speed=.2,
        speed_sample_dt=.5,target_forward_margin=.5,
        criteria=dict(min_empty_progress_m=8.,min_lead_progress_m=2.,max_final_lead_speed_mps=.5,
                      min_clearance_m=0.,max_lateral_error_m=.5,collisions=0,invalid_plans=0),
        scope='controlled synchronous Ego-only chain; inference pauses simulation; not realtime or ToolV2X method evaluation')
    (out/'spec.json').write_text(json.dumps(spec,indent=2))
    detector,metadata=load_detector(args);(out/'detector_metadata.json').write_text(json.dumps(metadata,indent=2))
    env=dict(os.environ,TOOLV2X_V2VGOT_ROOT=args.v2vgot_root)
    workers=[];logs=[]
    for mode,python in [('track',args.tracker_python),('pdm',args.pdm_python)]:
        log=(out/(mode+'_worker.log')).open('w');logs.append(log)
        workers.append(subprocess.Popen([python,str(ROOT/'scripts/local_runtime_worker.py'),mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,universal_newlines=True,bufsize=1,env=env))
    tracking,pdm=workers;client=carla.Client('127.0.0.1',args.port);client.set_timeout(60)
    outcomes=[]
    try:
        for case in ['empty','lead']:
            world=client.load_world('Town03');original=world.get_settings();settings=world.get_settings()
            settings.synchronous_mode=True;settings.fixed_delta_seconds=spec['dt'];world.apply_settings(settings)
            actors=[];sensors=[];records=[];events=[];phase='settling';begun=time.perf_counter()
            try:
                m=world.get_map();wp=m.get_waypoint(carla.Location(x=-34.87,y=-139,z=0));route=[];cur=wp.previous(8)[0]
                for _ in range(50):
                    if cur.is_junction:break
                    t=cur.transform;route.append(dict(x=t.location.x,y=t.location.y,yaw=t.rotation.yaw,width=cur.lane_width,road_id=cur.road_id,section_id=cur.section_id,lane_id=cur.lane_id))
                    nxt=cur.next(1.)
                    if len(nxt)!=1:break
                    cur=nxt[0]
                def spawn(waypoint):
                    pose=waypoint.transform;pose.location.z+=.5
                    v=world.spawn_actor(world.get_blueprint_library().find('vehicle.lincoln.mkz2017'),pose)
                    actors.append(v);v.apply_control(carla.VehicleControl(brake=1));return v
                ego=spawn(wp);peer=spawn(wp.next(spec['lead_distance_m'])[0]) if case=='lead' else None
                lidar_bp=world.get_blueprint_library().find('sensor.lidar.ray_cast')
                attrs=dict(range='85',rotation_frequency='20',channels='64',upper_fov='10',lower_fov='-30',points_per_second='500000',atmosphere_attenuation_rate='0.004',dropoff_general_rate='0',dropoff_intensity_limit='0.8',dropoff_zero_intensity='0.4',sensor_tick='0.05')
                for k,v in attrs.items():lidar_bp.set_attribute(k,v)
                lidar=world.spawn_actor(lidar_bp,carla.Transform(carla.Location(x=1.3,z=1.85),carla.Rotation(yaw=-90)),attach_to=ego);actors.append(lidar);sensors.append(lidar);q=queue.Queue();lidar.listen(q.put)
                collision=world.spawn_actor(world.get_blueprint_library().find('sensor.other.collision'),carla.Transform(),attach_to=ego);actors.append(collision);sensors.append(collision)
                collision.listen(lambda e:events.append(dict(frame=e.frame,other_type=e.other_actor.type_id,impulse=float(e.normal_impulse.length()))))
                for _ in range(spec['settling_ticks']):world.tick()
                # Spawn/settling contacts are not driving collisions; raw event history is retained.
                settled_frame=world.get_snapshot().frame
                rpc(tracking,dict(reset=True));gate=StartupGate(spec['min_stable_frames'],spec['max_start_acceleration'],spec['min_track_hits'])
                controller=VehiclePIDController(ego,args_lateral=spec['lateral_pid'],args_longitudinal=spec['longitudinal_pid'],max_throttle=spec['max_throttle'],max_brake=spec['max_brake'],max_steering=spec['max_steering'])
                case_dir=out/case;case_dir.mkdir();(case_dir/'lidar').mkdir();phase='warmup';driving=0;first_position=None;control_start_frame=None
                def xyz(v):return [v.x,v.y,v.z]
                with (case_dir/'frames.jsonl').open('w') as stream:
                    for index in range(spec['max_warmup_frames']+spec['steps']):
                        frame=world.tick();snapshot=world.get_snapshot()
                        while True:
                            scan=q.get(timeout=15)
                            if scan.frame==frame:break
                            if scan.frame>frame:raise RuntimeError('missed LiDAR frame')
                        if abs(scan.timestamp-snapshot.timestamp.elapsed_seconds)>1e-6:raise RuntimeError('timestamp mismatch')
                        start=time.perf_counter();raw=np.frombuffer(scan.raw_data,dtype=np.float32).reshape(-1,4).copy()
                        np.save(str(case_dir/'lidar'/('%04d.npy'%index)),raw)
                        pose=ego.get_transform();physics=ego.get_physics_control();box=ego.bounding_box;velocity=ego.get_velocity();speed=float(np.linalg.norm([velocity.x,velocity.y]))
                        wheel_positions=np.array([xyz(w.position) for w in physics.wheels])/100.;local_wheels=(wheel_positions-np.array(xyz(pose.location)))@np.array(pose.get_matrix())[:3,:3]
                        wheelbase=local_wheels[:2,0].mean()-local_wheels[2:,0].mean()
                        steering=-math.atan(wheelbase*math.radians(ego.get_angular_velocity().z)/speed) if speed>spec['velocity_proxy_min_speed'] else 0.
                        state=dict(vehicle=0,index=index,frame=frame,timestamp=scan.timestamp,world_from_vehicle=pose.get_matrix(),world_from_sensor=scan.transform.get_matrix(),box_extent=xyz(box.extent),box_location=xyz(box.location),wheel_positions=[xyz(w.position) for w in physics.wheels],center_of_mass=xyz(physics.center_of_mass),velocity=xyz(velocity),acceleration=xyz(ego.get_acceleration()),steering_angle_rad=steering,steering_provenance='own yaw-rate bicycle proxy; zero at standstill',route_samples=route,map_identity=dict(name=m.name,revision='CARLA_0.9.10.1',route='road19_lane_minus1_closedloop_probe_v1'))
                        detection=detector(raw,scan.transform.location.z)
                        tracked=rpc(tracking,dict(record=detection,state=state,spec=spec));scene=tracked['scene'];plan=None;target=None;status='warmup_brake'
                        if phase=='warmup':
                            ready=gate.update(scene['acceleration_mps2'],tracked['tracks'])
                            if ready:
                                phase='driving';first_position=np.array(xyz(pose.location));control_start_frame=frame
                            elif index+1>=spec['max_warmup_frames']:raise RuntimeError('startup did not stabilize')
                        control=carla.VehicleControl(brake=1.)
                        if phase=='driving':
                            plan=rpc(pdm,dict(scene=scene))
                            unknown=any(t['hits']<spec['min_track_hits'] for t in tracked['tracks'])
                            if unknown:status='unconfirmed_track_brake'
                            else:
                                rear=np.array(tracked['world_from_rear']);body_center=float((np.array(xyz(pose.location))-rear[:3,3])@rear[:3,0])
                                try:
                                    target=control_target(plan['waypoints'],rear,body_center,spec['speed_sample_dt'],spec['target_forward_margin'])
                                    if target['mode']=='hold_no_forward_target':status=target['mode']
                                    else:
                                        target_wp=SimpleNamespace(transform=carla.Transform(carla.Location(x=target['world_xy'][0],y=target['world_xy'][1],z=pose.location.z)))
                                        control=controller.run_step(target['speed_kmh'],target_wp);status='pdm_pid'
                                except ValueError as exc:status='invalid_plan';target={'error':str(exc)}
                            driving+=1
                        ego.apply_control(control)
                        # Evaluation-only peer pose below. It never enters detection/tracking/planning/control.
                        metrics=dict(speed_mps=speed,lateral_error_m=float(abs((pose.location.x-wp.transform.location.x)*math.sin(math.radians(wp.transform.rotation.yaw))-(pose.location.y-wp.transform.location.y)*math.cos(math.radians(wp.transform.rotation.yaw)))))
                        if first_position is not None:metrics['progress_m']=float(np.linalg.norm(np.array(xyz(pose.location))-first_position))
                        if peer is not None:
                            delta=peer.get_location()-ego.get_location();forward=pose.get_forward_vector()
                            metrics['bumper_clearance_m']=float(delta.x*forward.x+delta.y*forward.y-ego.bounding_box.extent.x-peer.bounding_box.extent.x)
                        row=dict(index=index,frame=frame,timestamp=scan.timestamp,phase=phase,state=state,detection=detection,tracked=tracked,plan=plan,target=target,control_status=status,applied_control=dict(throttle=control.throttle,brake=control.brake,steer=control.steer),evaluation_only=metrics,loop_seconds=time.perf_counter()-start)
                        stream.write(json.dumps(row)+'\n');stream.flush();records.append(row)
                        if driving>=spec['steps']:break
                driven=[r for r in records if r['phase']=='driving'];last=driven[-1]['evaluation_only'];criteria=spec['criteria']
                contacts=[e for e in events if e['frame']>=control_start_frame]
                invalid=sum(r['control_status']=='invalid_plan' for r in driven)
                lateral=max(r['evaluation_only']['lateral_error_m'] for r in driven)
                clearance=min((r['evaluation_only']['bumper_clearance_m'] for r in driven),default=None) if peer else None
                passed=(not contacts and invalid==0 and lateral<=criteria['max_lateral_error_m'] and last['progress_m']>criteria['min_empty_progress_m' if peer is None else 'min_lead_progress_m'])
                if peer:passed=passed and clearance>0 and last['speed_mps']<criteria['max_final_lead_speed_mps']
                result=dict(case=case,acceptance_pass=bool(passed),driving_steps=len(driven),warmup_steps=len(records)-len(driven),final_metrics=last,min_clearance_m=clearance,max_lateral_error_m=lateral,collision_events=contacts,all_collision_events=events,settled_frame=settled_frame,invalid_plans=invalid,wall_seconds=time.perf_counter()-begun,max_driving_abs_acceleration=max(abs(r['tracked']['scene']['acceleration_mps2']) for r in driven),mean_loop_seconds=float(np.mean([r['loop_seconds'] for r in driven])),pdm_calls=sum(r['plan'] is not None for r in records),detections=len(records))
                outcomes.append(result);print(json.dumps(result),flush=True)
            except Exception as exc:
                outcomes.append(dict(case=case,error=str(exc),phase=phase,frames_written=len(records),acceptance_pass=False));raise
            finally:
                (out/'summary.json').write_text(json.dumps(dict(spec=spec,outcomes=outcomes),indent=2))
                for sensor in sensors:sensor.stop()
                for actor in reversed(actors):actor.destroy()
                world.apply_settings(original)
    finally:
        for p in workers:
            p.stdin.close()
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=5)
        for log in logs:log.close()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['output','carla-root','source-root','model-dir','overlap-extension-dir','v2vgot-root','tracker-python','pdm-python']:p.add_argument('--'+name,required=True)
    p.add_argument('--port',type=int,default=2200);run(p.parse_args())
