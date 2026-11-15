"""Indicative cash contribution plans, never broker order requests."""
import json,math
from .decision import contributions


def build(profile,market,weights,capital):
    published=None
    for fact in market['facts']:
        if fact.get('research_tool')!='release_notes':continue
        try:value=json.loads(fact['text'])
        except (ValueError,TypeError):continue
        if value.get('id','').startswith('toss-us-fees-'):published={'fact_id':fact['id'],**value['observations']}
    if not published:return {'available':False,'reason':'현재 유효한 공개 기본 수수료와 환전 조건을 검증하지 못했어요.'}
    if profile['base_currency']!='KRW' or any(market['assets'].get(s,{}).get('asset_class')!='equity' or market['assets'].get(s,{}).get('currency')!='USD' for s,w in weights.items() if w>0 and s!='CASH'):
        return {'available':False,'reason':'이 비용 예시는 KRW로 납입하는 USD 주식·ETF에만 적용해요. 외화 현금·다른 자산은 별도 계산이 필요해요.'}
    missing=[s for s,w in weights.items() if s!='CASH' and w>0 and
        (type(market['prices'].get(s,{}).get('price')) not in (int,float) or not math.isfinite(market['prices'][s]['price']) or market['prices'][s]['price']<=0)]
    if missing:return {'available':False,'reason':'선택 자산의 유효한 기준통화 가격이 없어 수량과 비용 예시를 완료하지 못했어요.','missing_prices':missing,'published_rates':published}
    scenarios=[];monthly=contributions(profile)['monthly_amount']
    for name,fx in [('regular_fx_hours',published['fx_regular_effective_spread_fraction']),('outside_fx_hours',published['fx_outside_effective_spread_fraction'])]:
        commission=published['us_stock_standard_commission_fraction'];rows=[];spent=0.;fees=0.
        for symbol,weight in weights.items():
            if symbol=='CASH' or not weight:continue
            price=market['prices'].get(symbol,{}).get('price')
            # KRW conversion at the frozen mid quote, full share illustration.
            cash_per_share=price*(1+commission)*(1+fx)
            units=math.floor(capital*weight/cash_per_share)
            gross=units*cash_per_share;asset_value=units*price
            rows.append({'symbol':symbol,'units':units,'frozen_base_currency_price':price,
                'asset_value':asset_value,'estimated_cash_needed':gross,'estimated_fee_fx_cost':gross-asset_value,
                'rule':'참고용 온주 계산. 실제 주문 단위·당시 시세·계좌 적용률·입금 확인 전 주문으로 사용할 수 없음.'})
            spent+=gross;fees+=gross-asset_value
        monthly_non_cash=monthly*(1-weights.get('CASH',0))
        scenarios.append({'name':name,'commission_fraction':commission,'fx_spread_fraction':fx,
            'monthly_cost_at_target_notional':monthly_non_cash*((1+commission)*(1+fx)-1),
            'first_contribution_integer_illustration':rows,'cash_remaining':capital-spent,'estimated_cost_total':fees})
    # A separate, disclosed example isolates the effect of using deposits to correct drift.
    desired_stock=capital*(1-weights.get('CASH',0));drift_overweight=capital*.05
    return {'available':True,'published_rates':published,'scenarios':scenarios,
        'deposit_vs_sale_example':{'scope':'가상의 주식 비중 5%p 초과 예. 실제 계좌가 초과 보유했다는 뜻 아님.',
            'assumed_overweight_value':drift_overweight,'sale_commission_at_standard_rate':drift_overweight*published['us_stock_standard_commission_fraction'],
            'deposit_to_cash_needed_to_restore_target':drift_overweight/(1-weights.get('CASH',0)) if desired_stock else None,
            'limits':'매도는 실현손익·세금·규제비용을 만들 수 있음. 현금 납입 조정은 해당 매도 비용을 피하지만 새 현금과 시간이 필요. 단순 불변 가격 가정.'},
        'not_included':['10 USD 이하 주문 수수료 면제는 예시에 미반영; 공개 기본률로 계산','계좌별 할인·최소/소수점 주문 지원','현 시점 시장 스프레드와 슬리피지','매도 규제비용·개인별 배당/양도 세금'],
        'authority':'illustrative_only_no_order_authorization'}
