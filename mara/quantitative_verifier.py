"""Independent decimal replay of disclosed allocation exhibits.

Uses a closed-form, sign-partition transaction-cost solution, independent of the
production simulator's bisection. No portfolio choice or forward return forecast.
"""
from decimal import Decimal,localcontext
import hashlib
import math
import calendar
from datetime import date
from pathlib import Path
from .domain import dumps


def D(value):return Decimal(str(value))


def number(value,low=None,high=None):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Non-finite numeric input')
    if low is not None and value<low or high is not None and value>high:raise ValueError('Numeric input outside verified domain')
    return value


def assumptions_valid(a):
    if a['contribution_timing']!='beginning, from second month':raise ValueError('Contribution timing not verified')
    if a['fund_expense_treatment']!='included in issuer NAV total returns, not deducted again':raise ValueError('Fund expense interpretation disagrees with replay')
    if a['personal_taxes_fx_costs']!='excluded; separate scenarios required':raise ValueError('Personal tax and FX treatment not verified')
    number(a['initial_usd_units'],.000001);number(a['monthly_usd_units'],0)
    number(a['one_way_cost_bps'],0,1000);number(a['cash_annual_assumption'],-.5,.5)
    if type(a['rebalance_months']) is not int or not 1<=a['rebalance_months']<=120:raise ValueError('Rebalance frequency not verified')


def weights_valid(w):
    for value in w.values():number(value,0,1)
    if not w or not math.isclose(sum(w.values()),1,abs_tol=1e-9,rel_tol=0):
        raise ValueError('Weights must sum to one')


def replay(series,weights,assumptions):
    w={s:D(x) for s,x in weights.items() if x>0};fee=D(assumptions['one_way_cost_bps'])/D(10000)
    initial=D(assumptions['initial_usd_units']);deposit=D(assumptions['monthly_usd_units'])
    cash=(D(1)+D(assumptions['cash_annual_assumption']))**(D(1)/12)-1
    frequency=assumptions['rebalance_months'];book={s:D(0) for s in w}
    twr=D(1);deposits=initial;total_cost=D(0);turnover=D(0);factors=[D(1)];period_returns=[]
    dates=sorted(next(iter(series.values())))
    for index,day in enumerate(dates):
        incoming=initial if index==0 else deposit
        denominator=initial if index==0 else sum(book.values())+deposit
        if index:deposits+=deposit
        net_deposit=incoming/(1+fee*sum(weight for s,weight in w.items() if s!='CASH'))
        total_cost+=incoming-net_deposit
        turnover+=net_deposit*sum(weight for s,weight in w.items() if s!='CASH')
        for s in w:book[s]=(book[s]+w[s]*net_deposit)*(1+(cash if s=='CASH' else D(series[s][day])))
        if (index+1)%frequency==0 and fee:
            gross=sum(book.values());paid=D(0)
            for _ in range(20):
                buy=[s for s in w if s!='CASH' and (gross-paid)*w[s]>=book[s]]
                sell=[s for s in w if s!='CASH' and s not in buy]
                slope=sum(w[s] for s in buy)-sum(w[s] for s in sell)
                offset=sum(book[s] for s in sell)-sum(book[s] for s in buy)
                new_paid=fee*(gross*slope+offset)/(1+fee*slope)
                if abs(new_paid-paid)<D('1e-24'):paid=new_paid;break
                paid=new_paid
            else:raise ValueError('Independent cost solution did not converge')
            total_cost+=paid;turnover+=paid/fee
            book={s:(gross-paid)*weight for s,weight in w.items()}
        elif (index+1)%frequency==0:
            gross=sum(book.values());turnover+=sum(abs(gross*w[s]-book[s]) for s in w if s!='CASH')
            book={s:gross*weight for s,weight in w.items()}
        end=sum(book.values());factor=end/denominator;twr*=factor;factors.append(twr);period_returns.append(factor-1)
    mean=sum(period_returns)/len(period_returns)
    variance=sum((r-mean)**2 for r in period_returns)/(len(period_returns)-1)
    peak=D(1);drawdown=D(0)
    for value in factors:peak=max(peak,value);drawdown=max(drawdown,1-value/peak)
    gross_by_asset={s:[w[s]*(cash if s=='CASH' else D(series[s][day])) for day in dates] for s in w}
    gross=[sum(values[i] for values in gross_by_asset.values()) for i in range(len(dates))]
    mean_gross=sum(gross)/len(gross)
    vol=(sum((r-mean_gross)**2 for r in gross)/(len(gross)-1)).sqrt()
    contribution={s:float(sum((x-sum(values)/len(values))*(y-mean_gross) for x,y in zip(values,gross))/(len(gross)-1)/vol*D(12).sqrt()) if vol else 0. for s,values in gross_by_asset.items()}
    return {'cumulative_return':float(twr-1),'annualized_return':float(twr**(D(12)/len(dates))-1),
        'annualized_volatility':float((variance*12).sqrt()),'month_end_max_drawdown':float(drawdown),
        'worst_month':float(min(period_returns)),'worst_12_month_return':float(min(factors[i+12]/factors[i]-1 for i in range(len(factors)-12))),
        'ending_wealth':float(end),'contributed':float(deposits),'profit':float(end-deposits),
        'transaction_cost_paid':float(total_cost),'gross_turnover':float(turnover),
        'target_weight_annual_volatility_contribution':contribution}


