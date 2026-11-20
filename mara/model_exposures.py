"""US equity sleeve research from comparable issuer files. All allocations are fractions."""
import csv
import io
import re
from collections import defaultdict
from datetime import datetime
from itertools import combinations

from .domain import weights
from .research_sources import dated, finite, fund_profile

ROOT = 'https://www.ishares.com/us/products/'
PRODUCTS = {
    'ITOT': '239724/ishares-core-s-p-total-u-s-stock-market-etf',
    'IWF': '239706/ishares-russell-1000-growth-etf',
    'IWD': '239708/ishares-russell-1000-value-etf',
    'IJR': '239774/ishares-core-s-p-small-cap-etf',
}


def acquire(archive, as_of):
    funds = {}
    positions = {}
    dates = set()
    for ticker, slug in PRODUCTS.items():
        url = ROOT + slug
        page, page_ref = archive.get(url)
        profile = fund_profile(page.decode('utf-8-sig'), ticker, as_of, url)
        csv_bytes, holdings_ref = archive.get(profile['holdings_url'])
        raw = csv_bytes.decode('utf-8-sig')
        lines = list(csv.reader(io.StringIO(raw)))
        date = datetime.strptime(next(row[1] for row in lines if row and row[0]=='Fund Holdings as of'),
                                 '%b %d, %Y').date().isoformat()
        dates.add(dated(date, as_of, 10))
        start = next(i for i, row in enumerate(lines) if row and row[0] == 'Ticker')
        columns = lines[start]
        rows = []
        ended = False
        footer = False
        if len(set(columns)) != len(columns):
            raise ValueError('Duplicate holdings columns')
        for row in lines[start+1:]:
            if not row or (len(row)==1 and not row[0].strip()):
                ended = True
                continue
            if ended and len(row)==1:
                footer |= 'BlackRock' in row[0]
                continue
            if ended or len(row)!=len(columns):
                raise ValueError('Incomplete holdings table')
            entry = dict(zip(columns, row))
            if entry['Currency']!='USD' or entry['Market Currency']!='USD':
                raise ValueError('USD market value basis required')
            rows.append(entry)
        count = profile['issuer_metrics'].get('numHoldings', {})
        equity_rows = sum(row['Asset Class']=='Equity' for row in rows)
        if not footer or count.get('observed_at') != date or count.get('value') != equity_rows:
            raise ValueError('Issuer count, date or holdings footer mismatch')
        basis = sum(finite(row['Market Value'],0) for row in rows)
        if len(rows)<10 or basis<=0:
            raise ValueError('Insufficient issuer holdings')
        shares = {}
        derivative = 0.
        swaps = 0.
        for entry in rows:
            notional = finite(entry['Notional Value'])
            if entry['Asset Class'] == 'Futures':
                derivative += abs(notional) / basis
            if entry['Asset Class'] != 'Equity':
                continue
            key = (entry['Ticker'], entry['Name'], entry['Exchange'])
            exposure = finite(entry['Market Value'],0) / basis
            if entry.get('Type')=='SWAP':
                exposure = finite(notional,0) / basis
                swaps += exposure
            prev, sector = shares.get(key,(0.,entry['Sector']))
            if sector != entry['Sector']:
                raise ValueError('Ambiguous security sector')
            shares[key] = (prev+exposure,sector)
        positions[ticker] = shares
        funds[ticker] = dict(index=profile['benchmark'], objective=profile['objective'],
            annual_fee=profile['expense_ratio'], fee_read_at=as_of, holdings_date=date,
            metrics=profile['issuer_metrics'], securities=len(shares), futures_gross=derivative, named_swaps=swaps,
            equity_fraction=sum(item[0] for item in shares.values()), sources=[page_ref, holdings_ref])
    if len(dates) != 1:
        raise ValueError('Common holdings date required')
    pairs = {}
    for a, b in combinations(funds, 2):
        shared = positions[a].keys() & positions[b].keys()
        pairs[a + '/' + b] = dict(common_positions=len(shared),
            weighted_overlap=sum(min(positions[a][k][0], positions[b][k][0]) for k in shared))
    return funds, positions, pairs


def calculate(allocation, funds, positions):
    weights(allocation)
    if not set(allocation) <= funds.keys():
        raise ValueError('Only eligible US equity funds allowed')
    companies, sectors = defaultdict(float), defaultdict(float)
    for ticker, fraction in allocation.items():
        for (_, name, _), (weight, sector) in positions[ticker].items():
            issuer = re.sub(r' (?:CLASS|CL) [A-Z]$', '', name)
            companies[issuer] += fraction * weight
            sectors[sector] += fraction * weight
    ranked = sorted(companies.items(), key=lambda pair: -pair[1])
    tech = sectors.get('Information Technology', 0)
    # Deliberately common shocks for all alternatives; no historical performance claim.
    return dict(weights=allocation, annual_fee=sum(w * funds[t]['annual_fee'] for t, w in allocation.items()),
        top_issuers=dict(ranked[:10]), top10_fraction=sum(w for _, w in ranked[:10]),
        sectors=dict(sorted(sectors.items(), key=lambda pair: -pair[1])),
        one_minus_mapped_exposure=1-sum(sectors.values()),
        named_swaps=sum(w * funds[t]['named_swaps'] for t,w in allocation.items()),
        futures_gross=sum(w * funds[t]['futures_gross'] for t,w in allocation.items()),
        shocks={'US_equity_minus30_USDKRW_minus10':(1-.30)*(1-.10)-1,
                'IT_minus40_other_equity_minus20_remainder_flat':-.4*tech-.2*(sum(sectors.values())-tech)})
