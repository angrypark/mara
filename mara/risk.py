"""Versioned portfolio evaluation, independent of model judgment and execution."""
import math
import statistics
from . import domain as d
from .decision import assessment,contributions,household

VERSION='portfolio-risk-1.1'


def history_metrics(w, market):
    """Constant-weight, daily rebalanced hypothetical total returns; never actual P&L."""
    missing={'status':'unavailable','annualized_volatility':None,'sharpe':None,
             'max_drawdown':None,'benchmark_beta':None,'pairwise_correlations':None,
             'reason':'동일 기간·기준 통화의 배당/분할 반영 일별 수익률과 현금·무위험 수익률이 필요해요.'}
    h=market.get('risk_history')
    if not h: return missing
    try:
        dates=h['dates']; n=len(dates)
        if n<60 or n>2520 or sorted(set(dates))!=dates: raise ValueError()
        if h['base_currency']!=market['base_currency'] or h['frequency']!='daily' or h['return_type']!='total_return': raise ValueError()
        if not h['source'].startswith('https://') or not dates[-1]<=h['known_at']<=market['as_of']: raise ValueError()
        for date in dates: d.day(date)
        if (d.day(market['as_of'])-d.day(dates[-1])).days>7: raise ValueError()
        series={s:h['returns'][s] for s,v in w.items() if v>0}
        rf=h['risk_free_returns']
        for values in list(series.values())+[rf]:
            if len(values)!=n: raise ValueError()
            for value in values: d.number(value,-0.999999)
        returns=[sum(w[s]*series[s][i] for s in series) for i in range(n)]
        excess=[r-f for r,f in zip(returns,rf)]
        vol=statistics.stdev(returns)*math.sqrt(252)
        excess_vol=statistics.stdev(excess)
        wealth=peak=1.; drawdown=0.
        for r in returns:
            wealth*=1+r; peak=max(peak,wealth); drawdown=max(drawdown,1-wealth/peak)
        def covariance(a,b):
            am,bm=statistics.mean(a),statistics.mean(b)
            return sum((x-am)*(y-bm) for x,y in zip(a,b))/(n-1)
        correlations={}
        names=sorted(s for s in series if s!='CASH')
        for i,a in enumerate(names):
            for b in names[i+1:]:
                scale=statistics.stdev(series[a])*statistics.stdev(series[b])
                correlations[a+'/'+b]=covariance(series[a],series[b])/scale if scale else None
        beta=None
        benchmark=h.get('benchmark_returns')
        if benchmark is not None:
            if len(benchmark)!=n: raise ValueError()
            for r in benchmark: d.number(r,-0.999999)
            variance=statistics.variance(benchmark)
            beta=covariance(returns,benchmark)/variance if variance else None
        return {'status':'available','observations':n,'start':dates[0],'end':dates[-1],
                'source':h['source'],'annualized_volatility':vol,
                'sharpe':statistics.mean(excess)/excess_vol*math.sqrt(252) if excess_vol else None,
                'max_drawdown':drawdown,'benchmark_beta':beta,'pairwise_correlations':correlations,
                'method':'현재 비중을 매일 리밸런싱한 가상 과거 수익률, 연 252일. 비용·세금 제외. 실제 성과나 미래 예측이 아니에요.'}
    except (KeyError,TypeError,ValueError,OverflowError,statistics.StatisticsError):
        return dict(missing,reason='수익률 자료의 기간·통화·출처·완전성 검증에 실패했어요.')


