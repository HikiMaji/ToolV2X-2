"""Original PDM numerical core on an explicit, already-authorized scene.

No simulator handles, provider reads, detector, predictor, labels or torch.
This is a low-level planner adapter, not yet a method_episode driver binding.
"""
from dataclasses import asdict, dataclass
import copy
import os
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

SOURCE_ROOT = Path(os.environ.get('TOOLV2X_PDM_SOURCE_ROOT',
    str(Path(__file__).resolve().parents[2] / 'vendor/pdm_core')))
sys.path.insert(0, str(SOURCE_ROOT))

from nuplan.common.actor_state.agent import Agent
from nuplan.common.actor_state.ego_state import EgoState
from nuplan.common.actor_state.oriented_box import OrientedBox
from nuplan.common.actor_state.scene_object import SceneObjectMetadata
from nuplan.common.actor_state.state_representation import StateSE2, StateVector2D, TimePoint
from nuplan.common.actor_state.tracked_objects import TrackedObjects
from nuplan.common.actor_state.tracked_objects_types import TrackedObjectType
from nuplan.common.actor_state.vehicle_parameters import VehicleParameters
from nuplan.common.maps.maps_datatypes import SemanticMapLayer
from nuplan.planning.simulation.observation.observation_type import DetectionsTracks
from nuplan.planning.simulation.trajectory.trajectory_sampling import TrajectorySampling
from shapely.geometry import Point, Polygon

from tuplan_garage.planning.simulation.planner.pdm_planner.observation.pdm_observation import PDMObservation
from tuplan_garage.planning.simulation.planner.pdm_planner.observation.pdm_occupancy_map import PDMOccupancyMap
from tuplan_garage.planning.simulation.planner.pdm_planner.proposal.batch_idm_policy import BatchIDMPolicy
from tuplan_garage.planning.simulation.planner.pdm_planner.proposal.pdm_generator import PDMGenerator
from tuplan_garage.planning.simulation.planner.pdm_planner.proposal.pdm_proposal import PDMProposalManager
from tuplan_garage.planning.simulation.planner.pdm_planner.scoring.pdm_scorer import PDMScorer
from tuplan_garage.planning.simulation.planner.pdm_planner.simulation.pdm_simulator import PDMSimulator
from tuplan_garage.planning.simulation.planner.pdm_planner.utils.pdm_emergency_brake import PDMEmergencyBrake
from tuplan_garage.planning.simulation.planner.pdm_planner.utils.pdm_geometry_utils import parallel_discrete_path
from tuplan_garage.planning.simulation.planner.pdm_planner.utils.pdm_path import PDMPath


@dataclass(frozen=True)
class PDMExecutionSpec:
    version: str = 'toolv2x_pdm_core_v1'
    dt: float = .1
    output_steps: int = 30
    proposal_steps: int = 20
    observation_sample_res: int = 2
    map_radius: float = 50.
    speed_limit_fractions: tuple = (.2, .4, .6, .8, 1.)
    lateral_offsets: tuple = (-1., 1.)
    fallback_target_velocity: float = 15.
    min_gap: float = 1.
    headway_time: float = 1.5
    accel_max: float = 1.5
    decel_max: float = 3.

    def __post_init__(self):
        if self.version != 'toolv2x_pdm_core_v1' or self.dt != .1:
            raise ValueError('v1 preserves original 0.1s TTC indexing')
        for n in ('output_steps', 'proposal_steps', 'observation_sample_res'):
            if type(getattr(self,n)) is not int or getattr(self,n) <= 0:
                raise ValueError('positive integer sampling required')
        if self.proposal_steps < 10 or self.output_steps < self.proposal_steps + 10:
            raise ValueError('output must cover proposals plus original TTC lookahead')
        if self.output_steps % self.observation_sample_res:
            raise ValueError('occupancy endpoint must align with prediction coverage')
        values=[self.map_radius,self.fallback_target_velocity,self.min_gap,self.headway_time,
                self.accel_max,self.decel_max,*self.speed_limit_fractions]
        if not self.speed_limit_fractions or not np.isfinite(values).all() or min(values)<=0:
            raise ValueError('positive finite policy parameters required')
        if not np.isfinite(self.lateral_offsets).all():
            raise ValueError('finite lateral offsets required')


