"""T3: paid remote E, receiver derivations and traceable units for the shared Z.

No driver, labels, filesystem access or policy. All returned ledgers are JSON
serializable snapshots. Runtime model identity is bound by FrozenPredictor.
"""
import copy
from time import perf_counter

import numpy as np

from probe.kinematic_tools import encode
from tools.task_spec import (FrozenPredictor, field_key, validate_provenance,
                            validate_task_request, validate_prediction, _check_window)
from tools.vehicle import decode_task_response, prediction_objects, TIMES


class EvidenceUpdateError(ValueError):
    def __init__(self, message, ledger):
        super().__init__(message)
        self.ledger = ledger


def _ref(window, handle, kind, producer, context):
    return dict(provider=window['source'], scene=window['scene'], g=window['g'],
                track_handle=int(handle), field_kind=kind, producer_version=copy.deepcopy(producer),
                context_version=copy.deepcopy(context))


def _forecast_value(obj, scope):
    return dict(forecast=obj['forecast'], forecast_scores=obj['forecast_scores'],
                forecast_times=TIMES, model_used=obj['model_used'], context_scope=scope)


def new_ledger(local_window, local_prediction, *, predictor, local_provenance,
               p_processing='local_mtr', include_local_history=False, task_version='toolv2x_task_v2', frame_binding=None):
    native=task_version=='toolv2x_task_v3'
    if task_version not in ('toolv2x_task_v2','toolv2x_task_v3'):raise ValueError('unsupported ledger task version')
    if native:
        from tools.native_time import check_binding
        check_binding(frame_binding)
        if p_processing!='observations_only':raise ValueError('native local MTR requires an explicit future adapter')
    elif frame_binding is not None:raise ValueError('legacy ledger has no native frame binding')
    _check_window(local_window,native=native)
    validate_prediction(local_window, local_prediction,native=native)
    validate_provenance(local_provenance)
    if (not isinstance(predictor, FrozenPredictor) or
            predictor.descriptor['model_version'] != local_provenance['prediction'] or
            p_processing not in ('local_mtr', 'observations_only') or
            type(include_local_history) is not bool):
        raise ValueError('explicit frozen predictor/provenance and P processing required')
    w = dict(local_window, states=np.asarray(local_window['states']), scores=np.asarray(local_window['scores']))
    local = []
    if native:
        objects=[dict(track_id=int(t),box=w['states'][i,-1].tolist(),score=float(w['scores'][i,-1]),
            forecast=local_prediction['means'][i].tolist(),forecast_scores=local_prediction['scores'][i].tolist(),
            model_used=bool(local_prediction['model_used'][i])) for i,t in enumerate(w['track_ids'])]
    else:objects=prediction_objects(w,local_prediction)
    for row, obj in enumerate(objects):
        fields = [('anchor', dict(box=obj['box'], score=obj['score']))]
        if include_local_history:
            valid = np.asarray(w['valid'][row])
            fields.append(('history', dict(history=w['states'][row].tolist(),
                history_valid=valid.tolist(), history_scores=w['scores'][row].tolist(),
                history_times=np.asarray(w['time_seconds']).tolist(), proxy_status=
                'causal_tracking_state_motion_proxy' if valid.sum() >= 2 else 'single_state_static_proxy')))
        fields.append(('forecast', _forecast_value(obj, 'ego_full_at_t')))
        if native:fields[-1][1]['forecast_times']=np.asarray(local_prediction['forecast_times']).tolist()
        for kind, value in fields:
            ref = _ref(w, obj['track_id'], kind, local_provenance[
                'prediction' if kind == 'forecast' else 'tracking'], local_provenance['context'])
            local.append(dict(ref=ref, value=value, origin='local'))
    result = dict(version='toolv2x_evidence_ledger_v2' if include_local_history else 'toolv2x_evidence_ledger_v1',
        scene=w['scene'], g=w['g'],
        local_source=w['source'], coordinate_frame='ego_at_t', local_fields=local,
        predictor_binding=predictor.descriptor, p_processing=p_processing,
        acquired_fields=[], derived_fields=[], receipts=[], contexts=[], active_contexts={},
        receiver_events=[], failed_receives=[], status='ready')
    if native:result.update(task_version=task_version,frame_binding=copy.deepcopy(frame_binding))
    return result


def _index(records):
    result = {}
    for record in records:
        key = field_key(record['ref'])
        if key in result:
            raise ValueError('duplicate ledger field identity')
        result[key] = record
    return result


