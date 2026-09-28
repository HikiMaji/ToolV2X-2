"""P/F services use source-local causal track states and an injected predictor.

history_valid marks available tracker output, including prediction-maintained
states on missed detections; it is not a per-frame detection-match mask.
"""
import copy
import json
from time import perf_counter
from uuid import uuid4
import numpy as np
from probe.kinematic_tools import encode, history_packet
from planning.inputs import validate_evidence

VERSION = 'toolv2x_pf_v1'
TIMES = [.5, 1., 1.5, 2., 2.5, 3.]
FUTURE_INDICES = [4, 9, 14, 19, 24, 29]
COMMON = {'track_id', 'box', 'score'}
P_FIELDS = COMMON | {'history', 'history_valid', 'history_scores', 'history_times'}
F_FIELDS = COMMON | {'forecast', 'forecast_scores', 'model_used'}
PACKET_FIELDS = {'version', 'tool', 'provider', 'scene', 'g', 'coordinate_frame', 'roi',
                 'status', 'coverage', 'objects', 'forecast_times'}


def check_roi(roi):
    if roi is None:
        return
    a = np.asarray(roi, dtype=float)
    if a.shape != (4,) or not np.isfinite(a).all() or not (a[0] < a[2] and a[1] < a[3]):
        raise ValueError('ROI must be finite [xmin, ymin, xmax, ymax]')


def in_roi(box, roi):
    return roi is None or (roi[0] <= box[0] <= roi[2] and roi[1] <= box[1] <= roi[3])


def prediction_objects(window, prediction):
    history_packet(window)
    count = len(window['track_ids'])
    if (not np.array_equal(window['track_ids'], prediction['track_ids']) or
            np.shape(prediction['means']) != (count, 6, 50, 2) or
            np.shape(prediction['scores']) != (count, 6) or
            np.shape(prediction['model_used']) != (count,) or
            not np.allclose(prediction['states'], window['states'][:, -1])):
        raise ValueError('predictor target/time alignment mismatch')
    return [dict(track_id=int(track_id), box=window['states'][i, -1].tolist(),
        score=float(window['scores'][i, -1]),
        forecast=prediction['means'][i][:, FUTURE_INDICES, :].tolist(),
        forecast_scores=prediction['scores'][i].tolist(), model_used=bool(prediction['model_used'][i]))
        for i, track_id in enumerate(window['track_ids'])]