def _array(value, shape):
    a=np.asarray(value,dtype=float)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError('invalid finite geometry shape')
    return a


def validate_scene(scene, spec):
    required={'version','coordinate_frame','timestamp_us','speed_mps','acceleration_mps2',
        'steering_angle_rad','vehicle','centerline','drivable_lanes','route_lane_ids',
        'intersections','speed_limit_mps','map_identity','objects','signal_constraints','input_kind'}
    if not isinstance(scene,dict) or set(scene)!=required:
        raise ValueError('scene whitelist mismatch; no World/Actor or label handles allowed')
    if scene['version']!='toolv2x_pdm_scene_v1' or scene['coordinate_frame']!='ego_rear_axle_rh':
        raise ValueError('explicit rear-axle right-handed frame required')
    if scene['input_kind'] not in ('synthetic_contract','causal_sensor_scene'):
        raise ValueError('input kind must distinguish fixtures and lawful sensor data')
    if type(scene['timestamp_us']) is not int or scene['timestamp_us']<0:
        raise ValueError('timestamp required')
    scalars=_array([scene[x] for x in ('speed_mps','acceleration_mps2','steering_angle_rad','speed_limit_mps')],(4,))
    if scalars[0]<0 or scalars[3]<=0 or scene['signal_constraints']:
        raise ValueError('v1 only forward, explicitly signal-free route segments')
    if set(scene['vehicle'])!={'width','front_length','rear_length','wheel_base','cog_position_from_rear_axle','height'}:
        raise ValueError('measured vehicle geometry required')
    dimensions=_array(list(scene['vehicle'].values()),(6,))
    if min(dimensions)<=0:raise ValueError('positive vehicle dimensions required')
    path=np.asarray(scene['centerline'],dtype=float)
    if path.ndim!=2 or path.shape[1]!=3 or len(path)<2 or not np.isfinite(path).all():
        raise ValueError('route centerline required')
    if np.any(np.linalg.norm(np.diff(path[:,:2],axis=0),axis=1)<=0):
        raise ValueError('duplicate route samples')
    identity=scene['map_identity']
    if set(identity)!={'name','revision','route'} or not all(isinstance(v,str) and v for v in identity.values()):
        raise ValueError('readable map and route identities required')
    if not scene['route_lane_ids'] or not set(scene['route_lane_ids'])<=set(scene['drivable_lanes']):
        raise ValueError('route lanes must have actual polygons')
    for points in list(scene['drivable_lanes'].values())+scene['intersections']:
        xy=np.asarray(points,dtype=float)
        if xy.ndim!=2 or xy.shape[1]!=2 or not np.isfinite(xy).all():raise ValueError('invalid map geometry')
        poly=Polygon(xy)
        if not poly.is_valid or poly.area<=0:raise ValueError('invalid map polygon')
    seen=set()
    for obj in scene['objects']:
        if set(obj)!={'token','box','velocity','forecast','parent_refs'}:
            raise ValueError('object whitelist mismatch')
        if not isinstance(obj['token'],str) or not obj['token'] or obj['token'] in seen:
            raise ValueError('unique nonempty entity tokens required')
        seen.add(obj['token'])
        box=_array(obj['box'],(7,));_array(obj['velocity'],(2,))
        if np.any(box[3:6]<=0):raise ValueError('positive box dimensions required')
        if not isinstance(obj['parent_refs'],list):raise ValueError('parent references required')
        f=obj['forecast']
        if f is not None:
            if set(f)!={'times','xy'}:raise ValueError('forecast must declare times and coordinates')
            times=np.asarray(f['times'],dtype=float)
            if times.ndim!=1 or len(times)<2 or not np.isfinite(times).all() or times[0]!=0 or np.any(np.diff(times)<=0):
                raise ValueError('forecast needs an anchor and increasing times')
            xy=_array(f['xy'],(len(times),2))
            if times[-1] < spec.output_steps*spec.dt-1e-8 or not np.allclose(xy[0],box[:2],atol=1e-6,rtol=0):
                raise ValueError('forecast anchor or horizon mismatch; extrapolation forbidden')


