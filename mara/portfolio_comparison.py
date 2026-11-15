"""Reproducible retrospective allocation comparison, not strategy selection proof."""
import math
import calendar
from datetime import date as calendar_date
import statistics
from .domain import weights
from .research_sources import finite


def metrics(returns):
    wealth=peak=1.;drawdown=0.;path=[]
    for r in returns:
        wealth*=1+r;peak=max(peak,wealth);drawdown=max(drawdown,1-wealth/peak);path.append(wealth)
    return {'cumulative_return':wealth-1,'annualized_return':wealth**(12/len(returns))-1,
        'annualized_volatility':statistics.stdev(returns)*math.sqrt(12),
        'month_end_max_drawdown':drawdown,'worst_month':min(returns),
        'worst_12_month_return':min(math.prod(1+r for r in returns[i:i+12])-1 for i in range(len(returns)-11)),
        'unit_wealth_path':path}


def compare(histories,allocations,initial=1.,monthly=.0,rebalance_months=3,cost_bps=10.,cash_annual=0.,currency='USD'):
    """All amounts use the explicit currency of validated input return series.

    Contributions arrive at the beginning of each period after the initial one.
    They buy target weights; calendar rebalancing happens after period returns.
    Costs apply to noncash turnover on each side, including first purchases.
    Issuer NAV returns already reflect fund expenses: TER is not deducted twice.
    """
    if currency not in ('USD','KRW'):raise ValueError('Unsupported comparison currency')
    return_type='issuer_reported_nav_total_return' if currency=='USD' else 'fx_converted_issuer_nav_total_return'
    initial=finite(initial,.000001);monthly=finite(monthly,0);fee=finite(cost_bps,0,1000)/10000
    cash_annual=finite(cash_annual,-.5,.5)
    if type(rebalance_months) is not int or not 1<=rebalance_months<=120:raise ValueError('Invalid rebalance frequency')
    maps={}
    for symbol,h in histories.items():
        if h['symbol']!=symbol or h['currency']!=currency or h['frequency']!='monthly' or h['return_type']!=return_type:raise ValueError('Incompatible total return series')
        pairs=h['observations'];dates=[x['date'] for x in pairs]
        if dates!=sorted(set(dates)):raise ValueError('Unordered or duplicate observations')
        for value in dates:
            dt=calendar_date.fromisoformat(value)
            if dt.isoformat()!=value or dt.day!=calendar.monthrange(dt.year,dt.month)[1]:raise ValueError('Monthly return requires calendar month end')
        maps[symbol]={x['date']:finite(x['return'],-.999999,10) for x in pairs}
    needed=set()
    for allocation in allocations.values():
        weights(allocation);needed.update(s for s,w in allocation.items() if s!='CASH' and w>0)
    if not needed or not needed<=maps.keys():raise ValueError('Missing selected asset history')
    dates=sorted(set.intersection(*(set(maps[s]) for s in needed)))
    if len(dates)<36:raise ValueError('Insufficient common history')
    for a,b in zip(dates,dates[1:]):
        ay,am=map(int,a[:7].split('-'));by,bm=map(int,b[:7].split('-'))
        if by*12+bm-ay*12-am!=1:raise ValueError('Common history contains gaps')
    cash=(1+cash_annual)**(1/12)-1;results={}
    for name,allocation in allocations.items():
        w={s:v for s,v in allocation.items() if v>0}
        book={s:0. for s in w};costs=0.;deposits=initial;returns=[];amounts=[];turnover=0.
        for i,date in enumerate(dates):
            contribution=monthly if i else 0.;start=sum(book.values()) if i else initial;deposits+=contribution
            incoming=initial if i==0 else contribution
            invested=incoming/(1+fee*(1-w.get('CASH',0)))
            purchases=invested*(1-w.get('CASH',0));paid=purchases*fee
            for s,v in w.items():book[s]+=invested*v
            costs+=paid;turnover+=purchases
            for s in book:book[s]*=1+(cash if s=='CASH' else maps[s][date])
            if (i+1)%rebalance_months==0 and any(s!='CASH' for s in w):
                total=sum(book.values());lo,hi=0.,total*2*fee
                for _ in range(48):
                    guess=(lo+hi)/2
                    charge=fee*sum(abs((total-guess)*v-book[s]) for s,v in w.items() if s!='CASH')
                    if guess<charge:lo=guess
                    else:hi=guess
                paid=(lo+hi)/2;traded=sum(abs((total-paid)*v-book[s]) for s,v in w.items() if s!='CASH')
                costs+=paid;turnover+=traded;book={s:(total-paid)*v for s,v in w.items()}
            end=sum(book.values());returns.append(end/(start+contribution)-1);amounts.append(end)
        summary=metrics(returns)
        # Static target-weight covariance diagnostic, distinct from the drifting
        # holdings and cost-aware simulation above. Cash is deterministic here.
        series={s:[w[s]*(cash if s=='CASH' else maps[s][d]) for d in dates] for s in w}
        gross=[sum(series[s][i] for s in series) for i in range(len(dates))];vol=statistics.stdev(gross)
        def covariance(a,b):
            ma,mb=statistics.mean(a),statistics.mean(b)
            return sum((x-ma)*(y-mb) for x,y in zip(a,b))/(len(a)-1)
        risk={s:covariance(rs,gross)/vol*math.sqrt(12) if vol else 0. for s,rs in series.items()}
        summary.update(weights=w,ending_wealth=end,contributed=deposits,profit=end-deposits,
            transaction_cost_paid=costs,gross_turnover=turnover,wealth_path=amounts,
            target_weight_annual_volatility_contribution=risk,
            risk_contribution_scope='static target weights, gross of account costs; not the actual drift path')
        results[name]=summary
    return {'schema_version':'mara.allocation-comparison/1.0.0','start':dates[0],'end':dates[-1],
        'observations':len(dates),'dates':dates,'currency':currency,'frequency':'monthly',
        'assumptions':{'initial_'+currency.lower()+'_units':initial,'monthly_'+currency.lower()+'_units':monthly,'contribution_timing':'beginning, from second month',
            'rebalance_months':rebalance_months,'one_way_cost_bps':cost_bps,'cash_annual_assumption':cash_annual,
            'fund_expense_treatment':'included in issuer NAV total returns, not deducted again',
            'personal_taxes_fx_costs':'excluded; separate scenarios required'},
        'results':results,'sources':{s:histories[s]['source'] for s in sorted(needed)},
        'limitations':['현재 선택 자산과 현재 데이터 빈티지의 역사적 배분 비교예요. 당시 선정 전략의 out-of-sample 검증이 아니에요.',
            'NAV 총수익률과 실제 매매가격은 달라요. '+currency+' 가상 비교이며 실제 계좌 성과가 아니에요.',
            '최대 낙폭은 월말 관측 기준이에요. 월중 손실·미래 최대 손실·개인 손실 한도 준수를 증명하지 않아요.',
            '납입 포함 자산과 수익을 구분해요. 현금 이율과 계좌 비용은 관측치가 아닌 명시된 가정이에요.']}
