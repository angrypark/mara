import copy
import hashlib
import json
import unittest
from mara.baseline_comparison import compare, rubric_bytes


class BaselineComparisonTests(unittest.TestCase):
    def fixture(self):
        raw = rubric_bytes()
        criteria = json.loads(raw)['criteria']
        rows = [{'id': c['id'], 'score': 3, 'weight': c['weight'], 'observation': 'Synthetic independently reviewed reason'} for c in criteria]
        a = {'id': 'single', 'source_sha256': 'a' * 64, 'criteria': rows, 'total': 75,
             'gates': [{'id': f'G{i}', 'status': 'pass'} for i in range(1, 5)]}
        b = copy.deepcopy(a); b['id'] = 'mara'; b['source_sha256'] = 'b' * 64
        return {'rubric_sha256': hashlib.sha256(raw).hexdigest(), 'outputs': [a, b],
                'condition_limits': ['Synthetic same-input analysis; no claim of causality'],
                'independence': 'independent_reviewer', 'blind': False,
                'execution_measurements': {'single': {'model_calls': 1, 'elapsed_seconds': 10, 'scope': 'analysis only'}}}

    def test_readability_gain_is_not_decision_gain_and_inputs_unchanged(self):
        x = self.fixture(); b = x['outputs'][1]
        b['criteria'][4]['score'] = 4; b['total'] = 78.75
        before = copy.deepcopy(x); result = compare(x, 'single', 'mara')
        self.assertEqual(result['content_score']['delta'], 3.75)
        self.assertEqual(result['decision_score_delta'], 0)
        self.assertEqual(result['evidence_score_delta'], 0)
        self.assertIsNone(result['execution_measurements']['mara'])
        self.assertEqual(result['reviewed_output_sha256']['mara'], 'b' * 64)
        self.assertEqual(x, before)

    def test_unknown_score_is_range_not_zero_and_gate_not_pass(self):
        x = self.fixture(); b = x['outputs'][1]
        b['criteria'][1]['score'] = None; b['total'] = None; b['gates'][0]['status'] = 'unknown'
        r = compare(x, 'single', 'mara')
        self.assertIsNone(r['decision_score_delta']); self.assertIsNone(r['content_score']['delta'])
        self.assertEqual(r['content_score']['delta_range'], [-18.75, 6.25])
        self.assertEqual(r['quality_gate_status'], 'unknown')
        b['gates'][1]['status'] = 'fail'
        self.assertEqual(compare(x, 'single', 'mara')['quality_gate_status'], 'fail')

    def test_invalid_receipts_scores_totals_and_duplicate_rows_rejected(self):
        def duplicate(x): x['outputs'][1]['criteria'][1] = copy.deepcopy(x['outputs'][1]['criteria'][0])
        def wrong_weight(x): x['outputs'][1]['criteria'][0]['weight'] = 30
        def bad_score(x): x['outputs'][1]['criteria'][0]['score'] = float('nan')
        def fractional(x): x['outputs'][1]['criteria'][0]['score'] = 3.1
        def boolean(x): x['outputs'][1]['criteria'][0]['score'] = True
        def total(x): x['outputs'][1]['total'] = 100
        def unknown_total(x): x['outputs'][1]['criteria'][0]['score'] = None
        def digest(x): x['outputs'][1]['source_sha256'] = ''
        def rubric(x): x['rubric_sha256'] = '0' * 64
        def gates(x): x['outputs'][1]['gates'].pop()
        def conditions(x): x['condition_limits'] = []
        def duplicate_candidate(x): x['outputs'][1]['id'] = 'single'
        for change in (duplicate, wrong_weight, bad_score, fractional, boolean, total, unknown_total, digest, rubric, gates, conditions, duplicate_candidate):
            with self.subTest(change=change.__name__):
                x = self.fixture(); change(x)
                with self.assertRaises(ValueError): compare(x, 'single', 'mara')

    def test_negative_delta_is_preserved(self):
        x = self.fixture(); x['outputs'][1]['criteria'][1]['score'] = 2.5; x['outputs'][1]['total'] = 71.875
        r = compare(x, 'single', 'mara')
        self.assertEqual(r['content_score']['delta'], -3.125)
        self.assertEqual(r['decision_score_delta'], -0.5)


if __name__ == '__main__':
    unittest.main()
