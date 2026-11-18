"""Versioned, tenant-scoped fact snapshots and explicit judgment citations.

Events remain authoritative. The catalog is an append-only relational index, not
an assertion that an observation supports a claim or that an agent read it all.
"""
import copy
import hashlib
import json
from .domain import dumps,day,number

VERSION='mara.fact-snapshot/1.0'
GRAPH='mara.fact-graph/1.0'

DDL='''
CREATE TABLE IF NOT EXISTS fact_catalog_versions(version TEXT PRIMARY KEY);
INSERT OR IGNORE INTO fact_catalog_versions VALUES ('mara.fact-catalog/1.0');
CREATE TABLE IF NOT EXISTS fact_snapshots(
 owner TEXT NOT NULL, snapshot_id TEXT NOT NULL, fact_id TEXT NOT NULL,
 schema_version TEXT NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY(owner,snapshot_id));
CREATE INDEX IF NOT EXISTS fact_logical_lookup ON fact_snapshots(owner,fact_id);
CREATE TABLE IF NOT EXISTS report_facts(
 owner TEXT NOT NULL, completed_id TEXT NOT NULL REFERENCES events(id), fact_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL, PRIMARY KEY(owner,completed_id,fact_id),
 FOREIGN KEY(owner,snapshot_id) REFERENCES fact_snapshots(owner,snapshot_id));
CREATE TABLE IF NOT EXISTS report_claims(
 owner TEXT NOT NULL, completed_id TEXT NOT NULL REFERENCES events(id), claim_id TEXT NOT NULL,
 body TEXT NOT NULL, PRIMARY KEY(owner,completed_id,claim_id));
CREATE TABLE IF NOT EXISTS claim_facts(
 owner TEXT NOT NULL, completed_id TEXT NOT NULL, claim_id TEXT NOT NULL, fact_id TEXT NOT NULL,
 snapshot_id TEXT, PRIMARY KEY(owner,completed_id,claim_id,fact_id),
 FOREIGN KEY(owner,completed_id,claim_id) REFERENCES report_claims(owner,completed_id,claim_id),
 FOREIGN KEY(owner,snapshot_id) REFERENCES fact_snapshots(owner,snapshot_id));
CREATE VIEW IF NOT EXISTS fact_metadata AS
 SELECT owner,snapshot_id,fact_id,schema_version,
 json_extract(body,'$.original.topic') AS topic,
 json_extract(body,'$.original.source') AS source,
 json_extract(body,'$.original.published_at') AS published_at,
 json_extract(body,'$.original.known_at') AS known_at,
 json_extract(body,'$.original.valid_until') AS valid_until
 FROM fact_snapshots;
CREATE VIEW IF NOT EXISTS judgment_evidence AS
 SELECT c.owner,c.completed_id,c.claim_id,
 json_extract(c.body,'$.statement') AS statement,
 e.fact_id,e.snapshot_id,f.source,f.published_at,f.known_at,f.valid_until
 FROM report_claims c JOIN claim_facts e
 ON c.owner=e.owner AND c.completed_id=e.completed_id AND c.claim_id=e.claim_id
 LEFT JOIN fact_metadata f ON e.owner=f.owner AND e.snapshot_id=f.snapshot_id;
'''
for _table in ('fact_snapshots','report_facts','report_claims','claim_facts'):
    for _action in ('UPDATE','DELETE'):
        DDL+=f"CREATE TRIGGER IF NOT EXISTS {_table}_no_{_action.lower()} BEFORE {_action} ON {_table} BEGIN SELECT RAISE(ABORT,'immutable fact index'); END;\n"


def fingerprint(value):return hashlib.sha256(dumps(value).encode()).hexdigest()


