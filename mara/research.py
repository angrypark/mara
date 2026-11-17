"""Bounded, read-only market tools used by the R2 collection stage.

Original responses are content-addressed and never pruned with active knowledge.
Only public market data enters the shared pack; no account/credential/profile is sent.
"""
import copy
import hashlib
import json
import os
import re
import time
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from . import research_sources as src
from . import domain as d
from .toss import BrokerError
from .contracts import validate,schema
from .registry import resource
from .decision import POLICY
from . import commentary_sources as commentary
from . import fund_history,policy_sources,fx_history

VERSION='mara.research/1.0.0'
TOOLS=[
 {'id':'fx_history','label':'원화·달러 월말 환율 이력','roles':['evidence','marks','bogle','validation','leader'],'provides':'FRED/연준 H.10 일별 원/달러의 월말 마지막 유효 관측. 원화 배분 비교와 실제 계좌 환율을 구분'},
 {'id':'release_notes','label':'검증된 공식 발표 보충','roles':['evidence','marks','validation'],'provides':'원문을 직접 대조한 발표 수치·결측 사유와 읽은 범위. 유효 기간 이후 자동 제외'},
 {'id':'fed_statement','label':'FOMC 정책 성명 본문','roles':['evidence','marks','validation','leader'],'provides':'공식 목록의 최신 성명 날짜·정책 본문·반대 의견. RSS 제목과 구분'},
 {'id':'fund_history','label':'ETF 월별 NAV 총수익률','roles':['bogle','marks','validation','leader'],'provides':'운용사 원본 XLS 월별 배당 재투자 NAV 총수익률. 비용 포함 정의·기간을 검증하고 별도 계산에 사용'},
 {'id':'sec_filings','label':'SEC 공시 목록','roles':['evidence','buffett','marks','validation'],'provides':'최근 공시 종류·공시일·원문 링크; 본문 미수집'},
 {'id':'sec_financials','label':'SEC 기업 재무','roles':['buffett','marks','validation'],'provides':'최대 3개 연간 기간의 매출·이익·영업현금·설비투자, 최근 현금·부채·자산·자본'},
 {'id':'treasury','label':'미국 국채 금리','roles':['evidence','marks','validation'],'provides':'최근 6거래일 만기별 par 금리와 장단기 차이'},
 {'id':'bls','label':'미국 물가·고용','roles':['evidence','marks','validation'],'provides':'CPI와 실업률, 최대 14개월 관측'},
 {'id':'fed','label':'연준 정책 발표','roles':['evidence','marks','validation'],'provides':'최근 공식 발표 RSS 제목·요약·날짜·원문'},
 {'id':'fund_profile','label':'ETF 상품·보수','roles':['bogle','validation'],'provides':'지원 ETF 운용사 투자목적·추종지수·보수'},
 {'id':'fund_holdings','label':'ETF 내부 구성','roles':['bogle','validation'],'provides':'지원 ETF 전체 구성 원문 보존, 상위 10개 및 섹터 합계'},
 {'id':'candles','label':'가격 이력·거래량','roles':['evidence','marks','validation'],'provides':'최대 80 수정 일봉에서 5/20/60 거래일 가격변화·평균 거래량'},
 {'id':'orderbook','label':'관측 호가','roles':['marks','validation'],'provides':'관측시각의 최우선 호가·스프레드; 체결 보장 아님'},
 {'id':'institutional_reports','label':'금융기관 주간 논평','roles':['evidence','marks','validation'],'provides':'BlackRock·Schwab 원문 HTML과 날짜·제목·도입부 발췌; 기관 전망'},
 {'id':'financial_news','label':'금융 언론 뉴스 탐색','roles':['evidence','marks','validation'],'provides':'CNBC 공식 RSS 최근 제목·발표시각·기사 링크; 본문 미검토'},
]
ALLOWED={'s201.q4cdn.com','investor.nvidia.com','cdn-dynmedia-1.microsoft.com','microsoft.gcs-web.com','www.invesco.com','dng-api.invesco.com','www.ssga.com','am.jpmorgan.com','fred.stlouisfed.org','d18rn0p25nwr6d.cloudfront.net','materials.proxyvote.com','www.bls.gov','www.sec.gov','data.sec.gov','www.ishares.com','www.federalreserve.gov','api.bls.gov','home.treasury.gov','www.blackrock.com','www.schwab.com','www.cnbc.com','www.microsoft.com','www.apple.com'}