class VehicleTools:
    def __init__(self, window_loader, predictor, scene, g, provider='no_fusion_cav1', *, task_provenance=None, task_frame_binding=None):
        self._task_frame_binding=copy.deepcopy(task_frame_binding)
        if task_frame_binding is not None:
            from tools.native_time import check_binding
            check_binding(task_frame_binding)
        self._load = window_loader
        self._predict = predictor
        self.scene, self.g, self.provider = scene, int(g), provider
        self._window = None
        self._forecast = None
        # v2 has its own episode state; v1 calls do not prewarm or issue v2 receipts.
        self._task_provenance = copy.deepcopy(task_provenance)
        self._task_window = None
        self._task_forecast = None
        self._task_receipts = {}
        self._task_records = []
        self._task_spec = None
        self._task_bytes = 0
        self._bundle_policies = {}
        self._bundle_records = []

    @property
    def bundle_records(self):
        """Detached outer wire/cost archives, including failed bundle attempts."""
        return copy.deepcopy(self._bundle_records)

    def register_bundle_policy(self, policy_id, policy):
        """Register a trusted local frozen control callable, never request code.

        As with the ego policy API, Python callables are trusted dependencies,
        not sandboxed programs. Only detached sent data is supplied to them.
        """
        from tools.task_spec import _version
        _version(policy_id)
        if self._bundle_records or policy_id in self._bundle_policies or not callable(policy):
            raise ValueError('bundle policies must be registered once before execution')
        if hasattr(policy, 'validate_provider'):
            policy.validate_provider(copy.deepcopy(getattr(self._predict, 'descriptor', None)),
                copy.deepcopy(self._task_provenance))
        self._bundle_policies[policy_id] = policy

    def query_bundle(self, envelope):
        """Controls-only one external round trip with at most two paid primitives."""
        from tools.control_bundle import execute_bundle
        return execute_bundle(self, envelope)

    @property
    def task_records(self):
        """Detached run records, including full ExecutionSpec and failed attempts."""
        return copy.deepcopy(self._task_records)

    def fork_task(self):
        """Offline branch continuation from this actual prefix; no sibling cache reuse.

        Keep the same frozen model/loader, but detach receipts, computed context
        and counters. This does not issue a receipt or preview an unbought field.
        """
        if self._bundle_records or len(self._task_records)>1 or any(
                r.get('status')!='completed' for r in self._task_records):
            raise ValueError('branch service requires a successful zero/one-call task prefix')
        result=VehicleTools(self._load,self._predict,self.scene,self.g,self.provider,
                            task_provenance=self._task_provenance,task_frame_binding=self._task_frame_binding)
        for name in ('_task_window','_task_forecast','_task_receipts','_task_records','_task_spec','_task_bytes'):
            setattr(result,name,copy.deepcopy(getattr(self,name)))
        return result

    def query_task(self, request):
        """Execute one task at fixed t; only issued remote-field receipts deduplicate.

        One instance owns one v2 episode (at most two attempts). The manifest
        acknowledges receipt fields; omitted acknowledgements permit retransmission.
        No receiver-derived equivalence, driver execution or future labels here.
        Requests use JSON-native types; predictor fields use CMP's NumPy arrays.
        """
        if self._bundle_records:
            raise ValueError('a bundle service cannot start an additional external task')
        return self._execute_task(request)

    def _execute_task(self, request, *, response_cap=None, internal=False):
        """Shared deterministic P/F executor; internal calls still consume attempts."""
        from tools.task_spec import (ExecutionSpec, validate_task_request, validate_provenance,
                                     field_key, rank_targets, _check_window, FrozenPredictor)
        begin = perf_counter()
        request = copy.deepcopy(request)
        validate_task_request(request, self._task_receipts)
        native=request['version']=='toolv2x_task_v3'
        if native and request['frame_binding']!=self._task_frame_binding:
            raise ValueError('native request must match provider-owned frame/time binding')
        if self._task_records:
            first=self._task_records[0]['request']
            if (native or first['version']=='toolv2x_task_v3') and (request['version']!=first['version'] or request.get('frame_binding')!=first.get('frame_binding') or request['times']!=first['times']):
                raise ValueError('protocol and frame binding frozen within episode')
        validate_provenance(self._task_provenance)
        if isinstance(self._predict, FrozenPredictor) and (
                self._predict.descriptor['model_version'] != self._task_provenance['prediction']):
            raise ValueError('predictor binding and provider model version differ')
        spec = ExecutionSpec.from_dict(request['execution_spec'])
        cap = spec.max_response_bytes if response_cap is None else min(response_cap, spec.max_response_bytes)
        if (request['provider'], request['scene'], request['g']) != (self.provider, self.scene, self.g):
            raise ValueError('request and provider source/scene/time differ')
        if self._task_spec is not None and self._task_spec != request['execution_spec']:
            raise ValueError('ExecutionSpec is frozen within a v2 episode')
        if len(self._task_records) >= 2:
            raise ValueError('v2 remote-call budget exhausted')
        if any(r['request']['request_id'] == request['request_id'] for r in self._task_records):
            raise ValueError('duplicate request ID in v2 episode')
        request_bytes = len(encode(request))
        if not internal and self._task_bytes + request_bytes + spec.max_response_bytes > spec.max_episode_bytes:
            raise ValueError('remaining episode budget cannot reserve response cap')
        packet = dict(version='toolv2x_task_response_v3' if native else 'toolv2x_task_response_v2', request=request, receipt_id=uuid4().hex,
            provenance=copy.deepcopy(self._task_provenance), records=[], references=[], ranking=[],
            status='no_observed_targets', coverage='not_established', truncated=False)
        if request['tool'] == 'F' and isinstance(self._predict, FrozenPredictor):
            packet['predictor_binding'] = self._predict.descriptor
        # This is the longest empty-status header, requiring no private window.
        if len(encode(packet)) > cap:
            raise ValueError('response cap cannot hold the complete header')
        cost = dict(request_bytes=request_bytes, response_bytes=0, service_seconds=0.,
            model_seconds=0., model_targets_computed=0, fallback_targets_computed=0,
            returned_targets=0, within_decision_forecast_cache_hit=False, complete=False)
        record = dict(request=request, status='started', cost=cost)
        self._task_records.append(record)
        self._task_spec = copy.deepcopy(request['execution_spec'])
        if not internal:
            self._task_bytes += request_bytes
        stage = 'window_loading'
        try:
            if self._task_window is None:
                w = copy.deepcopy(self._load())
                _check_window(w,native=native)
                if (w['source'], w['scene'], w['g']) != (self.provider, self.scene, self.g):
                    raise ValueError('provider window source/scene/time mismatch')
                for key in ('states', 'valid', 'scores', 'track_ids', 'time_seconds'):
                    w[key] = np.asarray(w[key])
                self._task_window = w
            w = self._task_window
            tool = request['tool']
            stage = 'prediction' if tool == 'F' else 'retrieval'
            forecast = None
            if tool == 'F':
                cost['within_decision_forecast_cache_hit'] = self._task_forecast is not None
                forecast = self._task_forecast
                if forecast is None:
                    prediction_window = copy.deepcopy(w)
                    cost.update(model_targets_computed=None, fallback_targets_computed=None)
                    model_begin = perf_counter()
                    try:
                        # Full context is retained even when only one target will fit.
                        forecast = self._predict(prediction_window)
                    finally:
                        cost['model_seconds'] = perf_counter() - model_begin
                    if (set(prediction_window) != set(w) or
                            any(not np.array_equal(prediction_window[key], w[key]) for key in w)):
                        raise ValueError('predictor modified the fixed causal context')
            ranked = rank_targets(w, request, forecast)
            if tool == 'F' and self._task_forecast is None:
                self._task_forecast = copy.deepcopy(forecast)
                cost['model_targets_computed'] = int(np.asarray(forecast['model_used']).sum())
                cost['fallback_targets_computed'] = len(w['track_ids']) - cost['model_targets_computed']
            stage = 'response_packing'
            acknowledged = {field_key(entry['ref']): entry for entry in request['acquired_field_manifest']}
            positions = {int(handle): i for i, handle in enumerate(w['track_ids'])}
            if tool=='F' and native:
                from tools.native_time import forecast_at
                paths=forecast_at(w,forecast,request['times'])
                forecasts={int(t):dict(forecast=paths[i].tolist(),forecast_scores=forecast['scores'][i].tolist(),model_used=bool(forecast['model_used'][i])) for i,t in enumerate(w['track_ids'])}
            else:
                forecasts = {o['track_id']: o for o in prediction_objects(w, forecast)} if tool == 'F' else {}
            candidates = []
            for rank in ranked:
                handle = rank['track_handle']
                i = positions[handle]
                values = dict(anchor=dict(box=w['states'][i, -1].tolist(), score=float(w['scores'][i, -1])))
                if native:
                    from tools.native_time import motion
                    values['anchor']['motion']=motion(w['states'][i],w['valid'][i],w['time_seconds'])
                if tool == 'P':
                    values['history'] = dict(history=w['states'][i].tolist(), history_valid=w['valid'][i].tolist(),
                        history_scores=w['scores'][i].tolist(), history_times=w['time_seconds'].tolist(),
                        proxy_status=rank['proxy_status'])
                else:
                    predicted = forecasts[handle]
                    values['forecast'] = dict(forecast=predicted['forecast'], forecast_scores=predicted['forecast_scores'],
                        forecast_times=request['times'] if native else TIMES, model_used=predicted['model_used'], context_scope='provider_full_at_t')
                records, references = [], []
                for kind, value in values.items():
                    ref = dict(provider=self.provider, scene=self.scene, g=self.g, track_handle=handle,
                        field_kind=kind, producer_version=copy.deepcopy(self._task_provenance[
                            'prediction' if kind == 'forecast' else 'tracking']),
                        context_version=copy.deepcopy(self._task_provenance['context']))
                    known = acknowledged.get(field_key(ref))
                    if known is not None:
                        references.append(copy.deepcopy(known))
                    else:
                        records.append(dict(ref=ref, value=value))
                if not records:
                    continue
                candidates.append((records, references, rank))
            # Compute the truncation flag for each actual tentative selection. JSON
            # false/true differ in size; cap checks must use the final flag's bytes.
            packet['truncated'] = bool(candidates)
            def with_certificate(candidate):
                if tool != 'P' or candidate['truncated']:
                    return candidate
                if request['mode'] == 'roi' and len(ranked) != len(w['track_ids']):
                    return candidate
                # A complete P covers every history through returned records or
                # authenticated acknowledgements. This order reveals no unbought IDs.
                certificate = dict(version='toolv2x_full_context_v1',
                    track_order=[int(t) for t in w['track_ids']],
                    array_dtypes={k: np.asarray(w[k]).dtype.name
                                  for k in ('track_ids', 'states', 'scores', 'valid', 'time_seconds')},
                    has_eligible='eligible' in w,
                    predictor_binding=self._predict.descriptor if isinstance(self._predict, FrozenPredictor) else None)
                trial = dict(candidate, context_certificate=certificate)
                return trial if len(encode(trial)) <= cap else candidate
            for records, references, rank in candidates:
                if len(packet['ranking']) >= spec.max_targets:
                    continue
                trial = dict(packet, records=packet['records'] + records,
                    references=packet['references'] + references, ranking=packet['ranking'] + [rank], status='ok',
                    truncated=len(packet['ranking']) + 1 < len(candidates))
                trial = with_certificate(trial)
                # Atomic target: shared anchor plus the complete history/forecast bundle.
                if len(encode(trial)) <= cap:
                    packet = trial
            if not packet['records']:
                packet['status'] = ('no_observed_targets' if not ranked else
                                    'no_new_fields' if not candidates else 'budget_empty')
                packet = with_certificate(packet)
            wire = encode(packet)
            decode_task_response(wire, request)
            # Only fields in the final returned packet acquire a receipt. Not candidates,
            # clipped records, receiver predictions or references to older receipts.
            self._task_receipts[packet['receipt_id']] = copy.deepcopy([r['ref'] for r in packet['records']])
            if not internal:
                self._task_bytes += len(wire)
            cost.update(response_bytes=len(wire), returned_targets=len(packet['ranking']), complete=True)
            record.update(status='completed', response=copy.deepcopy(packet))
        except Exception as exc:
            record.update(status='error', error=dict(stage=stage, error_type=type(exc).__name__, message=str(exc)))
            raise
        finally:
            cost['service_seconds'] = perf_counter() - begin
        return dict(request=copy.deepcopy(request), wire=wire, cost=copy.deepcopy(cost))

    def query(self, tool, roi=None):
        if tool not in ('P', 'F'):
            raise ValueError('unknown tool')
        check_roi(roi)
        roi = None if roi is None else np.asarray(roi, dtype=float).tolist()
        request = dict(version=VERSION, tool=tool, provider=self.provider, scene=self.scene, g=self.g, roi=roi)
        begin = perf_counter()
        if self._window is None:
            window = self._load()
            history_packet(window)
            if window.get('scene') != self.scene or window['source'] != self.provider or window['g'] != self.g:
                raise ValueError('provider window scene/source/time mismatch')
            self._window = window
        w = self._window
        model_seconds = 0.
        model_targets, fallback_targets = 0, 0
        cache_hit = self._forecast is not None
        if tool == 'P':
            objects = [dict(track_id=int(track_id), box=w['states'][i, -1].tolist(),
                score=float(w['scores'][i, -1]), history=w['states'][i].tolist(),
                history_valid=w['valid'][i].tolist(), history_scores=w['scores'][i].tolist(),
                history_times=w['time_seconds'].tolist()) for i, track_id in enumerate(w['track_ids'])]
        else:
            if self._forecast is None:
                start = perf_counter()
                # Full-frame prediction preserves every target's original neighbour context.
                # ponytail: predicts all current targets once; query-target batching can remove
                # unused output computation without changing context in a later measured update.
                self._forecast = self._predict(w)
                model_seconds = perf_counter() - start
            objects = prediction_objects(w, self._forecast)
            if not cache_hit:
                model_targets = sum(obj['model_used'] for obj in objects)
                fallback_targets = len(objects) - model_targets
        objects = [obj for obj in objects if in_roi(obj['box'], roi)]
        packet = dict(request, coordinate_frame='ego_at_t', objects=objects,
            status='ok' if objects else 'no_observed_targets', coverage='not_established',
            forecast_times=TIMES if tool == 'F' else [])
        wire = encode(packet)
        decode_response(wire, self.scene, self.g)
        return dict(request=request, wire=wire, cost=dict(request_bytes=len(encode(request)),
            response_bytes=len(wire), service_seconds=perf_counter() - begin,
            model_seconds=model_seconds, model_targets_computed=model_targets,
            fallback_targets_computed=fallback_targets, returned_targets=len(objects),
            within_decision_forecast_cache_hit=cache_hit if tool == 'F' else False))