def series_view(series,as_of):
    """Explicit series only. Never parse chart values or trends out of prose."""
    from .contracts import validate,schema
    validate(series,schema('price-series'))
    for key in ('requested_start','requested_end'):day(series[key])
    if series['requested_start']>series['requested_end'] or series['requested_end']>as_of:raise ValueError('Series period outside report')
    points=series['observations'];dates=[p['date'] for p in points]
    if dates!=sorted(set(dates)):raise ValueError('Unique ordered observation dates required')
    for point in points:
        day(point['date']);number(point['value'],0)
        if point['value']<=0 or not series['requested_start']<=point['date']<=series['requested_end']:raise ValueError('Invalid price observation')
    result=copy.deepcopy(series)
    result['calculation']={'rule_version':'mara.series-summary/1.0','formula':'last / first - 1',
        'start_inclusive':True,'end_inclusive':True,'missing_policy':'no_interpolation',
        'actual_start':dates[0],'actual_end':dates[-1],'observations':len(points),
        'period_return':points[-1]['value']/points[0]['value']-1,
        'each_observed_step_down':all(b['value']<a['value'] for a,b in zip(points,points[1:])),
        'continuous_decline_verified':False,
        'scope':'실제 첫·마지막 관측의 변동률이에요. 표본 사이 가격과 요청 기간 전체의 연속 하락을 증명하지 않아요.'}
    return result


def derivation_binding(session,run_id,as_of,role,delivered,source_ids):
    """Bind canonical identity separately from the exact role-visible projection."""
    from .research import project_fact
    canonical={}
    starts=[e for e in session.events('run_started') if e['run_id']==run_id]
    if starts:
        from .history import market_input
        start=starts[-1]['body'];market=market_input(session.get(start['market_id'])['body'],start.get('history_scope',{'after_seq':0,'reset_id':None}))
        canonical.update({f['id']:f for f in market['facts']})
    for e in session.events('research_evidence'):
        if e['run_id']==run_id:
            f=e['body']['fact']
            if f['id'] in canonical and canonical[f['id']]!=f:raise ValueError('Canonical source collision')
            canonical[f['id']]=f
    archived_ids=set(canonical);supplied={f['id']:f for f in delivered};parents=[]
    for fid in source_ids:
        seen=supplied[fid];original=canonical.get(fid,seen)
        if seen!=original and seen!=project_fact(original,role):raise ValueError('Unknown source projection')
        canonical[fid]=original
    nodes={n['fact_id']:n for n in snapshots(list(canonical.values()),as_of)[0]}
    for fid in sorted(source_ids):
        node=nodes[fid];parents.append({'fact_id':fid,'snapshot_id':node['snapshot_id'],'content_sha256':node['content_sha256'],
            'delivered_content_sha256':fingerprint(supplied[fid]),'delivery_scope':'canonical' if supplied[fid]==canonical[fid] else 'role_projection','role':role,
            'canonical_origin':'archived_run' if fid in archived_ids else 'provided_input_only'})
    return parents