def digest(raw):return hashlib.sha256(raw).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise src.EvidenceError('source_redirect_requires_verification')


class PublicArchive:
    def __init__(self,root,now=None,transport=None,clock=None):
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.now=now or datetime.now(timezone.utc);self.transport=transport
        self.requests=0;self.started=time.monotonic();self.last_sec=0

    def preserve(self,body,url):
        raw=body.encode() if isinstance(body,str) else body
        sha=digest(raw);target=self.root/(sha+'.raw')
        try:
            fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f:f.write(raw)
        except FileExistsError:
            if digest(target.read_bytes())!=sha:raise ValueError('Archive hash mismatch')
        return {'sha256':sha,'source':url,'retrieved_at':self.clock().isoformat(),'bytes':len(raw)}

    def get(self,url):
        u=urllib.parse.urlsplit(url)
        if u.scheme!='https' or u.hostname not in ALLOWED or u.port not in (None,443) or u.username or u.password:
            raise ValueError('Unapproved public source')
        key=digest(url.encode());cache=self.root/(key+'.cache.json')
        try:
            meta=json.loads(cache.read_text());age=(self.clock()-datetime.fromisoformat(meta['retrieved_at'])).total_seconds()
            raw=(self.root/(meta['sha256']+'.raw')).read_bytes()
            if 0<=age<21600 and digest(raw)==meta['sha256'] and meta['source']==url:
                return raw,dict(meta,cache_hit=True)
        except (OSError,KeyError,ValueError):pass
        if self.requests>=48 or time.monotonic()-self.started>150:raise TimeoutError('Research budget')
        self.requests+=1
        if u.hostname.endswith('sec.gov'):
            time.sleep(max(0,.55-(time.monotonic()-self.last_sec)));self.last_sec=time.monotonic()
        if self.transport:raw=self.transport(url)
        else:
            # FRED's CSV endpoint accepts urllib's standard client header; the
            # custom research header repeatedly stalls this endpoint. SEC retains
            # the explicit application identity on all requests.
            headers={} if u.hostname=='fred.stlouisfed.org' else {'User-Agent':'MaraResearch/1.0 personal investment research'}
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.build_opener(NoRedirect).open(req,timeout=30 if u.hostname=='fred.stlouisfed.org' else 10) as response:raw=response.read(8_000_001)
        if len(raw)>8_000_000:raise ValueError('Research response too large')
        meta=self.preserve(raw,url)
        # Cache is replaceable; original content-addressed responses are not.
        temp=cache.with_suffix('.tmp');temp.write_text(d.dumps(meta));temp.chmod(0o600);temp.replace(cache)
        return raw,dict(meta,cache_hit=False)


def safe_code(exc):
    from .document_text import ExtractionError
    if isinstance(exc,ExtractionError):return exc.code
    if isinstance(exc,src.EvidenceError):return exc.code
    if isinstance(exc,(json.JSONDecodeError,src.ET.ParseError,zipfile.BadZipFile)):return 'source_format_changed'
    if isinstance(exc,(KeyError,TypeError,AttributeError)):return 'source_structure_changed'
    if isinstance(exc,StopIteration):return 'required_source_field_missing'
    if isinstance(exc,TimeoutError):return 'time_budget_or_timeout'
    if isinstance(exc,urllib.error.HTTPError):return 'http_'+str(exc.code)
    if isinstance(exc,urllib.error.URLError):return 'network_unavailable'
    return 'unsupported_or_invalid_data'