def decode_response(wire, scene, g):
    p = json.loads(wire)
    if (set(p) != PACKET_FIELDS or p['version'] != VERSION or p['tool'] not in ('P', 'F') or
            p['scene'] != scene or p['g'] != g or isinstance(p['g'], bool) or
            not isinstance(p['g'], int) or p['coordinate_frame'] != 'ego_at_t' or
            not isinstance(p['provider'], str) or not p['provider'] or
            p['coverage'] != 'not_established' or not isinstance(p['objects'], list)):
        raise ValueError('invalid source/time/packet contract')
    check_roi(p['roi'])
    if p['status'] != ('ok' if p['objects'] else 'no_observed_targets'):
        raise ValueError('inconsistent response status')
    if p['forecast_times'] != (TIMES if p['tool'] == 'F' else []):
        raise ValueError('invalid forecast time axis')
    ids = []
    for obj in p['objects']:
        if set(obj) != (P_FIELDS if p['tool'] == 'P' else F_FIELDS):
            raise ValueError('unexpected response object fields')
        box = np.asarray(obj['box'], dtype=float)
        if (box.shape != (7,) or (box[3:6] <= 0).any() or not 0 <= obj['score'] <= 1 or
                not in_roi(box, p['roi']) or isinstance(obj['track_id'], bool) or not isinstance(obj['track_id'], int)):
            raise ValueError('invalid target anchor or identity')
        ids.append(obj['track_id'])
        if p['tool'] == 'P':
            history = np.asarray(obj['history'])
            valid = np.asarray(obj['history_valid'])
            scores = np.asarray(obj['history_scores'])
            times = np.asarray(obj['history_times'])
            if (history.shape != (11, 7) or valid.shape != (11,) or valid.dtype != bool or
                    not valid[-1] or scores.shape != (11,) or (scores < 0).any() or (scores > 1).any() or
                    times.shape != (11,) or not np.allclose(times, np.arange(-10, 1) / 10.) or
                    not np.allclose(history[-1], box) or not np.isclose(scores[-1], obj['score'])):
                raise ValueError('invalid causal track-state history')
        else:
            scores = np.asarray(obj['forecast_scores'])
            if (np.shape(obj['forecast']) != (6, 6, 2) or scores.shape != (6,) or
                    (scores < 0).any() or scores.sum() > 1.0001 or not isinstance(obj['model_used'], bool)):
                raise ValueError('invalid multimodal forecast')
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate source-local targets')
    encode(p)
    return p


