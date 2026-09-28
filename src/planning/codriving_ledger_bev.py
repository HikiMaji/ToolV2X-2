"""Purchased ledger fields -> CoDriving raster records, without model execution.

Only for trusted in-process ledgers produced by apply_response. Receipt/wire
consistency is checked, not cryptographic authenticity. Calibration binding is
caller-supplied provenance, not inferred from a generic 'ego_at_t' label.
"""
import copy
import numpy as np
from planning.evidence import known_field_manifest, _validate_resolved
from tools.task_spec import field_key
from tools.vehicle import decode_task_response
from probe.kinematic_tools import encode


def records_from_ledger(ledger,binding):
    """Return P/F records in an explicitly bound current ego actor RH frame.

    Legacy F-CV needs two valid purchased history states, retained in refs/cost.
    Native v3 can instead use its paid motion anchor, enabling standalone F.
    Receiver-derived forecasts are deliberately not reclassified as remote F.
    """
    if (ledger['status']!='ready' or ledger['coordinate_frame']!='ego_at_t'
        or binding['scene']!=ledger['scene'] or binding['g']!=ledger['g']
        or binding['coordinate_frame']!='ego_at_t' or binding['axes']!='x_forward_y_left'
        or binding['origin']!='ego_actor' or not np.isfinite(binding['decision_time'])
        or not isinstance(binding['time_binding'],str) or not binding['time_binding'].strip()):
        raise ValueError('explicit matching scene/epoch/ego actor coordinate binding required')
    if ledger.get('task_version')=='toolv2x_task_v3' and any(binding.get(k)!=v for k,v in ledger['frame_binding'].items()):
        raise ValueError('native ledger binding mismatch')
    issued={}
    for receipt in ledger['receipts']:
        req=receipt['request'];wire=receipt['wire_text'].encode('utf-8')
        packet=decode_task_response(wire,req)
        cost=receipt['cost']
        if (packet!=receipt['response'] or packet['receipt_id']!=receipt['receipt_id']
            or (req['scene'],req['g'])!=(ledger['scene'],ledger['g'])
            or req['provider']==ledger['local_source'] or not cost['complete']
            or cost['request_bytes']!=len(encode(req)) or cost['response_bytes']!=len(wire)):
            raise ValueError('receipt/wire/epoch/cost mismatch')
        for record in packet['records']:
            key=field_key(record['ref'])
            if key in issued and issued[key]!=record['value']:raise ValueError('conflicting receipts')
            issued[key]=record['value']
    known_field_manifest(ledger)
    _validate_resolved(ledger['acquired_fields'])
    groups={}
    for record in ledger['acquired_fields']:
        ref=record['ref'];key=field_key(ref)
        if issued.get(key)!=record['value']:raise ValueError('field not in decoded receipt')
        ident=(ref['provider'],ref['track_handle'])
        fields=groups.setdefault(ident,{})
        if ref['field_kind'] in fields:raise ValueError('ambiguous context for target field')
        fields[ref['field_kind']]=record
    ps=[];fs=[]
    for (source,track),fields in sorted(groups.items()):
        anchor=fields['anchor'];box=anchor['value']['box'];history=fields.get('history')
        if any(r['ref']['context_version']!=anchor['ref']['context_version'] for r in fields.values()):
            raise ValueError('mixed target contexts')
        velocity=np.zeros(2);valid=False;past=[];refs=[anchor['ref']]
        if history:
            h=history['value'];indices=np.flatnonzero(h['history_valid'])
            if len(indices)>=2:
                a,b=indices[-2:];dt=h['history_times'][b]-h['history_times'][a]
                velocity=(np.asarray(h['history'][b])[:2]-np.asarray(h['history'][a])[:2])/dt
                valid=True
            refs.append(history['ref'])
            past=[dict(time=t,box=[b[i] for i in (0,1,3,4,6)],valid=v)
                  for t,b,v in zip(h['history_times'],h['history'],h['history_valid'])]
        if ledger.get('task_version')=='toolv2x_task_v3':
            m=anchor['value']['motion'];velocity=np.asarray(m['velocity']);valid=m['valid']
        base=dict(source=source,track=str(track),box=[box[i] for i in (0,1,3,4,6)],
                  velocity=velocity.tolist(),velocity_valid=valid,refs=copy.deepcopy(refs))
        if history:ps.append(dict(copy.deepcopy(base),history=past))
        if 'forecast' in fields:
            if not valid:raise ValueError('F-CV requires paid causal history or valid native motion anchor')
            forecast=fields['forecast'];value=forecast['value']
            fs.append(dict(copy.deepcopy(base),refs=copy.deepcopy(refs+[forecast['ref']]),
                forecast=copy.deepcopy(value['forecast']),forecast_times=copy.deepcopy(value['forecast_times']),
                forecast_scores=copy.deepcopy(value['forecast_scores']),model_used=value['model_used']))
    return ps,fs
