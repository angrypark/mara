"""Explicit household and KRW hurdle scenarios; no estimated probabilities or forecasts."""


def joint_household(profile,household,capital,equity,foreign,foreign_equity,monthly):
    expenses=household['stress'][0]['expenses'];cash=household['reported_account_cash']
    property_value=household.get('property_value');loan=household.get('mortgage_balance');rows=[]
    for income_fraction,rate_increase in ((.7,0),(0,0),(.7,.02)):
        income=profile['monthly_income']*income_fraction
        extra_interest=(loan*rate_increase/12) if loan is not None else None
        if rate_increase and extra_interest is None:continue
        expenses_stressed=expenses+(extra_interest or 0)
        deficit=max(0,expenses_stressed-income)*6
        gap=max(0,deficit-cash)
        stock_shock=-.5;fx_shock=-.2
        portfolio_return=equity*stock_shock+foreign*fx_shock+foreign_equity*stock_shock*fx_shock
        rows.append({'income_fraction_assumption':income_fraction,'property_return_assumption':-.2,
            'equity_return_assumption':stock_shock,'foreign_currency_return_assumption':fx_shock,
            'mortgage_rate_increase_assumption':rate_increase,'months_assumption':6,
            'monthly_income':income,'monthly_expenses':expenses_stressed,
            'additional_monthly_interest_assumption':extra_interest,
            'property_equity_loss':property_value*.2 if property_value is not None else None,
            'proposal_loss_if_funded':-capital*portfolio_return,
            'cash_needed_if_contributions_paused':deficit,
            'gap_against_reported_account_cash_only':gap,
            'monthly_affordable_contribution_before_reserve_replenishment':max(0,income-expenses_stressed),
            'income_needed_to_resume_planned_contribution':expenses_stressed+monthly,
            'income_needed_with_six_month_cash_gap_replenishment':expenses_stressed+monthly+gap/6,
            'action_boundary':'납입 가능액은 필수 지출 이후 잉여. 이미 사용한 현금 보충을 우선하면 재개 가능액이 더 낮아짐. 실제 소득·잔고 변화 확인 후 재평가.'})
    return {'scenarios':rows,'scope':'6개월 동시 충격 가정. 부동산 평가손실·조건부 제안 손실·생활비 지급을 별도 표시하며 합산 현금 부족액으로 부르지 않음.',
        'liquidity_basis':'확인된 계좌 현금만 비교. 외부 비상금·부동산 매각·미입금 예정 납입은 더하지 않음. 이미 지출에 포함한 기존 원리금은 다시 차감하지 않음.',
        'limitations':'충격 확률·최악 손실·강제 매도 예측 아님. 금리 +2%p는 대출 원금 고정 단순 이자 추가 가정이며 실제 금리 유형/원리금 상환 조건은 미확인. 6개월은 연구 시나리오이지 사용자에게 새로 부과한 의무 비상금 기간이 아님.'}


def cash_hurdle(profile,costs):
    published=costs.get('published_conditions_and_examples',{})
    if profile['base_currency']!='KRW' or not published.get('available'):
        return {'available':False,'reason':'KRW 기준 공개 비용 조건이 없어 원화 현금 대비 손익분기 예시를 계산하지 않음'}
    rates=published['published_rates'];fee=rates['us_stock_standard_commission_fraction']
    rows=[]
    for cash_return in (0,.02,.04):
        for fx_return in (-.1,0,.1):
            entry=(1+fee)*(1+rates['fx_regular_effective_spread_fraction'])
            # Compare equal initial KRW, marked to KRW at year end; not a sale.
            hurdle=(1+cash_return)*entry/(1+fx_return)-1
            rows.append({'krw_cash_one_year_return_assumption':cash_return,'usd_krw_one_year_change_assumption':fx_return,
                'required_usd_nav_total_return_to_match_cash':hurdle})
    return {'available':True,'horizon_years_assumption':1,'scenarios':rows,
        'formula':'required USD return = (1 + KRW cash return) * (1 + entry commission) * (1 + entry FX spread) / (1 + USDKRW change) - 1',
        'fee_source_fact_id':rates['fact_id'],'entry_commission_fraction':fee,
        'entry_fx_spread_fraction':rates['fx_regular_effective_spread_fraction'],
        'limits':'고정 1회 납입의 1년 말 원화 평가액 손익분기 예시. 실제 계좌 현금 이율·환율 예상·역사적 KRW 성과가 아님. 월별 적립/매도/출금 환전/개인 세금/시장 스프레드는 제외. NAV 총수익률에 운용 보수를 재차 차감하지 않음. 이 표만으로 기대 초과수익·적정 주식 비중을 정하지 않음.'}


def macro_consistency(market):
    import json,re,math
    from decimal import Decimal,ROUND_HALF_UP
    index=None;release=None;ids=[]
    for fact in market['facts']:
        try:value=json.loads(fact['text'])
        except (ValueError,TypeError):continue
        if not isinstance(value,dict):continue
        if fact.get('research_tool')=='bls' and value.get('series')=='CUSR0000SA0':index=value;ids.append(fact['id'])
        if fact.get('research_tool')=='release_notes' and value.get('id','').startswith('bls-cpi-'):
            release=value;ids.append(fact['id'])
    unavailable={'available':False,'reason':'동일 기간 CPI 계절조정 지수와 공식 발표 월변화 대조 자료가 없어요.'}
    if not index or not release or index.get('unit')!='index 1982-84=100, seasonally adjusted':return unavailable
    obs=release.get('observations',{});month=obs.get('period') if isinstance(obs,dict) else None
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month) or month>market['as_of'][:7]:return unavailable
    observations=index.get('observations')
    if not isinstance(observations,list) or any(not isinstance(r,dict) or 'month' not in r or type(r.get('value')) not in (int,float) or not math.isfinite(r['value']) for r in observations):return unavailable
    if type(obs.get('all_items_monthly_change_percent_sa')) not in (int,float) or not math.isfinite(obs['all_items_monthly_change_percent_sa']):return unavailable
    year,number=map(int,month.split('-'))
    prior=f'{year-1}-12' if number==1 else f'{year}-{number-1:02}'
    values={r['month']:r['value'] for r in observations}
    if month not in values or prior not in values or values[prior]<=0:return unavailable
    calculated=(Decimal(str(values[month]))/Decimal(str(values[prior]))-1)*100
    rounded=calculated.quantize(Decimal('.1'),rounding=ROUND_HALF_UP)
    reported=Decimal(str(obs['all_items_monthly_change_percent_sa']))
    return {'available':True,'series':'CUSR0000SA0','period':month,'previous_period':prior,
        'index_current':values[month],'index_previous':values[prior],
        'calculated_monthly_change_percent':float(calculated),'rounded_one_decimal_percent':float(rounded),
        'published_monthly_change_percent':float(reported),'agrees_at_published_precision':rounded==reported,
        'source_fact_ids':ids,'formula':'(current seasonally adjusted index / previous month index - 1) * 100, rounded to one decimal percent',
        'limits':'반올림 정밀도 대조이며 원자료의 독립 검증이 아님. 지표·조정 여부·월과 현재 빈티지에 한정. 전년비 결측을 대체하지 않음.'}