def history_window(packet):
    p = decode_response(encode(packet), packet['scene'], packet['g'])
    if p['tool'] != 'P':
        raise ValueError('track-state history requires P')
    objects, n = p['objects'], len(p['objects'])
    w = dict(source=p['provider'], scene=p['scene'], g=p['g'], track_ids=np.array([o['track_id'] for o in objects], dtype=np.int64),
        states=np.array([o['history'] for o in objects], dtype=np.float32).reshape(n, 11, 7),
        valid=np.array([o['history_valid'] for o in objects], dtype=bool).reshape(n, 11),
        scores=np.array([o['history_scores'] for o in objects], dtype=np.float32).reshape(n, 11),
        time_seconds=np.arange(-10, 1) / 10.)
    history_packet(w)
    return w


def make_evidence(local_window, local_prediction, packets, predictor, predict_p=True):
    if not isinstance(predict_p, bool):
        raise ValueError('P processing must explicitly enable or disable local prediction')
    objects = []
    for obj in prediction_objects(local_window, local_prediction):
        objects.append(dict(obj, source='ego', forecast_times=TIMES))
    queries, peer_anchors = [], {}
    for p in packets:
        p = decode_response(encode(p), local_window['scene'], local_window['g'])
        if p['provider'] == local_window['source']:
            raise ValueError('remote response must come from a different source')
        if p['tool'] == 'P' and predict_p:
            w = history_window(p)
            predicted = prediction_objects(w, predictor(w))
            observed = {o['track_id']: o for o in p['objects']}
            for obj in predicted:
                original = observed[obj['track_id']]
                obj.update(history=original['history'], history_valid=original['history_valid'],
                           history_times=original['history_times'])
        elif p['tool'] == 'P':
            predicted = [{k: v for k, v in obj.items() if k != 'history_scores'} for obj in p['objects']]
        else:
            predicted = p['objects']
        for obj in predicted:
            key = (p['provider'], obj['track_id'])
            if key in peer_anchors and not np.allclose(peer_anchors[key], obj['box']):
                raise ValueError('P/F anchor conflict at identical source/time')
            peer_anchors[key] = obj['box']
            source = p['provider'] + ((':P_local' if predict_p else ':P') if p['tool'] == 'P' else ':F')
            objects.append(dict(obj, source=source, **({'forecast_times': TIMES} if 'forecast' in obj else {})))
        queries.append(dict(tool=p['tool'], roi=p['roi'], response_bytes=len(encode(p)), status=p['status']))
    relations = []
    for ego in objects:
        if ego['source'] != 'ego':
            continue
        for (provider, peer_id), peer_box in peer_anchors.items():
            distance = float(np.linalg.norm(np.asarray(ego['box'][:2]) - np.asarray(peer_box[:2])))
            ratios = np.asarray(peer_box[3:6]) / np.asarray(ego['box'][3:6])
            if distance <= 3. and (ratios >= .5).all() and (ratios <= 2.).all():
                relations.append(dict(ego_id=ego['track_id'], peer_id=peer_id, distance_m=distance,
                    status='current_geometry_candidate_not_confirmed_identity'))
    result = dict(as_of_g=int(local_window['g']), coordinate_frame='ego_at_t', objects=objects,
                  relations=relations, queries=queries)
    validate_evidence(result)
    return result


