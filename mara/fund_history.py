"""Issuer-reported monthly NAV total returns, separate from daily price bars."""
import calendar
import re
from datetime import datetime
from xml.etree import ElementTree as ET
from .research_sources import finite,dated

NAMES={'ITOT':'iShares Core S&P Total U.S. Stock Market ETF',
       'IVV':'iShares Core S&P 500 ETF'}
PORTFOLIOS={'ITOT':'239724','IVV':'239726'}
NS='urn:schemas-microsoft-com:office:spreadsheet'


def export_url(symbol):
    return ('https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document'
        '?appSubType=ISHARES&appType=PRODUCT_PAGE&component=fundDownload&locale=en_US&portfolioId='+PORTFOLIOS[symbol]+
        '&targetSite=us-ishares&userType=individual')


def monthly_returns(raw,symbol,as_of):
    if symbol not in NAMES:raise ValueError('Unsupported issuer identity')
    if len(raw)>15000000 or '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValueError('Unsafe issuer workbook')
    # The official export has literal ampersands in hyperlink attributes.
    # Escape only bare ampersands; preserve original bytes outside this parser.
    fixed=re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)', '&amp;', raw)
    root=ET.fromstring(fixed)
    sheets={w.get('{'+NS+'}Name'):w for w in root.findall('{'+NS+'}Worksheet')}
    rows=[]
    for row in sheets['Performance'].findall('{'+NS+'}Table/{'+NS+'}Row'):
        cells=[]
        for cell in row.findall('{'+NS+'}Cell'):
            index=int(cell.get('{'+NS+'}Index',len(cells)+1))
            if index<len(cells)+1 or index>100:raise ValueError('Invalid workbook cell index')
            cells.extend(['']*(index-len(cells)-1))
            data=cell.find('{'+NS+'}Data');cells.append(''.join(data.itertext()).strip() if data is not None else '')
        rows.append(cells)
    if not rows or rows[0]!=[NAMES[symbol]]:raise ValueError('Issuer workbook identity mismatch')
    header=['Month End Date','Monthly Total (NAV) Return']
    start=rows.index(header)+1;observations={};missing=[]
    for row in rows[start:]:
        if not row or not row[0]:continue
        if len(row)!=2:raise ValueError('Changed issuer return table')
        dt=datetime.strptime(row[0],'%b %d, %Y').date()
        if dt.day!=calendar.monthrange(dt.year,dt.month)[1]:raise ValueError('Return date must be month end')
        date=dt.isoformat()
        if date>as_of:continue
        if row[1] in ('--','-',''):missing.append(date);continue
        value=finite(row[1],-100,1000)/100
        if date in observations:raise ValueError('Duplicate monthly return')
        observations[date]=value
    if len(observations)<36:raise ValueError('Insufficient monthly history')
    dates=sorted(observations);dated(dates[-1],as_of,62)
    for a,b in zip(dates,dates[1:]):
        ay,am=map(int,a[:7].split('-'));by,bm=map(int,b[:7].split('-'))
        if by*12+bm-ay*12-am!=1:raise ValueError('Gap in monthly total return history')
    nav=None;nav_issue='Issuer export has no recognized Historical NAV table'
    if 'Historical' in sheets:
        try:
            nav_rows=[]
            for row in sheets['Historical'].findall('{'+NS+'}Table/{'+NS+'}Row'):
                nav_rows.append([''.join(c.itertext()).strip() for c in row.findall('{'+NS+'}Cell/{'+NS+'}Data')])
            if nav_rows and nav_rows[0]==['As Of','NAV per Share','Ex-Dividends','Shares Outstanding']:
                nav_candidates=[]
                for row in nav_rows[1:]:
                    if len(row)!=4:raise ValueError('Invalid NAV row')
                    stamp=datetime.strptime(row[0],'%b %d, %Y').date().isoformat()
                    if stamp<=as_of:nav_candidates.append((stamp,row))
                if nav_candidates:
                    stamp,row=max(nav_candidates,key=lambda x:x[0]);dated(stamp,as_of,10)
                    nav={'date':stamp,'nav_per_share_usd':finite(row[1],.000001),'shares_outstanding':finite(row[3],1),
                        'scope':'Issuer USD NAV, not an executable price. Compare only with a quote from the same US trading date.'}
                    nav_issue=None
                else:nav_issue='No NAV on or before the decision date'
        except (ValueError,TypeError,KeyError):
            nav_issue='Optional NAV failed date, freshness, structure or numeric validation; valid monthly returns retained'
    return {'symbol':symbol,'currency':'USD','frequency':'monthly','return_type':'issuer_reported_nav_total_return',
        'observed_at':dates[-1],'latest_nav':nav,'latest_nav_unavailable_reason':nav_issue,'observations':[{'date':d,'return':observations[d]} for d in dates],
        'excluded_missing_dates':missing,'source':export_url(symbol),
        'units':'source percentage points divided by 100',
        'limits':'운용사가 현재 제공한 월별 NAV 총수익률. 시장 체결 수익률이 아니며 한국 세금·환전·계좌 비용을 포함하지 않아요. 월별 관측은 월중 최대 손실을 숨길 수 있어요. 현재 빈티지와 현재 선택 자산을 사용한 역사적 비교이며 과거 선정 전략의 예측력 검증이 아니에요.'}