def actor_at(obj, seconds):
    """One state query supplies polygon, heading and velocity consistently."""
    box=np.asarray(obj['box'],dtype=float);velocity=np.asarray(obj['velocity'],dtype=float)
    xy=box[:2]+seconds*velocity;heading=box[6]
    if obj['forecast'] is not None:
        f=obj['forecast'];times=np.asarray(f['times']);path=np.asarray(f['xy'])
        if seconds<0 or seconds>times[-1]+1e-8:raise ValueError('forecast extrapolation forbidden')
        xy=np.array([np.interp(seconds,times,path[:,i]) for i in (0,1)])
        segment=min(max(np.searchsorted(times,seconds,side='right')-1,0),len(times)-2)
        velocity=(path[segment+1]-path[segment])/(times[segment+1]-times[segment])
        if seconds>0 and np.linalg.norm(velocity)>1e-6:
            heading=float(np.arctan2(velocity[1],velocity[0]))
        elif seconds>0:
            displacement=np.diff(path[:segment+2],axis=0)
            moving=np.flatnonzero(np.linalg.norm(displacement,axis=1)>1e-6)
            if len(moving):
                last=displacement[moving[-1]]
                heading=float(np.arctan2(last[1],last[0]))
    return Agent(TrackedObjectType.VEHICLE,
        OrientedBox(StateSE2(float(xy[0]),float(xy[1]),float(heading)),
                    length=box[3],width=box[4],height=box[5]),
        StateVector2D(*velocity),SceneObjectMetadata(timestamp_us=int(round(seconds*1e6)),
            token=obj['token'],track_token=obj['token'],track_id=None))


class ForecastObservation(PDMObservation):
    def set_paths(self, objects):
        self._forecast_actors={}
        for obj in objects:
            if obj['forecast'] is None or obj['token'] not in self.unique_objects:continue
            actors=[actor_at(obj,i*self._observation_sample_res*self._sample_interval)
                    for i in range(len(self._occupancy_maps))]
            self._forecast_actors[obj['token']]=actors
        for index,occupancy in enumerate(self._occupancy_maps):
            geometry=[self._forecast_actors[token][index].box.geometry
                if token in self._forecast_actors else occupancy[token] for token in occupancy.tokens]
            self._occupancy_maps[index]=PDMOccupancyMap(occupancy.tokens,np.asarray(geometry,dtype=object))

    def object_at(self, token, time_idx):
        if token in self._forecast_actors:
            return self._forecast_actors[token][self._global_to_local_idcs[time_idx]]
        return self.unique_objects[token]


class _Intersections:
    """Scorer's only direct map query; route geometry is supplied separately."""
    def __init__(self, polygons):
        self.polygons=[Polygon(x) for x in polygons]

    def is_in_layer(self, point, layer):
        if layer!=SemanticMapLayer.INTERSECTION:raise ValueError('unsupported map query')
        return any(p.covers(Point(point.x,point.y)) for p in self.polygons)


