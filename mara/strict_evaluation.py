"""Versioned report sufficiency gates. Model judgments never replace calculations."""
from .contracts import ContractError
import json


def exact(rows,ids,label):
    if len(rows)!=len(ids) or {r['id'] for r in rows}!=set(ids):
        raise ContractError('Every '+label+' exactly once: '+', '.join(ids))


def compute(output,payload,pointer):
    rubric=payload['rubric'];levels={};errors=[]
    broad={'/profile','/market/facts','/report/proposal','/report/analysis','/report/perspectives','/report/proposal/investment_case'}
    def inspect(path,label,required):
        try:value=pointer(payload,path)
        except ContractError:
            errors.append(label+': unknown path '+path);return
        if required and value in (None,[],{},''):
            errors.append(label+': empty evidence '+path)
    exact(output.get('gates',[]),rubric['acceptance']['required_gates'],'required gate')
    exact(output.get('coverage',[]),rubric['coverage_ids'],'coverage requirement')
    for c in rubric['criteria']:
        row=next(r for r in output['criteria'] if r['id']==c['id'])
        checks=row.get('checks',[]);exact(checks,[x['id'] for x in c['checks']],'atomic check')
        by_id={x['id']:x for x in checks};level=0
        for spec in c['checks']:
            check=by_id[spec['id']]
            if check['status']=='met' and not check['evidence_paths']:errors.append(spec['id']+': met requires evidence paths')
            for path in check['evidence_paths']:
                if not any((path.startswith(p) and len(path)>len(p)) or
                    (path==p.rstrip('/') and path not in broad) for p in spec['allowed_prefixes']):
                    errors.append(spec['id']+': outside scope '+path+'; allowed '+', '.join(spec['allowed_prefixes']))
                inspect(path,spec['id'],check['status']=='met')
            if level==spec['level']-1 and check['status']=='met':level=spec['level']
        # The model supplies observations, not the awarded level. Normalize before persistence.
        row['score']=level;levels[c['id']]=level
    for row in output['gates']+output['coverage']:
        if row['status'] in ('pass','supported') and not row['evidence_paths']:errors.append(row['id']+': passing judgment requires evidence')
        for path in row['evidence_paths']:
            inspect(path,row['id'],row['status'] in ('pass','supported'))
    if errors:raise ContractError('\n'.join(errors))
    gates={g['id']:g['status'] for g in output['gates']};findings=[]
    def lower(gate,status):
        rank={'pass':0,'unknown':1,'fail':2}
        if rank[status]>rank[gates[gate]]:gates[gate]=status
    report=payload['report'];market=payload['market'];as_of=payload['as_of']
    facts={f['id']:f for f in market['facts']}
    if len(facts)!=len(market['facts']):gates['G1']='fail';findings.append('Duplicate fact identity')
    for fact in facts.values():
        if fact['known_at']>as_of or fact['published_at']>as_of or fact['valid_until']<as_of:
            gates['G1']='fail';findings.append('Evidence outside frozen decision date: '+fact['id'])
        tool=fact.get('research_tool')
        if tool in ('fund_profile','fund_history','sec_filings'):
            try:value=json.loads(fact['text'])
            except (ValueError,TypeError):value={}
            prefix='research-'+tool+'-'
            expected=fact['id'][len(prefix):] if fact['id'].startswith(prefix) else fact.get('company_identity',{}).get('symbol')
            observed=value.get('symbol') if isinstance(value,dict) else None
            if expected and observed and str(expected).replace('.','-')!=str(observed).replace('.','-'):
                gates['G1']='fail';findings.append('Conflicting requested and reported asset identity: '+fact['id'])
    # Material claims must identify actual delivered evidence or deterministic calculation.
    case=report['proposal'].get('investment_case',{})
    claims=case.get('claims',[])
    if not claims:lower('G2','unknown');findings.append('No structured material claim ledger')
    delivery=report.get('evidence_delivery',[])
    leader_ids=set().union(*(set(x['fact_ids']) for x in delivery if x['role']=='leader')) if delivery else set()
    for claim in claims:
        refs=claim.get('fact_ids',[])
        if claim.get('status')=='unresolved':lower('G2','unknown');findings.append('Unresolved material claim: '+claim['id'])
        if not refs and not claim.get('calculation_paths'):
            lower('G2','unknown');findings.append('No material claim support: '+claim['id'])
        if not set(refs)<=facts.keys() or not set(refs)<=leader_ids:
            gates['G2']='fail';findings.append('Claim cites evidence not delivered to leader: '+claim['id'])
        for path in claim.get('calculation_paths',[]):
            try:
                if not path.startswith(('/analysis/','/funding/','/valuation/')) and path!='/proposal/investment_case/monitoring':raise ContractError('Not an analysis exhibit')
                value=pointer(payload,'/report'+path)
                if path.startswith(('/funding/','/valuation/')) and type(value) not in (int,float):raise ContractError('Numeric funding or valuation field required')
                if value in (None,[],{},''):raise ContractError('Empty calculation')
            except ContractError:gates['G3']='fail';findings.append('Unknown or non-exhibit calculation: '+claim['id'])

    if not report.get('analysis',{}).get('comparison',{}).get('available'):
        lower('G3','unknown');findings.append('Comparable quantitative history unavailable')
    receipt=payload.get('role_outputs',{}).get('quantitative_verifier',{})
    if receipt.get('status')=='failed':lower('G3','fail');findings.append('Independent quantitative replay disagrees with the report')
    elif receipt.get('status')!='passed':lower('G3','unknown');findings.append('Independent quantitative replay not verified')
    numeric=report.get('validation',{}).get('final_numeric',{})
    final=report.get('validation',{}).get('final_critique',{})
    # A well-founded defer can be suitable; a rejected proposal cannot be declared ready.
    if report['proposal']['eligibility']!='blocked' and (not numeric.get('passed') or not final.get('qualitative_pass')):
        gates['G4']='fail';findings.append('Proposal readiness conflicts with final R4')
    if report['proposal'].get('decision_status',{}).get('execution_status')!='not_authorized':
        gates['G4']='fail';findings.append('Research report must not authorize execution')
    from .coverage import coverage_ledger
    try:ledger=coverage_ledger(report,market)
    except (KeyError,TypeError,ValueError):ledger=[]
    delivered=(len(ledger)==len(rubric['coverage_ids']) and {x['id'] for x in ledger}==set(rubric['coverage_ids'])
        and all(x['retrieved'] and x['delivered'] and x['claim_ids'] for x in ledger))
    coverage=delivered and all(c['status']=='supported' for c in output['coverage'])
    if not coverage:
        gates['G5']='unknown' if gates['G5']=='pass' else gates['G5']
        findings.append('At least one fixed material evidence requirement remains unsupported')
    if not report.get('evidence_delivery'):
        lower('G5','unknown');findings.append('Actual role delivery trace missing')
    total=round(sum(levels[c['id']]/4*c['weight'] for c in rubric['criteria']),1)
    strict=(total>=rubric['acceptance']['min_total'] and min(levels.values())>=rubric['acceptance']['min_each']
        and all(v=='pass' for v in gates.values()) and coverage and not output['red_flags'])
    return {'total':total,'strict_pass':strict,'criterion_levels':levels,'gates':gates,
        'coverage_complete':coverage,'deterministic_findings':findings}