def snapshots(facts,as_of):
    lookup={};issues=[]
    for fact in facts:
        fid=fact['id']
        for key in ('published_at','known_at','valid_until'):day(fact[key])
        if fid in lookup:raise ValueError('Ambiguous duplicate logical fact ID')
        lookup[fid]=fact
    ids={};parent_map={};bindings={}
    for fid,fact in lookup.items():
        try:value=json.loads(fact['text'])
        except (ValueError,TypeError):value=None
        assumptions=value.get('assumptions') if isinstance(value,dict) else None
        refs=assumptions.get('source_ids') if isinstance(assumptions,dict) else None
        parent_map[fid]=list(dict.fromkeys(refs)) if fact.get('research_tool')=='company_valuation' and isinstance(refs,list) and all(isinstance(x,str) for x in refs) else []
        derivation=value.get('derivation') if isinstance(value,dict) else None
        bindings[fid]=derivation if isinstance(derivation,dict) else None
    def identify(fid,trail=()):
        if fid not in lookup:return None
        if fid in trail:raise ValueError('Cyclic fact derivation')
        if fid not in ids:
            recorded=bindings[fid].get('parents',[]) if bindings[fid] else []
            expected={p.get('fact_id'):p.get('snapshot_id') for p in recorded if isinstance(p,dict)} if isinstance(recorded,list) else {}
            parents=[{'fact_id':p,'snapshot_id':expected.get(p) if bindings[fid] else identify(p,trail+(fid,))} for p in parent_map[fid]]
            ids[fid]='fact:'+fingerprint({'original':lookup[fid],'parents':parents})
        return ids[fid]
    for fid in lookup:identify(fid)
    nodes=[]
    for fid,fact in lookup.items():
        tool=fact.get('research_tool','');kind={'company_filing_search':'filing_excerpt','company_filing_read':'filing_excerpt',
            'company_xbrl_read':'xbrl_observations','company_valuation':'valuation'}.get(tool,'text')
        try:parsed=json.loads(fact['text'])
        except (ValueError,TypeError):parsed=None
        source_ids=parent_map[fid]
        series=None
        if 'series' in fact:
            try:
                if not isinstance(fact['series'],dict) or fact['series'].get('source')!=fact['source']:raise ValueError('Series source differs from fact')
                series=series_view(fact['series'],as_of);kind='price_series'
            except (ValueError,KeyError,TypeError):issues.append({'code':'invalid_price_series','fact_id':fid})
        current=fact['published_at']<=fact['known_at']<=as_of<=fact['valid_until']
        if not current:issues.append({'code':'outside_report_time','fact_id':fid})
        recorded=bindings[fid].get('parents',[]) if bindings[fid] else []
        expected={p.get('fact_id'):p for p in recorded if isinstance(p,dict)} if isinstance(recorded,list) else {}
        parents=[{'fact_id':p,'snapshot_id':expected.get(p,{}).get('snapshot_id') if bindings[fid] else ids.get(p)} for p in source_ids]
        derivation_status='not_derived'
        if kind=='valuation':
            derivation_status='legacy_report_citations'
            if bindings[fid]:
                bound=(set(expected)==set(source_ids) and all(p in lookup and expected[p].get('snapshot_id')==ids[p] and expected[p].get('content_sha256')==fingerprint(lookup[p]) for p in source_ids))
                derivation_status='bound_parent_snapshots' if bound else 'parent_snapshot_mismatch'
                if not bound:issues.append({'code':'parent_snapshot_mismatch','fact_id':fid})
        for p in parents:
            if not p['snapshot_id']:issues.append({'code':'missing_parent_fact','fact_id':fid,'parent_id':p['fact_id']})
        node={'schema_version':VERSION,'snapshot_id':ids[fid],'fact_id':fid,'kind':kind,'as_of':as_of,
            'current_at_report':current,'content_sha256':fingerprint(fact),'original':copy.deepcopy(fact),
            'parents':parents,'series':series,'derivation_status':derivation_status,
            'epistemic_scope':'analyst_assumptions_and_calculation' if kind=='valuation' else 'supplied_evidence_not_independently_certified'}
        from .contracts import validate,schema
        validate(node,schema('fact-snapshot'));nodes.append(node)
    return nodes,issues


def graph(report,facts,completed_id):
    nodes,issues=snapshots(facts,report['as_of']);lookup={n['fact_id']:n for n in nodes};claims=[];seen=set()
    for index,c in enumerate(report.get('proposal',{}).get('investment_case',{}).get('claims',[])):
        cid=c['id']
        if cid in seen:raise ValueError('Duplicate judgment ID')
        seen.add(cid);refs=[]
        for fid in dict.fromkeys(c.get('fact_ids',[])):
            node=lookup.get(fid);refs.append({'fact_id':fid,'snapshot_id':node['snapshot_id'] if node else None})
            if node is None:issues.append({'code':'missing_claim_fact','claim_id':cid,'fact_id':fid})
        claims.append({'claim_id':cid,'statement':c['statement'],'author':'leader','scope':'explicit_claim_citation',
            'path':'/proposal/investment_case/claims/'+str(index),'fact_refs':refs,
            'calculation_paths':copy.deepcopy(c.get('calculation_paths',[])),
            'support_status':c.get('status'),'support_scope':'작성자의 판단이에요. 인용 연결 자체는 주장 지지나 최종 승인을 뜻하지 않아요.'})
    result={'schema_version':GRAPH,'completed_id':completed_id,'as_of':report['as_of'],'facts':nodes,'claims':claims,'issues':issues}
    from .contracts import validate,schema
    validate(result,schema('fact-graph'))
    return result


def authoritative_facts(session,row):
    from .history import market_input
    r=row['body'];market=market_input(session.get(r['market_id'])['body'],r.get('history_scope',{'after_seq':0,'reset_id':None}))
    lookup={f['id']:copy.deepcopy(f) for f in market['facts'] if f['published_at']<=f['known_at']<=r['as_of']<=f['valid_until']}
    for e in session.events('research_evidence'):
        if e['run_id']!=r['run_id'] or e['seq']>row['seq']:continue
        f=e['body']['fact']
        if not f['published_at']<=f['known_at']<=r['as_of']<=f['valid_until']:continue
        if f['id'] in lookup and lookup[f['id']]!=f:raise ValueError('Ambiguous historical fact ID')
        lookup[f['id']]=copy.deepcopy(f)
    return list(lookup.values())