class PDMCore:
    def __init__(self, spec=None):
        self.spec=spec or PDMExecutionSpec()

    def plan(self, scene, *, original_cv=False):
        """Execute original numerical stages, rebuilding state at this physical time.

        original_cv is an explicit upstream-CV diagnostic, not a tool policy.
        Causal scene construction / paid ledger authorization belong to the caller.
        """
        begin=perf_counter();spec=self.spec
        validate_scene(scene,spec)
        if original_cv and any(o['forecast'] is not None for o in scene['objects']):
            raise ValueError('original CV diagnostic cannot silently discard F')
        vehicle=VehicleParameters(**scene['vehicle'],vehicle_name='declared_ego',vehicle_type='vehicle')
        ego=EgoState.build_from_rear_axle(StateSE2(0.,0.,0.),
            StateVector2D(scene['speed_mps'],0.),StateVector2D(scene['acceleration_mps2'],0.),
            scene['steering_angle_rad'],TimePoint(scene['timestamp_us']),vehicle)
        sampling=TrajectorySampling(num_poses=spec.output_steps,interval_length=spec.dt)
        proposals_sampling=TrajectorySampling(num_poses=spec.proposal_steps,interval_length=spec.dt)
        cls=PDMObservation if original_cv else ForecastObservation
        observation=cls(sampling,proposals_sampling,spec.map_radius,spec.observation_sample_res)
        route={token:None for token in scene['route_lane_ids']}
        observation.update(ego,DetectionsTracks(TrackedObjects([actor_at(o,0.) for o in scene['objects']])),[],route)
        if not original_cv:observation.set_paths(scene['objects'])
        discrete=[StateSE2(*x) for x in scene['centerline']]
        centerline=PDMPath(discrete)
        paths=[centerline]+[PDMPath(parallel_discrete_path(discrete,float(offset))) for offset in spec.lateral_offsets]
        policies=BatchIDMPolicy(float(spec.fallback_target_velocity),list(spec.speed_limit_fractions),
            float(spec.min_gap),float(spec.headway_time),float(spec.accel_max),float(spec.decel_max))
        manager=PDMProposalManager(paths,policies);manager.update(scene['speed_limit_mps'])
        generator=PDMGenerator(sampling,proposals_sampling)
        proposals=generator.generate_proposals(ego,observation,manager)
        simulated=PDMSimulator(proposals_sampling).simulate_proposals(proposals,ego)
        tokens=list(scene['drivable_lanes'])
        area=PDMOccupancyMap(tokens,np.asarray([Polygon(scene['drivable_lanes'][t]) for t in tokens],dtype=object))
        scorer=PDMScorer(proposals_sampling)
        scores=scorer.score_proposals(simulated,ego,observation,centerline,route,area,_Intersections(scene['intersections']))
        trajectory=PDMEmergencyBrake(sampling).brake_if_emergency(ego,scores,scorer)
        emergency=trajectory is not None
        if trajectory is None:trajectory=generator.generate_trajectory(int(np.argmax(scores)))
        times=np.arange(.5,spec.output_steps*spec.dt+1e-8,.5)
        states=[trajectory.get_state_at_time(TimePoint(scene['timestamp_us']+int(round(t*1e6)))) for t in times]
        waypoints=[[s.rear_axle.x,s.rear_axle.y] for s in states]
        if not np.isfinite(waypoints).all() or not np.isfinite(scores).all():raise ValueError('nonfinite PDM result')
        return dict(version='toolv2x_pdm_result_v1',execution_spec=asdict(spec),
            input_kind=scene['input_kind'],timestamp_us=scene['timestamp_us'],
            map_identity=copy.deepcopy(scene['map_identity']),waypoints=waypoints,times=times.tolist(),
            proposal_scores=scores.tolist(),simulated_proposals=simulated.tolist(),
            selected_index=int(np.argmax(scores)),emergency_brake=emergency,
            forecast_tokens=sorted(observation._forecast_actors) if not original_cv else [],
            input_parent_refs={o['token']:copy.deepcopy(o['parent_refs']) for o in scene['objects']},
            retained_object_tokens=sorted(observation.unique_objects),
            excluded_object_tokens=sorted(o['token'] for o in scene['objects'] if o['token'] not in observation.unique_objects),
            compute_seconds=perf_counter()-begin,score_semantics='internal_candidate_relative_not_reward')


