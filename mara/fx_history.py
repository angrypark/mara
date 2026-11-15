"""FRED DEXKOUS daily KRW per USD to explicitly dated month-end observations."""
import calendar,csv,io,math
from datetime import date,timedelta

SOURCE='https://fred.stlouisfed.org/series/DEXKOUS'


def url(as_of):
    end=date.fromisoformat(as_of).replace(day=1)-timedelta(days=1)
    return 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS&cosd=2004-01-01&coed='+end.isoformat()


def parse(raw,as_of):
    today=date.fromisoformat(as_of);reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames!=['observation_date','DEXKOUS']:raise ValueError('FX series identity or CSV columns changed')
    months={};previous=None
    for row in reader:
        day=date.fromisoformat(row['observation_date'])
        if day.isoformat()!=row['observation_date'] or (previous and day<=previous):raise ValueError('Duplicate or unordered FX dates')
        if day>today:raise ValueError('Future FX observation')
        previous=day
        if row['DEXKOUS'] in ('','.'):continue
        rate=float(row['DEXKOUS'])
        if not math.isfinite(rate) or not 0<rate<100000:raise ValueError('Invalid KRW per USD rate')
        end=day.replace(day=calendar.monthrange(day.year,day.month)[1])
        if end>=today.replace(day=1):continue
        months[end.isoformat()]={'date':end.isoformat(),'observed_at':day.isoformat(),'krw_per_usd':rate}
    observations=list(months.values())
    if len(observations)<37:raise ValueError('Insufficient FX monthly levels')
    for row in observations:
        if (date.fromisoformat(row['date'])-date.fromisoformat(row['observed_at'])).days>7:raise ValueError('Stale month-end FX observation')
    for a,b in zip(observations,observations[1:]):
        ay,am=map(int,a['date'][:7].split('-'));by,bm=map(int,b['date'][:7].split('-'))
        if by*12+bm-ay*12-am!=1:raise ValueError('Gap in FX monthly levels')
    expected=(today.replace(day=1)-timedelta(days=1)).isoformat()
    if observations[-1]['date']!=expected:raise ValueError('Latest completed FX month missing')
    return {'series':'DEXKOUS','units':'KRW per USD','frequency':'monthly_last_observed_daily_rate',
        'source':SOURCE,'known_at':as_of,'observations':observations,
        'limits':'FRED/연준 H.10 일별 환율의 매월 마지막 유효 관측. ETF 종가와 동시 체결 환율이 아니며 휴장 차이와 현재 수정 빈티지가 있음. 실제 계좌 환전율·미래 예상·당시 이용 가능 데이터 빈티지 아님.'}