def evaluate(w, p, m, capital, actual=None):
    base=d.suitability(w,p,m,capital)
    errors=list(base['errors']); missing=[]; warnings=[]
    c=p.get('criteria',{})
    sectors={}; classes={}; currencies={}; unknown_sector=unknown_class=0.
    fee=0.; unknown_fee=0.; illiquid=0.
    for symbol,weight in w.items():
        if not weight: continue
        if symbol=='CASH':
            classes['cash']=classes.get('cash',0)+weight; currencies[p['base_currency']]=currencies.get(p['base_currency'],0)+weight
            continue
        a=m['assets'].get(symbol,{})
        kind=a.get('asset_class','unknown')
        classes[kind]=classes.get(kind,0)+weight
        if kind=='unknown': unknown_class+=weight
        currency=a.get('currency','unknown')
        currencies[currency]=currencies.get(currency,0)+weight
        if a.get('liquid') is not True: illiquid+=weight
        if a.get('eligible') is False: errors.append('편입 불가 종목: '+symbol)
        if a.get('expense_ratio') is None: unknown_fee+=weight
        else: fee+=weight*a.get('expense_ratio',0)
        exposures=a.get('sector_exposures')
        if exposures is None or a.get('sector_valid_until','')<m['as_of']:
            # Bonds also need sector/issuer data when exclusions are requested.
            unknown_sector+=weight
        else:
            for name,share in exposures.items(): sectors[name]=sectors.get(name,0)+weight*share
            # Provider tags may overlap. Never divide multi-sector membership equally.
            if not a.get('sector_complete',False): unknown_sector+=weight
    equity=classes.get('equity',0)
    foreign=sum(v for k,v in currencies.items() if k not in (p['base_currency'],'unknown'))
    if c:
        if w.get('CASH',0)+1e-9<c['min_cash_fraction']: errors.append('최소 현금 비중 미달')
        if equity>c['max_equity_fraction']+1e-9: errors.append('주식 비중 상한 초과')
        if unknown_class and c['max_equity_fraction']<1: missing.append('자산군 미분류로 주식 비중 상한을 확인할 수 없어요.')
        if foreign>c['max_foreign_fraction']+1e-9: errors.append('외화 표시 자산 비중 상한 초과')
        if currencies.get('unknown',0) and c['max_foreign_fraction']<1: missing.append('통화 미확인 자산이 있어요.')
        for sector,weight in sectors.items():
            if weight>c['max_sector_fraction']+1e-9: errors.append('섹터 상한 초과: '+sector)
            if sector in c['excluded_sectors'] and weight>1e-9: errors.append('제외 섹터 포함: '+sector)
        # Unknown exposure can all belong to one sector. If even that bound is
        # below the cap, missing labels cannot make the proposed cap fail.
        sector_upper=max(sectors.values(),default=0)+unknown_sector
        if unknown_sector and (sector_upper>c['max_sector_fraction']+1e-9 or c['excluded_sectors']):
            missing.append('ETF 내부 구성 또는 섹터 자료가 부족해 섹터 제한을 검증할 수 없어요.')
    risky=[v for s,v in w.items() if s!='CASH' and m['assets'].get(s,{}).get('asset_class')!='cash' and v>0]
    actual_risky=any(v>0 and s!='CASH' and m['assets'].get(s,{}).get('asset_class')!='cash'
                     for s,v in (actual or {}).get('weights',{}).items())
    readiness=assessment(w,m)
    if readiness is not None:
        missing.extend(x['subject']+': '+x['reason'] for x in readiness['blockers'])
    elif m.get('coverage',{}).get('actionable_risky_allocation') is False and (risky or actual_risky):
        missing.append('기업·시장 근거의 적합성 및 거래·위험 자료 검토가 아직 끝나지 않았어요. 추가 수집 성공만으로 위험자산 제안을 확정하지 않아요.')
    invested=sum(risky); hhi=sum((v/invested)**2 for v in risky) if invested else None
    contribution=contributions(p);family=household(p)
    monthly_contribution=contribution['monthly_amount']
    surplus=family['monthly_surplus_before_investing']
    if family['cashflow_complete'] is False:warnings.append('담보대출 상환액이 월 지출에 포함됐는지 미확인이에요. 납입 지속 가능성의 조건으로 확인해요.')
    if p.get('funding_source')=='future_income' and monthly_contribution>max(0,surplus):
        missing.append('향후 소득만으로 납입하는 계획이 확인된 월 잉여자금을 초과해요. 납입액 또는 재원을 확인해요.')
    if monthly_contribution>max(0,surplus): warnings.append('예정 납입액이 월 소득에서 지출을 뺀 금액보다 커요. 별도 자금 출처를 확인해요.')
    if unknown_sector: warnings.append('일부 섹터 노출은 미확인이에요. 분산이 충분하다는 뜻이 아니에요.')
    if unknown_fee: warnings.append('일부 보수율이 미확인이며 총 비용은 계산하지 못했어요.')
    if illiquid: warnings.append('유동성 확인이 필요한 종목이 있어요.')
    hist=history_metrics(w,m)
    if hist['status']!='available': warnings.append('변동성·Sharpe ratio·최대 낙폭·상관관계: 자료 부족으로 계산 불가')
    if p.get('criteria',{}).get('risk_level')=='conservative' and equity>0.5:
        warnings.append('안정 우선 선호와 높은 주식 비중이 충돌할 수 있어요. 검증 에이전트가 사유를 확인해요.')
    turnover=None
    if actual and actual.get('nav',0)>0 and abs(actual['nav']-capital)<1:
        turnover=sum(abs(w.get(s,0)-actual['weights'].get(s,0)) for s in set(w)|set(actual['weights']))/2
    return dict(base,version=VERSION,passed=not errors and not missing,
        status='blocked' if errors else ('needs_review' if missing or warnings else 'pass'),
        errors=errors,missing=missing,warnings=warnings,evidence_assessment=readiness,
        calculation_scope={'cash_reserved':'제안 금액에 제안 현금 비중을 적용한 계획액. 실제 가용 현금 아님.',
                           'position_limit':'비현금 종목·ETF 대상. CASH/현금성 자산 제외.',
                           'contribution':contribution},household=family,
        metrics={'capital':capital,'scenario_loss_amount':capital*base['scenario_loss_fraction'],
            'max_position_fraction':max(risky,default=0),'position_hhi':hhi,
            'effective_positions':1/hhi if hhi else None,'sector_exposures':sectors,
            'unknown_sector_fraction':unknown_sector,'asset_classes':classes,'currencies':currencies,
            'cash_months_of_expenses':base['cash_reserved']/p['monthly_expenses'] if p['monthly_expenses'] else None,
            'monthly_surplus':surplus,'monthly_contribution':monthly_contribution,
            'actual_cash_available':(actual or {}).get('values',{}).get('CASH'),
            'proposal_cash_reserved':base['cash_reserved'],
            'known_weighted_expense_ratio':fee,'unknown_fee_fraction':unknown_fee,
            'one_way_turnover':turnover},historical=hist,
        limitations=['종목 HHI는 ETF 내부 종목 중복·상관관계를 설명하지 않아요.',
            '섹터 분류는 출처별로 겹칠 수 있어요. ETF를 하나의 섹터로 간주하지 않아요.',
            '표시 통화 비중은 환헤지·기업 매출 통화를 반영한 순환위험이 아니에요.',
            '시나리오 손실은 가정이며 최대 손실 보장이 아니에요.'])
