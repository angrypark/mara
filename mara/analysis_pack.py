"""Deterministic decision exhibits. Public returns never masquerade as account P&L."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from . import domain as d
from .decision import household,contributions,source_values
from .portfolio_comparison import compare
from .risk import evaluate

VERSION='mara.analysis/1.0.0'


def small_comparison(value):
    return {**value,'dates':[value['dates'][0],value['dates'][-1]],'results':{
        k:{a:b for a,b in row.items() if a not in ('unit_wealth_path','wealth_path')}
        for k,row in value['results'].items()}}


def build(profile,actual,market,valuation,capital,selected=None):
    h=household(profile);monthly=contributions(profile)['monthly_amount']
    cash=actual['cash'];outside=h.get('outside_emergency_cash')
    # Do not presume a separately entered emergency cash balance is disjoint
    # from the reported account. Display it separately, never double-count it.
    household_stress=[]
    expenses=profile['monthly_expenses']+(h['monthly_debt_payment'] or 0 if h['debt_payment_in_expenses'] in ('no','unknown') else 0)
    for income_fraction in (1.,.7,0.):
        income=profile['monthly_income']*income_fraction
        surplus=income-expenses
        household_stress.append({'income_fraction_assumption':income_fraction,'income':income,'expenses':expenses,
            'surplus_before_investing':surplus,'remaining_after_planned_contribution':surplus-monthly,
            'cash_consumption_if_contributions_pause_6m':max(0,-surplus)*6,
            'reported_account_cash_months_if_income_stops':cash/expenses if expenses else None,
            'affordable_contribution_before_reserve_replenishment':max(0,surplus)})
    declared=h.get('reported_liquid_cash')
    for row in household_stress:
        row['declared_total_cash_months_if_income_stops']=declared/expenses if declared is not None and expenses else None
        row['gap_against_declared_total_cash_if_contributions_pause_6m']=max(0,row['cash_consumption_if_contributions_pause_6m']-declared) if declared is not None else None
    h.update(stress=household_stress,reported_account_cash=cash,reported_outside_emergency_cash=outside,
        reserve_scope='외부 비상금과 계좌 현금의 중복 여부를 가정하지 않고 별도 표시. 입금 전 예정 납입·부동산 자기자본은 유동성에 더하지 않음.',
        property_stress=[{'property_change_assumption':x,'equity_after_shock':h['property_value']*(1+x)-h['mortgage_balance'],
            'equity_loss':-h['property_value']*x,'loan_balance_assumed_fixed':True} for x in (-.1,-.2)] if h['property_value'] is not None and h['mortgage_balance'] is not None else [],
        mortgage_rate_sensitivity={'annual_rate_increase_assumption':.02,'monthly_interest_only_increase':h['mortgage_balance']*.02/12,
            'scope':'원금 고정 단순 이자 민감도. 변동금리 여부·만기·상환방식 미확인으로 실제 상환액 예측 아님'} if h['mortgage_balance'] else None)
    histories=market.get('return_histories',{})
    decision_pending=selected is None
    allocations={'cash_proxy':{'CASH':1}}
    for symbol in ('ITOT','IVV'):
        if symbol in histories and symbol in market['assets']:
            for weight in ((.2,.4,.6) if symbol=='ITOT' else (.4,)):
                allocations[symbol+'_'+str(round(weight*100))]={symbol:weight,'CASH':1-weight}
    if {'ITOT','IVV'}<=histories.keys() and {'ITOT','IVV'}<=market['assets'].keys():
        allocations['ITOT_40_IVV_10']={'ITOT':.4,'IVV':.1,'CASH':.5}
    if profile.get('contribution_risk_preference')=='growth' and {'ITOT','IVV'}<=histories.keys() and {'ITOT','IVV'}<=market['assets'].keys():
        allocations['growth_80_diagnostic']={'ITOT':.4,'IVV':.4,'CASH':.2}
    if selected is not None and all(s in histories or s=='CASH' for s,w in selected.items() if w>0):allocations['proposal']=selected
    if valuation['weights'] and all(s in histories or s=='CASH' for s,w in valuation['weights'].items() if w>0):allocations['actual_weights_proxy']=valuation['weights']
    comparison={'available':False,'reason':'선택 자산과 비교 대안의 검증된 월별 NAV 총수익률을 확보하지 못했어요.'}
    try:
        result=compare(histories,allocations,initial=100,monthly=monthly/capital*100,
            rebalance_months=max(1,round(profile['rebalance_every_days']/30.4375)))
        comparison={'available':True,**small_comparison(result),
            'source_series_hash':hashlib.sha256(d.dumps(histories).encode()).hexdigest(),
            'amount_unit':'기준액=100 USD, 월납입은 계획 납입/기준액 비율. 실제 원화 계좌·확정 투자금·미래 예측 아님',
            'cash_proxy_warning':'역사 비교 CASH는 0% USD 현금 가정. 실제 제안 CASH는 KRW이므로 이 수치를 실제 원화 현금과의 성과 차이로 해석하지 않아요. FX는 별도 충격 시나리오.',
            'feasibility':{name:{'passed':r['passed'],'errors':r['errors'],'missing':r['missing']} for name,w in allocations.items()
                for r in [evaluate(w,profile,market,capital,valuation)]},
            'unavailable_selected_assets':[s for s,w in (selected or {}).items() if w>0 and s!='CASH' and s not in histories]}
        # Same assets, dates and flows; change exactly one declared assumption.
        proposed=allocations.get('proposal')
        anchor={'comparison_anchor':proposed if proposed and any(s!='CASH' and w>0 for s,w in proposed.items()) else allocations.get('ITOT_40',next(w for w in allocations.values() if w.get('CASH',0)<1))}
        sensitivity=[]
        comparison['sensitivity']=sensitivity
        base_rebalance=result['assumptions']['rebalance_months']
        for changed,cost,rebalance,flow,cash_yield in [('cost',0,base_rebalance,monthly/capital*100,0),('cost',50,base_rebalance,monthly/capital*100,0),('rebalance',10,1 if base_rebalance!=1 else 3,monthly/capital*100,0),('rebalance',10,12 if base_rebalance!=12 else 6,monthly/capital*100,0),('contribution',10,base_rebalance,0,0),('cash_yield',10,base_rebalance,monthly/capital*100,.02)]:
            if changed=='contribution' and monthly==0:continue
            v=small_comparison(compare(histories,anchor,initial=100,monthly=flow,rebalance_months=rebalance,cost_bps=cost,cash_annual=cash_yield))
            sensitivity.append({'changed_assumption':changed,'comparison_anchor_weights':anchor['comparison_anchor'],'assumptions':v['assumptions'],'result':v['results']['comparison_anchor']})
        comparison['sensitivity']=sensitivity
    except (ValueError,KeyError,TypeError,StopIteration) as exc:
        comparison['error_type']=type(exc).__name__
        if comparison.get('available'):comparison['sensitivity_unavailable_reason']='추가 민감도 계산이 완료되지 않았어요. 기본 배분 비교와 별개이며 누락된 검증을 통과로 해석하지 않아요.'
    if selected is None:selected={}
    foreign_symbols={s for s in selected if s!='CASH' and market['assets'].get(s,{}).get('currency') not in (None,profile['base_currency'])}
    unknown_currency=[s for s,w in selected.items() if w>0 and s!='CASH' and market['assets'].get(s,{}).get('currency') is None]
    foreign=sum(selected[s] for s in foreign_symbols)
    foreign_equity=sum(selected[s] for s in foreign_symbols if market['assets'][s].get('asset_class')=='equity')
    equity=sum(w for s,w in selected.items() if s!='CASH' and market['assets'].get(s,{}).get('asset_class')=='equity')
    scenarios=[]
    for equity_shock,fx_shock in [(-.2,0),(-.4,0),(-.4,-.15),(-.2,.15),(.1,-.1),(-.5,-.2),(-.7,-.2)]:
        # Non-equity foreign cash has FX exposure only. Domestic cash is unchanged.
        change=equity*equity_shock+foreign*fx_shock+foreign_equity*equity_shock*fx_shock
        scenarios.append({'equity_return_assumption':equity_shock,'foreign_currency_return_in_base_assumption':fx_shock,
            'portfolio_change_fraction':change,'loss_on_proposal_capital':-change*capital,
            'breaches_reported_loss_tolerance':None if profile.get('loss_budget_scope')=='analysis_only' else -change>profile['max_loss_fraction'],
            'breaches_reference_loss_fraction':-change>profile['max_loss_fraction'],
            'breaches_effective_loss_budget':-change>d.loss_budget(profile)['effective_fraction']})
    costs={'status':'account_specific_rates_unconfirmed','assumed_one_way_bps':[0,10,50,100],
        'monthly_non_cash_allocation':monthly*sum(w for s,w in selected.items() if s!='CASH' and market['assets'].get(s,{}).get('asset_class')!='cash'),
        'monthly_cost_sensitivity':[{'bps':b,'base_currency_amount':monthly*sum(w for s,w in selected.items() if s!='CASH' and market['assets'].get(s,{}).get('asset_class')!='cash')*b/10000} for b in (0,10,50,100)],
        'fund_fee':'운용사 NAV 총수익률에 포함. 역사 비교에서 TER 재차 차감하지 않음.',
        'excluded':'개인별 세금·실제 환전 스프레드·수량/소수점 가능 여부. 주문 전 별도 확인.',
        'authority':'연구용 조건부 계획. 주문·사용자 승인·실제 보유 변경 아님'}
    products={}
    for s in sorted(set(selected)|{'ITOT','IVV'}):
        if s=='CASH':continue
        values=source_values(market,'fund_profile',s);hold=source_values(market,'fund_holdings',s)
        if values or hold:products[s]={'profile_fact_ids':[x[0] for x in values],'holdings_fact_ids':[x[0] for x in hold],
            'valuation':'ETF PE/PB는 구성자산의 집계 배수이며 내재가치/안전마진/미래 수익의 입증이 아님',
            'holdings_date':hold[0][1].get('observed_at') if hold else None,
            'weighted_sector_exposure':{k:v*selected.get(s,0) for k,v in hold[0][1]['sector_weights'].items()} if hold else {},
            'top_holdings_weight':sum(x['weight'] for x in hold[0][1]['top_holdings']) if hold and hold[0][1].get('top_holdings') else None}
    for symbol,product in products.items():
        nav=histories.get(symbol,{}).get('latest_nav')
        product['nav_comparison']={'available':False,'reason':'같은 미국 거래일의 NAV와 USD 시세를 대조하지 못했어요.'}
        if not nav:continue
        for fact in market['facts']:
            if fact['id']!='toss-'+symbol:continue
            try:
                quote=json.loads(fact['text'])['quote'];stamp=datetime.fromisoformat(quote['timestamp'])
                if stamp.tzinfo is None or quote['currency']!='USD':continue
                trading_date=stamp.astimezone(ZoneInfo('America/New_York')).date().isoformat()
                price=float(quote['lastPrice'])
                if trading_date==nav['date'] and price>0:
                    product['nav_comparison']={'available':True,'us_trading_date':trading_date,'price_usd':price,
                        'nav_per_share_usd':nav['nav_per_share_usd'],'premium_fraction':price/nav['nav_per_share_usd']-1,
                        'quote_fact_id':fact['id'],'nav_fact_id':'research-fund_history-'+symbol,
                        'limit':'같은 미국 거래일 자료이나 종가/장중 시각 일치 보장 없음. 지수 내재가치/미래 추적 성과/현재 체결을 입증하지 않음.'}
            except (ValueError,KeyError,TypeError):continue
    from .cost_exhibits import build as cost_exhibit
    costs['published_conditions_and_examples']=cost_exhibit(profile,market,selected,capital)
    from .product_comparison import build as product_compare
    costs['product_comparison']=product_compare(profile,market,capital,costs)
    lookthrough=exposures(market,selected)
    from .planning_scenarios import joint_household,cash_hurdle,macro_consistency
    h['joint_stress']=joint_household(profile,h,capital,equity,foreign,foreign_equity,monthly)
    from .monitoring_exercise import exercise
    h['monitoring_exercise']=exercise(profile,h,monthly)
    costs['krw_cash_hurdle']=cash_hurdle(profile,costs)
    from .sleeves import build as sleeve_analysis
    result={'allocation_sleeves':sleeve_analysis(profile,market,selected,capital,monthly,decision_pending),'risk_budget':d.loss_budget(profile),'macro_consistency':macro_consistency(market),'lookthrough':lookthrough,'schema_version':VERSION,'as_of':market['as_of'],'selected_weights':selected,
        'household':h,'comparison':comparison,'products':products,'costs':costs,
        'fx_stress':{'formula':'equity_weight*r + foreign_weight*f + foreign_equity_weight*r*f',
            'base_currency':profile['base_currency'],'capital':capital,'foreign_fraction':foreign,'equity_fraction':equity,
            'scenarios':scenarios,'unknown_currency_assets':unknown_currency,'limitation':'결정론적 충격 가정. 실제 FX 역사·VaR·예측확률·최대손실 보증 아님. 외화 주식은 동일 통화 충격을 가정.'},
        'source_market_as_of':market['as_of'],'reproduction':'mara.analysis_pack.build + immutable market.return_histories; original issuer response hashes in source facts'}
    from .quantitative_verifier import verify
    receipt=verify({'as_of':market['as_of'],'analysis':result},market)
    result['comparison']['independent_replay']={k:v for k,v in receipt.items() if k not in ('recomputed','recomputed_sensitivities')}
    result['comparison']['independent_replay']['verified_portfolios']=list(receipt.get('recomputed',{})) if receipt['status']=='passed' else []
    result['comparison']['independent_replay']['verified_name_count']=len(result['comparison']['independent_replay']['verified_portfolios'])
    result['comparison']['independent_replay']['distinct_positive_weight_count']=len({tuple(sorted((s,float(w)) for s,w in allocations[name].items() if w>0)) for name in result['comparison']['independent_replay']['verified_portfolios']})
    result['comparison']['independent_replay']['stage_scope']='현재 selected_weights의 비교. 결정 전에는 proposal이 없고 지수 비중은 벤치마크일 뿐이에요. 리더의 실제 제안 비중으로 최종 검증에서 다시 계산해요.'
    from .krw_comparison import build as krw_compare
    conditions=costs['published_conditions_and_examples']
    result['krw_comparison']={'available':False,'reason':'KRW 기준 공개 비용과 환율 원문이 있어야 원화 비교를 완료할 수 있어요.'}
    if profile['base_currency']=='KRW' and conditions.get('available'):
        rates=conditions['published_rates'];fee=((1+rates['us_stock_standard_commission_fraction'])*(1+rates['fx_regular_effective_spread_fraction'])-1)*10000
        result['krw_comparison']=krw_compare(market,allocations,capital,monthly,max(1,round(profile['rebalance_every_days']/30.4375)),fee)
        result['krw_comparison']['cost_source_fact_id']=rates['fact_id']
    if selected:
        result['selected_comparison']={
            'weights':dict(selected),'capital':capital,'base_currency':profile['base_currency'],
            'numeric_checks':evaluate(selected,profile,market,capital,valuation),
            'numeric_scenario_assumptions':{s:market['assets'].get(s,{}).get('stress_loss') for s,w in selected.items() if w>0 and s!='CASH'},
            'fx_stress':result['fx_stress'],'allocation_sleeves':result['allocation_sleeves'],
            'historical_performance':{'available':False,'reason':'이 객체는 동일 기준액의 결정론적 비중·위험 비교예요. 역사 수익률은 계산하지 않으며 별도 검증된 comparison/krw_comparison만 해당 범위에서 인용해요.'},
            'scope':'수치 제약과 가정별 충격 비교. 기업 가격 타당성·기대수익·과거 성과·통계적 위험 또는 대안 우월성의 입증이 아니에요. numeric_checks는 상품별 stress_loss 합계이며 fx_stress는 별도 주가·환율·교차항 시나리오예요.'}
    return result


from .coverage import COVERAGE,coverage_ledger


def exposures(market,weights):
    rows=market.get('fund_constituents',{});underlying={};missing=[];used={}
    for symbol,weight in weights.items():
        if not weight or symbol=='CASH':continue
        asset=market['assets'].get(symbol,{})
        if asset.get('asset_class')=='cash':continue
        if asset.get('kind') in {'STOCK','FOREIGN_STOCK','REIT','DEPOSITARY_RECEIPT'}:
            underlying[symbol]=underlying.get(symbol,0)+weight
        elif symbol in rows:
            used[symbol]={r['symbol']:r['weight'] for r in rows[symbol]}
            for r in rows[symbol]:underlying[r['symbol']]=underlying.get(r['symbol'],0)+weight*r['weight']
        else:missing.append(symbol)
    overlap=[]
    for i,a in enumerate(used):
        for b in list(used)[i+1:]:
            overlap.append({'left':a,'right':b,'reported_equity_overlap':sum(min(w,used[b].get(s,0)) for s,w in used[a].items()),
                'definition':'sum min(unscaled issuer constituent weights), not percentage of portfolio'})
    top=sorted(underlying.items(),key=lambda x:x[1],reverse=True)[:10]
    return {'available':not missing,'missing_assets':missing,'constituent_count':len(underlying),
        'portfolio_reported_equity_weight':sum(underlying.values()),
        'top_underlying_positions':[{'symbol':s,'portfolio_weight':w} for s,w in top],
        'largest_underlying_weight':top[0][1] if top else 0.,'fund_overlap':overlap,
        'source_hash':hashlib.sha256(d.dumps(rows).encode()).hexdigest(),
        'limitations':'운용사 전체 CSV의 보고된 주식 비중과 직접 보유를 합산. 현금·파생상품·결측 비중은 주식으로 가정하지 않음. 반올림·종목 클래스 차이가 있고 완전한 파생 look-through 아님.'}
