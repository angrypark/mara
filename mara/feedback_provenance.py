"""Read-only original timestamps for verified reused request/response events."""

def present(session, completed):
    report=completed['body'];limit=completed['seq']
    receipts=[e for e in session.events('execution_prefix_reuse') if e['seq']<limit]
    starts={e['run_id']:e for e in session.events('run_started') if e['seq']<limit}
    cache={}
    def remap(value, mapping, times, path=()):
        if isinstance(value,str):
            if value in mapping:return mapping[value]
            if path and (path[-1] in {'requested_at','queued_at','responded_at','assessed_at'} or path[-1]=='recorded_at' and 'memory_feedback' in path):return times.get(value,value)
            return value
        if isinstance(value,list):return [remap(v,mapping,times,path+(str(i),)) for i,v in enumerate(value)]
        if isinstance(value,dict):return {k:remap(v,mapping,times,path+(k,)) for k,v in value.items()}
        return value
    def origin(eid,kind):
        key=(eid,kind)
        if key in cache:return cache[key]
        try:first=session.get(eid)
        except PermissionError:return {'status':'unverified','current_event_id':eid,'receipt_ids':[]}
        if first['owner']!=session.owner or first['kind']!=kind or first['run_id']!=report['run_id'] or first['seq']>=limit or first['effective']>completed['effective']:
            return {'status':'unverified','current_event_id':eid,'receipt_ids':[]}
        current=first;seen={eid};hops=[];status='new'
        for _ in range(8):
            matches=[r for r in receipts if r['run_id']==current['run_id'] and current['id'] in r['body'].get('id_mapping',{})]
            if not matches:
                if any(r['run_id']==current['run_id'] and current['seq']<r['seq'] for r in receipts):status='unverified'
                break
            if len(matches)!=1:status='unverified';break
            receipt=matches[0];body=receipt['body'];mapping=body['id_mapping']
            try:
                source=session.get(mapping[current['id']]);failed=session.get(body['source_failed_id'])
                start=starts[current['run_id']];source_start=starts[source['run_id']]
                assert all(e['owner']==session.owner for e in (current,source,failed,receipt,start,source_start))
                assert all(e['effective']<=completed['effective'] for e in (source,failed,receipt,start,source_start))
                assert failed['kind']=='failed' and failed['run_id']==source['run_id']==body['source_run_id']
                assert source['seq']<failed['seq']<start['seq']<=current['seq']<receipt['seq']<limit
                assert source_start['body'].get('previous_id')==start['body'].get('previous_id')
                assert source_start['body'].get('mode')==start['body'].get('mode')
                assert source_start['body'].get('history_scope',{}).get('after_seq',0)==start['body'].get('history_scope',{}).get('after_seq',0)
                assert source['kind']==current['kind'] and source['effective']==current['effective'] and source['id'] not in seen
                assert source['body']==remap(current['body'],mapping,body.get('recorded_time_mapping',{}))
            except (PermissionError,KeyError,AssertionError,TypeError):status='unverified';break
            hops.append(receipt['id']);seen.add(source['id']);current=source;status='reused'
        else:status='unverified'
        row={'status':status,'current_event_id':first['id'],'current_recorded':first['recorded'],'receipt_ids':hops}
        if status!='unverified':row.update(origin_event_id=current['id'],origin_recorded=current['recorded'])
        cache[key]=row;return row
    def linked(request,label,field,kind):
        eid=request[field]
        try:
            body=session.get(eid)['body']
            if label=='request':
                assert body['role']==request['requester']
                assert any(q and all(request.get(k)==v for k,v in q.items()) for q in body['output'].get('evidence_requests',[]))
            elif label=='queued':
                assert body['request_id']==request['request_id'] and body['source_output_id']==request['source_output_id']
            elif label=='response':
                assert request['response']['request_id']==request['request_id'] and request['response'] in body['responses']
                if request.get('supplier_output_id'):assert body['supplier_output_id']==request['supplier_output_id']
            else:
                assert all(body[k]==request[k] for k in ('request_id','request_event_id','response_event_id','assessment'))
        except (PermissionError,KeyError,AssertionError,TypeError):return {'status':'unverified','current_event_id':eid,'receipt_ids':[]}
        return origin(eid,kind)
    rows={}
    for request in report.get('evidence_feedback',{}).get('exchanges',[]):
        key=request.get('request_event_id')
        if not key:continue
        rows[key]={label:linked(request,label,field,kind) for label,field,kind in (
            ('request','source_output_id','agent_output'),('queued','request_event_id','evidence_feedback_request'),
            ('response','response_event_id','evidence_feedback_return'),('assessment','assessment_event_id','evidence_feedback_assessment')) if request.get(field)}
    return {'rows':rows,'scope':'Original event times verified through same-owner failed-prefix receipts and exact remapped bodies; stored completed documents are unchanged. Reused requests may have new assessments.'}
