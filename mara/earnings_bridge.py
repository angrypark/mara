"""Observation-bound normalization arithmetic; no default economic assumptions."""
import hashlib
import json
import math
from .domain import day, dumps
from .valuation_evidence import validate_sources
from .contracts import validate, schema
from .research_sources import EvidenceError


def observations(market, ticker):
    """Return exact locators, including period/unit, without selecting a preferred year/tag."""
    rows=[]
    for fact in market.get('facts',[]):
        kind=fact.get('research_tool')
        if kind not in ('sec_financials','company_xbrl_read'):continue
        try:body=json.loads(fact['text'])
        except (ValueError,TypeError):continue
        identity=fact.get('company_identity',{})
        if not (identity.get('symbol')==ticker or body.get('symbol')==ticker or fact['id']=='research-sec_financials-'+ticker):continue
        series=[]
        if kind=='sec_financials':
            for metric,entries in body.get('metrics',{}).items():
                for si,entry in enumerate(entries):
                    series.append((metric,entry.get('unit'),entry.get('observations',[]),'/metrics/'+metric.replace('~','~0').replace('/','~1')+'/'+str(si)+'/observations'))
        else:series=[(body.get('tag'),body.get('unit'),body.get('observations',[]),'/observations')]
        for metric,unit,values,path in series:
            for oi,value in enumerate(values):
                value=dict(zip(body['observation_columns'],value)) if isinstance(value,list) else value
                number=value.get('value',value.get('val'))
                rows.append(dict(ref={'fact_id':fact['id'],'path':path+'/'+str(oi)},concept=metric,unit=unit,value=number,
                    start=value.get('start'),end=value.get('end'),filed=value.get('filed'),
                    accession=value.get('accession',value.get('accn')),source_sha256=hashlib.sha256(dumps({k:v for k,v in body.items() if k!='provenance'}).encode()).hexdigest()))
    return rows


def normalize(args,market,as_of):
    validate(args,schema('earnings-bridge'))
    ticker=args['symbol'];facts={f['id']:f for f in market['facts']}
    quote=facts.get(args['quote_fact_id'])
    if not quote:raise EvidenceError('normalization_quote_not_delivered')
    try:company=json.loads(quote['text'])['companies'][0];price=company['quote']
    except (KeyError,TypeError,IndexError):raise EvidenceError('normalization_quote_missing') from None
    refs=[c['shares'] for c in args['cases'].values()]+[x['observation'] for c in args['cases'].values() for x in c['components']]
    ids=sorted({args['quote_fact_id']}|{r['fact_id'] for r in refs})
    binding=validate_sources(dict(source_ids=ids,price=price['price'],price_as_of=price['observed_at']),market,ticker,as_of)
    days=(day(args['period_end'])-day(args['period_start'])).days
    if not 335<=days<=400 or day(args['period_end'])>day(as_of):raise EvidenceError('normalization_requires_one_annual_period')
    catalog={(r['ref']['fact_id'],r['ref']['path']):r for r in observations(market,ticker)}
    def read(ref,unit):
        row=catalog.get((ref['fact_id'],ref['path']))
        if not row:raise EvidenceError('normalization_observation_locator_missing')
        if row['unit']!=unit or (row['start'],row['end'])!=(args['period_start'],args['period_end']):
            raise EvidenceError('normalization_period_or_unit_mismatch')
        if type(row['value']) not in (float,int) or not math.isfinite(row['value']):raise EvidenceError('normalization_numeric_observation_required')
        return row
    cases={}
    for name,case in args['cases'].items():
        share=read(case['shares'],'shares')
        if share['value']<=0:raise EvidenceError('normalization_share_denominator_nonpositive')
        used=set();parts=[]
        for item in case['components']:
            ref=item['observation'];key=(ref['fact_id'],ref['path'])
            if key in used:raise EvidenceError('normalization_duplicate_component')
            used.add(key);row=read(ref,'USD');amount=row['value']*item['multiplier']
            parts.append(dict(item,observed=row,adjusted_amount_usd=amount))
        total=math.fsum(x['adjusted_amount_usd'] for x in parts)
        earnings=total/share['value']
        if not math.isfinite(earnings):raise EvidenceError('normalization_result_nonfinite')
        cases[name]=dict(owner_earnings_per_share=earnings,normalized_annual_usd=total,shares=share,components=parts,
            explanation=case['explanation'],reinvestment=case['reinvestment'],dilution=case['dilution'],falsifier=case['falsifier'],
            positive_earnings_model_applicable=earnings>0)
    return dict(schema_version='mara.earnings-bridge/1.0',symbol=ticker,as_of=as_of,inputs=args,cases=cases,
        source_ids=ids,source_validation=binding,share_basis=args['share_basis'],
        formula='sum(observed annual USD component * explicit analyst multiplier) / observed same-period shares',
        scope='Arithmetic and locator validation only. Multipliers, omissions, double-counting across concepts, split basis and economic interpretation require analyst challenge. Not a verified owner earnings estimate or recommendation. Negative cases are retained; do not force them into positive-earnings DCF.')


def bind_valuation(fact_id,assumptions,market,ticker,as_of):
    fact=next((f for f in market['facts'] if f['id']==fact_id),None)
    if not fact or fact.get('research_tool')!='company_normalize_earnings':raise EvidenceError('normalization_bridge_not_delivered')
    value=json.loads(fact['text'])
    if value.get('symbol')!=ticker or value.get('as_of')!=as_of:raise EvidenceError('normalization_identity_or_date_mismatch')
    recomputed=normalize(value['inputs'],market,as_of)
    if recomputed!={k:v for k,v in value.items() if k!='derivation'}:raise EvidenceError('normalization_source_version_changed')
    if not set(value['source_ids'])<=set(assumptions['source_ids']):raise EvidenceError('normalization_parent_citation_missing')
    cases=assumptions.get('earnings_cases')
    if not cases or assumptions['share_basis']!=value['share_basis']:raise EvidenceError('normalization_cases_or_share_basis_changed')
    for name,row in value['cases'].items():
        actual=float(cases[name]['owner_earnings_per_share'])
        if not math.isclose(actual,row['owner_earnings_per_share'],rel_tol=1e-10,abs_tol=1e-12):raise EvidenceError('normalization_earnings_mismatch')
    return {'fact_id':fact_id,'sha256':hashlib.sha256(dumps(value).encode()).hexdigest(),
        'status':'arithmetic_bound_economic_judgment_unverified','source_ids':value['source_ids']}
