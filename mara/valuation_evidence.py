"""Bind valuation citations to delivered observations, not to valuation outputs."""
import json
import math
import re
from urllib.parse import urlsplit
from .domain import day


def _cik(value):
    if isinstance(value,bool) or not re.fullmatch(r'\d{1,10}',str(value)) or int(value)<=0:
        raise ValueError('Valuation source company identity required')
    return str(int(value))


def _sec_url(url,path):
    u=urlsplit(url)
    return u.scheme=='https' and u.netloc=='data.sec.gov' and u.path==path and not u.query and not u.fragment


def references(value):
    if not isinstance(value,list) or not value or any(not isinstance(x,str) or not x for x in value) or len(set(value))!=len(value):
        raise ValueError('Distinct supplied valuation source_ids required')
    return set(value)


def _observation(row,unit,as_of,value_key,accession_key):
    from .xbrl_read import FORMS
    if not isinstance(row,dict) or not isinstance(unit,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9:/_-]{0,63}',unit):
        raise ValueError('Valuation observation unit and row required')
    number=row.get(value_key)
    if type(number) not in (int,float) or not math.isfinite(number):raise ValueError('Valuation observation finite numeric value required')
    if row.get('form') not in FORMS or not isinstance(row.get(accession_key),str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',row[accession_key]):
        raise ValueError('Valuation observation filing identity required')
    if not (day(row['end'])<=day(row['filed'])<=day(as_of)) or row.get('start') and day(row['start'])>day(row['end']):
        raise ValueError('Valuation observation is future or has invalid period')


def validate_sources(a,market,ticker,as_of):
    """Checks delivery/identity/time/type. It does NOT validate economic meaning."""
    requested=references(a.get('source_ids'));facts={f['id']:f for f in market['facts']}
    if len(facts)!=len(market['facts']) or not requested<=facts.keys():raise ValueError('Valuation needs distinct delivered source facts')
    values={}
    for fid in requested:
        f=facts[fid]
        if not (day(f['published_at'])<=day(as_of) and day(f['known_at'])<=day(as_of)<=day(f['valid_until'])):
            raise ValueError('Valuation source is future or expired')
        values[fid]=json.loads(f['text'])
        if not isinstance(values[fid],dict):raise ValueError('Valuation source object required')
    companies=[]
    for fid,v in values.items():
        if facts[fid].get('research_tool')=='company_company':
            rows=v.get('companies',[])
            if len(rows)!=1 or rows[0].get('symbol')!=ticker:raise ValueError('Valuation company citation mismatch')
            company=rows[0]
            if company.get('known_at','9999')>as_of:raise ValueError('Valuation company is future')
            companies.append(company)
    matched=[c for c in companies if c.get('quote') and c['quote'].get('currency')=='USD'
             and c['quote'].get('price')==a.get('price') and c['quote'].get('observed_at')==a.get('price_as_of')]
    if not matched:raise ValueError('Valuation price must match cited company USD quote')
    identities={_cik(c.get('cik')) for c in companies}
    if len(identities)!=1:raise ValueError('Valuation company identities conflict')
    cik=identities.pop();sub='/submissions/CIK'+cik.zfill(10)+'.json';fin='/api/xbrl/companyfacts/CIK'+cik.zfill(10)+'.json'
    observed=set();bound=[]
    for fid,v in values.items():
        f=facts[fid];kind=f.get('research_tool');valid=False;substantive=False
        if kind=='company_company':
            c=v['companies'][0]
            valid=_cik(c.get('cik'))==cik and any(_sec_url(r.get('source',''),sub) for r in c.get('raw_refs',[]))
        elif kind in {'sec_financials','sec_filings'}:
            identity=f.get('company_identity',{})
            named=(f['id']=='research-'+kind+'-'+ticker or identity.get('symbol')==ticker and _cik(identity.get('cik'))==cik)
            valid=named and _cik(v.get('cik'))==cik and _sec_url(f.get('source',''),fin if kind=='sec_financials' else sub)
            if kind=='sec_financials':
                observations=[]
                for series in v.get('metrics',{}).values():
                    for entry in series:
                        for row in entry.get('observations',[]):
                            row=dict(zip(v['observation_columns'],row)) if isinstance(row,list) else row
                            _observation(row,entry.get('unit'),as_of,'value','accession')
                            observations.append(row)
                if v.get('latest_filed') and day(v['latest_filed'])>day(as_of):raise ValueError('Valuation financial filing is future')
                substantive=bool(observations)
        elif kind in {'company_filing_read','company_filing_search'}:
            filing=v.get('filing',{});u=urlsplit(filing.get('url',''));acc=filing.get('accession','')
            valid=(v.get('symbol')==ticker and v.get('source_scope')=='same_filing'
                   and day(filing['filed'])<=day(as_of) and re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc)
                   and u.scheme=='https' and u.netloc=='www.sec.gov'
                   and u.path.startswith('/Archives/edgar/data/'+cik+'/'+acc.replace('-','')+'/'))
            substantive=bool(v.get('text','').strip() or any(h.get('excerpt','').strip() for h in v.get('hits',[])))
        elif kind=='company_xbrl_read':
            valid=(v.get('symbol')==ticker and _cik(v.get('cik'))==cik and _sec_url(f.get('source',''),fin))
            for row in v.get('observations',[]):_observation(row,v.get('unit'),as_of,'val','accn')
            substantive=bool(v.get('observations'))
        if not valid:raise ValueError('Valuation citations must be current observations for the quoted company')
        if substantive:observed.add(fid)
        bound.append({'fact_id':fid,'research_tool':kind,'source':f['source'],'substantive_observation':substantive})
    if not observed:raise ValueError('Valuation needs financial observations or filing text, not only quote/catalog')
    cases=a.get('earnings_cases')
    if cases is not None:
        if not isinstance(cases,dict) or set(cases)!={'bear','base','bull'}:raise ValueError('Three named earnings cases required')
        for case in cases.values():
            if not isinstance(case,dict):raise ValueError('Earnings case object required')
            ids=references(case.get('source_ids'))
            if not ids<=requested or not ids&observed:raise ValueError('Each earnings case needs cited observed company evidence')
    return {'version':'valuation-evidence/1.0','company':ticker,'cik':cik,'sources':sorted(bound,key=lambda x:x['fact_id']),
            'scope':'현재 전달된 자료의 기업·시점·종류와 가격 인용을 확인했어요. 정상화 조정식·기간/단위의 경제적 적합성·가정의 타당성을 인증한 결과는 아니에요.'}
