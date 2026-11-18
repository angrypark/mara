"""Bounded, deterministic source overview for planning; never a sufficiency verdict.

Only current-role facts carry content. Cross-role receipts are navigation metadata.
JSON projections contain complete values with original pointers, never JSON slices.
"""
import copy
import hashlib
import json
from .domain import dumps

VERSION='mara.planner-evidence/1.0'
MAX_CHARACTERS=32000


def _pointer(path,key):
    return path+'/'+str(key).replace('~','~0').replace('/','~1')


def _projection(value,budget):
    selected=[];omitted=[];omitted_count=0
    def omit(path,reason,**extra):
        nonlocal omitted_count
        omitted_count+=1
        if len(omitted)<20:omitted.append(dict(path=path,reason=reason,**extra))
    def visit(node,path,depth=0):
        encoded=dumps(node)
        item={'path':path,'value':node}
        if len(encoded)<=700:
            if len(dumps(selected+[item]))<=budget:selected.append(item)
            else:omit(path,'projection_budget')
            return
        if depth>=7:omit(path,'depth_bound');return
        if isinstance(node,dict):
            # Short scalar context (unit, period, source, limits) precedes tables.
            keys=sorted(node,key=lambda k:(isinstance(node[k],(dict,list)),k))
            for key in keys:visit(node[key],_pointer(path,key),depth+1)
        elif isinstance(node,list):
            indexes=sorted(set([0,1,len(node)-2,len(node)-1])) if len(node)>4 else list(range(len(node)))
            if len(node)>4:omit(path,'sampled_array',total_items=len(node),included_indexes=indexes)
            for i in indexes:visit(node[i],_pointer(path,i),depth+1)
        else:omit(path,'long_scalar_not_truncated')
    visit(value,'')
    return {'values':selected,'omitted':omitted,'omitted_paths_count':omitted_count,
        'omitted_list_complete':omitted_count==len(omitted),
        'scope':'Original JSON pointers and complete values only. Array samples are not full history; omitted content remains unread.'}


def _fact(f,budget):
    text=f.get('text','');serialized=dumps(f)
    entry={'fact_id':f['id'],'research_tool':f.get('research_tool'),
        'published_at':f.get('published_at'),'known_at':f.get('known_at'),
        'uncertainty':f.get('uncertainty'),'input_sha256':hashlib.sha256(serialized.encode()).hexdigest(),
        'original_read':{'tool':'evidence_read','arguments':{'fact_id':f['id'],'offset':0,'limit':8000}}}
    # Long metadata must not consume the body budget or appear silently clipped.
    missing_metadata=[]
    for key in ('uncertainty',):
        if len(dumps(entry[key]))>700:entry[key]=None;missing_metadata.append(key)
    if missing_metadata:entry['omitted_metadata']=missing_metadata
    try:value=json.loads(text);format_='json'
    except (ValueError,TypeError):value=text;format_='text'
    entry['body_format']=format_
    full=dict(entry,content_status='complete_input_body',body=value)
    if len(dumps(full))<=budget:return full
    entry['content_status']='partial_input_body' if format_=='json' else 'metadata_only'
    if format_=='json':
        entry['projection']=_projection(value,max(0,budget-len(dumps(entry))-850))
        # Omission descriptions may themselves consume the allowance.
        while len(dumps(entry))>budget and entry['projection']['omitted']:
            entry['projection']['omitted'].pop();entry['projection']['omitted_list_complete']=False
        if not entry['projection']['values']:entry['content_status']='metadata_only'
    else:entry['omitted_body_reason']='Long text is not cut into a misleading partial document. Read the original range.'
    return entry


def _receipt(event,current):
    body=event['body'];call=body.get('call',{});result=body.get('result') or {};args=call.get('arguments',{})
    if not isinstance(result,dict):result={}
    fact_id=body.get('fact_id') or result.get('fact_id') or args.get('fact_id')
    record={'event_id':event['id'],'role':body.get('role'),'question_ids':call.get('question_ids',[]),
        'tool':call.get('tool'),'fact_id':fact_id,'status':body.get('status',result.get('status','returned')),
        'available_in_current_input':fact_id in current,'receipt_only':True}
    if event['kind']=='research_tool_failure':record['status']='failed'
    if result.get('reason'):record['failure_reason']=result['reason'] if len(dumps(result['reason']))<=300 else 'See original event'
    record['original_request']={k:copy.deepcopy(v) for k,v in args.items() if len(dumps(v))<=700}
    record['omitted_arguments']=[k for k in args if k not in record['original_request']]
    raw=result.get('raw_ref') or {}
    record['content_identity']={k:result[k] for k in ('sha256','extraction_version') if k in result}
    if raw.get('sha256'):record['content_identity']['raw_sha256']=raw['sha256']
    record['ranges']=[{k:result[k] for k in ('offset','start','end','next_offset','total_characters') if k in result}]
    if not record['ranges'][0]:record['ranges']=[]
    if isinstance(result.get('hits'),list):
        record['ranges']=[{k:r[k] for k in ('start','end') if k in r} for r in result['hits'][:8] if isinstance(r,dict)]
        record['ranges_omitted']=max(0,len(result['hits'])-8)
    if 'observations' in result and isinstance(result['observations'],list):record['observation_count']=len(result['observations'])
    if call.get('tool')=='evidence_read' and fact_id in current:
        record['matches_current_input']=result.get('sha256')==hashlib.sha256(dumps(current[fact_id]).encode()).hexdigest()
        record['range_unit']='serialized fact JSON characters, not source-document coverage'
    if fact_id in current:record['read_with']={'tool':'evidence_read','arguments':{'fact_id':fact_id,'offset':0,'limit':8000}}
    else:record['read_with']='Use the original typed tool request if needed; this fact is not available to evidence_read in the current input.'
    return record


