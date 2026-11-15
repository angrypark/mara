"""KRW retrospective alternatives from issuer NAV returns and dated H.10 FX."""
import calendar,hashlib,math
from datetime import date,timedelta
from decimal import Decimal,localcontext
from pathlib import Path
from .domain import dumps
from .portfolio_comparison import compare
from .quantitative_verifier import replay


def build(market,allocations,initial,monthly,rebalance_months,cost_bps):
    fx=market.get('fx_history');histories=market.get('return_histories',{})
    if not fx:return {'available':False,'reason':'검증된 월말 USD/KRW 이력이 없어 원화 비교를 완료하지 못했어요.'}
    try:
        if fx['series']!='DEXKOUS' or fx['units']!='KRW per USD' or fx['frequency']!='monthly_last_observed_daily_rate' or fx['known_at']>market['as_of']:raise ValueError('FX identity, units, frequency or knowledge date mismatch')
        levels={};prev=None
        for row in fx['observations']:
            dt=date.fromisoformat(row['date']);observed=date.fromisoformat(row['observed_at']);rate=row['krw_per_usd']
            if row['date'] in levels or (prev and dt<=prev) or dt>=date.fromisoformat(market['as_of']).replace(day=1):raise ValueError('Duplicate, unordered or future FX month')
            if dt.day!=calendar.monthrange(dt.year,dt.month)[1] or not 0<=(dt-observed).days<=7:raise ValueError('FX month end or observation date mismatch')
            if type(rate) not in (int,float) or not math.isfinite(rate) or rate<=0:raise ValueError('Invalid FX level')
            levels[row['date']]=rate;prev=dt
        if not levels or list(levels)[-1]!=(date.fromisoformat(market['as_of']).replace(day=1)-timedelta(days=1)).isoformat():raise ValueError('Latest completed FX month missing')
        needed={s for w in allocations.values() for s,v in w.items() if s!='CASH' and v>0}
        converted={};independent={}
        for symbol in sorted(needed):
            h=histories[symbol]
            if h['symbol']!=symbol or h['currency']!='USD' or h['frequency']!='monthly' or h['return_type']!='issuer_reported_nav_total_return':raise ValueError('Underlying NAV series identity or frequency mismatch')
            rows=[];independent[symbol]={};last=None
            for row in h['observations']:
                dt=date.fromisoformat(row['date'])
                if dt.isoformat()!=row['date'] or dt.day!=calendar.monthrange(dt.year,dt.month)[1] or dt>=date.fromisoformat(market['as_of']).replace(day=1):raise ValueError('NAV is not a completed calendar month')
                if last and dt<=last:raise ValueError('NAV date order mismatch')
                last=dt
                y,m=(dt.year-1,12) if dt.month==1 else (dt.year,dt.month-1)
                before=date(y,m,calendar.monthrange(y,m)[1]).isoformat()
                if row['date'] not in levels or before not in levels:continue
                ret=row['return']
                if type(ret) not in (int,float) or not math.isfinite(ret) or ret<=-1:raise ValueError('Invalid NAV return')
                value=(1+ret)*levels[row['date']]/levels[before]-1
                rows.append({'date':row['date'],'return':value})
                with localcontext() as ctx:
                    ctx.prec=34
                    independent[symbol][row['date']]=float((1+Decimal(str(ret)))*Decimal(str(levels[row['date']]))/Decimal(str(levels[before]))-1)
            converted[symbol]={'symbol':symbol,'currency':'KRW','frequency':'monthly','return_type':'fx_converted_issuer_nav_total_return','source':h['source'],'observations':rows}
        result=compare(converted,allocations,initial=initial,monthly=monthly,rebalance_months=rebalance_months,cost_bps=cost_bps,currency='KRW')
        # The replay's legacy *_usd_units parameter names are internal scalar
        # slots only. Public assumptions and series remain explicitly KRW.
        def verified(value):
            a=value['assumptions'];internal={**a,'initial_usd_units':a['initial_krw_units'],'monthly_usd_units':a['monthly_krw_units']}
            series={s:{dt:rows[dt] for dt in value['dates']} for s,rows in independent.items()}
            failures=[]
            def check(name,expected,actual):
                for k,v in expected.items():
                    if isinstance(v,dict):check(name+'/'+k,v,actual[k])
                    elif not math.isclose(v,actual[k],rel_tol=1e-8,abs_tol=1e-8):failures.append(name+'/'+k)
            with localcontext() as ctx:
                ctx.prec=34
                for name,row in value['results'].items():check(name,replay(series,row['weights'],internal),row)
            return failures
        failures=verified(result);sensitivity=[]
        for changed,fee,cash in [('cash_yield',cost_bps,.02),('cash_yield',cost_bps,.04),('cost',0,0),('cost',50,0)]:
            if changed=='cost' and fee==cost_bps:continue
            value=compare(converted,allocations,initial=initial,monthly=monthly,rebalance_months=rebalance_months,cost_bps=fee,cash_annual=cash,currency='KRW')
            failures.extend(changed+'/'+x for x in verified(value))
            sensitivity.append({'changed_assumption':changed,'cash_annual_assumption':cash,'one_way_combined_cost_bps':fee,
                'results':{name:{k:row[k] for k in ('annualized_return','month_end_max_drawdown','profit','transaction_cost_paid')} for name,row in value['results'].items()}})
        for row in result['results'].values():
            row.pop('wealth_path',None);row.pop('unit_wealth_path',None)
        result['dates']=[result['dates'][0],result['dates'][-1]]
        result['assumptions']['personal_taxes_fx_costs']='개인별 세금 제외. 매매와 환전을 합친 편도 비용은 시나리오 가정으로 포함.'
        return {'available':True,**result,'sensitivity':sensitivity,
            'amount_unit':'실제 제안 기준액 및 월납입과 같은 KRW 금액을 과거 공통 기간에 가정. 실제 계좌 성과/미래 목표액 아님.',
            'conversion_formula':'KRW total return = (1 + issuer USD NAV total return) * month-end KRW_per_USD / previous month-end KRW_per_USD - 1',
            'cash_scope':'CASH는 KRW 현금. 실제 계좌 이율 미확인으로 기본 0%, 2%/4% 별도 가정 비교. USD 현금 대용치 아님.',
            'cost_scope':'명시한 매매+환전 편도 비용 '+str(cost_bps)+'bps 가정. 매매할 때마다 KRW로 환전한다고 가정하므로 USD를 보유한 재조정과 다름. 계좌 실제 요율/세금/시장 스프레드/소수점 제약은 미반영.',
            'fx_source':fx['source'],'fx_source_limits':fx['limits'],
            'independent_replay':{'status':'failed' if failures else 'passed','discrepancies':failures,
                'input_hash':hashlib.sha256(dumps({'market_as_of':market['as_of'],'fx':fx,'histories':{s:histories[s] for s in sorted(needed)},'allocations':allocations,'initial':initial,'monthly':monthly,'rebalance_months':rebalance_months,'cost_bps':cost_bps}).encode()).hexdigest(),
                'implementation_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'method':'Separate Decimal FX conversion and existing independent closed-form cost replay; historical metrics and '+str(len(sensitivity))+' sensitivity scenarios checked.',
                'scope':'원본 수치의 진실성·실제 계좌 이율/세금/체결·미래 성과 검증은 아님. 월말 환율과 NAV의 시각 차이는 보존.'}}
    except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
        return {'available':False,'reason':'원화 비교 입력/계산을 검증하지 못했어요.','diagnostic':str(exc)[:200]}
