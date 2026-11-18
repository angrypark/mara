"""Public company library and bounded agent tools, independent of private context."""
import copy
import fcntl
import hashlib
import json
import math
import os
import re
from datetime import date,timedelta
from html.parser import HTMLParser
from pathlib import Path
from .research import PublicArchive,safe_code
from . import research_sources as src
from .registry import resource
from .domain import dumps,day
from .document_text import FilingText,extract,excerpts,excerpt_page,read_chunk,EXTRACTION_VERSION


def symbol(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',value):raise ValueError('Invalid symbol')
    return value.replace('.','-')


def quality(fin):
    """Matched annual periods only; no sector-neutral 'moat score'."""
    metrics=fin['metrics'];result=[]
    def rows(k):return { (r.get('start'),r['end']):r for s in metrics.get(k,[])[:1] for r in s['observations']}
    revenue=rows('revenue');income=rows('net_income');cfo=rows('operating_cashflow');capex=rows('capital_expenditure')
    for period,r in sorted(revenue.items(),reverse=True)[:3]:
        row={'start':period[0],'end':period[1],'revenue_usd':r['value'],'net_margin':None,'operating_cash_margin':None,'fcf_proxy_usd':None}
        if r['value']>0:
            if period in income:row['net_margin']=income[period]['value']/r['value']
            if period in cfo:row['operating_cash_margin']=cfo[period]['value']/r['value']
        if period in cfo and period in capex and capex[period]['value']>=0:row['fcf_proxy_usd']=cfo[period]['value']-capex[period]['value']
        result.append(row)
    return {'annual_comparison':result,'formula':'net margin=net income/revenue; cash margin=CFO/revenue; FCF proxy=CFO-capex, same start/end/USD',
        'limits':'FCF proxy는 owner earnings가 아니에요. 유지 투자·희석·운전자본·일회성·업종 차이 미조정. 경쟁우위와 경영진 평가는 공시/경쟁 근거로 별도 판단.'}


def owner_value(a,known_ids,as_of):
    required={'owner_earnings_per_share','currency','earnings_period','share_basis','normalization','price','price_as_of','source_ids','scenarios','margin_of_safety'}
    if set(a) not in (required,required|{'earnings_cases'}) or a['currency']!='USD':raise ValueError('Explicit USD per-share valuation inputs required')
    if not a['source_ids'] or not set(a['source_ids'])<=known_ids:raise ValueError('Valuation needs supplied evidence references')
    if not all(isinstance(a[k],str) and a[k].strip() for k in ('earnings_period','share_basis','normalization')):raise ValueError('Normalization and share basis required')
    if day(a['price_as_of'])>day(as_of) or (day(as_of)-day(a['price_as_of'])).days>10:raise ValueError('Price is future or stale')
    def positive_earnings(value):
        number=src.finite(value)
        if number<=0:raise src.EvidenceError('valuation_model_nonpositive_earnings')
        return number
    earn=positive_earnings(a['owner_earnings_per_share']);price=src.finite(a['price'],.000001);mos=src.finite(a['margin_of_safety'],0,.9)
    if not isinstance(a['scenarios'],list) or len(a['scenarios'])!=3 or any(not isinstance(s,dict) for s in a['scenarios']) or {s.get('name') for s in a['scenarios']}!={'bear','base','bull'}:raise ValueError('Three distinct scenarios required')
    cases=a.get('earnings_cases');case_earnings={}
    if 'earnings_cases' in a:
        from .valuation_evidence import references
        if not isinstance(cases,dict) or set(cases)!={'bear','base','bull'}:raise ValueError('Three named earnings cases required')
        for name,case in cases.items():
            if not isinstance(case,dict) or set(case)!={'owner_earnings_per_share','normalization','reinvestment','dilution','source_ids','falsifier'}:raise ValueError('Explicit normalization, reinvestment, dilution and falsifier required')
            case_earnings[name]=positive_earnings(case['owner_earnings_per_share'])
            if not references(case['source_ids'])<=set(a['source_ids']):raise ValueError('Earnings case references must be included in source_ids')
            if not all(isinstance(case[k],str) and case[k].strip() for k in ('normalization','reinvestment','dilution','falsifier')):raise ValueError('Earnings case explanations required')
        if case_earnings['base']!=earn:raise ValueError('Base earnings must match owner_earnings_per_share')
    values=[];parsed_scenarios={}
    def calculate(e,g,r,t,n):
        flows=sum(e*(1+g)**i/(1+r)**i for i in range(1,n+1));terminal=e*(1+g)**n*(1+t)/(r-t)/(1+r)**n
        value=flows+terminal
        if not math.isfinite(value) or value<=0:raise ValueError('Finite positive valuation required')
        return {'value_per_share':value,'price_margin':1-price/value,'buy_ceiling':value*(1-mos),'terminal_value_fraction':terminal/value}
    for s in a['scenarios']:
        if set(s)!={'name','growth','discount','terminal_growth','years','reason'} or not isinstance(s['reason'],str) or not s['reason'].strip():raise ValueError('Scenario assumptions required')
        g=src.finite(s['growth'],-.5,.5);r=src.finite(s['discount'],.01,.5);t=src.finite(s['terminal_growth'],-.05,.1);n=s['years']
        if type(n)!=int or not 1<=n<=20 or t>=r:raise ValueError('Discount must exceed terminal growth; horizon 1..20')
        e=case_earnings[s['name']] if cases else earn
        parsed_scenarios[s['name']]={'growth':g,'discount':r,'terminal_growth':t,'years':n}
        row=calculate(e,g,r,t,n)
        row['price_implied_annual_earnings_per_share']=price/(row['value_per_share']/e)
        row['earnings_to_meet_margin_of_safety']=price/((row['value_per_share']/e)*(1-mos))
        row['normalized_earnings_to_price_implied_ratio']=e/row['price_implied_annual_earnings_per_share']
        values.append(dict(s,owner_earnings_per_share=e,**row))
    base=parsed_scenarios['base']
    sensitivity=[dict(name=name,owner_earnings_per_share=e,
        **calculate(e,base['growth'],base['discount'],base['terminal_growth'],base['years'])) for name,e in sorted(case_earnings.items())]
    return {'method':'discounted normalized owner earnings per share; analyst assumptions, not observed fair value',
        'assumptions':a,'scenarios':values,'formula':'sum(E*(1+g)^t/(1+r)^t,t=1..N)+E*(1+g)^N*(1+terminal)/(r-terminal)/(1+r)^N',
        'normalization_sensitivity':{'mode':'case_earnings' if cases else 'fixed_earnings','rows':sensitivity,
            'held_constant':{k:base[k] for k in ('growth','discount','terminal_growth','years')},
            'scope':'base의 성장·할인·영구성장·기간을 고정하고 정상화 이익만 바꿨어요.' if cases else '모든 시나리오가 같은 정상화 이익을 사용해요. 정상화 이익의 민감도는 검증하지 않았어요.'},
        'assumption_scope':'경우별 재투자·희석 설명은 이익과 주당 성장률에 반영한 분석 가정이에요. 별도 투자 지출·주식 수 경로를 계산하지 않아요. bear도 최대 손실 보장이 아니에요. 0·음수 이익의 하방은 이 양수 이익 모형이 표현하지 못해요.',
        'limits':'정상화와 주당/분할 기준은 분석자의 명시 가정. 자동 검증된 가치 아님. 부채를 다시 차감하지 않는 equity per-share 모델. 기업가치 FCFF/WACC와 혼용 금지. 음수 이익·은행/보험 등에는 적합한 별도 방법 필요.'}



def document_catalog(sub,cik,as_of):
    """Keep each useful form even when many 8-Ks crowd out quarterly/annual filings."""
    recent=sub['filings']['recent'];rows=[];counts={}
    for i,form in enumerate(recent.get('form',[])):
        if form not in {'10-K','10-Q','20-F','6-K','8-K','10-K/A','10-Q/A'} or counts.get(form,0)>=3:continue
        filed=recent['filingDate'][i];acc=recent['accessionNumber'][i];doc=recent['primaryDocument'][i]
        if not 0<=(day(as_of)-day(filed)).days<=1850:continue
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc) or not re.fullmatch(r'[A-Za-z0-9_.-]+',doc):continue
        rows.append({'form':form,'filed':filed,'report_date':recent['reportDate'][i],
            'accession':acc,'url':f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-","")}/{doc}'})
        counts[form]=counts.get(form,0)+1
    return rows

class CompanyLibrary:
    def __init__(self,root,transport=None,today=None,quote_provider=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.transport=transport;self._today=today
        self.quote_provider=quote_provider

    @property
    def today(self):return self._today or date.today().isoformat()

    def archive(self):return PublicArchive(self.root/'raw',transport=self.transport)

    def universe(self):
        try:
            raw,meta=self.archive().get(src.SEC_TICKERS);data=json.loads(raw)
            if not isinstance(data,dict) or any(not isinstance(x,dict) for x in data.values()):raise ValueError('Invalid SEC ticker map shape')
            rows=[{'symbol':symbol(x['ticker']),'name':x['title'],'cik':int(x['cik_str'])} for x in data.values()]
            return rows,'SEC current ticker map'
        except (OSError,ValueError,KeyError,TypeError):
            seed=json.loads(resource('resources/sec-tickers.json').read_text())
            return [{'symbol':symbol(k),'name':k,'cik':int(v)} for k,v in seed['tickers'].items()],'partial dated seed; live SEC map unavailable'

    def latest(self,ticker,as_of):
        p=self.root/'companies'/symbol(ticker)
        rows=[]
        for file in p.glob('*.json'):
            value=json.loads(file.read_text())
            if value['known_at']<=as_of:rows.append(value)
        return max(rows,key=lambda x:x['retrieved_at']) if rows else None

    def collect(self,tickers,as_of,progress=lambda x:None):
        if as_of!=self.today:raise ValueError('Historical analysis cannot collect current company data')
        tickers=list(dict.fromkeys(symbol(s) for s in tickers))
        if not 1<=len(tickers)<=200:raise ValueError('Collect 1..200 companies per batch')
        universe,coverage=self.universe();mapping={x['symbol']:x for x in universe};receipts=[]
        # Public-only lock coordinates SEC requests; each company is a durable checkpoint.
        with open(self.root/'collection.lock','a') as lock:
            os.chmod(self.root/'collection.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
            for i,ticker in enumerate(tickers):
                try:
                    old=self.latest(ticker,as_of)
                    if old and old['known_at']==as_of and old.get('schema_version')=='company-dossier/1.1':receipts.append({'symbol':ticker,'status':'cached','version':old['version']});continue
                    identity=mapping[ticker];cik=identity['cik'];archive=self.archive()
                    # Reset per-company size/time budgets, never the per-request SEC spacing.
                    url=f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
                    raw,submeta=archive.get(url);sub=json.loads(raw)
                    if not isinstance(sub,dict):raise ValueError('Invalid submissions shape')
                    filings=src.sec_filings(sub,ticker,as_of)
                    raw,fmeta=archive.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
                    rawfin=json.loads(raw)
                    if not isinstance(rawfin,dict):raise ValueError('Invalid financial facts shape')
                    if int(rawfin['cik'])!=cik:raise ValueError('Company identity mismatch')
                    fin=src.sec_financials(rawfin,as_of)
                    recent=sub['filings']['recent'];annual=[]
                    for j,form in enumerate(recent['form']):
                        if form not in ('10-K','20-F') or recent['filingDate'][j]>as_of:continue
                        acc=recent['accessionNumber'][j];doc=recent['primaryDocument'][j]
                        if re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc) and re.fullmatch(r'[A-Za-z0-9_.-]+',doc):
                            annual=[{'form':form,'filed':recent['filingDate'][j],'accession':acc,'url':f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-","")}/{doc}'}];break
                    body={'schema_version':'company-dossier/1.1','symbol':ticker,'cik':cik,'entity':sub['name'],'known_at':as_of,'retrieved_at':fmeta['retrieved_at'],
                        'financials':fin,'quality':quality(fin),'filings':filings,'annual_filing':annual,'raw_refs':[submeta,fmeta],
                        'documents':document_catalog(sub,cik,as_of),
                        'coverage':'annual standard US GAAP; no independent moat or intrinsic value assertion'}
                    body['version']=hashlib.sha256(dumps(body).encode()).hexdigest()
                    folder=self.root/'companies'/ticker;folder.mkdir(parents=True,exist_ok=True)
                    p=folder/(body['version']+'.json');p.write_text(dumps(body));p.chmod(0o600)
                    receipts.append({'symbol':ticker,'status':'collected','version':body['version']})
                except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:receipts.append({'symbol':ticker,'status':'unavailable','reason':safe_code(exc)})
                finally:progress({'done':i+1,'total':len(tickers),'latest':receipts[-1]})
        return {'receipts':receipts,'identity_coverage':coverage,'requested':len(tickers),'completed':sum(r['status']!='unavailable' for r in receipts),
            'read_policy':'Collected does not mean read. compare returns pages; company returns selected dossiers.'}

    def filing_list(self,ticker,as_of):
        body=self.latest(ticker,as_of)
        if not body:raise src.EvidenceError('company_not_collected')
        rows=body.get('documents',body.get('annual_filing',[])+body.get('filings',{}).get('filings',[]))
        seen=set();rows=[r for r in rows if r['filed']<=as_of and not (r['accession'] in seen or seen.add(r['accession']))]
        return {'symbol':symbol(ticker),'filings':rows,'scope':'Bounded recent submissions, not all historical filings; choose an accession before reading'}

    def document(self,ticker,as_of,accession=None,expected_sha256=None):
        body=self.latest(ticker,as_of)
        if not body:raise src.EvidenceError('company_not_collected')
        if as_of!=self.today:raise ValueError('Historical filing text must already be in original run evidence')
        if accession:
            rows=self.filing_list(ticker,as_of)['filings']
            filing=next((x for x in rows if x['accession']==accession),None)
            if not filing:raise src.EvidenceError('unknown_filing_accession')
        else:
            if not body.get('annual_filing'):raise src.EvidenceError('annual_filing_unavailable')
            filing=body['annual_filing'][0]
        fallback=None;attempts=[]
        def unavailable(code):
            error=src.EvidenceError(code);error.attempts=copy.deepcopy(attempts)
            raise error from None
        def checked(raw,required=()):
            text,fmt=extract(raw);normalized=re.sub(r'\s+',' ',text).casefold()
            head=normalized[:2000]
            if any(x in head for x in ('access denied','request rate threshold exceeded','undeclared automated tool','captcha','request blocked')):
                raise src.EvidenceError('source_error_page')
            if any(re.sub(r'\s+',' ',term).casefold() not in normalized for term in required):
                raise src.EvidenceError('document_identity_mismatch')
            return text,fmt
        try:
            raw,meta=self.archive().get(filing['url'])
            required=[body['entity']] if body.get('entity') else []
            required.append(filing['form'].removesuffix('/A'))
            if filing.get('report_date'):
                dt=day(filing['report_date']);required.append(dt.strftime('%B')+' '+str(dt.day)+', '+str(dt.year))
            text,format_info=checked(raw,required)
        except (OSError,ValueError) as exc:
            attempts.append({'source':filing['url'],'status':safe_code(exc)})
            registry=json.loads(resource('resources/issuer-documents.json').read_text())
            candidates=[registry['documents'].get(symbol(ticker))]+registry.get('additional_documents',{}).get(symbol(ticker),[])
            candidates=[f for f in candidates if f and f.get('filing_accession')==filing['accession']
                and 0<=(day(as_of)-day(f['verified_on'])).days<=180
                and all(key not in f or f[key]==expected for key,expected in
                    (('cik',body.get('cik')),('form',filing.get('form')),('report_date',filing.get('report_date'))))]
            if not candidates:
                unavailable(attempts[-1]['status'] if attempts[-1]['status'].startswith('source_text_extraction') else 'no_verified_same_filing_source')
            for candidate in candidates[:3]:
                try:
                    raw,meta=self.archive().get(candidate['url'])
                    if candidate.get('observed_sha256') and meta['sha256']!=candidate['observed_sha256']:
                        raise src.EvidenceError('registered_document_changed_requires_review')
                    text,format_info=checked(raw,candidate.get('required_text',[]))
                    fallback=candidate;break
                except (OSError,ValueError) as error:
                    attempts.append({'source':candidate['url'],'status':safe_code(error)})
            if fallback is None:unavailable(attempts[-1]['status'])
        if expected_sha256 and meta['sha256']!=expected_sha256:raise src.EvidenceError('document_changed_restart_cursor')
        return text,{'symbol':symbol(ticker),'filing':filing,'issuer_fallback':fallback,'raw_ref':meta,
            'attempts':attempts,'text_length':len(text),'extraction_version':EXTRACTION_VERSION,'document_format':format_info,
            'source_scope':'same_filing' if not fallback or fallback.get('filing_accession') else 'supplement_not_verified_same_filing',
            'limits':'Read ranges only, not full-document review. Issuer statement, not independently verified financial truth.'}

    def filing_search(self,ticker,query,as_of,accession=None,offset=0,expected_sha256=None,expected_extraction_version=None):
        if offset and not expected_sha256:raise ValueError('Continuation requires original document hash')
        if offset and expected_extraction_version!=EXTRACTION_VERSION:raise src.EvidenceError('extraction_changed_restart_cursor')
        text,receipt=self.document(ticker,as_of,accession,expected_sha256)
        return dict(receipt,**excerpt_page(text,query,offset))

    def filing_read(self,ticker,as_of,accession,offset=0,limit=10000,expected_sha256=None,expected_extraction_version=None):
        if offset and not expected_sha256:raise ValueError('Continuation requires original document hash')
        if offset and expected_extraction_version!=EXTRACTION_VERSION:raise src.EvidenceError('extraction_changed_restart_cursor')
        text,receipt=self.document(ticker,as_of,accession,expected_sha256)
        return dict(receipt,**read_chunk(text,offset,limit))


class ResearchTools:
    def __init__(self,library,session,run_id,as_of):self.lib,self.s,self.run_id,self.as_of=library,session,run_id,as_of

    def activate(self,role,fact,market):
        if self.s.store.in_transaction:raise src.EvidenceError('research_activation_requires_owned_transaction')
        staged=dict(market,facts=copy.deepcopy(market['facts']))
        with self.s.store.transaction():accepted=self._activate(role,fact,staged)
        if accepted:market['facts']=staged['facts']
        return accepted

    def _activate(self,role,fact,market):
        rows=[e['body'] for e in self.s.events('research_evidence') if e['run_id']==self.run_id]
        existing={}
        for row in rows:
            old=existing.get(row['fact']['id'])
            if old is not None and old!=row['fact']:raise src.EvidenceError('evidence_id_collision')
            existing[row['fact']['id']]=row['fact']
        current=next((f for f in market['facts'] if f['id']==fact['id']),None)
        if current is not None:
            canonical=existing.get(fact['id'])
            if canonical is not None and canonical!=fact:raise src.EvidenceError('evidence_id_collision')
            if current!=fact:
                from .research import project_fact
                if canonical is None or current!=project_fact(canonical,role):raise src.EvidenceError('evidence_id_collision')
                # Explicit rereading restores the full same original, without a
                # new acquisition charge or a claim that a projection was full.
                market['facts']=[copy.deepcopy(canonical) if f['id']==fact['id'] else f for f in market['facts']]
            return True
        if fact['id'] in existing:
            if existing[fact['id']]!=fact:raise src.EvidenceError('evidence_id_collision')
            market['facts'].append(copy.deepcopy(existing[fact['id']]))
            return True
        prerequisites={'company_company','sec_financials','sec_filings','company_filing_search','company_filing_read','company_valuation','company_normalize_earnings','company_xbrl_read'}
        from .research_budget import allocate
        allocation,self.activation_budget=allocate(self.s,self.run_id,self.as_of,rows,role,fact,fact.get('research_tool') in prerequisites)
        if allocation is None:return False
        buckets=[k for k,v in allocation.items() if v];bucket=buckets[0] if len(buckets)==1 else 'mixed'
        market['facts'].append(fact)
        self.s.append('research_evidence',{'role':role,'fact':fact,'budget_bucket':bucket,'budget_allocation':allocation},self.as_of,self.run_id)
        return True

    def execute(self,role,call,market):
        tool=call['tool'];args=call['arguments'];result=None
        if tool=='search':
            rows,coverage=self.lib.universe();q=args.get('query','').upper();rows=[r for r in rows if q in (r['symbol']+' '+r['name']).upper()]
            offset=args.get('offset',0);limit=args.get('limit',20)
            result={'companies':rows[offset:offset+limit],'total':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None,'coverage':coverage}
        elif tool=='collect':
            result=self.lib.collect(args['symbols'],self.as_of,lambda x:self.s.append('research_progress',dict(role=role,**x),date.today().isoformat(),self.run_id))
        elif tool in ('compare','company'):
            names=args.get('symbols',[]) if tool=='compare' else [args['symbol']];offset=args.get('offset',0);limit=args.get('limit',20)
            if not names:raise ValueError('Explicit company symbols required')
            rows=[]
            for ticker in names[offset:offset+limit]:
                value=self.lib.latest(ticker,self.as_of)
                if not value:rows.append({'symbol':ticker,'status':'not_collected'});continue
                if tool=='company':rows.append(value)
                else:rows.append({k:value[k] for k in ('symbol','entity','version','known_at','quality','coverage')})
            result={'companies':rows,'requested':len(names),'next_offset':offset+limit if offset+limit<len(names) else None}
            if tool=='company' and rows and rows[0].get('financials'):
                company=copy.deepcopy(rows[0]);rows[0]=company;company['quote']=None
                if self.lib.quote_provider and self.as_of==self.lib.today:
                    try:company['quote']=self.lib.quote_provider(args['symbol'])
                    except Exception:company['quote_status']='unavailable; no assumed price'
                # Make the full retrieved financial and filing evidence available to
                # the deterministic selected-asset gate as well as downstream agents.
                company['evidence_refs']={}
                for kind,value in [('sec_financials',company['financials']),('sec_filings',company['filings'])]:
                    fid='company-'+kind+'-'+company['version'][:24]
                    fact={'id':fid,'topic':company['symbol']+' · '+kind,'text':dumps(value),
                        'source':company['raw_refs'][1 if kind=='sec_financials' else 0]['source'],
                        'published_at':value.get('latest_filed') or max(f['filed'] for f in value['filings']),
                        'known_at':self.as_of,'valid_until':self.as_of,'uncertainty':value['limits'],'research_tool':kind,
                        'company_identity':{'symbol':company['symbol'],'cik':company['cik'],'version':company['version'],'verification':'SEC submissions ticker match'},
                        'raw_refs':company['raw_refs']}
                    delivered=self.activate(role,fact,market)
                    company['evidence_refs'][kind]={'fact_id':fid if delivered else None,
                        'status':'delivered' if delivered else 'stored_not_activated',
                        'source':fact['source'],'rule':'Read the actual delivered fact; this link is not financial evidence.'}
                company.pop('financials');company.pop('filings')
                company['document_catalog']={'count':len(company.pop('documents',[])),'read_with':'filing_list'}
                company['scope']='Company identity, quote and summary. Financial tables/filings are separate cited facts; full original dossier is retained in the library.'
        elif tool=='filing_list':result=self.lib.filing_list(args['symbol'],self.as_of)
        elif tool=='filing_search':result=self.lib.filing_search(args['symbol'],args['query'],self.as_of,
            args.get('accession'),args.get('offset',0),args.get('expected_sha256'),args.get('expected_extraction_version'))
        elif tool=='filing_read':result=self.lib.filing_read(args['symbol'],self.as_of,args['accession'],
            args.get('offset',0),args.get('limit',10000),args.get('expected_sha256'),args.get('expected_extraction_version'))
        elif tool in ('xbrl_search','xbrl_read'):
            from .xbrl_read import run
            result=run(self.lib,tool,args,self.as_of)
        elif tool=='normalize_earnings':
            from .earnings_bridge import normalize
            result=normalize(args,market,self.as_of)
        elif tool=='valuation':
            from .valuation_evidence import validate_sources
            a=args['assumptions'];binding=validate_sources(a,market,symbol(args['symbol']),self.as_of)
            result=owner_value(a,{f['id'] for f in market['facts']},self.as_of)
            result['symbol']=symbol(args['symbol'])
            result['identity_basis']='validated company dossier and matching USD quote/source_ids'
            result['source_validation']=binding
            result['normalization_binding']={'status':'not_bound','reason':'No structured observation-to-earnings bridge supplied'}
            if args.get('normalization_fact_id'):
                from .earnings_bridge import bind_valuation
                result['normalization_binding']=bind_valuation(args['normalization_fact_id'],a,market,symbol(args['symbol']),self.as_of)
        else:raise ValueError('Unknown research tool')
        if tool=='normalize_earnings':
            from .fact_catalog import derivation_binding
            result['derivation']={'schema_version':'mara.valuation-derivation/1.0','operation':'normalize_earnings/1',
                'implementation_sha256':hashlib.sha256(Path(__file__).with_name('earnings_bridge.py').read_bytes()).hexdigest(),
                'parents':derivation_binding(self.s,self.run_id,self.as_of,role,market['facts'],result['source_ids']),
                'scope':'원관측 버전과 산술 연결. 경제적 가정의 타당성은 별도 검토해요.'}
        if tool=='valuation':
            from .fact_catalog import derivation_binding
            result['derivation']={'schema_version':'mara.valuation-derivation/1.0','operation':'owner_value/1',
                'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'parents':derivation_binding(self.s,self.run_id,self.as_of,role,market['facts'],args['assumptions']['source_ids']+([args['normalization_fact_id']] if args.get('normalization_fact_id') else [])),
                'scope':'계산을 만들 때 사용한 원자료 버전이에요. 가정의 경제적 타당성을 인증하지 않아요.'}
        # Receipts and discovery results are not financial evidence.
        fact=None
        if tool in ('compare','company','filing_search','filing_read','valuation','normalize_earnings','xbrl_read') and result.get('status')!='no_observations':
            ident='company-'+hashlib.sha256(dumps(result).encode()).hexdigest()[:24]
            fact={'id':ident,'topic':tool+' · '+args.get('symbol',','.join(args.get('symbols',[])[:5])),
                'text':dumps(result),'source':'https://www.sec.gov/search-filings/edgar-application-programming-interfaces',
                'published_at':self.as_of,'known_at':self.as_of,'valid_until':self.as_of,
                'uncertainty':'분석자 가정 계산' if tool in ('valuation','normalize_earnings') else 'SEC 표준 재무/발행사 진술. 상세 기간·공시일은 본문에 포함.',
                'research_tool':'company_'+tool}
            if tool in ('filing_search','filing_read'):fact['raw_refs']=[result['raw_ref']]
            if tool=='xbrl_read':
                fact.update(source=result['raw_ref']['source'],raw_refs=[result['raw_ref']],
                    published_at=max(r['filed'] for r in result['observations']),
                    company_identity={k:result[k] for k in ('symbol','cik','dossier_version')},
                    uncertainty='선택한 SEC 항목의 원래 관측치예요. 기간·단위·수정치를 합치지 않았고 정상화 이익이나 내재가치를 검증한 결과가 아니에요.')
            if tool in ('filing_search','filing_read'):fact['source']=result['raw_ref']['source']
            if tool=='company':fact['raw_refs']=[r for company in result['companies'] for r in company.get('raw_refs',[])]
            activated=self.activate(role,fact,market)
            if not activated:
                self.s.append('research_tool_result',{'role':role,'call':call,'result':result,'fact_id':None,'status':'archived_context_budget','budget':self.activation_budget},self.as_of,self.run_id)
                return {'status':'stored_not_activated','reason':'활성 자료 예산 한도. 자료 부재가 아니며 원본은 보존됐어요. 더 좁은 기업/본문/가치평가 요청을 사용해요.','budget':self.activation_budget,'fact_id':None}
        self.s.append('research_tool_result',{'role':role,'call':call,'result':result,'fact_id':fact['id'] if fact else None},self.as_of,self.run_id)
        return {'result':result,'fact_id':fact['id'] if fact else None}


def research_loop(s,model,role,guide,payload,run_id,as_of,library):
    """Model chooses typed tools. Its final analysis sees receipts and cited returned facts."""
    if role not in ('evidence','buffett','marks','bogle','wood','validation') or model.mode!='live':return payload
    if as_of!=library.today or payload.get('frozen_revision'):
        payload['research_access']={'status':'frozen_snapshot','rule':'당시 고정 근거만 사용. 최신 자료 소급 수집 불가.'};return payload
    contract=json.loads(resource('contracts/research-plan.schema.json').read_text());toolguide=resource('guides/roles/company-tools.md').read_text()
    from .contracts import validate
    from .decision_calibration import enabled,validate_knowledge
    if enabled(model):contract['required']=list(dict.fromkeys(contract['required']+['knowledge_feedback']))
    runner=ResearchTools(library,s,run_id,as_of);transcript=[];collected=0
    from .research_progress import Progress
    progress=Progress();extensions=[];completed_rounds=0;planning_feedback=None;repair_used=False;repair_pending=False
    questions=(payload.get('decision_scope') or {}).get('questions',[])
    question_ids={q['id'] for q in questions}
    stop_reason='round_budget';stop_detail='8 research rounds reached'
    def record_stop(reason,detail):
        s.append('research_stop',{'role':role,'stage':payload.get('analysis_stage'),'reason':reason,'detail':detail,
            'question_ids':sorted(question_ids),'calls':len(transcript),'sufficiency':'requires_independent_review',
            'extensions':extensions,'reading_progress':progress.history},as_of,run_id)
    for round_no in range(8):
        if round_no>=4:
            extension='one_contract_shape_repair' if repair_pending else progress.extend()
            if not extension:
                stop_reason='no_recent_source_progress';stop_detail='No new delivered source range/observation or unused discovery-to-read bridge';break
            extensions.append({'round':round_no+1,'reason':extension})
        repair_pending=False
        completed_rounds=round_no+1;round_progress=[]
        prior_review=(payload.get('improvement') or payload.get('external_review') or {}).get('feedback',{})
        analysis=payload.get('analysis',{});comparison=analysis.get('comparison',{})
        from .planner_evidence import overview
        from .thesis_workspace import build as thesis_workspace
        request={'thesis_workspace':thesis_workspace(payload,role),'role':role,'as_of':as_of,'question':payload.get('question'),
            'knowledge':copy.deepcopy(payload.get('knowledge',{})),
            'research_feedback_history':copy.deepcopy(payload.get('research_feedback_history')),
            'knowledge_policy':'전달된 지식마다 knowledge_feedback에 적용/검토/미적용/재검증과 구체적인 도구 선택 영향을 기록해요. 이력과 회고는 절차 근거이며 현재 시장의 독립 증거가 아니에요. 낡은 사실은 재검증 전 적용하지 않아요.',
            'evidence_assignments':copy.deepcopy(payload.get('evidence_assignments',[])),
            'shared_research_policy':'같은 research_group은 기간·단위·기준이 일치하는 조사 대상이에요. 검색/원문 독해를 공유하고 각 request_id의 수용 조건은 별도로 답하세요. 그룹이 다르면 합치지 않아요. 배정 실패는 부정 근거가 아니에요.',
            'evidence_feedback':copy.deepcopy(payload.get('evidence_feedback',[])),
            'assignment_policy':'각 요청에 맞는 원문과 기존 근거를 읽고 부족하면 더 조사해요. 확보는 분석 충분성이나 매수 승인이 아니며 경제적 가정 선택은 요청자가 재검토해요.',
            'execution_boundary':'외부 브라우저·쉘 도구를 직접 실행하지 않아요. 이 계약의 calls 배열에 조사 요청을 반환하는 것은 허용돼요. Mara가 허용 도구를 실행하고 다음 입력에 결과를 전달해요.',
            'planning_feedback':copy.deepcopy(planning_feedback),
            'research_capabilities':'mara.research-tools/1.2','decision_questions':questions,'objective':payload.get('profile',{}).get('goal'),'available_symbols':list(payload['market'].get('assets',{})),
            'prior_review':{k:copy.deepcopy(prior_review[k]) for k in ('criteria','gates','coverage','deterministic_findings','instruction') if k in prior_review},
            'available_analysis':{'comparison_available':comparison.get('available',False),
                'independent_replay':copy.deepcopy(comparison.get('independent_replay',{})),
                'comparison_period':{k:comparison[k] for k in ('start','end','observations','currency','frequency') if k in comparison},
                'products':list(analysis.get('products',{})),
                'published_costs_available':analysis.get('costs',{}).get('published_conditions_and_examples',{}).get('available',False),
                'rule':'이미 전달 가능한 계산과 부족한 자료를 구분. 원문을 읽어야 하는 주장은 적합한 기업/본문 도구로 확인.'},
            'analysis_paths':['/analysis/'+k.replace('~','~0').replace('/','~1') for k in analysis],
            'personal_context':{k:copy.deepcopy(payload[k]) for k in ('funding','decision_context') if k in payload},
            'market_prices':{'currency':payload['market'].get('base_currency'),'quotes':payload['market'].get('prices',{}),
                'rule':'기준통화 환산 가격. USD 가치 계산에는 company 도구의 원래 USD quote를 사용.'},
            'existing_evidence':[{'id':f['id'],'topic':f['topic'],'source':f['source'],
                'characters':len(dumps(f)),'read_with':'evidence_read'} for f in payload['market']['facts']],
            'evidence_overview':overview(s,payload,run_id,role),
            'research_results':transcript,'round':round_no+1,'max_rounds':8,'collected_this_call':collected,
            'research_budget':{'base_rounds':4,'hard_max_rounds':8,'extensions':extensions,
                'recent_progress':progress.history[-2:],'rule':'After four rounds, continue only with new delivered source ranges/observations tied to the original questions. One discovery-to-read bridge is allowed. Repeated failures, pages, mere fact IDs and unactivated results do not establish progress or analytical sufficiency.'}}
        plan_input_id=s.append('research_plan_input',{'role':role,'guide':guide+'\n'+toolguide,'contract':contract,'payload':request,
            'provider':model.identity},as_of,run_id)
        plan=model.complete(role,guide+'\n'+toolguide,request,contract)
        plan_output_id=s.append('research_plan_output',{'role':role,'input_id':plan_input_id,'output':plan},as_of,run_id)
        try:
            validate(plan,contract)
            if enabled(model):validate_knowledge(plan.get('knowledge_feedback',[]),payload)
            if any(not set(c.get('question_ids',[]))<=question_ids for c in plan['calls']):raise ValueError('Unknown decision question')
            if questions and any(not c.get('question_ids') and not c.get('discovery_reason','').strip() for c in plan['calls']):raise ValueError('Question or explicit discovery reason required')
        except ValueError as error:
            s.append('research_tool_failure',{'role':role,'call':{'tool':'plan'},'result':{'status':'invalid_plan','output':plan}},as_of,run_id)
            diagnostics=[str(error)[:1000]]
            if isinstance(plan,dict) and isinstance(plan.get('calls'),list):
                for i,call in enumerate(plan['calls']):
                    if not isinstance(call,dict):continue
                    option=next((v for v in contract['properties']['calls']['items']['oneOf'] if v['properties']['tool'].get('const')==call.get('tool')),None)
                    if option:
                        try:validate(call,option,'$.calls['+str(i)+']')
                        except ValueError as detail:diagnostics.append(str(detail)[:1000])
            if not repair_used and round_no<7:
                repair_used=True;repair_pending=True
                planning_feedback={'code':'invalid_plan','errors':diagnostics[:4],'previous_plan':plan,
                    'instruction':'이 계획의 도구는 아직 실행하지 않았어요. 형식·질문 ID 오류를 한 번 교정하여 전체 계획을 다시 반환하세요. hash/ID/기간/단위를 추측하지 말고 실제 입력의 값을 그대로 사용하세요. 필요한 값을 확인할 수 없으면 읽기부터 요청하거나 공백을 명시하세요. 이것은 계약 교정이며 새 근거나 분석 완료가 아니에요.'}
                s.append('research_planning_feedback',{'role':role,'round':round_no+1,'feedback':planning_feedback},as_of,run_id)
                progress.finish_round([])
                continue
            record_stop('invalid_plan','Plan or question reference rejected')
            payload['research_access']={'status':'invalid_plan','planning_repairs':int(repair_used),'last_plan_errors':diagnostics[:4],
                'limits':'추가 조사 계획이 계약 검증에 실패했어요. 기존 근거만으로 판단하고 공백을 명시해요. 자료 부재와 도구 요청 형식 실패를 구분해요.'}
            return payload
        if planning_feedback and planning_feedback.get('code')=='invalid_plan':planning_feedback=None
        s.append('research_plan',{'role':role,'plan':plan,'provider':model.identity,'round':round_no+1},as_of,run_id)
        if not plan['calls'] and round_no==0 and plan.get('stop_reason')=='capability_gap' and request['existing_evidence']:
            planning_feedback={'code':'check_readable_payload_before_capability_stop',
                'rule':'existing_evidence는 현재 payload에서 evidence_read로 읽을 수 있는 fact ID 목록이에요. 등록된 내용이 목록·요약·발췌·역할 투영일 수도 있어 필요한 공시 전문이 있다는 뜻은 아니에요. 필요한 자료와 연결되는 ID를 읽거나, 현재 도구로 해결할 수 없는 이유를 구분해 다시 계획해요. 외부 도구 금지는 JSON calls 반환 금지가 아니에요. 그래도 자료·분석 역량이 부족하면 capability_gap으로 종료할 수 있어요.',
                'original_reason':plan['reason'],'remaining_base_rounds_at_feedback':3,
                'scope':'한 번의 계획 재검토이며 새 자료·충분성·주장 지지를 뜻하지 않아요.'}
            s.append('research_planning_feedback',{'role':role,'round':1,'feedback':planning_feedback},as_of,run_id)
            progress.finish_round([])
            continue
        s.append('research_plan_accepted',{'role':role,'input_id':plan_input_id,'output_id':plan_output_id,'knowledge_feedback':plan.get('knowledge_feedback',[])},as_of,run_id)
        if not plan['calls']:
            stop_reason=plan.get('stop_reason','planner_stopped_unspecified');stop_detail=plan['reason'];break
        for call in plan['calls']:
            before_ids={f['id'] for f in payload['market']['facts']}
            try:
                if call['tool']=='collect':
                    collected+=len(call['arguments'].get('symbols',[]))
                    if collected>200:raise ValueError('200 company collection budget reached')
                if call['tool'] in ('evidence_read','analysis_read'):
                    from .research_read import read
                    result=read(payload,call)
                    answer={'result':result,'fact_id':None}
                    s.append('research_tool_result',{'role':role,'call':call,'result':result,'fact_id':None},as_of,run_id)
                else:answer=runner.execute(role,call,payload['market'])
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                answer={'status':'unavailable','reason':safe_code(exc),'action':'Reduce scope or use already frozen evidence; never invent data'}
                if isinstance(exc,src.EvidenceError) and getattr(exc,'attempts',None):answer['source_attempts']=exc.attempts
                s.append('research_tool_failure',{'role':role,'call':call,'result':answer},as_of,run_id)
            source_fact=next((f for f in payload['market']['facts'] if f['id']==call['arguments'].get('fact_id')),None) if call['tool']=='evidence_read' else None
            observed_progress=progress.observe(call,answer,[f for f in payload['market']['facts'] if f['id'] not in before_ids],source_fact)
            round_progress.append(observed_progress)
            receipts=answer.get('result',{}).get('receipts',[])
            failures=[r for r in receipts if r.get('status')=='unavailable']
            s.append('research_activity',{'role':role,'question_ids':call.get('question_ids',[]),'discovery_reason':call.get('discovery_reason'),
                'tool':call['tool'],'target':call['arguments'].get('symbol',call['arguments'].get('symbols',call['arguments'].get('fact_id',call['arguments'].get('path')))),
                'status':answer.get('status','returned'),'fact_id':answer.get('fact_id'),
                'source_status':('collection_failed' if len(failures)==len(receipts) else 'collection_partial') if failures else answer.get('result',{}).get('status'),
                'reason':answer.get('reason'),'collection_failures':failures,
                'sufficiency':'not_reviewed','reading_progress':observed_progress},as_of,run_id)
            transcript.append({'call':call,'answer':answer})
        progress.finish_round(round_progress)
        if len(dumps(transcript))>65000:
            stop_reason='transcript_budget';stop_detail='Research transcript reached bounded input limit';break
    record_stop(stop_reason,stop_detail)
    payload['research_access']={'status':'executed','stop_reason':stop_reason,'sufficiency':'requires_independent_review','rounds':completed_rounds,'calls':len(transcript),'planning_repairs':int(repair_used),
            'extensions':extensions,'reading_progress':progress.history,
            'limits':'기본 4회, 자료를 새로 읽으면 최대 8회 조사. 새 목록에서 읽기로 넘어갈 기회는 한 번 허용. 최대 200기업 수집, 페이지 20개. 보충 근거는 이전 실행에서 이어온 자료를 포함해 최대 368,000자예요. 남은 공간을 공통/역할별로 배분하며 실제 몫은 budget 응답에 있어요. 원본과 전문은 별도 보존하며 미수집·미독해·보관만 된 자료를 명시.'}
    return payload