def scene_from_ledger(base_scene, ledger, motion, *, rear_from_evidence, ego_history=None):
    """Reuse receipt verification and entity association; never read a provider.

    Fixed first integration rule: a purchased remote forecast replaces a local
    forecast for the matched entity; otherwise use local forecast/state. This is
    an explicit engineering baseline, not a quality estimator. No mode averaging.
    Coordinate transform must be supplied from verified calibration, not guessed.
    """
    from planning.structured_inputs import build_structured_plan_input, StructuredDriverSpec
    from tools.task_spec import field_key
    if base_scene['objects']:
        raise ValueError('base scene must not bypass ledger with prefilled objects')
    transform=_array(rear_from_evidence,(3,3))
    rotation=transform[:2,:2]
    if (not np.allclose(transform[2],[0.,0.,1.]) or
            not np.allclose(rotation.T@rotation,np.eye(2),atol=1e-8)):
        raise ValueError('explicit rigid/reflected planar calibration required')
    if motion['speed_mps'] != base_scene['speed_mps']:
        raise ValueError('ego motion mismatch')
    spec=StructuredDriverSpec(p_processing=ledger['p_processing'])
    prepared=build_structured_plan_input(motion,ledger,spec,ego_history=ego_history)
    scene=copy.deepcopy(base_scene);consumed={};selected=[]
    for entity in prepared['entities']:
        if entity['role']=='ego' or entity['tensor_index'] is None:continue
        forecasts=sorted(entity['forecast_sets'],key=lambda f:(
            not f['model_used'], f['context_scope']=='receiver_acquired_subset',
            f['source_role']!='remote',f['source'],tuple(field_key(r) for r in f['primary_refs'])))
        forecast=forecasts[0] if forecasts else None
        source=forecast['source'] if forecast else entity['representative_anchor']['source']
        observation=next(o for o in entity['observations'] if o['source']==source)
        value=observation['value'];box=np.asarray(value['states'][-1],dtype=float).copy()
        valid=np.asarray(value['valid'],bool);times=np.asarray(value['times'])
        history=np.asarray(value['states'])
        velocity=np.zeros(2)
        if valid.sum()>=2:
            t=times[valid];xy=history[valid,:2];centered=t-t.mean()
            velocity=(centered[:,None]*(xy-xy.mean(axis=0))).sum(axis=0)/(centered@centered)
        refs=[observation['anchor_ref']]+observation['primary_refs']
        path=None;mode=None
        if forecast is not None:
            mode=int(np.argmax(forecast['forecast_scores']))
            future=np.asarray(forecast['forecast'][mode])
            path=dict(times=[0.]+list(forecast['forecast_times']),
                      xy=np.concatenate([box[None,:2],future],axis=0))
            path['xy']=(path['xy']@rotation.T+transform[:2,2]).tolist()
            refs+=forecast['primary_refs']+forecast['parent_refs']+[forecast['anchor_ref']]
        heading_vector=rotation@np.array([np.cos(box[6]),np.sin(box[6])])
        box[:2]=rotation@box[:2]+transform[:2,2]
        box[6]=np.arctan2(heading_vector[1],heading_vector[0])
        refs_by_key={field_key(ref):copy.deepcopy(ref) for ref in refs}
        consumed.update(refs_by_key)
        scene['objects'].append(dict(token=entity['entity_id'],box=box.tolist(),
            velocity=(rotation@velocity).tolist(),forecast=path,
            parent_refs=[refs_by_key[k] for k in sorted(refs_by_key)]))
        selected.append(dict(entity_id=entity['entity_id'],source=source,mode=mode))
    report=prepared['admission_report']
    return scene,dict(version='toolv2x_pdm_admission_v1',
        source_selection='model_full_context_remote_then_local_canonical_v1',
        acquired_field_refs=copy.deepcopy(report['acquired_field_refs']),
        derived_field_refs=copy.deepcopy(report['derived_field_refs']),
        scene_construction_refs=[consumed[k] for k in sorted(consumed)],
        legacy_preparation_refs=copy.deepcopy(report['admitted_field_refs']),
        selections=selected,association_spec=spec.to_dict(),
        rear_from_evidence=transform.tolist())
