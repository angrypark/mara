"""Prepare a point-in-time decision, freeze the submission, then score its path."""
import argparse
from datetime import date
import json
from pathlib import Path

from .decision_gold import check, digest, finite, instant, load, path_metrics, replay, string
from .domain import weights


VERSION = 'mara.portfolio-replay/1'
AUTHOR_CONTRACT = {'weights': {'CASH': 1.0}, 'rationale': 'string', 'evidence_ids': ['record id'],
                   'alternatives': ['credible alternative and rejection condition'], 'uncertainties': ['string']}
REVIEW_CONTRACT = {'findings': ['decision, evidence, suitability and alternatives findings'],
                   'limitations': ['unresolved issue']}


def allocation(value, universe):
    weights(value)
    check(set(value) <= set(universe), 'Asset outside the frozen universe')
    return dict(value)


def calendar_for(policy, start, end):
    calendar = policy['calendar']
    check(isinstance(calendar, list) and all(isinstance(day,str) for day in calendar)
          and calendar == sorted(set(calendar)) and len(calendar) >= 2
          and calendar[0] == start and calendar[-1] == end
          and all(date.fromisoformat(day).isoformat() == day for day in calendar),
          'Freeze the common trading calendar for the exact window')
    return calendar


def prepare(case):
    """Project disclosure, revisions and quote observations at the same cutoff."""
    source = replay(case)
    cutoff = instant(source['as_of'])
    policy = case['portfolio_policy']
    universe = policy['universe']
    check(isinstance(universe, list) and all(map(string, universe)) and len(universe) == len(set(universe)),
          'Freeze a unique asset universe')
    benchmark = allocation(policy['benchmark'], universe)
    start, end = map(date.fromisoformat, (policy['start'], policy['end']))
    check(end > start > cutoff.date(), 'Freeze a post-decision start and end date')
    check(string(policy['currency']) and string(policy['basis']), 'Currency and price basis required')
    calendar = calendar_for(policy, start.isoformat(), end.isoformat())
    selected = {row['id'] for row in source['records']}
    prices = []
    for row in case['records']:
        if row['id'] not in selected or 'quote' not in row:
            continue
        quote = row['quote']
        check(set(quote) == {'asset', 'level', 'currency', 'basis'}, 'Unexpected quote fields')
        check(quote['asset'] in universe and finite(quote['level']) and quote['level'] > 0
              and quote['currency'] == policy['currency'] and quote['basis'] == policy['basis'],
              'Invalid point-in-time quote')
        prices.append(dict(quote, record_id=row['id'], observed_at=row['observed_at']))
    source['quotes'] = sorted(prices, key=lambda row: (row['asset'], row['observed_at'], row['record_id']))
    return {'version': VERSION, 'packet': source, 'policy': {
        'universe': universe, 'benchmark': benchmark, 'start': start.isoformat(), 'end': end.isoformat(),
        'currency': policy['currency'], 'basis': policy['basis'], 'calendar': calendar,
    }}


def validate_prepared(prepared):
    packet = prepared['packet']
    by_id = {row['id']: dict(row) for row in packet['records']}
    check(len(by_id) == len(packet['records']), 'Repeated prepared record')
    for quote in packet['quotes']:
        row = by_id.get(quote['record_id'])
        check(row is not None and quote['observed_at'] == row['observed_at'] and 'quote' not in row,
              'Quote lacks an eligible source record')
        row['quote'] = {k: quote[k] for k in ('asset', 'level', 'currency', 'basis')}
    case = dict(packet, records=list(by_id.values()), split='tuning', regimes=['prepared'],
                portfolio_policy=prepared['policy'])
    check(prepared == prepare(case), 'Prepared portfolio contains noncanonical or ineligible inputs')


def freeze(prepared, candidate, review=None):
    validate_prepared(prepared)
    check(set(candidate) == set(AUTHOR_CONTRACT), 'Unrecognized proposal fields')
    weights_ = allocation(candidate['weights'], prepared['policy']['universe'])
    evidence_ids = candidate['evidence_ids']
    delivered = {row['id'] for row in prepared['packet']['records']}
    check(isinstance(evidence_ids, list) and all(map(string, evidence_ids))
          and set(evidence_ids) <= delivered and len(evidence_ids) == len(set(evidence_ids)),
          'Proposal cites evidence outside the frozen packet')
    check(string(candidate['rationale']), 'Proposal rationale required')
    for field in ('alternatives', 'uncertainties'):
        check(isinstance(candidate[field], list) and candidate[field] and all(map(string, candidate[field])),
              'Document alternatives and uncertainty')
    submission = dict(candidate, weights=weights_)
    if review is not None:
        check(set(review) == set(REVIEW_CONTRACT) and all(isinstance(rows, list) and rows and all(map(string, rows))
              for rows in review.values()), 'Invalid independent review')
    receipt = {'version': VERSION, 'case_id': prepared['packet']['case_id'], 'input_sha256': digest(prepared),
               'proposal': submission, 'decision_review': review}
    return dict(receipt, submission_sha256=digest(receipt))