def known_field_manifest(ledger):
    """Only actual remote receipts; never receiver-derived forecast claims."""
    issued = {r['receipt_id']: {field_key(x['ref']): x['value'] for x in r['response']['records']}
              for r in ledger['receipts']}
    entries = []
    for record in sorted(ledger['acquired_fields'], key=lambda r: field_key(r['ref'])):
        if record['origin'] != 'remote':
            raise ValueError('manifest can only acknowledge remote fields')
        receipt = next((r for r in record['receipt_ids']
                        if issued.get(r, {}).get(field_key(record['ref'])) == record['value']), None)
        if receipt is None:
            raise ValueError('acquired field lacks an actual receipt')
        entries.append(dict(receipt_id=receipt, ref=copy.deepcopy(record['ref'])))
    return entries


def _validate_resolved(records):
    """The wire decoder cannot inspect values carried only by an old reference."""
    targets = {}
    for r in records:
        ref = r['ref']
        targets.setdefault((ref['provider'], ref['track_handle']), {})[ref['field_kind']] = r['value']
    for fields in targets.values():
        anchor = fields.get('anchor')
        if anchor is None:
            raise ValueError('remote primary field has no acquired anchor')
        history, forecast = fields.get('history'), fields.get('forecast')
        if history and (history['history'][-1] != anchor['box'] or history['history_scores'][-1] != anchor['score']):
            raise ValueError('referenced anchor and history conflict')
        if history and 'motion' in anchor:
            from tools.native_time import motion
            if anchor['motion']!=motion(np.asarray(history['history']),np.asarray(history['history_valid']),np.asarray(history['history_times'])):
                raise ValueError('referenced motion and paid history conflict')
        if forecast and not forecast['model_used'] and not np.all(
                np.asarray(forecast['forecast']) == np.asarray(anchor['box'][:2])):
            raise ValueError('referenced anchor and fallback conflict')


def _context(ledger, provider):
    fields = [r for r in ledger['acquired_fields'] if r['ref']['provider'] == provider]
    histories = {r['ref']['track_handle']: r for r in fields if r['ref']['field_kind'] == 'history'}
    if not histories:
        return None
    certificates = [r['response']['context_certificate'] for r in ledger['receipts']
                    if r['request']['provider'] == provider and 'context_certificate' in r['response']]
    cert = certificates[0] if certificates else None
    if any(c != cert for c in certificates):
        raise ValueError('complete context certificates conflict at fixed time')
    order = cert['track_order'] if cert else sorted(histories)
    if set(order) != set(histories):
        raise ValueError('certificate and cumulative acquired histories disagree')
    dtypes = cert['array_dtypes'] if cert else dict(track_ids='int64', states='float64',
                                                   scores='float64', valid='bool', time_seconds='float64')
    values = [histories[t]['value'] for t in order]
    times = values[0]['history_times']
    if any(v['history_times'] != times for v in values):
        raise ValueError('acquired histories have inconsistent time axes')
    raw = dict(track_ids=order, states=[v['history'] for v in values],
               scores=[v['history_scores'] for v in values], valid=[v['history_valid'] for v in values], time_seconds=times)
    w = dict(source=provider, scene=ledger['scene'], g=ledger['g'],
             **{k: np.asarray(v, dtype=dtypes[k]) for k, v in raw.items()})
    if any(not np.array_equal(np.asarray(raw[k]), w[k]) for k in raw):
        raise ValueError('context dtype conversion would change purchased values')
    if cert and cert['has_eligible']:
        w['eligible'] = w['valid'].sum(axis=1) >= 2
    _check_window(w,native=ledger.get('task_version')=='toolv2x_task_v3')
    base = histories[order[0]]['ref']['context_version']
    revision = base['revision'] + ('.full.' if cert else '.subset.') + '.'.join(map(str, order))
    version = dict(name='receiver_' + base['name'], revision=revision)
    parent_refs = [r['ref'] for r in fields if r['ref']['field_kind'] in ('anchor', 'history')
                   and r['ref']['track_handle'] in histories]
    return dict(version=version, provider=provider, window={k: v.tolist() if isinstance(v, np.ndarray) else v
        for k, v in w.items()}, array_dtypes=copy.deepcopy(dtypes),
        scope='provider_full_at_t' if cert else 'receiver_acquired_subset',
        provider_context=copy.deepcopy(base), parent_refs=sorted(parent_refs, key=field_key),
        predictor_binding=copy.deepcopy(ledger['predictor_binding']),
        same_predictor_binding=bool(cert and cert['predictor_binding'] == ledger['predictor_binding']))


def _window(context):
    w = copy.deepcopy(context['window'])
    for name, dtype in context['array_dtypes'].items():
        w[name] = np.asarray(w[name], dtype=dtype)
    if 'eligible' in w:
        w['eligible'] = np.asarray(w['eligible'], dtype=bool)
    return w


