import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mara.portfolio_replay import author, freeze, link, prepare, score, status_for_proposal
from mara.store import Store


def row(key, clock, level):
    return dict(id=key, series_id='asset-quote', observed_at='2023-01-02T20:00:00Z',
                released_at='2023-01-02T20:00:00Z', revision_at=clock, available_at=clock,
                source='frozen fixture', text=key,
                quote=dict(asset='A', level=level, currency='USD', basis='total_return'))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.case = dict(case_id='fixture', version='1', split='tuning', regimes=['test'],
                         as_of='2023-01-03T00:00:00Z', task='Frozen task', holdings={}, persona={},
                         portfolio_policy=dict(universe=['A', 'CASH'], benchmark={'CASH': 1.0},
                                               start='2023-01-04', end='2023-01-06',
                                               calendar=['2023-01-04','2023-01-05','2023-01-06'],
                                               currency='USD', basis='total_return'),
                         records=[row('public', '2023-01-02T21:00:00Z', 100),
                                  row('future-sentinel', '2023-01-03T00:01:00Z', 123456789)])
        self.candidate = dict(weights={'A': 0.5, 'CASH': 0.5}, rationale='Conditional',
                              evidence_ids=['public'], alternatives=['cash'], uncertainties=['limited history'])
        self.outcomes = dict(currency='USD', basis='total_return', source='outcome source',
                             calendar=['2023-01-04', '2023-01-05', '2023-01-06'],
                             rows=[dict(date='2023-01-0'+str(day), levels={'A': level,'CASH':1})
                                   for day, level in [(4,100),(5,80),(6,120)]])

    def test_future_versions_and_outcomes_never_reach_any_author_role(self):
        calls = []
        def complete(role, guide, payload, contract):
            calls.append((role, copy.deepcopy(payload)))
            return {'evidence': {'summary':'available','gaps':[]}, 'leader': self.candidate,
                    'evaluator': {'findings':['conditional'], 'limitations':['one source']}}[role]
        prepared = prepare(self.case)
        receipt = author(prepared, type('Recorder', (), {'complete': staticmethod(complete)})())
        self.assertEqual([r for r, _ in calls], ['evidence','leader','evaluator'])
        for _, payload in calls:
            self.assertNotIn('future-sentinel', repr(payload))
            self.assertNotIn('123456789', repr(payload))
            self.assertNotIn('2023-01-06', repr(payload))
            self.assertEqual(payload['packet']['quotes'][0]['level'], 100)
        result = score(prepared, receipt, self.outcomes)
        self.assertAlmostEqual(result['excess_return'], 0.1)
        self.assertAlmostEqual(result['proposal']['max_drawdown'], 0.1)

    def test_missing_common_observation_blocks_and_mutation_is_rejected(self):
        prepared = prepare(self.case)
        receipt = freeze(prepared, self.candidate)
        self.outcomes['rows'].pop(1)
        self.assertEqual(score(prepared, receipt, self.outcomes)['reason'], 'missing_observation_dates')
        self.outcomes['calendar'].pop(1)
        with self.assertRaisesRegex(ValueError, 'calendar'):
            score(prepared, receipt, self.outcomes)
        receipt['proposal']['rationale'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'changed'):
            score(prepared, receipt, self.outcomes)
        with self.assertRaisesRegex(ValueError, 'outside'):
            freeze(prepared, dict(self.candidate,evidence_ids=['future-sentinel']))

    def test_modified_prepared_input_is_checked_before_provider_call(self):
        prepared = prepare(self.case)
        prepared['packet']['records'][0]['available_at'] = '2023-01-03T00:01:00Z'
        with self.assertRaisesRegex(ValueError, 'ineligible'):
            author(prepared, None)
        prepared = prepare(self.case)
        prepared['packet']['quotes'][0]['record_id'] = 'future-sentinel'
        with self.assertRaisesRegex(ValueError, 'eligible source'):
            author(prepared, None)

    def test_link_exposes_outcome_for_owned_report_without_rewriting_it(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root)/'test.sqlite')
            self.addCleanup(store.close)
            own = store.session(store.create_user('own'))
            other = store.session(store.create_user('other'))
            report_id = own.append('model_completed', {'proposal':{'weights':{'A':1}}}, '2023-01-02', 'run')
            prepared = prepare(self.case)
            receipt = freeze(prepared, self.candidate)
            args = (report_id, prepared, receipt, self.outcomes, 'Both decisions evaluate A exposure.',
                    '2023-01-06')
            before = own.get(report_id)
            first = link(own,*args)
            self.assertEqual(link(own,*args), first)
            self.assertEqual(own.get(report_id), before)
            self.assertEqual(status_for_proposal(other, report_id)['status'], 'no_comparable_replay')
            outcome, = status_for_proposal(own, report_id)['cases']
            self.assertEqual(outcome['event_id'], first)
            self.assertAlmostEqual(outcome['score']['excess_return'], 0.1)
            with self.assertRaises(PermissionError):
                link(other,*args)
