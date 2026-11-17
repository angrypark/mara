"""Two explicit denominators; foreign cash never becomes risk-free KRW."""
def build(profile,market,weights,capital,monthly,pending=False):
    cash={s:w for s,w in weights.items() if s=='CASH' or market['assets'].get(s,{}).get('asset_class')=='cash'}
    invested={s:w for s,w in weights.items() if s not in cash and w>0};fraction=sum(invested.values())
    return {'version':'allocation-sleeves/1','status':'decision_pending' if pending else 'selected',
        'scope':'이번 납입 계획. 실제 보유·가계 현금·부동산을 합산하지 않음. 숫자 제약의 분모는 전체 제안액으로 유지.',
        'capital':capital,'monthly_contribution':monthly,'invested_fraction':fraction,
        'invested_weights':{s:w/fraction for s,w in invested.items()} if fraction else {},
        'rows':[{'symbol':s,'kind':'cash' if s in cash else 'investment','whole_fraction':w,
            'invested_fraction':w/fraction if s in invested and fraction else None,
            'proposal_amount':capital*w,'monthly_amount':monthly*w} for s,w in weights.items() if w>0],
        'usd_buffer_reference_fraction':profile.get('usd_buffer_reference_fraction'),
        'reference_authority':'사용자 예시를 비교 기준으로 해석. 확정 배분·주문 아님.',
        'unknown_asset_classes':[s for s in invested if market['assets'].get(s,{}).get('asset_class','unknown')=='unknown'],
        'cash_warning':'USD_CASH는 달러 현금이며 원화 대비 환율 위험이 있음. CASH는 기준통화 현금. 투자 부분이 0이면 내부 비중은 미정.'}


def validate(analysis):
    from math import isclose
    from .contracts import ContractError
    x=analysis.get('allocation_sleeves')
    if x is None:return  # Older immutable reports have no sleeve extension.
    weights=analysis['selected_weights'];rows=x['rows'];symbols=[r['symbol'] for r in rows]
    def check(ok):
        if not ok:raise ContractError('Inconsistent allocation sleeve denominators or amounts')
    def close(a,b):return isclose(a,b,rel_tol=1e-8,abs_tol=1e-6)
    check(len(symbols)==len(set(symbols)))
    check(set(symbols)=={s for s,w in weights.items() if w>0})
    check(x['status']!='decision_pending' or not weights and not rows)
    check(x['status']!='selected' or close(sum(weights.values()),1))
    fraction=sum(r['whole_fraction'] for r in rows if r['kind']=='investment')
    check(close(fraction,x['invested_fraction']))
    check(set(x['invested_weights'])=={r['symbol'] for r in rows if r['kind']=='investment'})
    for r in rows:
        w=r['whole_fraction'];check(close(w,weights[r['symbol']]))
        check(close(r['proposal_amount'],w*x['capital']) and close(r['monthly_amount'],w*x['monthly_contribution']))
        if r['kind']=='cash':check(r['invested_fraction'] is None)
        else:check(fraction>0 and r['invested_fraction'] is not None and close(r['invested_fraction'],w/fraction) and close(x['invested_weights'][r['symbol']],w/fraction))