def decode_task_response(wire, request):
    """Strict v2 wire decoder; v1 decode_response remains unchanged.

    Checks references against the acknowledged request. Authenticating those
    acknowledgements is the provider's job before query_task reads private data.
    """
    from tools.task_spec import (_request_spec, _keys, _array, _text, _integer,
                                 field_key, validate_provenance)
    spec = _request_spec(request)
    native=request['version']=='toolv2x_task_v3'
    if not isinstance(wire, bytes) or len(wire) > spec.max_response_bytes:
        raise ValueError('response must be UTF-8 bytes within configured cap')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result

    packet = json.loads(wire.decode('utf-8'), object_pairs_hook=unique_object)
    expected = {'version', 'request', 'receipt_id', 'provenance', 'records', 'references',
                'ranking', 'status', 'coverage', 'truncated'}
    _keys(packet, expected | (set(packet) & {'context_certificate', 'predictor_binding'}), 'task response')
    _request_spec(packet['request'])
    if (packet['version'] != ('toolv2x_task_response_v3' if native else 'toolv2x_task_response_v2') or packet['request'] != request or
            packet['coverage'] != 'not_established' or type(packet['truncated']) is not bool):
        raise ValueError('response request/coverage contract mismatch')
    _text(packet['receipt_id'])
    validate_provenance(packet['provenance'])
    for name in ('records', 'references', 'ranking'):
        if not isinstance(packet[name], list):
            raise ValueError('response lists required')
    acknowledged = {}
    for entry in request['acquired_field_manifest']:
        _keys(entry, ('receipt_id', 'ref'), 'manifest entry')
        _text(entry['receipt_id'])
        key = field_key(entry['ref'])
        if key in acknowledged or key[:3] != (request['provider'], request['scene'], request['g']):
            raise ValueError('invalid acknowledged field identity')
        acknowledged[key] = entry
    all_fields, new_targets = {}, set()
    target_fields = {}
    for name in ('records', 'references'):
        for item in packet[name]:
            _keys(item, ('ref', 'value') if name == 'records' else ('ref', 'receipt_id'), 'response field')
            ref = item['ref']
            key = field_key(ref)
            kind, handle = ref['field_kind'], ref['track_handle']
            expected_producer = packet['provenance']['prediction' if kind == 'forecast' else 'tracking']
            if (key in all_fields or key[:3] != (request['provider'], request['scene'], request['g']) or
                    ref['producer_version'] != expected_producer or
                    ref['context_version'] != packet['provenance']['context'] or
                    kind not in ('anchor', 'history' if request['tool'] == 'P' else 'forecast')):
                raise ValueError('invalid returned field identity/context')
            if name == 'references':
                if acknowledged.get(key) != item:
                    raise ValueError('response references an unacknowledged receipt')
            else:
                if key in acknowledged:
                    raise ValueError('response retransmitted an acknowledged field')
                _validate_task_value(kind, item['value'],native=native)
                if native and kind=='forecast' and item['value']['forecast_times']!=request['times']:raise ValueError('forecast/request time mismatch')
                if request['mode'] == 'roi' and kind == 'anchor' and not in_roi(item['value']['box'], request['roi']):
                    raise ValueError('returned anchor is outside the controls ROI')
                new_targets.add(handle)
            all_fields[key] = item
            target_fields.setdefault(handle, {})[kind] = item
    expected_kinds = {'anchor', 'history' if request['tool'] == 'P' else 'forecast'}
    if any(set(value) != expected_kinds for value in target_fields.values()):
        raise ValueError('incomplete target fields/references')
    if set(target_fields) != new_targets or len(new_targets) > spec.max_targets:
        raise ValueError('target cap or reference-only target mismatch')
    order = []
    for rank in packet['ranking']:
        _keys(rank, ('track_handle', 'score', 'proxy_status'), 'ranking')
        handle = _integer(rank['track_handle'])
        score = rank['score']
        tags = ('causal_tracking_state_motion_proxy', 'single_state_static_proxy') if request['tool'] == 'P' else (
            'mtr', 'stationary_short_history')
        if type(score) not in (int, float) or not np.isfinite(score) or not 0 <= score <= 1 or rank['proxy_status'] not in tags:
            raise ValueError('invalid task ranking metadata')
        payload = target_fields.get(handle, {}).get('history' if request['tool'] == 'P' else 'forecast', {})
        if 'value' in payload:
            value = payload['value']
            expected_tag = (value['proxy_status'] if request['tool'] == 'P' else
                            'mtr' if value['model_used'] else 'stationary_short_history')
            if rank['proxy_status'] != expected_tag:
                raise ValueError('ranking and returned proxy/fallback metadata disagree')
        order.append((-score, handle))
    if (order != sorted(order) or len(order) != len(new_targets) or
            {handle for _, handle in order} != new_targets):
        raise ValueError('invalid deterministic returned ranking')
    if packet['records']:
        if packet['status'] != 'ok':
            raise ValueError('nonempty response must be ok')
    elif (packet['status'] not in ('no_observed_targets', 'no_new_fields', 'budget_empty') or
          packet['truncated'] != (packet['status'] == 'budget_empty')):
        raise ValueError('invalid empty response boundary')
    for values in target_fields.values():
        if 'value' in values['anchor'] and 'history' in values and 'value' in values['history']:
            anchor, history = values['anchor']['value'], values['history']['value']
            if native:
                from tools.native_time import motion
                expected_motion=motion(np.asarray(history['history']),np.asarray(history['history_valid']),np.asarray(history['history_times']))
                if anchor['motion']!=expected_motion:raise ValueError('motion anchor and paid history disagree')
            if history['history'][-1] != anchor['box'] or history['history_scores'][-1] != anchor['score']:
                raise ValueError('history and current anchor disagree')
        if 'value' in values['anchor'] and 'forecast' in values and 'value' in values['forecast']:
            forecast = values['forecast']['value']
            if not forecast['model_used'] and not np.all(
                    np.asarray(forecast['forecast']) == np.asarray(values['anchor']['value']['box'][:2])):
                raise ValueError('static fallback does not equal current anchor')
    encode(packet)  # Reject non-finite JSON anywhere, including unused metadata.
    if 'context_certificate' in packet:
        _validate_context_certificate(packet)
    if 'predictor_binding' in packet:
        if packet['request']['tool'] != 'F':
            raise ValueError('forecast binding belongs to F')
        _validate_predictor_binding(packet['predictor_binding'], packet['provenance'])
    return packet


