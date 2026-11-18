"""B1: summarize independent single-agent comparisons without judging investments.

Scores come from a separately recorded reviewer. This module validates and
aggregates them; it neither calls a model nor changes Q1 or a saved decision.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from .registry import resource


def rubric_bytes():
    return resource('resources/decision-content-rubric.json').read_bytes()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def checked_scores(output, rubric):
    if not re.fullmatch(r'[0-9a-f]{64}', output.get('source_sha256', '')):
        raise ValueError('Reviewed output digest required')
    rows = output['criteria']
    expected = {c['id']: c['weight'] for c in rubric['criteria']}
    if len(rows) != len(expected) or {r['id'] for r in rows} != set(expected):
        raise ValueError('Each criterion must occur exactly once')
    scores = {}
    for row in rows:
        value = row['score']
        if row['weight'] != expected[row['id']]:
            raise ValueError('Frozen criterion weight differs')
        if value is not None and (not finite(value) or not 0 <= value <= 4 or value * 2 != int(value * 2)):
            raise ValueError('Score must be null or 0..4 in half steps')
        if not isinstance(row.get('observation'), str) or not row['observation'].strip():
            raise ValueError('Reviewer observation required')
        scores[row['id']] = value
    low = sum(expected[k] * v / 4 for k, v in scores.items() if v is not None)
    high = low + sum(expected[k] for k, v in scores.items() if v is None)
    total = low if all(v is not None for v in scores.values()) else None
    supplied = output.get('total')
    if total is None:
        if supplied is not None:
            raise ValueError('Unknown criteria cannot have a point total')
    elif not finite(supplied) or not math.isclose(supplied, total, abs_tol=1e-9):
        raise ValueError('Reported total differs from frozen weighted scores')
    gates = output.get('gates', [])
    if len(gates) != 4 or {g['id'] for g in gates} != {'G1', 'G2', 'G3', 'G4'}:
        raise ValueError('All four quality gates required')
    if any(g.get('status') not in ('pass', 'fail', 'unknown') for g in gates):
        raise ValueError('Invalid quality gate status')
    return scores, total, [low, high]


def compare(assessment, baseline_id, candidate_id):
    raw = rubric_bytes(); rubric = json.loads(raw)
    sha = hashlib.sha256(raw).hexdigest()
    if assessment.get('rubric_sha256') != sha:
        raise ValueError('Assessment must use the frozen B1 content rubric')
    outputs = assessment['outputs']
    if len({o['id'] for o in outputs}) != len(outputs):
        raise ValueError('Duplicate candidate ID')
    if baseline_id == candidate_id:
        raise ValueError('Baseline and candidate must differ')
    indexed = {o['id']: o for o in outputs}
    baseline, candidate = indexed[baseline_id], indexed[candidate_id]
    bs, bt, br = checked_scores(baseline, rubric)
    cs, ct, cr = checked_scores(candidate, rubric)
    delta = {k: cs[k] - bs[k] if cs[k] is not None and bs[k] is not None else None for k in bs}
    statuses = [g['status'] for o in (baseline, candidate) for g in o['gates']]
    gate_status = 'fail' if 'fail' in statuses else 'unknown' if 'unknown' in statuses else 'pass'
    conditions = assessment.get('condition_limits')
    if not isinstance(conditions, list) or not conditions or not all(isinstance(c, str) and c.strip() for c in conditions):
        raise ValueError('Comparison conditions and limits required')
    costs = assessment.get('execution_measurements', {})
    return {
        'schema_version': 'mara.baseline-comparison/1.0', 'metric_id': 'B1',
        'rubric_sha256': sha, 'baseline_id': baseline_id, 'candidate_id': candidate_id,
        'reviewed_output_sha256': {baseline_id: baseline['source_sha256'], candidate_id: candidate['source_sha256']},
        'assessment_sha256': hashlib.sha256(json.dumps(assessment, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        'content_score': {'baseline': bt, 'candidate': ct,
            'delta': ct - bt if ct is not None and bt is not None else None,
            'delta_range': [cr[0] - br[1], cr[1] - br[0]]},
        'criterion_deltas': delta,
        'decision_score_delta': delta['C2'], 'evidence_score_delta': delta['C3'],
        'quality_gate_status': gate_status,
        'gates': {baseline_id: baseline['gates'], candidate_id: candidate['gates']},
        'execution_measurements': {baseline_id: costs.get(baseline_id), candidate_id: costs.get(candidate_id)},
        'paired_assessment': assessment.get('paired_assessment'),
        'condition_limits': conditions,
        'independence': assessment.get('independence', 'unverified'),
        'blind': assessment.get('blind'),
        'interpretation': 'Observed score differences in this case only. A higher total does not establish better allocation decisions, causal orchestration value, efficiency or investment performance. Review the paired reasons, C2/C3, gates and input/cost scope separately.',
    }


def main():
    parser = argparse.ArgumentParser(description='B1 single-agent comparison; no model call or database mutation')
    parser.add_argument('assessment', type=Path)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.assessment.read_text()), args.baseline, args.candidate)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
