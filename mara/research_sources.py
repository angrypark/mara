"""Pure parsers for dated public research. No model, account or execution authority."""
import csv
import io
import json
import math
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from .domain import day

SEC_TICKERS='https://www.sec.gov/files/company_tickers.json'
FED='https://www.federalreserve.gov/feeds/press_monetary.xml'
FUNDS={
 'ITOT':'https://www.ishares.com/us/products/239724/ishares-core-s-p-total-u-s-stock-market-etf',
 'IVV':'https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf'}
METRICS={
 'revenue':('USD',['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet']),
 'net_income':('USD',['NetIncomeLoss','ProfitLoss']),
 'operating_cashflow':('USD',['NetCashProvidedByUsedInOperatingActivities']),
 'capital_expenditure':('USD',['PaymentsToAcquirePropertyPlantAndEquipment']),
 'cash':('USD',['CashAndCashEquivalentsAtCarryingValue']),
 'assets':('USD',['Assets']),
 'liabilities':('USD',['Liabilities']),
 'long_term_debt':('USD',['LongTermDebtCurrent','LongTermDebtNoncurrent','LongTermDebt']),
 'equity':('USD',['StockholdersEquity']),
 'diluted_eps':('USD/shares',['EarningsPerShareDiluted']),
}
DURATIONS={'revenue','net_income','operating_cashflow','capital_expenditure','diluted_eps'}


class EvidenceError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code


def finite(v,lo=None,hi=None):
    if isinstance(v,bool):raise ValueError('boolean number')
    n=float(str(v).replace(',',''))
    if not math.isfinite(n) or lo is not None and n<lo or hi is not None and n>hi:raise ValueError('invalid number')
    return n


def dated(value,as_of,max_age):
    d=day(value)
    age=(day(as_of)-d).days
    if age<0:raise EvidenceError('future_observation')
    if age>max_age:raise EvidenceError('stale_observation')
    return value


def sec_financials(raw,as_of):
    """Annual durations stay annual; latest instants stay instants. Never sum overlaps."""
    facts=raw.get('facts',{}).get('us-gaap',{})
    data={}; publication=[]
    for name,(unit,tags) in METRICS.items():
        # Debt components remain separate: they are NOT interchangeable fallbacks.
        series=[]
        for tag in tags:
            by_period={}
            for r in facts.get(tag,{}).get('units',{}).get(unit,[]):
                if r.get('form') not in {'10-K','10-Q','10-K/A','10-Q/A'}:continue
                try:
                    filed=r['filed']; end=r['end'];day(filed);day(end)
                    if filed>as_of or end>filed or (day(as_of)-day(end)).days>1850:continue
                    duration=(day(end)-day(r['start'])).days if 'start' in r else None
                    if name in DURATIONS and (duration is None or not 330<=duration<=380):continue
                    if name not in DURATIONS and duration is not None:continue
                    value=finite(r['val']);acc=r['accn']
                    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc):continue
                    key=(r.get('start'),end)
                    row={'end':end,'filed':filed,'value':value,'accession':acc,'form':r['form']}
                    if 'start' in r:row['start']=r['start']
                    if key not in by_period or by_period[key]['filed']<filed:by_period[key]=row
                except (KeyError,TypeError,ValueError):continue
            rows=sorted(by_period.values(),key=lambda r:r['end'],reverse=True)[:3 if name in DURATIONS else 1]
            if rows:
                series.append({'tag':tag,'unit':unit,'period_type':'annual' if name in DURATIONS else 'instant','observations':rows})
        if series:
            if name!='long_term_debt':series=[max(series,key=lambda s:(max(r['end'] for r in s['observations']),max(r['filed'] for r in s['observations'])))]
            data[name]=series
            publication.extend(r['filed'] for s in series for r in s['observations'])
    if not data:raise ValueError('no supported US GAAP observations')
    return {'entity':raw['entityName'],'cik':raw['cik'],'metrics':data,
        'missing_metrics':[k for k in METRICS if k not in data],
        'latest_filed':max(publication),
        'stale_metrics':[k for k,v in data.items() if all((day(as_of)-day(row['end'])).days>550 for series in v for row in series['observations'])],
        'limits':'US GAAP 표준 태그 일부. 연간 수치이며 TTM/정상화 이익 아님. 각 기간·공시일·단위를 따로 비교. 부채 태그 중복 합산 금지. 유지/성장 투자·만기·경쟁우위·내재가치 미확인. 수정치는 이번 수집 시점에 알려진 값.'}