class Research:
    def __init__(self,root,now=None,transport=None):
        self.archive=PublicArchive(root,now,transport);self.now=self.archive.now
        self.as_of=self.now.date().isoformat();self.calls=[];self.facts=[];self.records=[]
        self.urls={};self.used_chars=0;self.constituents={}

    def fetch(self,url):
        raw,meta=self.archive.get(url);self.records.append(meta);self.urls[url]=meta
        return raw.decode('utf-8-sig')

    def record(self,tool,target,fn,source,ttl=7):
        call={'tool':tool,'target':target,'status':'failed','fact_ids':[],'raw_refs':[]}
        start=len(self.records)
        try:
            if time.monotonic()-self.archive.started>180:
                call.update(status='skipped',reason='collection_time_budget');return None
            value=fn()
            if not isinstance(value,dict):raise ValueError('Research output must be an object')
            if tool=='orderbook' and value.get('availability')=='no_quote':
                call.update(status='skipped',reason='quote_not_observed');return None
            if tool=='fund_holdings':
                self.constituents[target]=value.pop('constituents',[])
            if tool=='sec_financials':
                # Lossless table encoding avoids repeating six field names on every
                # observation; periods, accessions and forms remain in the fact.
                columns=['start','end','filed','value','accession','form']
                value['observation_columns']=columns
                for series in value['metrics'].values():
                    for entry in series:entry['observations']=[[row.get(k) for k in columns] for row in entry['observations']]
            text=d.dumps(value)
            if tool=='sec_financials' and self.used_chars+len(text)>140000:
                call.update(status='skipped',reason='financial_evidence_budget');return None
            if self.used_chars+len(text)>160000:
                call.update(status='skipped',reason='active_evidence_budget');return None
            fact_id='research-'+tool+'-'+re.sub('[^A-Za-z0-9_-]','-',target)
            published=value.get('latest_filed') or value.get('observed_at') or self.as_of
            if tool=='sec_filings':published=max(x['filed'] for x in value['filings'])
            if tool=='fed':published=max(x['published_at'] for x in value['items'])
            if tool=='treasury':published=value['observations'][0]['date']
            d.day(published)
            if published>self.as_of:raise ValueError('Future research publication')
            self.facts.append({'id':fact_id,'topic':target+' · '+next(x['label'] for x in TOOLS if x['id']==tool),
                'text':text,'source':source,'published_at':published,'known_at':self.as_of,
                'valid_until':(d.day(self.as_of)+timedelta(days=ttl)).isoformat(),
                'uncertainty':value.get('limits',''),'research_tool':tool,
                'raw_refs':copy.deepcopy(self.records[start:])})
            self.used_chars+=len(text)
            call.update(status='collected',fact_ids=[fact_id],reason='검증된 요약을 분석 입력에 포함했어요.')
            return value
        except (OSError,ValueError,KeyError,TypeError,IndexError,StopIteration,ArithmeticError,BrokerError,src.ET.ParseError,AttributeError,zipfile.BadZipFile) as exc:
            call.update(reason=safe_code(exc));return None
        finally:
            call['raw_refs']=copy.deepcopy(self.records[start:]);self.calls.append(call)

    def release_notes(self):
        notes=json.loads(resource('resources/official-release-notes.json').read_text())['notes']
        for note in notes:
            if not note['verified_on']<=self.as_of<=note['valid_until']:continue
            def read(n=note):
                self.records.append(self.archive.preserve(d.dumps(n),n['source']))
                return dict(n,observed_at=n['published_at'],retrieval_method='manually verified official text extract; not complete HTML')
            self.record('release_notes',note['id'],read,note['source'],(d.day(note['valid_until'])-d.day(self.as_of)).days)

    def exchange_history(self,market):
        history={};url=fx_history.url(self.as_of)
        def summary():
            history.update(fx_history.parse(self.fetch(url).encode(),self.as_of))
            return {**{k:v for k,v in history.items() if k!='observations'},
                'start':history['observations'][0]['date'],'end':history['observations'][-1]['date'],
                'observation_count':len(history['observations']),'latest_months':history['observations'][-3:]}
        if self.record('fx_history','DEXKOUS',summary,url,14):
            history['raw_refs']=copy.deepcopy(self.calls[-1]['raw_refs']);market['fx_history']=history

    def enrich(self,market,symbols,broker=None,progress=lambda msg:None):
        self.as_of=market['as_of']
        if self.as_of!=self.now.astimezone().date().isoformat() and self.as_of!=self.now.date().isoformat():
            raise ValueError('Collect current evidence only; reuse frozen snapshots for history')
        # Preserve supplied order: actual holdings first, followed by the candidate screen.
        all_symbols=list(dict.fromkeys(symbols))
        selected=[s for s in all_symbols if market['assets'][s].get('kind') in {'STOCK','FOREIGN_STOCK','DEPOSITARY_RECEIPT','REIT'}][:8]
        funds=[s for s in src.FUNDS if s in all_symbols or s in ('ITOT','IVV')]
        # Comparison research only; this does not add a tradable asset or user candidate.
        progress('공식 거시 지표와 정책 발표를 수집하고 있어요.')
        treasury_url=f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{self.as_of[:4]}/all?type=daily_treasury_yield_curve&field_tdr_date_value={self.as_of[:4]}&page&_format=csv'
        self.record('treasury','US',lambda:src.treasury(self.fetch(treasury_url),self.as_of),treasury_url)
        for series in ('CUSR0000SA0','LNS14000000'):
            url='https://api.bls.gov/publicAPI/v1/timeseries/data/'+series
            self.record('bls',series,lambda u=url,s=series:src.bls(json.loads(self.fetch(u)),s,self.as_of),url)
        self.record('fed','US',lambda:src.fed_news(self.fetch(src.FED),self.as_of),src.FED,14)
        def policy_statement():
            url=policy_sources.discover_statement(self.fetch,self.as_of)
            result=policy_sources.statement(self.fetch(url),url,self.as_of);result['document_url']=url
            return result
        self.record('fed_statement','US',policy_statement,'https://www.federalreserve.gov/newsevents/pressreleases/'+self.as_of[:4]+'-press-fomc.htm',14)
        self.release_notes()
        if market['base_currency']=='KRW':self.exchange_history(market)
        progress('금융기관 주간 리포트와 공식 금융 뉴스 피드를 확인하고 있어요.')
        for name,config in commentary.REPORTS.items():
            url=config['url']
            self.record('institutional_reports',name,lambda u=url,n=name:commentary.report(self.fetch(u),n,self.as_of),url)
        self.record('financial_news','CNBC',lambda:commentary.news(self.fetch(commentary.NEWS),self.as_of,datetime.now(timezone.utc).isoformat()),commentary.NEWS,3)
        # Identity bootstrap is a dated SEC subset; every ticker must be reconfirmed
        # against live submissions. Never guess a CIK from a similar company name.
        seed=json.loads(resource('resources/sec-tickers.json').read_text())
        mapping={k.replace('.','-'):v for k,v in seed['tickers'].items()}
        identity_mode='dated_bootstrap_reconfirmed_by_submissions'
        try:
            live=json.loads(self.fetch(src.SEC_TICKERS))
            current={}
            for x in live.values():
                ticker=x.get('ticker');cik=x.get('cik_str')
                if isinstance(ticker,str) and re.fullmatch(r'[A-Z0-9.\-]{1,15}',ticker) and not isinstance(cik,bool) and re.fullmatch(r'[0-9]{1,10}',str(cik)) and int(cik)>0:
                    current[ticker.replace('.','-')]=int(cik)
            if not current:raise ValueError('No valid SEC identities')
            mapping=current
            identity_mode='current_SEC_ticker_map'
        except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
        market['return_histories']={}
        for symbol in funds:
            progress('ETF 운용사 상품·구성 확인 중: '+symbol)
            history_url=fund_history.export_url(symbol)
            history={}
            def history_summary(u=history_url,s=symbol):
                history.update(fund_history.monthly_returns(self.fetch(u),s,self.as_of))
                from .portfolio_comparison import metrics
                result={k:v for k,v in history.items() if k!='observations'}
                result.update(start=history['observations'][0]['date'],observations=len(history['observations']),
                    summary={k:v for k,v in metrics([x['return'] for x in history['observations']]).items() if k!='unit_wealth_path'})
                return result
            if self.record('fund_history',symbol,history_summary,history_url,14):
                history['raw_refs']=copy.deepcopy(self.calls[-1]['raw_refs'])
                market['return_histories'][symbol]=history
            url=src.FUNDS[symbol]
            profile=self.record('fund_profile',symbol,lambda u=url,s=symbol:src.fund_profile(self.fetch(u),s,self.as_of),url)
            if profile:
                profile_refs=copy.deepcopy(self.calls[-1]['raw_refs'])
                asset=market['assets'].get(symbol)
                if asset is not None:asset['expense_ratio']=profile['expense_ratio']
                if asset is not None:asset['expense_source']=url
                if asset is not None and profile['asset_class']=='Equity':asset['asset_class']='equity'
                def holdings(u=profile['holdings_url'],p=profile,refs=profile_refs):
                    raw=self.fetch(u)
                    issue=None
                    if p.get('net_assets'):
                        self.records.extend(refs)
                        from .fund_economic_exposure import holdings as economic
                        try:return economic(raw,p,self.as_of)
                        except (ValueError,KeyError,TypeError,StopIteration) as exc:issue=str(exc)[:200] if isinstance(exc,ValueError) else type(exc).__name__
                    result=src.fund_holdings(raw,self.as_of)
                    result['economic_exposure_issue']=issue or 'same_date_issuer_NAV_not_available'
                    return result
                self.record('fund_holdings',symbol,holdings,profile['holdings_url'])
                # The issuer's sector taxonomy cannot silently replace Toss's
                # user-selected exclusions; preserve unknown sector validation.
            else:
                self.calls.append({'tool':'fund_holdings','target':symbol,'status':'skipped','reason':'fund_profile_unavailable','fact_ids':[],'raw_refs':[]})
        from .additional_funds import collect,EXTRA
        collect(self,market,all_symbols)
        funds+=list(s for s in EXTRA if s in all_symbols)
        for symbol in selected:
            progress('기업 공시·재무 확인 중: '+symbol)
            cik=mapping.get(symbol.replace('.','-'))
            if cik is None and symbol=='BRK.A':cik=mapping.get('BRK-B') # live ticker validation still required
            if cik is None:
                self.calls.append({'tool':'sec_filings','target':symbol,'status':'skipped','reason':'SEC_identifier_unavailable','fact_ids':[],'raw_refs':[]})
                self.calls.append({'tool':'sec_financials','target':symbol,'status':'skipped','reason':'SEC_identifier_unavailable','fact_ids':[],'raw_refs':[]});continue
            url=f'https://data.sec.gov/submissions/CIK{int(cik):010d}.json'
            filings=self.record('sec_filings',symbol,lambda u=url,s=symbol:src.sec_filings(json.loads(self.fetch(u)),s,self.as_of),url)
            if not filings:
                self.calls.append({'tool':'sec_financials','target':symbol,'status':'skipped','reason':'SEC_identity_source_failed','fact_ids':[],'raw_refs':[]});continue
            url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json'
            def financials(u=url,c=cik):
                raw=json.loads(self.fetch(u))
                if int(raw['cik'])!=int(c):raise ValueError('CIK mismatch')
                return src.sec_financials(raw,self.as_of)
            self.record('sec_financials',symbol,financials,url)
        if broker:
            for symbol in list(dict.fromkeys([s for s in funds if s in all_symbols]+selected)):
                progress('가격 이력·거래량·관측 호가 확인 중: '+symbol)
                def candles(s=symbol):
                    raw=broker.candles(s)
                    self.records.append(self.archive.preserve(d.dumps(raw),'https://openapi.tossinvest.com/api/v1/candles?'+urllib.parse.urlencode({'symbol':s,'interval':'1d','count':80,'adjusted':'true'})))
                    return src.price_history(raw,s,self.as_of)
                def book(s=symbol):
                    raw=broker.orderbook(s)
                    self.records.append(self.archive.preserve(d.dumps(raw),'https://openapi.tossinvest.com/api/v1/orderbook?'+urllib.parse.urlencode({'symbol':s})))
                    return src.orderbook(raw,self.as_of,datetime.now(timezone.utc))
                self.record('candles',symbol,candles,'https://developers.tossinvest.com/docs/market-data')
                self.record('orderbook',symbol,book,'https://developers.tossinvest.com/docs/market-data',0)
        by_tool={t['id']:[c for c in self.calls if c['tool']==t['id']] for t in TOOLS}
        available=[];missing=[]
        for t in TOOLS:
            calls=by_tool[t['id']];ok=[c for c in calls if c['status']=='collected']
            if ok:available.append(t['label']+f' ({len(ok)}/{len(calls)})')
            if len(ok)!=len(calls) or not calls:missing.append(t['label']+' 일부 미수집' if ok else t['label']+' 미확인')
        manifest={'schema_version':VERSION,'owner_role':'evidence','tools':TOOLS,'calls':self.calls,
            'selection':{'company_symbols':selected,'fund_symbols':funds,'not_deeply_collected':[s for s in all_symbols if s not in selected+funds],
                'reason':'보유 우선, 이후 입력/자동 후보 순서. 기업 최대 8개와 지원 ETF. 전체 시장 조사 아님.', 'sec_identity_mode':identity_mode,'sec_seed_as_of':seed['retrieved_at']},
            'budget':{'max_companies':8,'max_http_requests':48,'max_seconds_before_new_request':150,'max_fact_characters':160000,'fact_characters':self.used_chars},
            'collected_at':self.now.isoformat(),'raw_policy':'원문 sha256 파일 보존. 활성 요약/pruning과 별개.'}
        validate(manifest,schema('research'))
        market['facts'].extend(self.facts);market['research']=manifest
        market['fund_constituents']={s:rows for s,rows in self.constituents.items() if any(c['tool']=='fund_holdings' and c['target']==s and c['status']=='collected' for c in self.calls)}
        missing+=['공시 본문·경쟁우위·정상화 가치 및 부채 만기 검토','산업·지정학·기업 뉴스의 포괄 수집','세금·환전·계좌별 총 거래 비용','ETF 구성과 토스 제외 섹터의 분류 대조','주문 시점의 유동성·체결 가능성']
        if len(market['return_histories'])!=len(funds):missing.append('일부 ETF 월별 NAV 총수익률 이력 미확인')
        market['coverage']={'status':'partial' if self.facts else 'limited',
            'available':market.get('coverage',{}).get('available',['기존 스냅샷 가격·자산 정보'])+available,'missing':missing,
            'research_fact_count':len(self.facts),'proposal_policy':POLICY,
            'reason':'편입을 제안한 자산의 필수 자료·개인 제약·R4 검증으로 판단해요. 다른 후보의 자료 부족이나 주문 시점 확인을 이유로 모든 배분 제안을 일괄 차단하지 않아요.'}
        d.market(market)
        return market