def apply_response(ledger, response, predictor, p_processing=None):
    """Consume an actual {request, wire, cost}; failed derivation keeps paid E.

    This local API trusts the service transport, not arbitrary fabricated packets.
    Old references are checked against this receiver's actual receipt/value records.
    """
    begin = perf_counter()
    try:
        return _apply_response(ledger, response, predictor, p_processing)
    except EvidenceUpdateError:
        raise
    except Exception as exc:
        failed = copy.deepcopy(ledger)
        wire = response.get('wire')
        failed['failed_receives'].append(dict(request=copy.deepcopy(response.get('request')),
            wire_hex=wire.hex() if isinstance(wire, bytes) else None,
            reported_cost=copy.deepcopy(response.get('cost')), receiver_seconds=perf_counter() - begin,
            error=dict(type=type(exc).__name__, message=str(exc)), complete=False))
        failed['status'] = 'receiver_error'
        raise EvidenceUpdateError(str(exc), failed) from exc


def _apply_response(ledger, response, predictor, p_processing):
    begin = perf_counter()
    if (ledger['status'] != 'ready' or not isinstance(predictor, FrozenPredictor) or
            predictor.descriptor != ledger['predictor_binding'] or
            (p_processing is not None and p_processing != ledger['p_processing'])):
        raise ValueError('receiver processing or frozen predictor changed')
    req = response['request']
    if (req['version']=='toolv2x_task_v3') != (ledger.get('task_version')=='toolv2x_task_v3') or req.get('frame_binding')!=ledger.get('frame_binding'):
        raise ValueError('ledger protocol/frame binding mismatch')
    if ledger.get('task_version')=='toolv2x_task_v3' and ledger.get('request_times',req['times'])!=req['times']:
        raise ValueError('native request time axis frozen across ledger providers')
    packet = decode_task_response(response['wire'], req)
    if (req['scene'], req['g']) != (ledger['scene'], ledger['g']) or req['provider'] == ledger['local_source']:
        raise ValueError('response source/scene/time differs from receiver')
    cost = response['cost']
    if (not cost.get('complete') or cost['request_bytes'] != len(encode(req)) or
            cost['response_bytes'] != len(response['wire'])):
        raise ValueError('response cost must match the actual request and wire bytes')
    for receipt in ledger['receipts']:
        if receipt['receipt_id'] == packet['receipt_id']:
            if receipt['wire_text'].encode('utf-8') != response['wire'] or receipt['cost'] != cost:
                raise ValueError('replayed receipt was changed')
            return copy.deepcopy(ledger)
        if receipt['request']['provider'] == req['provider']:
            if receipt['request']['request_id'] == req['request_id']:
                raise ValueError('different response reused a request ID')
            if receipt['response']['provenance'] != packet['provenance']:
                raise ValueError('provider provenance changed within fixed context')
    known = {r['receipt_id']: r['record_refs'] for r in ledger['receipts']}
    validate_task_request(req, known)
    result = copy.deepcopy(ledger)
    if req['version']=='toolv2x_task_v3':result['request_times']=copy.deepcopy(req['times'])
    index = _index(result['acquired_fields'])
    for record in packet['records']:
        key = field_key(record['ref'])
        if key in index:
            if index[key]['value'] != record['value']:
                raise ValueError('same remote field identity returned different content')
            index[key]['receipt_ids'].append(packet['receipt_id'])
        else:
            stored = dict(copy.deepcopy(record), origin='remote', receipt_ids=[packet['receipt_id']])
            result['acquired_fields'].append(stored)
            index[key] = stored
    for item in packet['references']:
        if field_key(item['ref']) not in index:
            raise ValueError('referenced field has no received value')
    _validate_resolved(result['acquired_fields'])
    result['acquired_fields'].sort(key=lambda r: field_key(r['ref']))
    result['receipts'].append(dict(receipt_id=packet['receipt_id'], request=copy.deepcopy(req),
        response=copy.deepcopy(packet), record_refs=[copy.deepcopy(r['ref']) for r in packet['records']],
        wire_text=response['wire'].decode('utf-8'), cost=copy.deepcopy(cost)))
    event = dict(receipt_id=packet['receipt_id'], receiver_seconds=0., model_seconds=0., model_calls=0,
                 model_targets_computed=0, fallback_targets_computed=0, cache_hit=False, complete=False)
    result['receiver_events'].append(event)
    try:
        context = _context(result, req['provider'])
        if context and result['p_processing'] == 'local_mtr':
            existing = next((c for c in result['contexts'] if c == context), None)
            event['cache_hit'] = existing is not None
            if existing is None:
                w = _window(context)
                event.update(model_calls=1, model_targets_computed=None, fallback_targets_computed=None)
                start = perf_counter()
                supplied = copy.deepcopy(w)
                try:
                    predicted = predictor(supplied)
                finally:
                    event['model_seconds'] = perf_counter() - start
                if set(supplied) != set(w) or any(not np.array_equal(supplied[k], w[k]) for k in w):
                    raise ValueError('receiver predictor modified purchased input context')
                validate_prediction(w, predicted)
                derived = [dict(ref=_ref(w, obj['track_id'], 'forecast', predictor.descriptor['model_version'],
                    context['version']), value=_forecast_value(obj, context['scope']), origin='receiver_derived',
                    parent_refs=copy.deepcopy(context['parent_refs'])) for obj in prediction_objects(w, predicted)]
                result['contexts'].append(context)
                result['derived_fields'].extend(derived)
                event.update(model_targets_computed=int(predicted['model_used'].sum()),
                             fallback_targets_computed=int((~predicted['model_used']).sum()))
            result['active_contexts'][req['provider']] = copy.deepcopy(context['version'])
        event['complete'] = True
    except Exception as exc:
        event.update(error=dict(type=type(exc).__name__, message=str(exc)))
        result['status'] = 'receiver_error'
        raise EvidenceUpdateError(str(exc), result) from exc
    finally:
        event['receiver_seconds'] = perf_counter() - begin
    return result