def sec_filings(raw,symbol,as_of):
    norm=lambda s:s.upper().replace('.','-')
    if norm(symbol) not in {norm(s) for s in raw.get('tickers',[])}:raise EvidenceError('identity_mismatch')
    recent=raw.get('filings',{}).get('recent',{});out=[]
    for i,form in enumerate(recent.get('form',[])):
        if form not in {'10-K','10-Q','8-K','20-F','6-K','10-K/A','10-Q/A'}:continue
        filed=recent['filingDate'][i]
        if filed>as_of or (day(as_of)-day(filed)).days>550:continue
        acc=recent['accessionNumber'][i];doc=recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',acc) or not re.fullmatch(r'[A-Za-z0-9_.-]+',doc):continue
        out.append({'form':form,'filed':filed,'report_date':recent['reportDate'][i],
                    'accession':acc,'url':f"https://www.sec.gov/Archives/edgar/data/{int(raw['cik'])}/{acc.replace('-','')}/{doc}"})
        if len(out)>=4:break
    if not out:raise ValueError('no recent filings')
    return {'symbol':symbol,'cik':raw['cik'],'entity':raw['name'],'sic':raw.get('sicDescription'),
            'filings':out,'limits':'공시 목록/메타데이터만 수집. 본문·실적 발표·사건 내용은 검토하지 않았어요.'}


def treasury(raw,as_of):
    rows=[]
    for r in csv.DictReader(io.StringIO(raw)):
        try:
            dt=datetime.strptime(r['Date'],'%m/%d/%Y').date().isoformat()
            if dt>as_of:continue
            rates={k:finite(r[k],-5,50) for k in ('3 Mo','2 Yr','10 Yr','30 Yr') if r.get(k)}
            if len(rates)<4:continue
            rows.append({'date':dt,'yield_percent':rates,'10y_minus_2y_pp':rates['10 Yr']-rates['2 Yr']})
        except (KeyError,ValueError):continue
    rows=sorted(rows,key=lambda x:x['date'],reverse=True)[:6]
    if not rows:raise ValueError('no Treasury yields')
    dated(rows[0]['date'],as_of,10)
    return {'observations':rows,'limits':'연율 par 수익률(%), 채권 가격/수익률 시계열 아님. 이번 다운로드의 수정치이며 과거 vintage 아님.'}


def bls(raw,series,as_of):
    if raw.get('status')!='REQUEST_SUCCEEDED':raise ValueError('BLS unavailable')
    items=raw['Results']['series']
    if len(items)!=1 or items[0]['seriesID']!=series:raise ValueError('BLS identity mismatch')
    rows=[];missing_months=[]
    for r in items[0]['data']:
        if not re.fullmatch(r'M(0[1-9]|1[0-2])',r['period']):continue
        month=r['year']+'-'+r['period'][1:]
        # A month's observation does not become known at the start of that month.
        if month>=as_of[:7]:continue
        if r['value'] in ('-','',None):
            missing_months.append(month);continue
        rows.append({'month':month,'value':finite(r['value']),'footnotes':[x['text'] for x in r.get('footnotes',[]) if x.get('text')]})
    rows=sorted(rows,key=lambda r:r['month'],reverse=True)[:14]
    if not rows:raise ValueError('no BLS observations')
    dated(rows[0]['month']+'-01',as_of,100)
    return {'series':series,'unit':'index 1982-84=100, seasonally adjusted' if series=='CUSR0000SA0' else 'percent, seasonally adjusted',
            'observations':rows,'missing_months':missing_months,'limits':'관측 월과 발표일은 달라요. API에 정확한 발표 시각이 없어 known_at은 이번 수집일. 수정된 현재 빈티지이며 당시 알려진 과거 자료로 소급하지 않아요.'}


def fed_news(raw,as_of):
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():raise ValueError('unsafe XML')
    root=ET.fromstring(raw);rows=[]
    for item in root.findall('.//item'):
        try:
            published=parsedate_to_datetime(item.findtext('pubDate')).date().isoformat()
            if not 0<=(day(as_of)-day(published)).days<=120:continue
            url=item.findtext('link','')
            if not url.startswith('https://www.federalreserve.gov/'):continue
            rows.append({'published_at':published,'title':item.findtext('title','')[:400],
                'summary':re.sub('<[^>]+>',' ',item.findtext('description',''))[:900],'url':url})
        except (ValueError,TypeError):continue
    if not rows:raise ValueError('no current policy news')
    return {'items':sorted(rows,key=lambda x:x['published_at'],reverse=True)[:4],
            'limits':'연준 공식 정책 발표 RSS 요약만 수집. 산업·지정학·기업 뉴스의 포괄 보도나 발표 본문 전체 분석이 아니에요.'}