def _validate_context_certificate(packet):
    from tools.task_spec import _keys, _integer, _version_pair, _text, _check_json_native
    c = packet['context_certificate']
    _keys(c, ('version', 'track_order', 'array_dtypes', 'has_eligible', 'predictor_binding'), 'context certificate')
    if (c['version'] != 'toolv2x_full_context_v1' or packet['request']['tool'] != 'P' or
            packet['truncated'] or type(c['track_order']) is not list or type(c['has_eligible']) is not bool):
        raise ValueError('invalid complete P context certificate')
    ids = [_integer(t) for t in c['track_order']]
    available = [r['ref'] for r in packet['records']] + [r['ref'] for r in packet['request']['acquired_field_manifest']]
    histories = {r['track_handle'] for r in available if r['field_kind'] == 'history'
                 and r['context_version'] == packet['provenance']['context']
                 and r['producer_version'] == packet['provenance']['tracking']}
    if len(set(ids)) != len(ids) or set(ids) != histories:
        raise ValueError('context certificate must cover exactly the acquired histories')
    _keys(c['array_dtypes'], ('track_ids', 'states', 'scores', 'valid', 'time_seconds'), 'context dtypes')
    for key, value in c['array_dtypes'].items():
        if type(value) is not str:
            raise ValueError('invalid context dtype')
        dtype = np.dtype(value)
        allowed = 'iu' if key == 'track_ids' else 'b' if key == 'valid' else 'fi'
        if dtype.kind not in allowed or dtype.name != value:
            raise ValueError('unsupported context dtype')
    if c['predictor_binding'] is not None:
        _validate_predictor_binding(c['predictor_binding'], packet['provenance'])


