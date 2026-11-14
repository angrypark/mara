"""Deterministic input, arithmetic and suitability checks. No model authority here."""
import json
import math
from datetime import date


def day(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('Use ISO YYYY-MM-DD dates')
    return result


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def number(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Finite number required')
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError('Number outside allowed range')
    return value


def required(obj, fields):
    if not isinstance(obj, dict) or any(k not in obj for k in fields):
        raise ValueError('Required fields: ' + ', '.join(fields))


def texts(value, nonempty=False):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError('Expected list of nonempty strings')
    if nonempty and not value:
        raise ValueError('At least one item required')


def profile(p):
    required(p, ['base_currency', 'markets', 'goal', 'horizon_months', 'total_assets',
                 'monthly_income', 'monthly_expenses', 'cash_need', 'cash_need_date',
                 'max_loss_fraction', 'max_position_fraction', 'contribution_amount',
                 'contribution_every_days', 'rebalance_every_days', 'constraints'])
    for k in ['total_assets', 'monthly_income', 'monthly_expenses', 'cash_need', 'contribution_amount']:
        number(p[k])
    for k in ['horizon_months', 'contribution_every_days', 'rebalance_every_days']:
        number(p[k], 1)
        if not isinstance(p[k], int): raise ValueError(k + ' must be integer')
    for k in ['max_loss_fraction', 'max_position_fraction']:
        number(p[k], 0, 1)
    texts(p['markets'], True)
    texts(p['constraints'])
    if not isinstance(p['goal'], str) or not p['goal'].strip(): raise ValueError('Goal required')
    if not isinstance(p['base_currency'], str) or len(p['base_currency']) != 3: raise ValueError('Currency required')
    day(p['cash_need_date'])
    return p


def holdings(p):
    required(p, ['as_of', 'base_currency', 'cash', 'positions', 'rationale', 'last_rebalanced'])
    day(p['as_of']); day(p['last_rebalanced'])
    if p['last_rebalanced'] > p['as_of']: raise ValueError('Future rebalance date')
    number(p['cash'])
    if not isinstance(p['positions'], dict): raise ValueError('positions must be symbol: units')
    for symbol, units in p['positions'].items():
        if not isinstance(symbol, str) or not symbol or symbol == 'CASH': raise ValueError('Invalid symbol')
        number(units)
    if not isinstance(p['rationale'], str) or not p['rationale'].strip(): raise ValueError('Actual holding rationale required')
    return p


def market(m):
    required(m, ['as_of', 'base_currency', 'prices', 'assets', 'facts'])
    day(m['as_of'])
    if not isinstance(m['prices'], dict) or not isinstance(m['assets'], dict): raise ValueError('Invalid market')
    for symbol, quote in m['prices'].items():
        required(quote, ['price', 'observed_at', 'known_at', 'source'])
        number(quote['price'], 0.00000001)
        if not quote['source'].startswith('https://'): raise ValueError('Price source URL required')
        if day(quote['observed_at']) > day(quote['known_at']) or quote['known_at'] > m['as_of']:
            raise ValueError('Future price evidence')
        if (day(m['as_of']) - day(quote['observed_at'])).days > 7: raise ValueError('Stale price')
        a = m['assets'][symbol]
        required(a, ['market', 'stress_loss', 'liquid', 'kind', 'expense_ratio'])
        number(a['stress_loss'], 0, 1); number(a['expense_ratio'], 0, 1)
        if type(a['liquid']) is not bool: raise ValueError('liquid must be boolean')
    ids = set()
    if not isinstance(m['facts'], list): raise ValueError('facts must be list')
    for f in m['facts']:
        required(f, ['id', 'topic', 'text', 'source', 'published_at', 'known_at', 'valid_until', 'uncertainty'])
        if not isinstance(f['text'], str) or not f['text'].strip(): raise ValueError('Fact text required')
        if f['id'] in ids: raise ValueError('Duplicate fact ID')
        ids.add(f['id'])
        if not f['source'].startswith('https://'): raise ValueError('Source URL required')
        for k in ['published_at','known_at','valid_until']: day(f[k])
        if f['published_at'] > f['known_at'] or f['known_at'] > m['as_of']: raise ValueError('Future fact')
    return m


def valuation(h, m):
    if h['base_currency'] != m['base_currency']: raise ValueError('Convert quotes to base currency with FX source first')
    if h['as_of'] > m['as_of']: raise ValueError('Future holdings')
    values = {s: units * m['prices'][s]['price'] for s, units in h['positions'].items() if units}
    values['CASH'] = h['cash']
    nav = sum(values.values())
    if nav <= 0: raise ValueError('Positive investable assets required')
    return {'nav': nav, 'weights': {s: v/nav for s,v in values.items()}, 'values': values}


def weights(w):
    if not isinstance(w, dict) or not w: raise ValueError('Nonempty weights required')
    for v in w.values(): number(v, 0, 1)
    if abs(sum(w.values()) - 1) > 1e-6: raise ValueError('Weights must sum to one')


def suitability(w, p, m, nav):
    weights(w)
    errors = []
    loss = 0
    liquid = 0
    for s, weight in w.items():
        if s == 'CASH':
            liquid += weight * nav
            continue
        if s not in m['assets'] or s not in m['prices']:
            errors.append('Unknown/unpriced asset: ' + s); continue
        a = m['assets'][s]
        if a['market'] not in p['markets']: errors.append('Market not allowed: ' + s)
        if weight > p['max_position_fraction'] + 1e-9: errors.append('Position limit: ' + s)
        loss += weight * a['stress_loss']
    # Cash reserve is intentionally conservative; a liquid risky asset is not guaranteed cash.
    if liquid + 1e-6 < p['cash_need']: errors.append('Cash reserve below stated cash need')
    if loss > p['max_loss_fraction'] + 1e-9: errors.append('Stress loss exceeds tolerance')
    return {'passed': not errors, 'errors': errors, 'scenario_loss_fraction': loss,
            'cash_reserved': liquid, 'limitation': 'User-supplied stress scenario, not a worst-case guarantee. Qualitative constraints need agent review.'}


def performance(previous, current, flows, start, end):
    days = (day(end)-day(start)).days
    if days <= 0: raise ValueError('Performance interval must advance')
    amount = sum(f['amount'] for f in flows)
    denominator = previous + sum(f['amount'] * (day(end)-day(f['date'])).days/days for f in flows)
    return {'start_nav': previous, 'end_nav': current, 'external_net_flows': amount,
            'pnl': current-previous-amount,
            'modified_dietz': (current-previous-amount)/denominator if denominator > 0 else None,
            'method': 'Modified Dietz; dated external cash flows, not a time-weighted or causal attribution metric'}