class LinkedData(HTMLParser):
    def __init__(self):super().__init__();self.active=False;self.parts=[];self.graph=[];self.components={}
    def handle_starttag(self,tag,attrs):
        if tag=='walrus-render-on-client':
            value=dict(attrs).get('componentprops')
            if value:
                try:
                    obj=json.loads(value)
                    if isinstance(obj,dict) and obj.get('componentId') in ('keyFundFacts','fundamentalsAndRisk'):
                        self.components[obj['componentId']]=obj
                except ValueError:pass
        if tag=='script' and dict(attrs).get('type')=='application/ld+json':self.active=True;self.parts=[]
    def handle_data(self,s):
        if self.active:self.parts.append(s)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.active=False
            value=json.loads(''.join(self.parts))
            if not isinstance(value,dict):raise ValueError('unsupported linked data shape')
            graph=value.get('@graph',[])
            if not isinstance(graph,list) or any(not isinstance(x,dict) for x in graph):raise ValueError('invalid linked data graph')
            self.graph.extend(graph)


def fund_profile(raw,symbol,as_of):
    parser=LinkedData();parser.feed(raw)
    graph=parser.graph
    fund=next(x for x in graph if x.get('alternateName')==symbol)
    fields={p['name']:p for x in graph for p in x.get('additionalProperty',[])}
    expense=finite(fields['Expense Ratio:']['value'],0,10)/100
    nav=fields['NAV as of'];dt=datetime.strptime(nav['valueReference']['value'],'%b %d, %Y').date().isoformat()
    dated(dt,as_of,10)
    desc=next(x['description'] for x in graph if x.get('@id','').endswith('#fund-description'))
    url=next(x['mainEntity']['contentUrl'] for x in graph if x.get('@id','').endswith('#holdings'))
    if url!=FUNDS[symbol]+'/latest-holdings.csv':raise ValueError('unexpected holdings URL')
    metrics={};missing=[]
    definitions={'thirtyDayAverageVolume':('shares',1),'thirtyDayMedianBidAskSpread':('fraction',.01),
        'beta3Yr':('ratio',1),'numHoldings':('count',1),'priceBook':('ratio',1),
        'priceEarnings':('ratio',1),'standardDeviation3Yr':('fraction',.01),
        'thirtyDaySecYield':('fraction',.01),'twelveMonTrlYld':('fraction',.01)}
    data={k:v for c in parser.components.values() for k,v in c.get('dataPoints',{}).items()}
    for key,(unit,scale) in definitions.items():
        try:
            item=data[key];date=datetime.strptime(item['formattedAsOfDate'],'%b %d, %Y').date().isoformat()
            dated(date,as_of,62)
            formatted=item['formattedValue']
            if scale==.01 and not formatted.endswith('%'):raise ValueError('Percentage unit required')
            metrics[key]={'value':finite(formatted.rstrip('%'))*scale,'unit':unit,'observed_at':date,'label':item['label']}
        except (ValueError,KeyError,TypeError,AttributeError):missing.append(key)
    return {'symbol':symbol,'name':fund['name'],'asset_class':fund.get('category'),'expense_ratio':expense,
        'issuer_metrics':metrics,'missing_issuer_metrics':missing,
        'benchmark':fields['Benchmark Index']['value'],'objective':desc[:700],
        'observed_at':dt,'expense_observed_at':as_of,'holdings_url':url,
        'limits':'보수는 조회 시점 상품 표시값으로 변경 발효일 미제공. 운용사 보수는 세금·환전·거래수수료를 포함하지 않아요. 투자 추천이나 전체 상품 비교가 아니에요.'}


