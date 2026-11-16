"""Issuer adapters for growth/reference candidates. No invented return histories."""
import html
import io
import json
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET
from .research_sources import finite,dated,LinkedData

QQQ_PAGE='https://www.invesco.com/qqq-etf/en/about.html'
QQQ_API='https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ'
XLV_PAGE='https://www.ssga.com/us/en/individual/etfs/state-street-health-care-select-sector-spdr-etf-xlv'
XLV_HOLDINGS='https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlv.xlsx'
IAU_PAGE='https://www.ishares.com/us/products/239561/ishares-gold-trust'
EXTRA=('QQQ','XLV','IAU','JEPI')
JEPI_ARTICLE='https://am.jpmorgan.com/us/en/asset-management/adv/investment-strategies/etf-investing/investment-ideas/why-invest-in-equity-premium-income-etf-jepi/'


def qqq_profile(raw,page,as_of):
    x=json.loads(raw)
    if x['ticker']!='QQQ' or x['currencyCode']!='USD' or 'Nasdaq-100' not in page:raise ValueError('QQQ identity/objective')
    dated(x['effectiveBusinessDate'],as_of,10)
    return {'symbol':'QQQ','name':'Invesco QQQ','asset_class':'Equity','observed_at':x['effectiveBusinessDate'],
        'expense_ratio':finite(x['feeValue'],0,10)/100,'benchmark':'Nasdaq-100',
        'objective':'Nasdaq-100 비금융 대형주 추종. 성장·기술 집중과 지수 내 중복을 별도 검토.',
        'nav_usd':finite(x['nav'],.000001),'limits':'상품 비교 근거. 저평가·미래 초과수익 또는 과거 개인 보유를 뜻하지 않음.'}


def qqq_holdings(raw,sector_raw,as_of):
    x=json.loads(raw);sector=json.loads(sector_raw)
    if x['cusip']!='QQQ' or sector['cusip']!='QQQ' or len(x['holdings'])!=x['totalNumberOfHoldings']:raise ValueError('Incomplete QQQ holdings')
    dated(x['effectiveBusinessDate'],as_of,10);dated(sector['effectiveDate'],as_of,45)
    rows=[];other=[];total=0.;seen=set()
    for r in x['holdings']:
        w=r['percentageOfTotalNetAssets']
        if w is not None:total+=finite(w,-100,100)/100
        if r['securityTypeName']=='Common Stock':
            if not r['ticker'] or r['ticker'] in seen or r['currency']!='USD':raise ValueError('QQQ holding identity')
            seen.add(r['ticker']);rows.append({'symbol':r['ticker'],'name':r['issuerName'],'weight':finite(w,0,100)/100,'sector':'issuer_sector_not_supplied'})
        else:other.append({'name':r['issuerName'],'type':r['securityTypeName'],'weight':None if w is None else w/100})
    if not rows or not .97<=total<=1.03:raise ValueError('QQQ weight coverage')
    sectors={r['name']:finite(r['value'],0,100)/100 for r in sector['holdingWeights']}
    if not .97<=sum(sectors.values())<=1.03:raise ValueError('QQQ sector coverage')
    return {'observed_at':x['effectiveBusinessDate'],'holdings_count':len(rows),'reported_weight_sum':total,
        'equity_fraction':sum(r['weight'] for r in rows),'sector_weights':sectors,'sector_observed_at':sector['effectiveDate'],
        'sector_taxonomy':'issuer ICB; not Toss','other_positions':other,'complete_lookthrough':False,
        'top_holdings':sorted(rows,key=lambda r:r['weight'],reverse=True)[:10],'constituents':rows,
        'limits':'주식 전량과 비주식/음수/결측 행을 구분. 월말 ICB 섹터는 현재 토스 섹터로 치환하지 않음. 파생상품 전체 경제노출 미확인.'}


def ssga_field(page,key):
    t=html.unescape(page)
    m=re.search(r'"'+re.escape(key)+r'"\s*:\s*\{[^{}]*?"value"\s*:\s*"([^"]+)"',t)
    if not m:raise ValueError('SSGA field unavailable: '+key)
    return m.group(1)


def xlv_profile(page,as_of):
    if ssga_field(page,'fund-ticker')!='XLV':raise ValueError('XLV identity')
    date=datetime.strptime(ssga_field(page,'nav-date'),'%d-%b-%Y').date().isoformat();dated(date,as_of,10)
    fee=ssga_field(page,'gross-expense-ratio')
    if not fee.endswith('%'):raise ValueError('SSGA percentage unit')
    return {'symbol':'XLV','name':'Health Care Select Sector SPDR ETF','asset_class':'Equity','observed_at':date,
        'expense_ratio':finite(fee[:-1],0,10)/100,'benchmark':ssga_field(page,'benchmark'),
        'objective':'미국 Health Care Select Sector Index를 추종하는 헬스케어 섹터 ETF.',
        'limits':'섹터 상품. 방어적 특성이나 손실 보호를 보장하지 않음.'}