def project_fact(fact,role):
    """The only permitted current-role projection of an immutable fact."""
    f=copy.deepcopy(fact);f.pop('raw_refs',None)
    if f.get('research_tool')=='sec_financials':
        value=json.loads(f['text'])
        if role in ('context','bogle','reflection','memory'):
            value={k:v for k,v in value.items() if k!='metrics'}
            value['scope']='상세 재무는 시장 근거·기업 관점·검증에 전달. 원본 시장 fact에서 확인.'
        else:value['provenance']='수치 검증이 같은 근거를 사용할 수 있도록 접수번호·공시일·기간·단위를 보존해요.'
        f['text']=d.dumps(value)
    return f


def compact_market(market,role,historical=False):
    """Model-only projection; full facts, manifest and raw responses stay frozen."""
    m=copy.deepcopy(market)
    m.pop('fund_constituents',None)
    m.pop('return_histories',None)  # full series stay in immutable market; roles receive reproducible summaries
    m.pop('fx_history',None)
    if 'research' not in m:return m
    r=m['research']
    # Complete per-call provenance stays in the stored market/workbench.
    m['research']={k:r[k] for k in ('schema_version','selection','budget','collected_at')}
    m['research']['tool_results']=[{k:c[k] for k in ('tool','target','status','reason')} for c in r['calls']]
    m['facts']=[project_fact(f,role) for f in m['facts']]
    return historical_market(m) if historical else m