def fund_holdings(raw,as_of):
    lines=list(csv.reader(io.StringIO(raw)))
    observed=datetime.strptime(next(r[1] for r in lines if r and r[0]=='Fund Holdings as of'),'%b %d, %Y').date().isoformat()
    dated(observed,as_of,10)
    header=next(i for i,r in enumerate(lines) if r and r[0]=='Ticker')
    data=[];sectors={};total=0;missing_weights=[];ended=False;seen=set()
    columns=lines[header]
    if len(set(columns))!=len(columns) or not {'Ticker','Asset Class','Sector','Name'}<=set(columns) or not {'Weight (%)','Market Weight'}&set(columns):raise ValueError('Incomplete holdings columns')
    for row in lines[header+1:]:
        if not row or len(row)==1 and not row[0].strip():ended=True;continue
        if len(row)!=len(columns):
            if not ended or len(row)!=1:raise ValueError('Truncated holdings row')
            continue
        if ended:raise ValueError('Unexpected holding after footer')
        r=dict(zip(columns,row))
        identity=(r['Ticker'],r['Name'],r.get('Exchange',''),r['Asset Class'])
        if not r['Ticker'] or not r['Name'] or identity in seen:raise ValueError('Ambiguous holdings identity')
        seen.add(identity)
        weight=r.get('Weight (%)',r.get('Market Weight'))
        if weight is None:continue
        if weight in ('-',''):
            missing_weights.append({'symbol':r.get('Ticker'),'asset_class':r.get('Asset Class'),'notional_weight_percent':r.get('Notional Weight')});continue
        w=finite(weight,-100,100)/100
        if w<0:raise ValueError('negative derivative holdings need a different adapter')
        total+=w
        if r.get('Asset Class')=='Equity':
            sectors[r['Sector']]=sectors.get(r['Sector'],0)+w
            data.append({'symbol':r['Ticker'],'name':r['Name'],'sector':r['Sector'],'weight':w})
    if not data or not 0.97<=total<=1.03:raise ValueError('incomplete fund weight coverage')
    result={'observed_at':observed,'holdings_count':len(data),'reported_weight_sum':total,
        'equity_fraction':sum(sectors.values()),'sector_weights':sectors,'missing_weight_rows':missing_weights,
        'complete_reported_weights':not missing_weights,
        'complete_lookthrough':False,
        'top_holdings':sorted(data,key=lambda x:x['weight'],reverse=True)[:10],
        'constituents':data,
        'limits':'전량 CSV를 보존하고 상위 10개와 섹터 합계를 요약. 결측 비중은 0으로 대체하지 않음. 반올림/현금/파생상품 차이가 있고 토스 섹터 분류와 같지 않아요. 개별 종목과의 전체 중복 위험은 별도 확인.'}

    from .holding_values import concentration
    try:result['market_value_concentration']=concentration(raw,as_of)
    except (ValueError,KeyError,TypeError,StopIteration):result['market_value_concentration']={'available':False,'reason':'보고 시장가치의 전량·통화·단위·기간 검증을 통과하지 못했어요.'}
    return result


def price_history(raw,symbol,as_of):
    rows={}
    for r in raw['candles']:
        dt=datetime.fromisoformat(r['timestamp'])
        if dt.tzinfo is None:raise EvidenceError('observation_timezone_missing')
        obs=dt.date().isoformat()
        # Today's bar may still be forming; only completed prior local trading dates.
        if obs>=as_of:continue
        if r['currency']!='USD':raise EvidenceError('currency_mismatch')
        value={'date':obs,'close':finite(r['closePrice'],0.000001),'volume':finite(r['volume'],0)}
        if obs in rows and rows[obs]!=value:raise ValueError('conflicting candle')
        rows[obs]=value
    rows=sorted(rows.values(),key=lambda r:r['date'])
    if len(rows)<20:raise EvidenceError('insufficient_observations')
    dated(rows[-1]['date'],as_of,7)
    changes={str(n)+'_sessions':rows[-1]['close']/rows[-1-n]['close']-1 for n in (5,20,60) if len(rows)>n}
    recent=rows[-20:]
    return {'symbol':symbol,'currency':'USD','first':rows[0]['date'],'last':rows[-1]['date'],'observations':len(rows),
        'price_changes':changes,'mean_20_session_volume':sum(r['volume'] for r in recent)/20,
        'mean_20_session_close_times_volume_usd':sum(r['close']*r['volume'] for r in recent)/20,
        'limits':'수정 일봉 가격 변화. 배당 재투자/환율/비용 반영 총수익률 아님. close×volume은 근사 거래대금. 거래량은 체결 보장이 아니며 위험 지표 시계열에 넣지 않아요.'}


def orderbook(raw,as_of,collected_at):
    # A valid empty provider response is not a dated executable quote.
    # Never invent a timestamp or a zero spread to make it pass.
    if raw.get('currency')=='USD' and raw.get('timestamp') is None and raw.get('asks')==[] and raw.get('bids')==[]:
        return {'availability':'no_quote','currency':'USD','timestamp':None,
            'limits':'공급자가 관측 호가를 제공하지 않았어요. 휴장 여부는 이 응답만으로 확정하지 않아요. 최근 거래량과 운용사 기간별 스프레드로 사전 유동성을 검토하고 주문 직전 호가는 별도로 확인해야 해요.'}
    stamp=datetime.fromisoformat(raw['timestamp'])
    if stamp.tzinfo is None or raw['currency']!='USD' or stamp>collected_at:raise ValueError('invalid or future orderbook')
    dated(stamp.date().isoformat(),as_of,7)
    asks=[finite(x['price'],0.000001) for x in raw['asks'] if finite(x['volume'],0)>0]
    bids=[finite(x['price'],0.000001) for x in raw['bids'] if finite(x['volume'],0)>0]
    ask,bid=min(asks),max(bids)
    if ask<bid:raise ValueError('crossed quote')
    return {'timestamp':raw['timestamp'],'currency':'USD','best_ask':ask,'best_bid':bid,
        'spread_fraction':(ask-bid)/((ask+bid)/2),'limits':'관측 시각의 호가 스냅샷. 장외/휴장·지연 가능. 지금의 유동성·체결 가능성·실제 주문 비용을 보장하지 않아요.'}