def xlv_holdings(raw,as_of):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist())>10_000_000:raise ValueError('Oversized workbook')
        strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',ns)]
        rows=[]
        for r in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row',ns):
            row={}
            for c in r:
                v=c.find('s:v',ns)
                if v is not None:row[re.sub('[0-9]','',c.get('r'))]=strings[int(v.text)] if c.get('t')=='s' else v.text
            rows.append(row)
    if rows[1].get('B')!='XLV' or rows[3].get('E')!='Weight':raise ValueError('XLV workbook identity/units')
    date=datetime.strptime(rows[2]['B'],'As of %d-%b-%Y').date().isoformat();dated(date,as_of,10)
    data=[];other=[];seen=set()
    for r in rows[4:]:
        if not r.get('A'):continue
        if r.get('E') in (None,''):
            if r.get('B'):raise ValueError('XLV holding weight missing')
            continue
        if r.get('H')!='USD' or not r.get('B'):raise ValueError('XLV holding identity')
        if r['B']=='-':
            other.append({'name':r['A'],'type':'cash' if r['A']=='US DOLLAR' else 'unclassified','weight':finite(r['E'],0,100)/100});continue
        if r['B'] in seen:raise ValueError('Duplicate XLV ticker')
        seen.add(r['B']);data.append({'symbol':r['B'],'name':r['A'],'weight':finite(r['E'],0,100)/100,'sector':'issuer_sector_not_supplied'})
    total=sum(r['weight'] for r in data+other)
    if not data or not .97<=total<=1.03:raise ValueError('XLV holdings incomplete')
    return {'observed_at':date,'holdings_count':len(data),'reported_weight_sum':total,
        'sector_weights':{'Unclassified issuer rows':total},'equity_fraction':None,'other_positions':other,
        'top_holdings':sorted(data,key=lambda r:r['weight'],reverse=True)[:10],'constituents':data,
        'complete_lookthrough':False,'limits':'운용사 전량 XLSX. 구성 파일의 섹터 값이 비어 있으므로 헬스케어 100%라고 대체하지 않음. 토스 구성종목 대조는 별도.'}


def iau_profile(page,as_of):
    parser=LinkedData();parser.feed(page)
    fund=next(x for x in parser.graph if x.get('alternateName')=='IAU')
    fields={p['name']:p for x in parser.graph for p in x.get('additionalProperty',[])}
    nav=fields['NAV as of'];date=datetime.strptime(nav['valueReference']['value'],'%b %d, %Y').date().isoformat();dated(date,as_of,10)
    desc=next(x['description'] for x in parser.graph if x.get('@id','').endswith('#fund-description'))
    return {'symbol':'IAU','name':fund['name'],'asset_class':fund['category'],'observed_at':date,
        'expense_ratio':finite(fields['Sponsor Fee:']['value'],0,10)/100,'benchmark':'Gold bullion price',
        'objective':desc[:700],'limits':'금 신탁은 기업 주식이나 예금이 아님. 주식 수익률·주식 섹터로 대체하지 않음. 별도 금 충격과 보관 구조 검토 필요.'}


def collect(research,market,symbols):
    r=research
    for s in EXTRA:
        if s not in symbols:continue
        if s=='QQQ':
            url=QQQ_API+'?idType=ticker&variationType=fundDetails&productType=ETF'
            profile=r.record('fund_profile',s,lambda:qqq_profile(r.fetch(url),r.fetch(QQQ_PAGE),r.as_of),url)
            hold=QQQ_API+'/holdings/fund?idType=ticker&interval=monthly&productType=ETF'
            sec=QQQ_API+'/weightedHoldings/fund?idType=ticker&productType=ETF&breakdown=sector'
            r.record('fund_holdings',s,lambda:qqq_holdings(r.fetch(hold),r.fetch(sec),r.as_of),hold)
        elif s=='XLV':
            profile=r.record('fund_profile',s,lambda:xlv_profile(r.fetch(XLV_PAGE),r.as_of),XLV_PAGE)
            def holdings():
                raw,meta=r.archive.get(XLV_HOLDINGS);r.records.append(meta)
                return xlv_holdings(raw,r.as_of)
            r.record('fund_holdings',s,holdings,XLV_HOLDINGS)
        elif s=='IAU':profile=r.record('fund_profile',s,lambda:iau_profile(r.fetch(IAU_PAGE),r.as_of),IAU_PAGE)
        else:
            def jepi():
                text=r.fetch(JEPI_ARTICLE)
                if 'JEPI' not in text or 'options' not in text:raise ValueError('JEPI source identity')
                return {'symbol':'JEPI','observed_at':r.as_of,'objective':'미국 대형주와 옵션 오버레이를 결합해 월 소득과 낮은 변동성을 추구. 일부 상승 참여를 포기하는 소득형 전략.',
                    'limits':'운용사 전략 설명이며 수익 보장 아님. 현재 전량 구성·ELN 거래상대방/담보·옵션 경제노출·공식 보수 검증은 미완료. 성장형 주식 ETF와 동등 위험으로 처리하지 않음.'}
            r.record('fund_profile',s,jepi,JEPI_ARTICLE);profile=None
        if profile and s in market['assets']:
            market['assets'][s].update(expense_ratio=profile['expense_ratio'],asset_class='commodity' if s=='IAU' else 'equity')
