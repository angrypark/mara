import copy
import unittest

from mara.portfolio_replay import author, freeze, prepare, score


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
        receipt['proposal']['rationale'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'changed'):
            score(prepared, receipt, self.outcomes)
        with self.assertRaisesRegex(ValueError, 'outside'):
            freeze(prepared, dict(self.candidate,evidence_ids=['future-sentinel']))
