"""Match reported fund constituents to the same broker taxonomy as user constraints."""
from datetime import timedelta
from . import domain as d
from .decision import source_values

SOURCE='https://openapi.tossinvest.com/openapi-docs/latest/openapi.json'


def apply(market,memberships,receipt=None):
    complete_taxonomy=bool(receipt and receipt.get('as_of')==market['as_of'] and
        receipt.get('expected_root_names') and set(receipt['expected_root_names'])<=set(memberships) and
        not any(body.get('hasNext') or body.get('nextPageToken') for body in memberships.values()))
    mapping={}
    for sector,body in memberships.items():
        if not isinstance(body.get('stocks'),list):raise ValueError('Sector membership list required')
        for row in body['stocks']:mapping.setdefault(row['symbol'].replace('.','-'),set()).add(sector)
    receipts={}
    for symbol,rows in market.get('fund_constituents',{}).items():
        if symbol not in market['assets']:continue
        exposures={};matched=0.;unmatched=[];seen=set();issues=[]
        evidence=source_values(market,'fund_holdings',symbol)
        hold=evidence[0][1] if evidence else {}
        economic=hold.get('economic_exposure',{})
        bounded=(economic.get('method')=='same_date_issuer_nav_and_explicit_usd_notional_v1' and
            economic.get('nav',{}).get('currency')=='USD' and economic['nav'].get('observed_at')==hold.get('observed_at'))
        if not complete_taxonomy:issues.append('root taxonomy completeness not established')
        if not hold.get('observed_at'):issues.append('dated holdings evidence missing')
        if not bounded and hold.get('missing_weight_rows'):issues.append('unresolved holding weights')
        if not bounded and hold.get('other_positions') and any(r.get('weight') is None or r.get('weight',0)<0 or
                r.get('type','').lower() not in {'cash','money market','currency','cash collateral','currency collateral'} for r in hold['other_positions']):
            issues.append('derivative economic exposure unresolved')
        for row in rows:
            ticker=row['symbol'].replace('.','-');w=row['weight'];d.number(w,0)
            if ticker in seen:
                issues.append('ambiguous duplicate constituent');continue
            seen.add(ticker);tags=mapping.get(ticker,set())
            if tags:
                matched+=w
                for tag in tags:exposures[tag]=exposures.get(tag,0)+w
            else:unmatched.append(ticker)
        # Residual includes unclassified equities, cash, derivatives and rounding.
        # A tag match does not establish absent memberships in other sectors.
        # Thus certify only when the provider returned the complete root universe.
        if matched>(economic['equity_fraction'] if bounded else 1)+1e-6:issues.append('reported mapped weights exceed source equity')
        unknown=(economic['gross_exposure_estimate'] if bounded else 1.) if issues else (
            max(0,economic['equity_fraction']-matched)+economic['non_equity_gross_fraction']+economic['reconciliation_residual_fraction'] if bounded else max(0,1-matched))
        if issues:exposures={}
        a=market['assets'][symbol]
        a['sector_estimate_only']=bool(bounded)
        if bounded:
            a['stress_loss']=min(1.,.5*max(1.,economic['gross_exposure_estimate']))
            a['stress_assumption']='보고된 USD 포지션/명목금액 추정치의 50% 가격 충격. 같은 평가기준 가정과 NAV 대조 차이를 반영하며 실제 노출 상한·미래 최대손실 보장 아님.'
        observed=hold.get('observed_at',market['as_of'])
        valid_until=next(f['valid_until'] for f in market['facts'] if f['id']==evidence[0][0]) if evidence else market['as_of']
        a.update(sector_exposures=exposures,sector_complete=unknown<1e-9,
            sector_exposure_unbounded=any(x in issues for x in ('derivative economic exposure unresolved','unresolved holding weights')),
            sector_unknown_fraction=unknown,sector_source=SOURCE,sector_as_of=observed,
            sector_valid_until=min(valid_until,
                (d.day(observed)+timedelta(days=10)).isoformat()))
        receipts[symbol]={'mapped_weight':matched,'unknown_weight':unknown,'unmatched_symbols':unmatched,
            'issues':issues,'holdings_observed_at':hold.get('observed_at'),'taxonomy_observed_at':receipt.get('as_of') if receipt else None,
            'economic_exposure':economic if bounded else None,
            'matched_taxonomy':'Toss root sectors','rule':'동일 티커 구성비를 각 토스 태그에 전량 반영. 중복 태그는 나누지 않음. 잔여 비중은 최악의 한 섹터로 합산.',
            'limits':'수집 시점 공개 태그 대조. 파생 경제노출·미보고 비중·이후 구성 변경은 확정하지 않음.'}
    market['sector_lookthrough']=receipts
    return receipts
