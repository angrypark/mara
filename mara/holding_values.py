"""Alternative concentration basis from every reported USD asset market value."""
import csv,io
from decimal import Decimal,InvalidOperation
from datetime import datetime
from .research_sources import dated


def concentration(raw,as_of):
    rows=list(csv.reader(io.StringIO(raw)));date=datetime.strptime(next(r[1] for r in rows if r and r[0]=='Fund Holdings as of'),'%b %d, %Y').date().isoformat();dated(date,as_of,10)
    start=next(i for i,r in enumerate(rows) if r and r[0]=='Ticker');header=rows[start]
    required={'Ticker','Asset Class','Market Value','Currency','Market Currency','Name','Exchange'}
    if not required<=set(header) or len(set(header))!=len(header):raise ValueError('Incomplete market-value columns')
    total=Decimal(0);equities=[];seen=set();count=0;ended=False
    for row in rows[start+1:]:
        if not row or len(row)==1 and not row[0].strip():ended=True;continue
        if len(row)!=len(header):
            if not ended or len(row)!=1:raise ValueError('Truncated constituent row')
            continue
        if ended:raise ValueError('Unexpected constituent after footer')
        r=dict(zip(header,row));symbol=r['Ticker'];identity=(symbol,r['Name'],r['Exchange'],r['Asset Class'])
        if not symbol or not r['Name'] or identity in seen:raise ValueError('Ambiguous constituent identity')
        seen.add(identity)
        if r['Currency']!='USD' or r['Market Currency']!='USD':raise ValueError('Market-value currency mismatch')
        try:value=Decimal(r['Market Value'].replace(',',''))
        except InvalidOperation:raise ValueError('Missing market value') from None
        if not value.is_finite() or value<0:raise ValueError('Unsupported market value')
        total+=value;count+=1
        if r['Asset Class']=='Equity':equities.append((symbol,value,r['Name'],r['Exchange']))
    if total<=0 or len(equities)<10:raise ValueError('Insufficient market values')
    top=sorted(equities,key=lambda x:x[1],reverse=True)[:10]
    return {'available':True,'observed_at':date,'currency':'USD','basis':'reported_asset_market_value_sum',
        'all_rows_numeric':True,'row_count':count,'equity_rows':len(equities),'denominator_usd':float(total),
        'top_equity_count':10,'top_equity_fraction':float(sum((x[1] for x in top),Decimal(0))/total),
        'top_equities':[{'symbol':s,'name':name,'exchange':exchange,'market_value_usd':float(v),'fraction_of_reported_asset_values':float(v/total)} for s,v,name,exchange in top],
        'limits':'전량 CSV의 USD 시장가치 합계가 분모. 순자산/NAV 또는 공시된 Weight 복구가 아님. 파생상품은 시장가치만 포함하고 명목 노출·미공시 부채를 포함하지 않음. 소수 구성의 원래 비중 결측은 그대로 보존. 티커만으로 합치지 않고 종목명·거래소가 다른 행은 별도 보고 포지션으로 보존하며 기업 단위 집중도와 다름. 동일 날짜/분모 정의로만 상대 비교.'}
