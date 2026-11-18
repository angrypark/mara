"""Three-month public daily observations, with units and exact endpoints.

Current FRED vintages are not point-in-time backtest data. Missing days are
omitted, never interpolated. A net fall never means a continuous decline.
"""
import csv
import io
import math
from datetime import date
from .editorial import period

SERIES={
    'SP500':{'name':'S&P 500 가격지수','unit':'index_points','change':'percent'},
    'DGS10':{'name':'미국 국채 10년물 금리','unit':'percent_per_annum','change':'basis_points'},
    'DEXKOUS':{'name':'원/달러 환율','unit':'KRW_per_USD','change':'percent'},
}


def url(series,as_of):
    if series not in SERIES:raise ValueError('Unsupported market series')
    p=period(as_of)
    return 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='+series+'&cosd='+p['start']+'&coed='+p['end']


def parse(raw,series,as_of):
    config=SERIES[series];p=period(as_of)
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames!=['observation_date',series]:raise ValueError('Market series identity changed')
    rows=[];previous=None;missing=[]
    for r in reader:
        day=date.fromisoformat(r['observation_date']);stamp=day.isoformat()
        if stamp!=r['observation_date'] or (previous and stamp<=previous):raise ValueError('Unordered market dates')
        if not p['start']<=stamp<=as_of:raise ValueError('Market observation outside requested period')
        previous=stamp
        if r[series] in ('','.'):missing.append(stamp);continue
        value=float(r[series])
        if not math.isfinite(value) or (series!='DGS10' and value<=0):raise ValueError('Invalid market observation')
        rows.append({'date':stamp,'value':value})
    if len(rows)<30:raise ValueError('Insufficient three-month observations')
    if (date.fromisoformat(rows[0]['date'])-date.fromisoformat(p['start'])).days>7 or (date.fromisoformat(as_of)-date.fromisoformat(rows[-1]['date'])).days>7:
        raise ValueError('Incomplete market endpoints')
    first,last=rows[0],rows[-1]
    change=(last['value']-first['value'])*100 if config['change']=='basis_points' else (last['value']/first['value']-1)*100
    return {'series':series,**config,'requested_period':p,'actual_start':first['date'],'actual_end':last['date'],
        'start_value':first['value'],'end_value':last['value'],'change_value':change,
        'change_unit':config['change'],'formula':'(last-first)*100' if config['change']=='basis_points' else '(last/first-1)*100',
        'observations':rows,'missing_dates':missing,'minimum':min(rows,key=lambda r:r['value']),
        'maximum':max(rows,key=lambda r:r['value']),'each_observed_step_down':all(b['value']<a['value'] for a,b in zip(rows,rows[1:])),
        'continuous_decline_verified':False,'observed_at':last['date'],
        'date_provenance':{'status':'available-by retrieval date; original publication day unknown',
            'original_published_at':None,'envelope_published_at':as_of},
        'source':url(series,as_of),'known_at':as_of,
        'limits':'FRED 현재 빈티지의 실제 관측일만 비교해요. 결측일은 보간하지 않아요. 지수는 배당 제외 가격지수, 금리는 연율 %와 bp 변화, 환율은 1달러당 원화예요. 과거 당시 이용 가능 빈티지·개인 계좌 수익률·기간 내내 같은 방향의 움직임을 뜻하지 않아요.'}
