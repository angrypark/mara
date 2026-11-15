"""Comparable product costs and explicit decision boundaries, not optimized returns."""
import math
from datetime import date
from .decision import source_values


def build(profile,market,capital,costs):
    rows={};ids=[]
    def valid_date(value):
        try:return isinstance(value,str) and date.fromisoformat(value)<=date.fromisoformat(market['as_of'])
        except (ValueError,TypeError):return False
    for symbol in ('ITOT','IVV'):
        profiles=source_values(market,'fund_profile',symbol);holdings=source_values(market,'fund_holdings',symbol)
        if not profiles or not holdings:return {'available':False,'reason':'두 상품의 동일 범위 보수·집중도 원문이 필요해요.'}
        fid,p=profiles[0];hid,h=holdings[0];fee=p.get('expense_ratio');spread=p.get('issuer_metrics',{}).get('thirtyDayMedianBidAskSpread',{}).get('value')
        top=h.get('top_holdings',[])
        metric=p.get('issuer_metrics',{}).get('thirtyDayMedianBidAskSpread',{})
        if p.get('symbol')!=symbol or metric.get('unit')!='fraction' or not all(valid_date(x) for x in (p.get('observed_at'),p.get('expense_observed_at'),metric.get('observed_at'))):
            return {'available':False,'reason':'상품 정체·보수/호가 단위·관측 날짜 검증을 통과하지 못했어요.'}
        if not isinstance(top,list) or any(not isinstance(x,dict) or type(x.get('weight')) not in (int,float) or not math.isfinite(x['weight']) or not 0<=x['weight']<=1 for x in top):
            return {'available':False,'reason':'보고 구성 비중이 유효하지 않아요.'}
        total=h.get('reported_weight_sum');complete=(h.get('complete_reported_weights') is True and h.get('missing_weight_rows')==[] and type(total) in (int,float) and math.isfinite(total) and 0.97<=total<=1.03 and sum(x['weight'] for x in top)<=total+1e-9 and valid_date(h.get('observed_at')))
        if not top or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in (fee,spread)):return {'available':False,'reason':'상품 비용·상위 구성 비중의 유효한 수치가 필요해요.'}
        rows[symbol]={'alternative_concentration':h.get('market_value_concentration',{}),'reported_concentration_verified':complete,'expense_fraction':fee,'median_full_spread_fraction':spread,'top_reported_holdings_fraction':sum(x['weight'] for x in top),'top_reported_holdings_count':len(top),'holdings_observed_at':h.get('observed_at'),'profile_observed_at':p.get('observed_at'),'spread_observed_at':p.get('issuer_metrics',{}).get('thirtyDayMedianBidAskSpread',{}).get('observed_at')};ids.extend([fid,hid])
    published=costs.get('published_conditions_and_examples',{})
    if not published.get('available'):return {'available':False,'reason':'같은 공개 거래 비용 조건이 필요해요.'}
    rates=published['published_rates'];commission=rates['us_stock_standard_commission_fraction'];fx=rates['fx_regular_effective_spread_fraction'];ids.append(rates['fact_id'])
    notional=capital*.4
    for symbol,row in rows.items():
        row.update(equal_asset_notional=notional,annual_ter_cost_at_constant_notional=notional*row['expense_fraction'],new_money_entry_cost_estimate=notional*((1+commission)*(1+fx)*(1+row['median_full_spread_fraction']/2)-1))
    a,b=rows['ITOT'],rows['IVV'];comparable=a['reported_concentration_verified'] and b['reported_concentration_verified'] and a['top_reported_holdings_count']==b['top_reported_holdings_count'] and a['holdings_observed_at']==b['holdings_observed_at']
    basis='reported_weight_fraction'
    for row in rows.values():row['comparison_top_fraction']=row['top_reported_holdings_fraction']
    if not comparable:
        def valid_alternative(value):
            if not isinstance(value,dict) or value.get('available') is not True or value.get('all_rows_numeric') is not True or value.get('basis')!='reported_asset_market_value_sum' or value.get('currency')!='USD' or not valid_date(value.get('observed_at')):return False
            top=value.get('top_equities');denom=value.get('denominator_usd');fraction=value.get('top_equity_fraction')
            if not isinstance(top,list) or len(top)!=10 or value.get('top_equity_count')!=10 or type(denom) not in (int,float) or not math.isfinite(denom) or denom<=0 or type(fraction) not in (int,float) or not math.isfinite(fraction) or not 0<=fraction<=1:return False
            if any(not isinstance(x,dict) or type(x.get('market_value_usd')) not in (int,float) or not math.isfinite(x['market_value_usd']) or not 0<=x['market_value_usd']<=denom for x in top):return False
            return math.isclose(sum(x['market_value_usd'] for x in top)/denom,fraction,abs_tol=1e-9,rel_tol=0)
        values=[row['alternative_concentration'] for row in rows.values()]
        if all(valid_alternative(x) for x in values) and values[0]['observed_at']==values[1]['observed_at']:
            comparable=True;basis='reported_asset_market_value_sum'
            for row in rows.values():row['comparison_top_fraction']=row['alternative_concentration']['top_equity_fraction']
    switch_fraction=2*commission+(a['median_full_spread_fraction']+b['median_full_spread_fraction'])/2
    savings=a['expense_fraction']-b['expense_fraction']
    horizons=[1,2,5,10]
    boundary=[{'years_assumption':years,'minimum_annual_fee_saving_bps':switch_fraction/years*10000,'current_annual_fee_saving_bps':savings*10000,'fee_savings_exceed_switch_estimate':savings*years>switch_fraction} for years in horizons]
    return {'available':True,'currency':profile['base_currency'],'products':rows,'source_fact_ids':ids,
        'comparison_basis':'같은 계획액의 40% 명목액을 일정하게 유지한 비용 예시. 현재 비중·주문 지시·미래 수익 예상이 아님. 1/2/5/10년은 민감도 기간이며 사용자의 매도 시점이 아님.',
        'switch_existing_ITOT_to_IVV':{'asset_notional':notional,'estimated_commission_and_half_spreads':notional*switch_fraction,'annual_ter_saving_at_constant_notional':notional*savings,'break_even_years':switch_fraction/savings if savings>0 else None,'boundaries':boundary,'formula':'switch cost/notional = two commissions + half each reported median spread; required annual TER saving = this fraction / years'},
        'new_money_ivv_entry_cost_minus_itot':b['new_money_entry_cost_estimate']-a['new_money_entry_cost_estimate'],
        'reported_concentration_comparable':comparable,'concentration_comparison_basis':basis,'concentration_basis_limit':'원래 공시 비중이 완전할 때 그 비중으로 비교. 그렇지 않으면 양쪽 전량 USD 시장가치 합계를 같은 분모 정의로 사용. 대체 분모는 NAV나 명목 파생 노출이 아니며 원래 비중 결측은 해소된 것으로 바꾸지 않음.',
        'ivv_minus_itot_top_holdings_fraction':b['comparison_top_fraction']-a['comparison_top_fraction'] if comparable else None,
        'decision_rule_interpretation':'연구 규칙 제안: 같은 광범위 분산 목표에서 비용·집중도 우위를 이유로 신규 자금 IVV 선호로 바꾸려면 동일 명목액의 진입비용·보수·같은 날짜와 범위의 상위 집중도 모두 악화되지 않고 적어도 하나가 개선돼야 함. 기존 ITOT 교체는 추가로 보유 가정 기간의 절감이 교체 비용을 넘어야 함. 조건 불충족은 열등한 미래 수익의 입증이 아니며 대형주 목표를 새로 채택하는 별도 판단은 열어둠.',
        'new_money_cost_and_concentration_dominance':None if not comparable else b['new_money_entry_cost_estimate']<=a['new_money_entry_cost_estimate'] and b['expense_fraction']<=a['expense_fraction'] and b['comparison_top_fraction']<=a['comparison_top_fraction'] and (b['new_money_entry_cost_estimate']<a['new_money_entry_cost_estimate'] or b['expense_fraction']<a['expense_fraction'] or b['comparison_top_fraction']<a['comparison_top_fraction']),
        'limits':'정책 규칙은 투자자의 확인된 견해가 아닌 시스템의 검토 가능한 해석. 운용 보수는 NAV 역사 수익에 이미 포함돼 재차 차감하지 않음. 거래량 가중/즉시 호가 아닌 30일 중앙 스프레드; 교체는 USD를 유지한다고 가정해 환전 제외. 개인 세금·규제비용·시장충격 제외로 실제 교체비용 하한도 보장하지 않음. 상위 일부 집중도는 전체 위험·분산 우열을 대신하지 않음.'}
