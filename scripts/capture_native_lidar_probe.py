#!/usr/bin/env python3
"""Controlled native-sensor capture; no autopilot, detector or planner control.

Per-vehicle own state/calibration files are separate from the capture manifest.
Do not use peer state files as online ego inputs.
"""
import argparse,json,queue
from pathlib import Path
import numpy as np
import carla


def capture(output,port=2200,count=30):
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    client=carla.Client('127.0.0.1',port);client.set_timeout(60)
    world=client.load_world('Town03');original=world.get_settings()
    settings=world.get_settings();settings.synchronous_mode=True;settings.fixed_delta_seconds=.05
    world.apply_settings(settings);actors=[];sensors=[]
    def xyz(v):return [v.x,v.y,v.z]
    try:
        m=world.get_map();wp=m.get_waypoint(carla.Location(x=-34.87,y=-139.,z=0))
        route=[];cur=wp.previous(8)[0]
        for _ in range(50):
            if cur.is_junction:break
            t=cur.transform;route.append(dict(x=t.location.x,y=t.location.y,yaw=t.rotation.yaw,
                width=cur.lane_width,road_id=cur.road_id,section_id=cur.section_id,lane_id=cur.lane_id))
            nxt=cur.next(1.)
            if len(nxt)!=1:break
            cur=nxt[0]
        vehicles=[];queues=[]
        attrs=dict(range='85',rotation_frequency='20',channels='64',upper_fov='10',lower_fov='-30',
            points_per_second='500000',atmosphere_attenuation_rate='0.004',dropoff_general_rate='0',
            dropoff_intensity_limit='0.8',dropoff_zero_intensity='0.4',sensor_tick='0.05')
        for i,waypoint in enumerate([wp,wp.next(15)[0]]):
            t=waypoint.transform;t.location.z+=.5
            vehicle=world.spawn_actor(world.get_blueprint_library().find('vehicle.lincoln.mkz2017'),t)
            actors.append(vehicle);vehicles.append(vehicle);vehicle.apply_control(carla.VehicleControl(brake=1.))
            bp=world.get_blueprint_library().find('sensor.lidar.ray_cast')
            for k,v in attrs.items():bp.set_attribute(k,v)
            sensor=world.spawn_actor(bp,carla.Transform(carla.Location(x=1.3,z=1.85),carla.Rotation(yaw=-90)),attach_to=vehicle)
            actors.append(sensor);sensors.append(sensor);q=queue.Queue();sensor.listen(q.put);queues.append(q)
            for name in ['lidar','measurements','own_state']:(out/('ego_vehicle_%d'%i)/name).mkdir(parents=True)
        for _ in range(30):world.tick()
        vehicles[0].apply_control(carla.VehicleControl())
        direction=vehicles[0].get_transform().get_forward_vector()
        vehicles[0].set_target_velocity(carla.Vector3D(x=direction.x*4,y=direction.y*4))
        captures=[]
        for step in range(count):
            frame=world.tick();snap=world.get_snapshot();capture_row=dict(index=step,frame=frame,timestamp=snap.timestamp.elapsed_seconds)
            for i,(v,q) in enumerate(zip(vehicles,queues)):
                while True:
                    scan=q.get(timeout=15)
                    if scan.frame==frame:break
                    if scan.frame>frame:raise ValueError('sensor frame skipped')
                if abs(scan.timestamp-snap.timestamp.elapsed_seconds)>1e-6:raise ValueError('sensor timestamp mismatch')
                base=out/('ego_vehicle_%d'%i)
                np.save(str(base/'lidar'/('%04d.npy'%step)),np.frombuffer(scan.raw_data,dtype=np.float32).reshape(-1,4).copy())
                pose=v.get_transform();physics=v.get_physics_control();box=v.bounding_box
                measurement=dict(lidar_pose_z=scan.transform.location.z)
                (base/'measurements'/('%04d.json'%step)).write_text(json.dumps(measurement))
                state=dict(vehicle=i,frame=frame,index=step,timestamp=scan.timestamp,blueprint=v.type_id,
                    world_from_vehicle=pose.get_matrix(),world_from_sensor=scan.transform.get_matrix(),
                    box_extent=xyz(box.extent),box_location=xyz(box.location),
                    wheel_positions=[xyz(w.position) for w in physics.wheels],center_of_mass=xyz(physics.center_of_mass),
                    velocity=xyz(v.get_velocity()),acceleration=xyz(v.get_acceleration()),
                    steering_angle_rad=0.,steering_provenance='controlled zero-steer initialization and command',
                    route_samples=route,map_identity=dict(name=m.name,revision='CARLA_0.9.10.1',route='road19_lane_minus1_coasting_probe_v1'))
                (base/'own_state'/('%04d.json'%step)).write_text(json.dumps(state,indent=2))
            captures.append(capture_row)
        (out/'capture_manifest.json').write_text(json.dumps(dict(scope='controlled coasting capture, not planner-controlled driving',
            simulation_dt=.05,frames=captures,sensor_attributes=attrs,sensor_mount=dict(x=1.3,z=1.85,yaw=-90),
            route_samples=route,initial_ego_speed_mps=4.,initial_peer_distance_m=15.,peer_braked=True,
            server_version=client.get_server_version()),indent=2))
        print('captured',count,'frames per vehicle')
    finally:
        for sensor in sensors:sensor.stop()
        for a in reversed(actors):a.destroy()
        world.apply_settings(original)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--port',type=int,default=2200);p.add_argument('--frames',type=int,default=30)
    a=p.parse_args();capture(a.output,a.port,a.frames)