def historical_market(m):
    """Keep prior quantitative comparisons within 8k; original + all prior
    investment rationales/risks remain in the report and immutable snapshot.
    Never cut a source in the middle of a claim or silently invent a summary.
    """
    retained=[];omitted=[];size=0
    for f in m['facts']:
        tool=f.get('research_tool')
        try:value=json.loads(f['text'])
        except (ValueError,TypeError):value=None
        summary=None
        if isinstance(value,dict) and tool:
            if tool=='sec_financials' and 'metrics' in value:
                summary=copy.deepcopy(value)
                for series in summary['metrics'].values():
                    for item in series:item['observations']=item['observations'][:1]
            elif tool in ('bls','treasury'):
                summary=copy.deepcopy(value);summary['observations']=summary.get('observations',[])[:1]
            elif tool=='fed':
                summary={'items':[{k:v for k,v in item.items() if k!='summary'} for item in value['items']], 'limits':value['limits']}
            elif tool=='fund_holdings':
                summary={k:v for k,v in value.items() if k!='top_holdings'}
            else:summary=value
        if summary is not None:
            item={k:v for k,v in f.items() if k!='text'};item['text']=d.dumps(summary)
            n=len(d.dumps(item))
            if size+n<=8000:retained.append(item);size+=n;continue
        omitted.append(f['id'])
    m['facts']=retained
    m['evidence_projection']={'mode':'previous_numeric_comparison','max_fact_characters':8000,
        'omitted_fact_ids':omitted,'reason':'이전 시장 원문은 원래 market_id에 보존. 현재 역할 입력에는 기간별 최신 수치 비교만 제한적으로 재사용. 이전 제안·각 관점의 이유·반론·위험·회고는 별도로 유지. 제외된 사실의 세부 변화는 미확인으로 남겨요.'}
    if 'research' in m:m['research'].pop('tool_results',None)
    return m