def author(prepared, model):
    validate_prepared(prepared)
    payload = {'packet': prepared['packet'], 'universe': prepared['policy']['universe'],
               'benchmark': prepared['policy']['benchmark'], 'currency': prepared['policy']['currency']}
    evidence = model.complete('evidence',
        'Assess source and price availability solely from the supplied cutoff packet. Use record IDs. '
        'Do not recall subsequent events or market outcomes.', payload,
        {'summary': 'string', 'gaps': ['string']})
    payload['evidence_review'] = evidence
    candidate = model.complete('leader',
        'Form a historically plausible long-only allocation. Use only the packet, choose among the supplied universe, '
        'cite eligible record IDs, and explain why its weights might change. Do not use hindsight.',
        payload, AUTHOR_CONTRACT)
    freeze(prepared, candidate)
    review = model.complete('evaluator',
        'Evaluate decision, evidence, suitability and alternatives from the same frozen packet. '
        'Give concrete findings and limits grounded in the supplied inputs. Future market outcomes are unknown.',
        dict(payload, proposal=candidate), REVIEW_CONTRACT)
    return freeze(prepared, candidate, review)


def score(prepared, receipt, data):
    expected = freeze(prepared, receipt['proposal'], receipt['decision_review'])
    check(receipt == expected, 'Frozen submission or input changed')
    policy = prepared['policy']
    check(data['currency'] == policy['currency'] and data['basis'] == policy['basis'] and string(data['source']),
          'Outcome metadata differs from the frozen policy')
    rows = data['rows']
    dates = [date.fromisoformat(row['date']).isoformat() for row in rows]
    check(dates == sorted(set(dates)), 'Outcome dates must be unique and increasing')

    result = {'version': VERSION, 'submission_sha256': receipt['submission_sha256'],
              'source': data['source'], 'currency': policy['currency'], 'basis': policy['basis'],
              'start': policy['start'], 'end': policy['end'], 'method': 'fixed shares, gross, no trades after entry'}
    by_day = {day: row['levels'] for day, row in zip(dates, rows)
              if policy['start'] <= day <= policy['end']}
    calendar = policy['calendar']
    check(data['calendar'] == calendar, 'Outcome calendar differs from the frozen policy')
    check(set(by_day) <= set(calendar), 'Outcome rows outside the common calendar')
    if set(by_day) != set(calendar):
        return dict(result, status='unavailable', reason='missing_observation_dates')
    allocations = {'proposal': receipt['proposal']['weights'], 'benchmark': policy['benchmark']}
    assets = {asset for w in allocations.values() for asset, weight in w.items() if weight > 0}
    initial = by_day[policy['start']]
    levels = []
    for day, quotes in by_day.items():
        if not all(finite(quotes.get(asset)) and quotes[asset] > 0 for asset in assets):
            return dict(result, status='unavailable', reason='missing_or_invalid_level', date=day)
        levels.append(dict(date=day, **{
            name: sum(weight * quotes[asset] / initial[asset] for asset, weight in allocation_.items() if weight > 0)
            for name, allocation_ in allocations.items()}))
    metrics = {name: path_metrics(levels, name) for name in allocations}
    return dict(result, status='available', observations=len(levels), **metrics,
                excess_return=metrics['proposal']['return'] - metrics['benchmark']['return'])


def link(session, report_id, prepared, receipt, data, comparability, as_of):
    """Associate an audited analogue with the owner-scoped immutable report."""
    report = session.get(report_id)
    check(report['owner'] == session.owner and report['kind'] in ('completed','model_completed'),
          'An owned completed portfolio report is required')
    check(string(comparability) and len(comparability) <= 1000,
          'Explain which features of the original decision and analogue are comparable')
    result = score(prepared, receipt, data)
    check(result['status'] == 'available', 'Historical outcome coverage is incomplete')
    check(as_of >= max(result['end'], report['effective']), 'The link date precedes the outcome or report')
    link_body = {'report_id': report_id, 'case_id': receipt['case_id'], 'scope': 'historical_analogue',
                 'cutoff': prepared['packet']['as_of'], 'comparability': comparability,
                 'historical_weights': receipt['proposal']['weights'],
                 'benchmark_weights': prepared['policy']['benchmark'],
                 'decision_review': receipt['decision_review'], 'score': result,
                 'outcome_sha256': digest(data)}
    with session.store.transaction():
        prior = [e for e in session.events('portfolio_replay_link') if e['body'] == link_body]
        return prior[-1]['id'] if prior else session.append('portfolio_replay_link',link_body,as_of,report['run_id'])


def status_for_proposal(session=None, report_id=None):
    if session is not None and report_id is not None:
        links = [dict(e['body'], event_id=e['id']) for e in session.events('portfolio_replay_link')
                 if e['body']['report_id'] == report_id]
        if links:
            return {'status': 'available', 'method': VERSION, 'cases': links}
    return {'status': 'no_comparable_replay', 'method': VERSION,
            'reason': 'Comparable evidence and a frozen historical submission have not been attached.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name, args in {'prepare': ('case',), 'author': ('prepared',), 'freeze': ('prepared', 'proposal'),
                       'score': ('prepared', 'receipt', 'outcomes')}.items():
        command = sub.add_parser(name)
        for arg in args:
            command.add_argument(arg, type=Path)
        command.add_argument('--out', type=Path, required=True)
        if name == 'author':
            command.add_argument('--model', default='')
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(load(args.case))
    else:
        prepared = load(args.prepared)
        if args.command == 'author':
            from .codex_model import CodexModel
            result = author(prepared, CodexModel(args.model))
        elif args.command == 'freeze':
            result = freeze(prepared, load(args.proposal))
        else:
            result = score(prepared, load(args.receipt), load(args.outcomes))
    with args.out.open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write('\n')


if __name__ == '__main__':
    main()
