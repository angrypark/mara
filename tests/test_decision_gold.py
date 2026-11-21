import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mara import decision_gold as g


AS_OF = '2026-01-03T12:00:00+00:00'
BEFORE = '2026-01-02T12:00:00+00:00'
AFTER = '2026-01-03T12:00:01+00:00'


def record(row_id='e1', series='s', text='historical original', time=BEFORE):
    return dict(id=row_id, series_id=series, text=text, source='unit test fixture',
                **{k: time for k in g.CLOCKS})


def case(case_id='demo', split='locked'):
    return dict(case_id=case_id, version='1', split=split, as_of=AS_OF, independence_unit=case_id,
                regimes=['uncertain liquidity', 'cash need'], task='Size a decision for ' + case_id,
                persona={'horizon': '1 month'}, holdings={'cash': 100}, records=[record()])


def gold():
    return dict(acceptable=['keep a documented reserve'], required=['fund near-term expenses'],
                prohibited=['rely on unconfirmed income'], frozen_at=AS_OF, adjudicator={'basis': 'independent fictional case owner'})


def config():
    systems = {k: {'kind': kind, 'version': k + '-v1', 'artifact_sha256': g.digest(k)}
               for k, kind in [('new', 'mara'), ('old', 'mara'), ('rule', 'simple'), ('solo', 'single')]}
    return dict(candidate='new', systems=systems, judges=['reviewer_1', 'reviewer_2'], repeats=2,
                holdout={'untouched': True, 'custodian': 'dataset owner', 'authorization_ref': 'test-only authorization'},
                conditions={'evidence_access': 'offline packet', 'resource_budget': 'fixed in advance',
                            'generation_protocol': 'registered independent generations'})


def ballots_for(directory):
    out = []
    index = g.load(directory / 'private.json')
    for key, assignment in index['assignments'].items():
        packet = g.load(directory / 'packets' / (key + '.json'))
        winner = assignment['candidate_slot']
        out.append(dict(packet_sha256=key, judge=assignment['judge'], session_id='call-' + key,
                        independent=True, identity_hidden=True, outcomes_hidden=True, preference=winner,
                        rulings=[dict(id=axis, winner=winner, quote_a=packet['reports']['A'],
                                      quote_b=packet['reports']['B'], reference_ids=['required:1', 'record:e1'],
                                      reason='The document connects the reserve to the bill.', gate_a='pass', gate_b='pass')
                                 for axis in g.AXES]))
    return out


class ReplayTest(unittest.TestCase):
    def test_each_clock_rejects_future_missing_malformed_date_only_or_naive(self):
        for field in g.CLOCKS:
            for invalid in (AFTER, None, 'unknown', '2026-01-03', '2026-01-03T11:59:59', 'absent'):
                with self.subTest(field=field, invalid=invalid):
                    c = case()
                    future = record('future', 'future')
                    if invalid == 'absent':
                        del future[field]
                    else:
                        future[field] = invalid
                    c['records'].append(future)
                    self.assertEqual(['e1'], [r['id'] for r in g.replay(c)['records']])

    def test_revision_vintage_instant_boundary_and_nondisclosure(self):
        c = case()
        revised = dict(record('e2', text='revised at cutoff'), revision_at='2026-01-03T21:00:00+09:00', available_at=AS_OF)
        late = dict(record('e3', text='post-cutoff secret'), revision_at=AFTER, available_at=AFTER)
        c.update(records=[late, revised, record()], outcome={'return': 1}, gold=gold())
        revised['future_extra_field'] = 'leak canary'
        output = g.replay(c)
        self.assertEqual(['e2'], [r['id'] for r in output['records']])
        for prohibited in ['split', 'regimes', 'outcome', 'gold', 'historical original', 'post-cutoff secret', 'leak canary']:
            self.assertNotIn(prohibited, json.dumps(output))
        c['as_of'] = BEFORE
        self.assertEqual(['e1'], [r['id'] for r in g.replay(c)['records']])

    def test_impossible_or_ambiguous_order_rejected(self):
        c = case()
        c['records'].append(record('e2'))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            g.replay(c)
        c['records'] = [dict(record(), revision_at=AS_OF)]
        with self.assertRaisesRegex(ValueError, 'chronology'):
            g.replay(c)

    def test_actual_curated_fixtures_exclude_canaries(self):
        root = Path(g.__file__).resolve().parents[1] / 'resources' / 'decision-gold'
        inputs = {'fx-lot-reserve': {'FX1', 'PX1', 'R1'}, 'settlement-window': {'N1', 'F1', 'I1'},
                  'lookthrough-cap': {'P1', 'C1', 'B1'}}
        for k, ids in inputs.items():
            self.assertEqual(ids, {r['id'] for r in g.replay(g.load(root / k / 'input.json'))['records']})

    def test_ex_post_drawdown_recovery_comparator_and_counterfactual(self):
        dates = ['2026-01-04', '2026-01-05', '2026-01-06', '2026-01-07']
        rows = [dict(date=d, asset=a, benchmark=b, cash=100) for d, a, b in zip(dates, [100, 120, 90, 120], [100, 102, 90, 101])]
        history = dict(asset_label='example', benchmark_label='same currency', basis='synthetic end of day levels',
                       series=rows, counterfactuals={'cash holding': 'cash'})
        report = g.outcome(case(), history)
        self.assertAlmostEqual(.25, report['asset']['max_drawdown'])
        self.assertEqual(dates[-1], report['asset']['recovery_date'])
        self.assertEqual('unrecovered_at_horizon', report['benchmark']['recovery_status'])
        self.assertAlmostEqual(.19, report['excess_return'])
        self.assertEqual('no_drawdown', report['counterfactuals']['cash holding']['recovery_status'])
        self.assertEqual('unidentified', report['causal_attribution'])
        rows[1]['date'] = dates[0]
        with self.assertRaisesRegex(ValueError, 'horizon'):
            g.outcome(case(), history)


class TrialTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = self.tmp / 'cases'
        self.root.mkdir()
        self.directory = self.tmp / 'judging'

    def setup_trial(self, n=1, design=None, split='locked'):
        design = design or config()
        for i in range(n):
            c = case('demo-' + str(i), split)
            folder = self.root / c['case_id']
            folder.mkdir()
            g.write(folder / 'input.json', c)
            g.write(folder / 'gold.json', gold())
        manifest = g.freeze(self.root, design)
        submissions = {**g.design_fields(design), 'runs': []}
        for case_id, metadata in manifest['cases'].items():
            for repeat in range(1, design['repeats'] + 1):
                for idx, system in enumerate(design['systems']):
                    run_id = f'{case_id}/{repeat}/{system}'
                    submissions['runs'].append(dict(case_id=case_id, system=system, repeat=repeat, author='author-' + system,
                                                    run_id=run_id, input_sha256=metadata['replay_sha256'],
                                                    text=f'Case-specific anonymous decision, alternative {idx}.',
                                                    closed_book=True, conditions_sha256=g.digest(design['conditions']),
                                                    input_mode='frozen_replay', started_at=AFTER))
        g.prepare(self.root, manifest, submissions, self.directory)
        return manifest, submissions, ballots_for(self.directory)

    def test_reproducible_comparison_separate_uncertainty_and_vote_count(self):
        manifest, _, ballots = self.setup_trial()
        report = g.compare(self.root, manifest, self.directory, ballots)
        self.assertEqual(report, g.compare(self.root, manifest, self.directory, ballots))
        self.assertEqual(['insufficient_case_level_evidence'], report['gate']['reasons'])
        self.assertEqual(.5, report['uncertainty']['old']['one_sided_exact_sign_p'])
        for pair in report['comparisons']:
            self.assertEqual({'A', 'B'}, {j['candidate_slot'] for j in pair['judgments']})
            self.assertFalse(pair['preference_disagreement'])
        self.assertTrue(all(c['measurements'] is None for c in report['execution_measurements']))

    def test_qualifying_synthetic_matrix_is_eligible(self):
        manifest, _, ballots = self.setup_trial(6)
        result = g.compare(self.root, manifest, self.directory, ballots)
        self.assertEqual({'status': 'eligible_on_locked_cases', 'reasons': []}, result['gate'])
        self.assertEqual(6, result['uncertainty']['solo']['wins'])

    def test_rulings_and_ballots_bound_to_frozen_artifacts(self):
        manifest, _, ballots = self.setup_trial()
        for patch, error in [
            ({'judge': 'anonymous impostor'}, 'Wrong judge'),
            ({'packet_sha256': 'x'}, 'ballot binding'),
            ({'session_id': ballots[1]['session_id']}, 'fresh independent'),
            ({'session_id': 'demo-0/1/new'}, 'fresh independent'),
            ({'preference': 'unknown'}, 'preference'),
        ]:
            with self.subTest(patch=patch):
                bad = copy.deepcopy(ballots)
                bad[0].update(patch)
                with self.assertRaisesRegex(ValueError, error):
                    g.compare(self.root, manifest, self.directory, bad)
        for field, value in [('quote_a', 'absent text'), ('quote_b', ''), ('reference_ids', ['record:future']),
                             ('reason', ''), ('gate_a', 'probably'), ('id', 'post_return')]:
            with self.subTest(field=field):
                bad = copy.deepcopy(ballots)
                bad[0]['rulings'][0][field] = value
                with self.assertRaises(ValueError):
                    g.compare(self.root, manifest, self.directory, bad)
        path = self.directory / 'packets' / (ballots[0]['packet_sha256'] + '.json')
        packet = g.load(path)
        packet['reports']['A'] += 'late edit'
        g.write(path, packet)
        with self.assertRaisesRegex(ValueError, 'packet changed'):
            g.compare(self.root, manifest, self.directory, ballots)

    def test_missing_ratings_disagreement_and_unknown_each_block(self):
        manifest, _, ballots = self.setup_trial()
        empty = g.compare(self.root, manifest, self.directory, [])
        self.assertEqual(len(ballots), empty['missing_ballots'])
        self.assertEqual('hold', empty['gate']['status'])
        bad = copy.deepcopy(ballots)
        bad[0]['identity_hidden'] = False
        bad[0]['rulings'][0]['gate_a'] = 'unknown'
        bad[0]['rulings'][0]['winner'] = 'unknown'
        bad[0]['preference'] = 'unknown'
        result = g.compare(self.root, manifest, self.directory, bad)
        for reason in ('incomplete_or_disputed_locked_case', 'independence_or_blinding_unverified',
                       'unknown_gate_or_candidate_failure', 'ruling_disagreement'):
            self.assertIn(reason, result['gate']['reasons'])
        self.assertTrue(any(r['preference_disagreement'] for r in result['comparisons']))

    def test_unanimous_decision_axis_regression_overrides_positive_total(self):
        manifest, _, ballots = self.setup_trial()
        for ballot in ballots:
            decision = next(r for r in ballot['rulings'] if r['id'] == 'decision')
            decision['winner'] = 'B' if decision['winner'] == 'A' else 'A'
        result = g.compare(self.root, manifest, self.directory, ballots)
        self.assertTrue(all(r['paired_preference'] == 1 for r in result['comparisons']))
        self.assertIn('locked_decision_axis_loss', result['gate']['reasons'])

    def test_tuning_votes_do_not_count_and_run_ids_are_independent(self):
        manifest, sub, _ = self.setup_trial(split='tuning')
        report = g.compare(self.root, manifest, self.directory, ballots_for(self.directory))
        self.assertEqual(0, report['uncertainty']['old']['wins'])
        self.assertIn('no_locked_cases', report['gate']['reasons'])
        sub['runs'][0]['run_id'] = sub['runs'][1]['run_id']
        with self.assertRaisesRegex(ValueError, 'Independent run IDs'):
            g.build_packets(self.root, manifest, sub, 'seed')

    def test_early_generation_and_tuning_alias_cannot_qualify(self):
        _, sub, _ = self.setup_trial()
        alias = case('same-episode', 'tuning')
        alias['independence_unit'] = 'demo-0'
        path = self.root / 'same-episode'
        path.mkdir()
        g.write(path / 'gold.json', gold())
        g.write(path / 'input.json', alias)
        manifest = g.freeze(self.root, config())
        sub['runs'][0]['started_at'] = BEFORE
        directory = self.tmp / 'repeated-episode'
        g.prepare(self.root, manifest, sub, directory)
        report = g.compare(self.root, manifest, directory, ballots_for(directory))
        self.assertIn('tuning_episode_reused_in_holdout', report['gate']['reasons'])
        self.assertIn('gold_before_generation_unverified', report['gate']['reasons'])

    def test_mutating_case_gold_or_private_provenance_fails(self):
        manifest, _, ballots = self.setup_trial()
        for filename, field in [('input.json', 'task'), ('gold.json', 'acceptable')]:
            path = self.root / 'demo-0' / filename
            original = g.load(path)
            g.write(path, dict(original, **{field: 'different'}))
            with self.assertRaisesRegex(ValueError, 'changed'):
                g.compare(self.root, manifest, self.directory, ballots)
            g.write(path, original)
        path = self.directory / 'private.json'
        key = g.load(path)
        key['submissions']['runs'][0]['input_mode'] = 'retrospective_alignment'
        g.write(path, key)
        with self.assertRaisesRegex(ValueError, 'Assignments changed'):
            g.compare(self.root, manifest, self.directory, ballots)

    def test_cli_missing_outcome_unknown_and_missing_pre_registration_held(self):
        _, submissions, _ = self.setup_trial()
        manifest = g.freeze(self.root)
        g.write(self.tmp / 'manifest.json', manifest)
        with redirect_stdout(io.StringIO()) as stdout:
            g.main(['outcome', str(self.root), str(self.tmp / 'manifest.json'), 'demo-0'])
        self.assertEqual('unknown', json.loads(stdout.getvalue())['status'])
        directory = self.tmp / 'pilot'
        submissions['runs'][0]['input_mode'] = 'retrospective_alignment'
        submissions['runs'][0]['closed_book'] = False
        g.prepare(self.root, manifest, submissions, directory)
        report = g.compare(self.root, manifest, directory, ballots_for(directory))
        for reason in ('design_not_preregistered', 'run_exposure_or_conditions_unverified',
                       'unused_holdout_authorization_unverified'):
            self.assertIn(reason, report['gate']['reasons'])


if __name__ == '__main__':
    unittest.main()