def remote_units(ledger):
    """Atomic primary bundles with shared-anchor refs and equivalent provenance aliases."""
    if ledger['status'] != 'ready':
        raise ValueError('failed receiver state cannot become a successful driver input')
    known_field_manifest(ledger)
    acquired = _index(ledger['acquired_fields'])
    all_records = list(ledger['acquired_fields'])
    contexts = {(c['provider'], tuple(sorted(c['version'].items()))): c for c in ledger['contexts']}
    for r in ledger['derived_fields']:
        ref = r['ref']
        context = contexts.get((ref['provider'], tuple(sorted(ref['context_version'].items()))))
        if (context is None or ref['track_handle'] not in context['window']['track_ids'] or
                not r['parent_refs'] or
                sorted(map(field_key, r['parent_refs'])) != sorted(map(field_key, context['parent_refs'])) or
                any(field_key(p) not in acquired for p in r['parent_refs']) or
                ref['producer_version'] != ledger['predictor_binding']['model_version'] or
                r['origin'] != 'receiver_derived' or ref['field_kind'] != 'forecast'):
            raise ValueError('derived forecast lacks its exact acquired context parent chain')
        if ledger['active_contexts'].get(ref['provider']) == ref['context_version']:
            all_records.append(r)
    anchors = {(r['ref']['provider'], r['ref']['track_handle']): r
               for r in ledger['acquired_fields'] if r['ref']['field_kind'] == 'anchor'}
    units = []
    for record in all_records:
        ref, value = record['ref'], record['value']
        kind = ref['field_kind']
        if kind == 'anchor':
            continue
        anchor = anchors[(ref['provider'], ref['track_handle'])]
        display_context = ref['context_version']
        can_merge = record['origin'] == 'remote' and any(
            r['receipt_id'] in record['receipt_ids'] and
            r['response'].get('predictor_binding') == ledger['predictor_binding'] for r in ledger['receipts'])
        if record['origin'] == 'receiver_derived':
            context = contexts[(ref['provider'], tuple(sorted(ref['context_version'].items())))]
            can_merge = context['scope'] == 'provider_full_at_t' and context['same_predictor_binding']
            if can_merge:
                display_context = context['provider_context']
        metadata = dict(context_version=copy.deepcopy(display_context), producer_version=copy.deepcopy(ref['producer_version']))
        payload = copy.deepcopy(value)
        if kind == 'forecast':
            metadata['context_scope'] = payload.pop('context_scope')
        obj = dict(source=ref['provider'], track_id=ref['track_handle'], **copy.deepcopy(anchor['value']),
                   **payload, field_metadata={kind: metadata})
        equivalent = next((u for u in units if kind == 'forecast' and can_merge and u['mergeable']
                           and u['object'] == obj), None)
        if equivalent is not None:
            equivalent['primary_refs'].append(copy.deepcopy(ref))
            continue
        units.append(dict(kind=kind, object=obj, primary_refs=[copy.deepcopy(ref)],
                          anchor_ref=copy.deepcopy(anchor['ref']), mergeable=can_merge))
    return sorted(units, key=lambda u: (float(np.hypot(*u['object']['box'][:2])),
        u['object']['source'], u['object']['track_id'], u['kind'],
        tuple(sorted(u['object']['field_metadata'][u['kind']]['context_version'].items())),
        field_key(u['primary_refs'][0])))
