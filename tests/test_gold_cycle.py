from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mara.gold_cycle import decide, register, decision_reasons
from mara.decision_gold import digest


class GoldCycleTests(unittest.TestCase):
    def test_registration_cannot_be_overwritten_or_reused_after_gold_change(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            manifest, registration = d/'manifest', d/'reg'
            manifest.write_text('{}')
            proposal = dict(target_axis='decision', id='h1', observation='missing quote', source_ref='tuning/cite',
                            hypothesis='quoting input improves traceability', change_ref='diff123',
                            candidate='candidate2', expected_change='fewer missing references', falsifier='no paired gains')
            register(proposal, manifest, registration)
            with self.assertRaises(FileExistsError):
                register(proposal, manifest, registration)
            manifest.write_text('{"v":2}')
            with self.assertRaisesRegex(ValueError, 'manifest'):
                decide(registration, d, manifest, d, d/'ballots', d/'decision')
            self.assertFalse((d/'decision').exists())

    def test_hypothesis_requires_evidence_and_falsifier(self):
        with self.assertRaises(ValueError):
            register({'id':'x'}, Path('missing'), Path('missing'))

    def test_overall_victory_cannot_override_a_failed_prediction(self):
        proposal = {'target_axis': 'decision', 'change_ref': 'v2'}
        manifest = {'design': {'hypothesis_sha256': digest(proposal)}}
        report = {'candidate': 'team', 'systems': {'team': {'version': 'v2'}, 'single': {}},
                  'gate': {'status': 'eligible_on_locked_cases', 'reasons': []},
                  'comparisons': [{'split': 'locked', 'comparator': 'single',
                                   'judgments': [{'axis_votes': {'decision': -1}}]}]}
        self.assertIn('target_axis_gain_not_verified:single', decision_reasons({'proposal': proposal}, manifest, report))
        report['comparisons'][0]['judgments'][0]['axis_votes']['decision'] = 1
        self.assertEqual(decision_reasons({'proposal': proposal}, manifest, report), [])
        manifest['design'] = {}
        self.assertIn('hypothesis_not_bound_to_frozen_design', decision_reasons({'proposal': proposal}, manifest, report))

    def test_custodian_cannot_reassign_an_exposed_episode(self):
        import json
        from mara.gold_cycle import reserve, has_reservation, digest as file_digest
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, ledger = root/'cases', root/'ledger.sqlite3'
            data = {'cases': {'c': {'split':'locked','independence_unit':'same dated event'}}}
            manifest.write_text(json.dumps(data))
            reg = root/'reg'
            reg.write_text(json.dumps({'manifest_sha256': file_digest(manifest)}))
            self.assertFalse(has_reservation(reg, data, ledger))
            reserve(reg, manifest, ledger)
            self.assertTrue(has_reservation(reg, data, ledger))
            with self.assertRaisesRegex(ValueError, 'Previously reserved'):
                reserve(reg, manifest, ledger)

    def test_first_batch_and_ballots_are_immutable_for_registered_run(self):
        from mara.gold_cycle import seal_value
        with TemporaryDirectory() as tmp:
            ledger = Path(tmp)/'custodian'
            for stage in ('batch', 'ballots'):
                seal_value(ledger, 'registered', stage, 'original')
                seal_value(ledger, 'registered', stage, 'original')
                with self.assertRaisesRegex(ValueError, 'prior'):
                    seal_value(ledger, 'registered', stage, 'substitution')