def overview(session,payload,run_id,role,max_characters=MAX_CHARACTERS):
    if max_characters<4000:raise ValueError('Planner overview budget must be at least 4000 characters')
    facts=sorted(payload.get('market',{}).get('facts',[]),key=lambda f:f['id'])
    current={f['id']:f for f in facts}
    result={'schema_version':VERSION,'max_characters':max_characters,
        'rule':'Use delivered content to choose the next unresolved question. Bodies are current-role input and may already be excerpts/projections. Topic/source are in existing_evidence. Metadata and reading receipts do not establish facts, complete coverage or analytical sufficiency. Original reads remain allowed.',
        'facts':[],'omitted_facts':{'ids':[],'count':0,'complete_list':True,'full_index':'existing_evidence'},
        'cross_role_reads':[],'omitted_receipts':0}
    events=[e for kind in ('research_tool_result','research_tool_failure') for e in session.events(kind)
        if e['run_id']==run_id and e['body'].get('role')!=role]
    fact_budget=int(max_characters*(.70 if events else .85))
    # Fact count must not shrink every content allowance to metadata-only.
    # Metadata already has an index; spend this budget on actual source values.
    candidates=[];metadata_only=0
    questions=dumps(payload.get('decision_scope',{}).get('questions',[]))
    def category(f):
        kind=f.get('research_tool','')
        if kind.startswith(('company_','sec_')) or f.get('company_identity'):return 'company'
        if kind in ('fund_profile','fund_holdings'):return 'fund'
        if kind in ('candles','fund_history','orderbook'):return 'prices'
        try:body=json.loads(f.get('text',''))
        except (ValueError,TypeError):body=None
        if isinstance(body,dict) and body.get('observation_period') and isinstance(body.get('observations'),list) and len(body['observations'])>1:return 'prices'
        return 'market'
    def content_priority(f):
        kind=f.get('research_tool','')
        # Price quotes are already in market_prices; discovery catalogs are
        # navigation, not the financial/filing observations sought by planners.
        if kind in ('sec_filings','company_company','company_compare','orderbook'):return 2
        try:body=json.loads(f.get('text',''))
        except (ValueError,TypeError):body=None
        if isinstance(body,dict) and body.get('observation_period') and isinstance(body.get('observations'),list) and len(body['observations'])>1:return -1
        if isinstance(body,dict) and (('instrument' in body and 'quote' in body) or 'midRate' in body):return 2
        return 0
    for f in facts:
        entry=_fact(f,min(4500,fact_budget))
        if entry['content_status']=='metadata_only':metadata_only+=1;continue
        candidates.append((f,entry))
    candidates.sort(key=lambda row:(row[0]['id'] not in questions,
        content_priority(row[0]),row[1]['content_status']!='complete_input_body',len(dumps(row[1])),row[0]['id']))
    shares={'market':.60,'company':.15,'fund':.10,'prices':.15} if role in ('evidence','marks') else {'company':.50,'market':.25,'fund':.15,'prices':.10}
    if role=='bogle':shares={'fund':.45,'market':.25,'company':.20,'prices':.10}
    selected=set()
    for group,share in shares.items():
        used=0
        for f,entry in candidates:
            size=len(dumps(entry))+1
            if category(f)==group and used+size<=fact_budget*share:
                result['facts'].append(entry);selected.add(f['id']);used+=size
    # Unused topic quota is reusable; bounded complete bodies still come first.
    for f,entry in candidates:
        if f['id'] not in selected and len(dumps(result['facts']+[entry]))<=fact_budget:
            result['facts'].append(entry);selected.add(f['id'])
    result['facts'].sort(key=lambda entry:entry['fact_id'])
    for f in facts:
        if f['id'] in selected:continue
        omitted=result['omitted_facts'];omitted['count']+=1
        if len(dumps(omitted['ids']+[f['id']]))<=max_characters*.06:omitted['ids'].append(f['id'])
        else:omitted['complete_list']=False
    result['selection']={'policy':'complete bodies first within role topic quotas, then unused budget',
        'topic_shares':shares,'metadata_only_excluded':metadata_only,
        'metadata_index':'existing_evidence','omitted_are_unread':True}
    # Prefer recent completed reads, preserve deterministic event ordering.
    events.sort(key=lambda e:(e.get('seq',0),e['id']),reverse=True)
    records={}
    for event in events:
        record=_receipt(event,current)
        identity=dumps({k:v for k,v in record.items() if k!='event_id'})
        if identity in records:records[identity]['matching_receipts']+=1
        else:records[identity]=dict(record,matching_receipts=1)
    for record in records.values():
        if len(dumps(dict(result,cross_role_reads=result['cross_role_reads']+[record])))<=max_characters:
            result['cross_role_reads'].append(record)
        else:result['omitted_receipts']+=record['matching_receipts']
    # Large identifier lists and metadata still respect the hard serialized bound.
    while len(dumps(result))>max_characters and result['cross_role_reads']:
        removed=result['cross_role_reads'].pop();result['omitted_receipts']+=removed['matching_receipts']
    while len(dumps(result))>max_characters and result['facts']:
        removed=result['facts'].pop();omitted=result['omitted_facts'];omitted['count']+=1
        if len(dumps(omitted['ids']+[removed['fact_id']]))<=max_characters*.06:
            omitted['ids'].append(removed['fact_id'])
        else:omitted['complete_list']=False
    assert len(dumps(result))<=max_characters
    return result
