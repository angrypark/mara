"""Same-date issuer NAV + USD holdings/explicit futures notional, with residuals."""
import csv,io
from datetime import datetime
from .research_sources import finite,dated


def holdings(raw,profile,as_of):
    nav=profile['net_assets'];denominator=finite(nav['value'],1)
    if nav['currency']!='USD':raise ValueError('NAV currency')
    rows=list(csv.reader(io.StringIO(raw)))
    observed=datetime.strptime(next(r[1] for r in rows if r and r[0]=='Fund Holdings as of'),'%b %d, %Y').date().isoformat()
    dated(observed,as_of,10)
    if nav['observed_at']!=observed:raise ValueError('NAV/holdings date mismatch')
    start=next(i for i,r in enumerate(rows) if r and r[0]=='Ticker');columns=rows[start]
    required={'Ticker','Name','Sector','Asset Class','Market Value','Notional Value','Currency','Quantity'}
    if not required<=set(columns) or len(set(columns))!=len(columns):raise ValueError('Explicit USD value/notional columns required')
    constituents=[];others=[];seen=set();ended=False;market_value=0.;gross_non_equity=0.;sectors={}
    for row in rows[start+1:]:
        if not row or len(row)==1 and not row[0].strip():ended=True;continue
        if len(row)!=len(columns):
            if not ended or len(row)!=1:raise ValueError('Truncated holdings row')
            continue
        if ended:raise ValueError('Holding after footer')
        r=dict(zip(columns,row));identity=(r['Ticker'],r['Name'],r.get('Exchange'),r['Asset Class'])
        if not r['Ticker'] or not r['Name'] or identity in seen or r['Currency']!='USD':raise ValueError('Holdings identity/currency')
        seen.add(identity);value=finite(r['Market Value']);notional=finite(r['Notional Value']);market_value+=value
        kind=r['Asset Class']
        if kind=='Equity':
            if value<0 or abs(notional-value)>max(1,abs(value)*.00001):raise ValueError('Unsupported equity economics')
            weight=value/denominator
            constituents.append({'symbol':r['Ticker'],'name':r['Name'],'sector':r['Sector'],'weight':weight})
            sectors[r['Sector']]=sectors.get(r['Sector'],0)+weight
        elif kind in {'Cash','Money Market','Cash Collateral and Margins','Futures'}:
            if kind=='Futures' and finite(r['Quantity'])!=0 and notional==0:raise ValueError('Nonzero future needs explicit notional')
            exposure=max(abs(value),abs(notional))/denominator;gross_non_equity+=exposure
            others.append({'name':r['Name'],'type':kind,'market_value_usd':value,'notional_usd':notional,'gross_exposure_fraction':exposure})
        else:raise ValueError('Unsupported economic instrument: '+kind)
    # Small same-date differences are not erased or called exact reconciliation.
    residual=abs(market_value-denominator)/denominator+1/denominator
    if not constituents or residual>.005:raise ValueError('NAV/holdings reconciliation outside 0.5% adapter bound')
    equity=sum(r['weight'] for r in constituents);bound=equity+gross_non_equity+residual
    if bound>1.1:raise ValueError('Gross exposure outside plain equity fund adapter')
    return {'observed_at':observed,'holdings_count':len(constituents),'reported_weight_sum':market_value/denominator,
        'equity_fraction':equity,'sector_weights':sectors,'top_holdings':sorted(constituents,key=lambda r:r['weight'],reverse=True)[:10],
        'constituents':constituents,'other_positions':others,'complete_lookthrough':False,'complete_reported_weights':False,
        'economic_exposure':{'method':'same_date_issuer_nav_and_explicit_usd_notional_v1','nav':nav,
            'nav_source':profile['net_assets_source'],'reported_market_value_usd':market_value,
            'reconciliation_difference_fraction':abs(market_value-denominator)/denominator,'rounding_allowance_usd':1.,
            'reconciliation_residual_fraction':residual,'non_equity_gross_fraction':gross_non_equity,
            'gross_exposure_estimate':bound,'equity_fraction':equity,'status':'estimate_under_valuation_basis_assumption',
            'valuation_basis_assumption':'CSV vendor 가격과 순자산 평가 가격을 비교 가능한 기준으로 가정. 발행사는 가격 기준/시점이 다를 수 있다고 명시하므로 같은 표기일은 가격 기준 일치 증명이 아님.',
            'reconciliation_policy_fraction':.005,'uncertainty':'절대 대조 차이는 추가 가정 여유분이며 상쇄 오차·미보고 gross의 상한을 입증하지 않음. 보고된 포지션을 사용한 조건부 연구 추정.'},
        'limits':'공식 동일일 순자산으로 USD 시장가치/명시 선물 명목금액을 나눔. 원 CSV 비중 결측을 0으로 보충하지 않음. NAV 차이를 잔여 위험에 더하며 비주식 경제노출은 어느 한 섹터에도 속할 수 있다고 검증. 델타/미래 가격·최대손실 보장 아님.'}