def persist(session,completed_id,facts):
    if not session.store.in_transaction:
        with session.store.transaction():return persist(session,completed_id,facts)
    row=session.get(completed_id)
    if row['kind']!='completed' or row['owner']!=session.owner:raise PermissionError('Own completed report required')
    original=authoritative_facts(session,row)
    if sorted(facts,key=lambda f:f['id'])!=sorted(original,key=lambda f:f['id']):raise ValueError('Facts differ from completed-run evidence')
    result=graph(row['body'],original,completed_id);db=session.store.db
    for n in result['facts']:
        # Report-specific dates and derived display fields are kept in the graph,
        # while a snapshot is only the complete canonical source fact.
        body=dumps({'original':n['original'],'parents':n['parents']})
        existing=db.execute('SELECT body FROM fact_snapshots WHERE owner=? AND snapshot_id=?',(session.owner,n['snapshot_id'])).fetchone()
        if existing and existing['body']!=body:raise ValueError('Fact snapshot collision')
        db.execute('INSERT OR IGNORE INTO fact_snapshots VALUES(?,?,?,?,?)',(session.owner,n['snapshot_id'],n['fact_id'],VERSION,body))
        db.execute('INSERT OR IGNORE INTO report_facts VALUES(?,?,?,?)',(session.owner,completed_id,n['fact_id'],n['snapshot_id']))
    for c in result['claims']:
        db.execute('INSERT OR IGNORE INTO report_claims VALUES(?,?,?,?)',(session.owner,completed_id,c['claim_id'],dumps(c)))
        for ref in c['fact_refs']:
            db.execute('INSERT OR IGNORE INTO claim_facts VALUES(?,?,?,?,?)',(session.owner,completed_id,c['claim_id'],ref['fact_id'],ref['snapshot_id']))
    if not stored_matches(session,result):raise ValueError('Fact index differs from immutable report')
    return result


def stored_matches(session,result):
    owner=session.owner;eid=result['completed_id'];row=session.get(eid)
    if row['owner']!=owner or row['kind']!='completed':raise PermissionError('Own completed report required')
    db=session.store.db
    pairs=[(r['fact_id'],r['snapshot_id'],r['body']) for r in db.execute('SELECT r.fact_id,r.snapshot_id,f.body FROM report_facts r JOIN fact_snapshots f ON f.owner=r.owner AND f.snapshot_id=r.snapshot_id WHERE r.owner=? AND r.completed_id=? ORDER BY r.fact_id',(owner,eid))]
    expected=sorted((n['fact_id'],n['snapshot_id'],dumps({'original':n['original'],'parents':n['parents']})) for n in result['facts'])
    claims=sorted((r['claim_id'],r['body']) for r in db.execute('SELECT claim_id,body FROM report_claims WHERE owner=? AND completed_id=?',(owner,eid)))
    edges=sorted((r['claim_id'],r['fact_id'],r['snapshot_id']) for r in db.execute('SELECT claim_id,fact_id,snapshot_id FROM claim_facts WHERE owner=? AND completed_id=?',(owner,eid)))
    return pairs==expected and claims==sorted((c['claim_id'],dumps(c)) for c in result['claims']) and edges==sorted((c['claim_id'],f['fact_id'],f['snapshot_id']) for c in result['claims'] for f in c['fact_refs'])


def present(session,report,facts,completed_id):
    row=session.get(completed_id)
    if row['owner']!=session.owner or row['kind']!='completed':raise PermissionError('Own completed report required')
    original=authoritative_facts(session,row)
    result=graph(row['body'],original,completed_id)
    indexed=session.store.db.execute('SELECT 1 FROM report_facts WHERE owner=? AND completed_id=? LIMIT 1',(session.owner,completed_id)).fetchone()
    result['storage_status']='stored_verified' if stored_matches(session,result) else 'index_mismatch_source_projection' if indexed else 'source_projection_not_indexed'
    if result['storage_status']=='index_mismatch_source_projection':result['issues'].append({'code':'stored_index_mismatch'})
    return result