def verify(report,market):
    comparison=report.get('analysis',{}).get('comparison',{})
    if not comparison.get('available'):return {'status':'unavailable','reason':'No disclosed comparison to replay'}
    histories=market.get('return_histories',{});results={};errors=[];sensitivities=[]
    try:
        assumptions_valid(comparison['assumptions'])
        if comparison['currency']!='USD' or comparison['frequency']!='monthly':raise ValueError('Comparison currency or frequency not verified')
        decision_dates=[value for value in (report.get('as_of'),report.get('analysis',{}).get('as_of'),market.get('as_of')) if value is not None]
        if not decision_dates:raise KeyError('Frozen decision date required for independent replay')
        if decision_dates:
            if len(set(decision_dates))!=1 or date.fromisoformat(decision_dates[0]).isoformat()!=decision_dates[0] or comparison['end']>decision_dates[0]:raise ValueError('Historical comparison exceeds or disagrees with the frozen decision date')
        needed=set()
        for row in comparison['results'].values():
            weights_valid(row['weights']);needed.update(s for s,w in row['weights'].items() if w>0 and s!='CASH')
        if not needed or not needed<=histories.keys():raise ValueError('Missing selected history')
        source={}
        for symbol in needed:
            h=histories[symbol]
            if h['symbol']!=symbol or h['currency']!='USD' or h['frequency']!='monthly' or h['return_type']!='issuer_reported_nav_total_return':raise ValueError('Series identity or return basis not verified')
            days=[x['date'] for x in h['observations']]
            if days!=sorted(set(days)):raise ValueError('Duplicate or unordered dates')
            for value in days:
                dt=date.fromisoformat(value)
                if dt.isoformat()!=value or dt.day!=calendar.monthrange(dt.year,dt.month)[1]:raise ValueError('Not a calendar month end')
            source[symbol]={x['date']:number(x['return'],-.999999,10) for x in h['observations'] if comparison['start']<=x['date']<=comparison['end']}
        dates=sorted(set.intersection(*(set(rows) for rows in source.values())))
        if len(dates)<36 or len(dates)!=comparison['observations'] or dates[0]!=comparison['start'] or dates[-1]!=comparison['end']:raise ValueError('Common observation period mismatch')
        for a,b in zip(dates,dates[1:]):
            ay,am=map(int,a[:7].split('-'));by,bm=map(int,b[:7].split('-'))
            if by*12+bm-ay*12-am!=1:raise ValueError('Gap in common monthly history')
        source={s:{dt:rows[dt] for dt in dates} for s,rows in source.items()}
        def check(name,expected,row):
            for metric,value in expected.items():
                if isinstance(value,dict):
                    if set(value)!=set(row[metric]):raise ValueError('Risk contribution keys disagree')
                    check(name+'/'+metric,value,row[metric]);continue
                number(row[metric])
                if not math.isclose(value,row[metric],rel_tol=1e-8,abs_tol=1e-8):errors.append({'portfolio':name,'metric':metric,'reported':row[metric],'recomputed':value})
        with localcontext() as context:
            context.prec=34
            for name,row in comparison['results'].items():
                expected=replay(source,row['weights'],comparison['assumptions']);results[name]=expected
                check(name,expected,row)
            for index,row in enumerate(comparison.get('sensitivity',[])):
                a=row['assumptions'];assumptions_valid(a);weights_valid(row['comparison_anchor_weights'])
                declared={'cost':'one_way_cost_bps','rebalance':'rebalance_months','contribution':'monthly_usd_units','cash_yield':'cash_annual_assumption'}[row['changed_assumption']]
                changed={k for k,v in comparison['assumptions'].items() if a[k]!=v}
                if changed!={declared}:raise ValueError('Sensitivity changes other than its declared single assumption')
                if row['result']['weights']!=row['comparison_anchor_weights'] or not any(r['weights']==row['comparison_anchor_weights'] for r in comparison['results'].values()):raise ValueError('Sensitivity anchor differs from comparison')
                expected=replay(source,row['comparison_anchor_weights'],a);sensitivities.append(expected)
                check('sensitivity/'+str(index),expected,row['result'])
        return {'status':'passed' if not errors else 'failed','method':'independent decimal replay with closed-form cost equation',
            'input_hash':hashlib.sha256(dumps({'histories':{s:histories[s] for s in sorted(needed)},
                'decision_dates':decision_dates,'start':comparison['start'],'end':comparison['end'],'observations':comparison['observations'],
                'currency':comparison['currency'],'frequency':comparison['frequency'],'assumptions':comparison['assumptions'],
                'allocations':{k:r['weights'] for k,r in comparison['results'].items()},'sensitivity':comparison.get('sensitivity',[])}).encode()).hexdigest(),
            'implementation_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'recomputed':results,'recomputed_sensitivities':sensitivities,'discrepancies':errors,'tolerance':{'absolute':1e-8,'relative':1e-8},
            'scope':'Verifies historical result and disclosed sensitivity metrics, static target risk contributions and input meaning from frozen issuer monthly series. Does not validate asset choice, original provider truth, future risk, taxes, actual account returns, household or FX stress arithmetic.'}
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        return {'status':'failed' if isinstance(exc,ValueError) else 'unavailable','reason':str(exc)[:250],
            'recomputed':results,'discrepancies':errors,'scope':'Replay incomplete; no quantitative pass'}
