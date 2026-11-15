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


def symbol(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',value):raise ValueError('Invalid symbol')
    return value.replace('.','-')


class FilingText(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.parts=[]
    def handle_starttag(self,t,a):
        if t in ('script','style','ix:header'):self.hidden+=1
        if t in ('p','div','tr','h1','h2','h3','br'):self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style','ix:header'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,s):
        if not self.hidden:self.parts.append(s)
    def text(self):return re.sub(r'[ \t]+',' ',''.join(self.parts))


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
    if set(a)!=required or a['currency']!='USD':raise ValueError('Explicit USD per-share valuation inputs required')
    if not a['source_ids'] or not set(a['source_ids'])<=known_ids:raise ValueError('Valuation needs supplied evidence references')
    if not all(isinstance(a[k],str) and a[k].strip() for k in ('earnings_period','share_basis','normalization')):raise ValueError('Normalization and share basis required')
    if day(a['price_as_of'])>day(as_of) or (day(as_of)-day(a['price_as_of'])).days>10:raise ValueError('Price is future or stale')
    earn=src.finite(a['owner_earnings_per_share'],.000001);price=src.finite(a['price'],.000001);mos=src.finite(a['margin_of_safety'],0,.9)
    if len(a['scenarios'])!=3 or {s.get('name') for s in a['scenarios']}!={'bear','base','bull'}:raise ValueError('Three distinct scenarios required')
    values=[]
    for s in a['scenarios']:
        if set(s)!={'name','growth','discount','terminal_growth','years','reason'} or not isinstance(s['reason'],str) or not s['reason'].strip():raise ValueError('Scenario assumptions required')
        g=src.finite(s['growth'],-.5,.5);r=src.finite(s['discount'],.01,.5);t=src.finite(s['terminal_growth'],-.05,.1);n=s['years']
        if type(n)!=int or not 1<=n<=20 or t>=r:raise ValueError('Discount must exceed terminal growth; horizon 1..20')
        flows=sum(earn*(1+g)**i/(1+r)**i for i in range(1,n+1));terminal=earn*(1+g)**n*(1+t)/(r-t)/(1+r)**n
        value=flows+terminal
        values.append(dict(s,value_per_share=value,price_margin=1-price/value,buy_ceiling=value*(1-mos),terminal_value_fraction=terminal/value))
    return {'method':'discounted normalized owner earnings per share; analyst assumptions, not observed fair value',
        'assumptions':a,'scenarios':values,'formula':'sum(E*(1+g)^t/(1+r)^t,t=1..N)+E*(1+g)^N*(1+terminal)/(r-terminal)/(1+r)^N',
        'limits':'정상화와 주당/분할 기준은 분석자의 명시 가정. 자동 검증된 가치 아님. 부채를 다시 차감하지 않는 equity per-share 모델. 기업가치 FCFF/WACC와 혼용 금지. 음수 이익·은행/보험 등에는 적합한 별도 방법 필요.'}


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
                    if old and old['known_at']==as_of:receipts.append({'symbol':ticker,'status':'cached','version':old['version']});continue
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
                    body={'symbol':ticker,'cik':cik,'entity':sub['name'],'known_at':as_of,'retrieved_at':fmeta['retrieved_at'],
                        'financials':fin,'quality':quality(fin),'filings':filings,'annual_filing':annual,'raw_refs':[submeta,fmeta],
                        'coverage':'annual standard US GAAP; no independent moat or intrinsic value assertion'}
                    body['version']=hashlib.sha256(dumps(body).encode()).hexdigest()
                    folder=self.root/'companies'/ticker;folder.mkdir(parents=True,exist_ok=True)
                    p=folder/(body['version']+'.json');p.write_text(dumps(body));p.chmod(0o600)
                    receipts.append({'symbol':ticker,'status':'collected','version':body['version']})
                except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:receipts.append({'symbol':ticker,'status':'unavailable','reason':safe_code(exc)})
                finally:progress({'done':i+1,'total':len(tickers),'latest':receipts[-1]})
        return {'receipts':receipts,'identity_coverage':coverage,'requested':len(tickers),'completed':sum(r['status']!='unavailable' for r in receipts),
            'read_policy':'Collected does not mean read. compare returns pages; company returns selected dossiers.'}

    def filing_search(self,ticker,query,as_of):
        body=self.latest(ticker,as_of)
        if not body or not body['annual_filing']:raise ValueError('Annual filing unavailable')
        filing=body['annual_filing'][0]
        if as_of!=self.today:raise ValueError('Historical filing text must already be in original run evidence')
        fallback=None
        try:raw,meta=self.archive().get(filing['url'])
        except (OSError,ValueError):
            fallback=json.loads(resource('resources/issuer-documents.json').read_text())['documents'].get(symbol(ticker))
            if not fallback or not 0<=(day(as_of)-day(fallback['verified_on'])).days<=180:raise ValueError('SEC document unavailable; no current verified issuer fallback') from None
            raw,meta=self.archive().get(fallback['url'])
        p=FilingText();p.feed(raw.decode('utf-8',errors='replace'));text=p.text()
        hits=[];terms=[x.strip() for x in query.split('|') if x.strip()][:6]
        for term in terms:
            for match in list(re.finditer(re.escape(term),text,re.I))[:3]:
                start=max(0,match.start()-250);end=min(len(text),match.end()+1400)
                hits.append({'query':term,'start':start,'end':end,'excerpt':text[start:end]})
                if len(hits)>=5:break
            if len(hits)>=5:break
        return {'symbol':ticker,'filing':filing,'issuer_fallback':fallback,'raw_ref':meta,'hits':hits,'text_length':len(text),
            'limits':'키워드 주변 발췌이며 문서 전체 독해 아님. SEC 발행사 진술을 독립 검증 사실과 구분. 위치는 추출된 텍스트 문자 기준.'}


class ResearchTools:
    def __init__(self,library,session,run_id,as_of):self.lib,self.s,self.run_id,self.as_of=library,session,run_id,as_of

    def activate(self,role,fact,market):
        existing={e['body']['fact']['id']:e['body']['fact'] for e in self.s.events('research_evidence') if e['run_id']==self.run_id}
        if fact['id'] in existing:
            if fact['id'] not in {f['id'] for f in market['facts']}:market['facts'].append(copy.deepcopy(existing[fact['id']]))
            return True
        # Original dossiers/raw/tool receipts remain stored even when active context is full.
        if sum(len(dumps(f)) for f in existing.values())+len(dumps(fact))>80000:return False
        if fact['id'] not in {f['id'] for f in market['facts']}:
            market['facts'].append(fact);self.s.append('research_evidence',{'role':role,'fact':fact},self.as_of,self.run_id)
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
                for kind,value in [('sec_financials',company['financials']),('sec_filings',company['filings'])]:
                    fid='company-'+kind+'-'+company['version'][:24]
                    fact={'id':fid,'topic':company['symbol']+' · '+kind,'text':dumps(value),
                        'source':company['raw_refs'][1 if kind=='sec_financials' else 0]['source'],
                        'published_at':value.get('latest_filed') or max(f['filed'] for f in value['filings']),
                        'known_at':self.as_of,'valid_until':self.as_of,'uncertainty':value['limits'],'research_tool':kind,
                        'company_identity':{'symbol':company['symbol'],'cik':company['cik'],'version':company['version'],'verification':'SEC submissions ticker match'},
                        'raw_refs':company['raw_refs']}
                    self.activate(role,fact,market)
        elif tool=='filing_search':result=self.lib.filing_search(args['symbol'],args['query'],self.as_of)
        elif tool=='valuation':
            a=args['assumptions'];quotes=[]
            for fact in market['facts']:
                if fact['id'] not in a.get('source_ids',[]) or fact.get('research_tool')!='company_company':continue
                for company in json.loads(fact['text']).get('companies',[]):
                    if company.get('symbol')==symbol(args['symbol']) and company.get('quote'):quotes.append(company['quote'])
            if not any(q['currency']=='USD' and q['price']==a.get('price') and q['observed_at']==a.get('price_as_of') for q in quotes):raise ValueError('Valuation price must match cited company USD quote')
            result=owner_value(a,{f['id'] for f in market['facts']},self.as_of)
        else:raise ValueError('Unknown research tool')
        # Receipts and discovery results are not financial evidence.
        fact=None
        if tool in ('compare','company','filing_search','valuation'):
            ident='company-'+hashlib.sha256(dumps(result).encode()).hexdigest()[:24]
            fact={'id':ident,'topic':tool+' · '+args.get('symbol',','.join(args.get('symbols',[])[:5])),
                'text':dumps(result),'source':'https://www.sec.gov/search-filings/edgar-application-programming-interfaces',
                'published_at':self.as_of,'known_at':self.as_of,'valid_until':self.as_of,
                'uncertainty':'분석자 가정 계산' if tool=='valuation' else 'SEC 표준 재무/발행사 진술. 상세 기간·공시일은 본문에 포함.',
                'research_tool':'company_'+tool}
            if tool=='filing_search':fact['raw_refs']=[result['raw_ref']]
            if tool=='filing_search':fact['source']=result['raw_ref']['source']
            if tool=='company':fact['raw_refs']=[r for company in result['companies'] for r in company.get('raw_refs',[])]
            activated=self.activate(role,fact,market)
            if not activated:
                self.s.append('research_tool_result',{'role':role,'call':call,'result':result,'fact_id':None,'status':'archived_context_budget'},self.as_of,self.run_id)
                return {'status':'stored_not_activated','reason':'실행 전체 추가 근거 80,000자 한도. 원본 수집은 보존됐어요. 더 작은 compare 페이지/본문 검색을 요청하거나 다음 실행에서 우선 조회해요.','fact_id':None}
        self.s.append('research_tool_result',{'role':role,'call':call,'result':result,'fact_id':fact['id'] if fact else None},self.as_of,self.run_id)
        return {'result':result,'fact_id':fact['id'] if fact else None}


def research_loop(s,model,role,guide,payload,run_id,as_of,library):
    """Model chooses typed tools. Its final analysis sees receipts and cited returned facts."""
    if role not in ('evidence','buffett','marks','bogle','validation') or model.mode!='live':return payload
    if as_of!=library.today or payload.get('frozen_revision'):
        payload['research_access']={'status':'frozen_snapshot','rule':'당시 고정 근거만 사용. 최신 자료 소급 수집 불가.'};return payload
    contract=json.loads(resource('contracts/research-plan.schema.json').read_text());toolguide=resource('guides/roles/company-tools.md').read_text()
    from .contracts import validate
    runner=ResearchTools(library,s,run_id,as_of);transcript=[];collected=0
    for round_no in range(4):
        request={'role':role,'as_of':as_of,'question':payload.get('question'),
            'objective':payload.get('profile',{}).get('goal'),'available_symbols':list(payload['market'].get('assets',{})),
            'market_prices':{'currency':payload['market'].get('base_currency'),'quotes':payload['market'].get('prices',{}),
                'rule':'기준통화 환산 가격. USD 가치 계산에는 company 도구의 원래 USD quote를 사용.'},
            'existing_evidence':[{'id':f['id'],'topic':f['topic']} for f in payload['market']['facts']],
            'research_results':transcript,'round':round_no+1,'max_rounds':4,'collected_this_call':collected}
        s.append('research_plan_input',{'role':role,'guide':guide+'\n'+toolguide,'contract':contract,'payload':request,
            'provider':model.identity},as_of,run_id)
        plan=model.complete(role,guide+'\n'+toolguide,request,contract)
        try:validate(plan,contract)
        except ValueError:
            s.append('research_tool_failure',{'role':role,'call':{'tool':'plan'},'result':{'status':'invalid_plan','output':plan}},as_of,run_id)
            payload['research_access']={'status':'invalid_plan','limits':'추가 조사 계획이 계약 검증에 실패했어요. 기존 근거만으로 판단하고 공백을 명시해요.'}
            return payload
        s.append('research_plan',{'role':role,'plan':plan,'provider':model.identity,'round':round_no+1},as_of,run_id)
        if not plan['calls']:break
        for call in plan['calls']:
            try:
                if call['tool']=='collect':
                    collected+=len(call['arguments'].get('symbols',[]))
                    if collected>200:raise ValueError('200 company collection budget reached')
                answer=runner.execute(role,call,payload['market'])
            except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                answer={'status':'unavailable','reason':safe_code(exc),'action':'Reduce scope or use already frozen evidence; never invent data'}
                s.append('research_tool_failure',{'role':role,'call':call,'result':answer},as_of,run_id)
            transcript.append({'call':call,'answer':answer})
        if len(dumps(transcript))>65000:break
    payload['research_access']={'status':'executed','rounds':round_no+1,'calls':len(transcript),
            'limits':'최대 4라운드/200기업 수집, 페이지 20개. 실행 전체 추가 활성 근거 80,000자. 원본과 전문은 별도 보존하며 미수집·미독해·보관만 된 자료를 명시.'}
    return payload