def _validate_predictor_binding(binding, provenance):
    from tools.task_spec import _keys, _text, _version_pair, _check_json_native
    _keys(binding, ('binding_id', 'model_version', 'settings'), 'predictor binding')
    _text(binding['binding_id'])
    _version_pair(binding['model_version'])
    _check_json_native(binding['settings'])
    if binding['model_version'] != provenance['prediction'] or not isinstance(binding['settings'], dict):
        raise ValueError('context predictor identity mismatch')


def _validate_task_value(kind, value, native=False):
    from tools.task_spec import _keys, _array
    if native:
        from tools.native_time import time_axis
    if kind == 'anchor':
        _keys(value, ('box', 'score', 'motion') if native else ('box', 'score'), 'anchor bundle')
        box = _array(value['box'], (7,))
        if ((box[3:6] <= 0).any() or type(value['score']) not in (int, float) or
                not np.isfinite(value['score']) or not 0 <= value['score'] <= 1):
            raise ValueError('invalid current anchor')
        if native:
            m=value['motion']
            _keys(m,('velocity','valid','support_times','source'),'motion anchor')
            velocity=_array(m['velocity'],(2,))
            if type(m['valid']) is not bool or m['source']!='causal_tracking_state_motion_proxy':raise ValueError('invalid motion source/validity')
            if m['valid']:
                t=_array(m['support_times'],(2,))
                if not t[0]<t[1] or t[1]!=0:raise ValueError('current causal velocity support required')
            elif m['support_times']!=[] or np.any(velocity!=0):raise ValueError('unknown velocity must be marked zero with no support')
    elif kind == 'history':
        _keys(value, ('history', 'history_valid', 'history_scores', 'history_times', 'proxy_status'), 'history bundle')
        h=len(value['history_times']) if native else 11
        history = _array(value['history'], (h, 7))
        scores = _array(value['history_scores'], (h,))
        times = _array(value['history_times'], (h,))
        if native:time_axis(times,history=True)
        valid = np.asarray(value['history_valid'])
        if (valid.shape != (h,) or valid.dtype != np.dtype(bool) or not valid[-1] or
                (history[valid, 3:6] <= 0).any() or (scores < 0).any() or (scores > 1).any() or
                times[-1] != 0 or (times > 0).any() or (not native and not np.allclose(times, np.arange(-10, 1) / 10.))):
            raise ValueError('invalid causal tracking-state history')
        expected = 'causal_tracking_state_motion_proxy' if valid.sum() >= 2 else 'single_state_static_proxy'
        if value['proxy_status'] != expected:
            raise ValueError('history proxy boundary mismatch')
    else:
        _keys(value, ('forecast', 'forecast_scores', 'forecast_times', 'model_used', 'context_scope'), 'forecast bundle')
        m=len(value['forecast']) if native else 6
        k=len(value['forecast_times']) if native else 6
        if native:
            time_axis(value['forecast_times'])
            if m<1:raise ValueError('empty forecast modes')
        paths = _array(value['forecast'], (m, k, 2))
        scores = _array(value['forecast_scores'], (m,))
        if ((not native and not np.array_equal(_array(value['forecast_times'], (6,)), TIMES)) or
                (scores < 0).any() or scores.sum() > 1.0001 or type(value['model_used']) is not bool or
                value['context_scope'] != 'provider_full_at_t'):
            raise ValueError('invalid full-context forecast metadata')
        if not value['model_used'] and not np.all(paths == paths[0, 0]):
            raise ValueError('fallback must be static across all times and modes')
