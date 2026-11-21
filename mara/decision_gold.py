"""Point-in-time decision evaluation. CLI commands never invoke a model or place orders."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets

from .baseline_comparison import finite, rubric_bytes


VERSION = 'mara.decision-gold/1'
AXES = {
    'decision': '선택과 규모, 단순 대안 대비 기회비용 및 재검토 조건',
    'evidence': '당시 근거, 단위, 시점, 자료 공백과 불확실성',
    'suitability': '현금 필요, 기간, 실제 보유와 위험 제약 준수',
    'alternatives': '허용되는 대안과 반례, 반증 근거 및 판단 경계',
}
POLICY = {
    'version': VERSION, 'axes': AXES, 'min_repeats': 2, 'min_regimes': 2,
    'family_alpha': 0.05, 'case_statistic': 'paired case sign; repeats and judges nested',
    'required_comparators': ['mara', 'simple', 'single'],
    'gate': 'All locked cases, frozen design and authorized unused holdout; concordant blind judges, no candidate hard failure, no observed case reversal or loss; familywise case sign test.',
    'b1_content_rubric_sha256': hashlib.sha256(rubric_bytes()).hexdigest(),
}
CLOCKS = ('observed_at', 'released_at', 'revision_at', 'available_at')
GOLD_FIELDS = ('acceptable', 'required', 'prohibited')
VOTES = {'A': 1, 'B': -1, 'tie': 0, 'unknown': None}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def check(condition, message):
    if not condition:
        raise ValueError(message)


def string(value):
    return isinstance(value, str) and bool(value.strip())


def string_list(value):
    return isinstance(value, list) and bool(value) and all(string(s) for s in value)


def instant(value):
    if not isinstance(value, str) or not re.search(r'T\d\d:\d\d', value):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.utcoffset() is not None else None
    except ValueError:
        return None


def case_path(root, case_id):
    check(isinstance(case_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', case_id), 'Invalid case ID')
    return Path(root) / case_id


def replay(case):
    """Only this allowlisted projection is supplied to report authors."""
    cutoff = instant(case['as_of'])
    check(cutoff is not None, 'Cutoff requires a timezone-aware instant')
    check(string(case['version']) and string(case['task']), 'Case version and task required')
    check(case['split'] in ('locked', 'tuning') and string_list(case['regimes']), 'Invalid case classification')
    check(all(isinstance(case[k], dict) for k in ('holdings', 'persona')), 'Fixed persona and holdings required')
    check(isinstance(case['records'], list), 'Evidence list required')
    selected = {}
    ids = set()
    versions = set()
    for row in case['records']:
        record_id, series = row['id'], row['series_id']
        check(string(record_id) and string(series) and record_id not in ids, 'Unique record and series IDs required')
        ids.add(record_id)
        clocks = [instant(row.get(k)) for k in CLOCKS]
        if any(t is None or t > cutoff for t in clocks):
            continue
        observed, released, revision, available = clocks
        check(observed <= revision and released <= revision <= available, 'Impossible record chronology: ' + record_id)
        check(string(row.get('text')) and string(row.get('source')), 'Frozen source and text required')
        check((series, revision) not in versions, 'Ambiguous versions of ' + series)
        versions.add((series, revision))
        if series not in selected or revision > selected[series][0]:
            selected[series] = revision, {k: row[k] for k in ('id', 'series_id', *CLOCKS, 'source', 'text')}
    packet = {k: case[k] for k in ('case_id', 'version', 'as_of', 'task', 'persona', 'holdings')}
    for key in ('alternatives', 'constraints'):
        if key in case:
            packet[key] = case[key]
    packet['records'] = [selected[k][1] for k in sorted(selected)]
    return packet


def oracle(gold):
    check(all(string_list(gold.get(k)) for k in GOLD_FIELDS), 'Gold needs acceptable, required and prohibited lists')
    return {kind + ':' + str(i): text for kind in GOLD_FIELDS for i, text in enumerate(gold[kind], 1)}


def freeze(root, design=None):
    cases = {}
    for path in sorted(Path(root).glob('*/input.json')):
        case = load(path)
        case_id = case['case_id']
        directory = case_path(root, case_id)
        check(directory == path.parent, 'Case folder differs from ID')
        gold = load(directory / 'gold.json')
        oracle(gold)
        for field in ('case_id', 'version', 'split'):
            check(gold.get(field, case[field]) == case[field], 'Gold and case identification differ')
        outcome_path = directory / 'outcome.json'
        cases[case_id] = {
            'split': case['split'], 'regimes': case['regimes'], 'version': case['version'],
            'input_sha256': digest(case), 'replay_sha256': digest(replay(case)),
            'gold_sha256': digest(gold),
            'gold_provenance_recorded': (instant(gold.get('frozen_at')) is not None
                                         and isinstance(gold.get('adjudicator'), dict)
                                         and string(gold['adjudicator'].get('basis'))),
            'independence_unit': case.get('independence_unit'),
            'outcome_sha256': digest(load(outcome_path)) if outcome_path.exists() else None,
        }
    check(cases, 'No cases found')
    if design is not None:
        design_fields(design)
    return {'version': VERSION, 'policy_sha256': digest(POLICY), 'cases': cases, 'design': design}


def checked(root, manifest, case_id, part):
    check(manifest['version'] == VERSION and manifest['policy_sha256'] == digest(POLICY), 'Frozen policy differs')
    check(case_id in manifest['cases'], 'Unregistered case')
    record = load(case_path(root, case_id) / (part + '.json'))
    frozen = manifest['cases'][case_id]
    check(digest(record) == frozen[part + '_sha256'], 'Frozen ' + part + ' changed: ' + case_id)
    if part == 'input':
        check(record['case_id'] == case_id and record['split'] == frozen['split'] and record['regimes'] == frozen['regimes']
              and digest(replay(record)) == frozen['replay_sha256'], 'Frozen replay or split differs')
    return record


def path_metrics(rows, field):
    levels = [r[field] for r in rows]
    check(all(finite(v) and v > 0 for v in levels), 'Positive finite levels required')
    peak = start = trough = 0
    drawdown = 0.0
    for i, value in enumerate(levels):
        if value >= levels[peak]:
            peak = i
        loss = 1 - value / levels[peak]
        if loss > drawdown:
            drawdown, start, trough = loss, peak, i
    recovery = next((j for j in range(trough + 1, len(levels)) if levels[j] >= levels[start]), None) if drawdown else None
    return {'return': levels[-1] / levels[0] - 1, 'max_drawdown': drawdown,
            'peak_date': rows[start]['date'] if drawdown else None,
            'trough_date': rows[trough]['date'] if drawdown else None,
            'recovery_date': rows[recovery]['date'] if recovery is not None else None,
            'peak_to_recovery_days': ((date.fromisoformat(rows[recovery]['date']) - date.fromisoformat(rows[start]['date'])).days
                                      if recovery is not None else None),
            'recovery_status': ('no_drawdown' if not drawdown else
                                'recovered' if recovery is not None else 'unrecovered_at_horizon')}


def outcome(case, data):
    rows = data['series']
    check(all(string(data.get(k)) for k in ('asset_label', 'benchmark_label', 'basis')), 'Outcome interpretation required')
    check(isinstance(rows, list) and len(rows) >= 2, 'At least two common observations required')
    dates = [date.fromisoformat(r['date']) for r in rows]
    check(dates == sorted(set(dates)) and dates[0] >= instant(case['as_of']).date(), 'Invalid post-decision horizon')
    a, b = path_metrics(rows, 'asset'), path_metrics(rows, 'benchmark')
    alternatives = data.get('counterfactuals', {})
    check(isinstance(alternatives, dict) and all(string(k) and string(v) for k, v in alternatives.items()),
          'Counterfactual names and shared series columns required')
    paths = {name: path_metrics(rows, column) for name, column in alternatives.items()}
    return {'case_id': case['case_id'], 'scope': 'ex_post_only', 'status': 'available',
            'counterfactuals': paths, 'causal_attribution': 'unidentified', 'start': rows[0]['date'], 'end': rows[-1]['date'],
            'observations': len(rows), 'asset_label': data['asset_label'], 'benchmark_label': data['benchmark_label'],
            'basis': data['basis'], 'asset': a, 'benchmark': b, 'excess_return': a['return'] - b['return'],
            'interpretation': '관측일 수준으로 계산한 공통 구간의 경로와 단순 수익률 차이예요. 당시 의사결정의 점수와 독립적으로 해석해요.'}


def design_fields(spec):
    systems = spec['systems']
    check(isinstance(systems, dict) and len(systems) >= 2, 'Two or more systems required')
    for name, system in systems.items():
        check(string(name) and system['kind'] in POLICY['required_comparators'] and string(system.get('version')),
              'Each system needs its kind and immutable version identifier')
    check(spec['candidate'] in systems and systems[spec['candidate']]['kind'] == 'mara', 'Mara candidate required')
    check(len({(s['kind'], s['version']) for s in systems.values()}) == len(systems), 'Duplicate system version')
    judges = spec['judges']
    check(string_list(judges) and len(judges) >= 2 and len(set(judges)) == len(judges) and len(judges) % 2 == 0,
          'Distinct even-sized counterbalanced judge panel required')
    return {k: spec[k] for k in ('candidate', 'systems', 'judges')}


def normalize_runs(root, manifest, submissions):
    design = design_fields(submissions)
    frozen = manifest.get('design')
    if frozen:
        check(design == design_fields(frozen), 'Submission differs from registered design')
    indexed = {}
    run_ids = set()
    inputs = {}
    for row in submissions['runs']:
        case_id, system, repeat = row['case_id'], row['system'], row['repeat']
        key = case_id, repeat, system
        check(system in design['systems'] and type(repeat) is int and repeat >= 1 and key not in indexed, 'Duplicate or invalid trial')
        check(string(row['author']) and row['author'] not in design['judges'], 'A judge cannot author a submission')
        check(string(row['run_id']) and row['run_id'] not in run_ids, 'Independent run IDs required')
        check(string(row['text']), 'Empty report')
        if case_id not in inputs:
            case = checked(root, manifest, case_id, 'input')
            inputs[case_id] = replay(case), oracle(checked(root, manifest, case_id, 'gold'))
        check(row['input_sha256'] == digest(inputs[case_id][0]), 'Run used a different frozen replay')
        run_ids.add(row['run_id'])
        indexed[key] = row
    check(indexed, 'No submissions')
    return indexed, inputs


def build_packets(root, manifest, submissions, seed):
    indexed, inputs = normalize_runs(root, manifest, submissions)
    candidate = submissions['candidate']
    judges = submissions['judges']
    bundles = {}
    manifest_sha, submissions_sha = digest(manifest), digest(submissions)
    for (case_id, repeat, system), rival in sorted(indexed.items()):
        if system == candidate:
            continue
        target = indexed.get((case_id, repeat, candidate))
        check(target, 'Missing paired candidate trial')
        material, standard = inputs[case_id]
        pair = [manifest_sha, submissions_sha, case_id, repeat, system, candidate, target['run_id'], rival['run_id']]
        tag = hmac.new(seed.encode(), digest(pair).encode(), hashlib.sha256).hexdigest()
        for i, judge in enumerate(judges):
            tag_j = hmac.new(seed.encode(), (tag + ':' + str(i)).encode(), hashlib.sha256).hexdigest()
            slot = 'A' if (int(tag[:2], 16) + i) % 2 == 0 else 'B'
            order = [target, rival] if slot == 'A' else [rival, target]
            packet = {
                'token': tag_j, 'task': material, 'standard': standard, 'axes': AXES,
                'reports': {k: r['text'] for k, r in zip('AB', order)},
                'instructions': '독립적으로 A/B를 평가하세요. 각 축에서 양쪽의 원문 인용, 당시 기록 또는 기준 ID, 구체적인 이유, 양쪽의 중대한 위반 여부를 적으세요. 우열은 네 축의 다수결로 집계하고 미확인이 있으면 unknown으로 남겨요. 신원 추정·사후 자료 노출은 표시하세요.',
                'ballot_format': {'packet_sha256': 'delivery digest', 'judge': 'assigned judge ID',
                                  'session_id': 'distinct independent evaluation call ID',
                                  'independent': 'boolean', 'identity_hidden': 'boolean', 'outcomes_hidden': 'boolean',
                                  'preference': 'A/B/tie/unknown', 'rulings': [
                                      {'id': 'one per axis', 'winner': 'A/B/tie/unknown', 'quote_a': 'exact report excerpt',
                                       'quote_b': 'exact report excerpt', 'reference_ids': ['required:1 or record:<id>'],
                                       'reason': 'case-specific reasoning', 'gate_a': 'pass/fail/unknown',
                                       'gate_b': 'pass/fail/unknown'}]},
            }
            key = digest(packet)
            bundles[key] = (packet, dict(case_id=case_id, repeat=repeat, comparator=system, judge=judge, candidate_slot=slot))
    check(bundles, 'No paired trial')
    return bundles


def prepare(root, manifest, submissions, output_dir):
    seed = secrets.token_hex(32)
    bundles = build_packets(root, manifest, submissions, seed)
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    (output_dir / 'packets').mkdir()
    for key, (packet, _) in bundles.items():
        write(output_dir / 'packets' / (key + '.json'), packet)
    write(output_dir / 'private.json', {'manifest_sha256': digest(manifest), 'submissions': submissions, 'seed': seed,
                                       'assignments': {k: v[1] for k, v in bundles.items()}})
    return {'packets': len(bundles), 'directory': str(output_dir),
            'delivery': '각 평가자에게 배정된 packets 파일만 전달해요. private.json에는 작성 시스템과 배정표가 있어요.'}


def judge_ballot(ballot, packet, assignment):
    check(ballot['judge'] == assignment['judge'] and string(ballot['session_id']), 'Wrong judge or missing evaluation session')
    flags = ['independent', 'identity_hidden', 'outcomes_hidden']
    check(all(type(ballot[k]) is bool for k in flags), 'Explicit judge attestations required')
    rulings = ballot['rulings']
    check(len(rulings) == len(AXES) and {r['id'] for r in rulings} == set(AXES), 'One ruling per frozen axis required')
    references = set(packet['standard']) | {'record:' + r['id'] for r in packet['task']['records']}
    votes = []
    for row in rulings:
        check(row['winner'] in VOTES and string(row['reason']), 'Reason and known vote required')
        check(string_list(row['reference_ids']) and set(row['reference_ids']) <= references, 'Unknown or absent ex-ante reference')
        for slot in 'AB':
            quote = row['quote_' + slot.lower()]
            check(string(quote) and len(quote.strip()) >= 3 and quote in packet['reports'][slot], 'Untraceable report excerpt')
            check(row['gate_' + slot.lower()] in ('pass', 'fail', 'unknown'), 'Invalid or absent hard gate')
        votes.append(VOTES[row['winner']])
    score = None if None in votes else sum(votes)
    preference = 'unknown' if score is None else 'A' if score > 0 else 'B' if score < 0 else 'tie'
    check(ballot['preference'] == preference, 'Pair preference differs from frozen ruling aggregation')
    slot = assignment['candidate_slot']
    return {
        'packet_sha256': digest(packet), 'judge': ballot['judge'], 'session_id': ballot['session_id'],
        'candidate_slot': slot, 'valid_blind_review': all(ballot[k] for k in flags),
        'attestations': {k: ballot[k] for k in flags},
        'preference': None if score is None else VOTES[preference] * VOTES[slot],
        'candidate_gates': [r['gate_' + slot.lower()] for r in rulings],
        'all_gates_known': all(r['gate_' + s] != 'unknown' for r in rulings for s in ('a', 'b')),
        'axis_votes': {r['id']: None if r['winner'] == 'unknown' else VOTES[r['winner']] * VOTES[slot] for r in rulings},
        'rulings': rulings,
    }


def sign_test(wins, losses):
    """One-sided exact sign test. Ties do not count as independent wins."""
    n = wins + losses
    return sum(math.comb(n, j) for j in range(wins, n + 1)) / 2**n if n else 1.0


def summarize(locked, comparators, comparisons, required_repeats, judge_count, blockers):
    results = {}
    for system in comparators:
        case_results = []
        for case_id in locked:
            rows = [r for r in comparisons if r['case_id'] == case_id and r['comparator'] == system]
            observed = [j['preference'] for r in rows for j in r['judgments'] if j['preference'] is not None]
            agreed = [r['paired_preference'] for r in rows]
            complete = (sorted(r['repeat'] for r in rows) == list(range(1, required_repeats + 1))
                        and all(r['received'] == judge_count for r in rows) and None not in agreed)
            case_vote = None
            if not complete:
                blockers.add('incomplete_or_disputed_locked_case')
            elif len(set(agreed)) != 1:
                blockers.add('unstable_across_repeats')
            else:
                case_vote = agreed[0]
            case_results.append({'case_id': case_id, 'case_vote': case_vote, 'observed_votes': len(observed),
                                 'observed_vote_range': [min(observed), max(observed)] if observed else None})
        counts = Counter(r['case_vote'] for r in case_results)
        p = sign_test(counts[1], counts[-1])
        if counts[-1]:
            blockers.add('observed_locked_case_loss')
        if p > POLICY['family_alpha'] / len(comparators):
            blockers.add('insufficient_case_level_evidence')
        results[system] = {'wins': counts[1], 'ties': counts[0], 'losses': counts[-1], 'unknown': counts[None],
                           'one_sided_exact_sign_p': p, 'familywise_threshold': POLICY['family_alpha'] / len(comparators),
                           'cases': case_results}
    return results


def compare(root, manifest, directory, ballots):
    directory = Path(directory)
    index = load(directory / 'private.json')
    submissions = index['submissions']
    check(digest(manifest) == index['manifest_sha256'], 'Manifest changed after blinding')
    bundles = build_packets(root, manifest, submissions, index['seed'])
    check({k: v[1] for k, v in bundles.items()} == index['assignments'], 'Assignments changed after blinding')
    check({p.name for p in (directory / 'packets').iterdir()} == {k + '.json' for k in bundles}, 'Missing or extra packet files')
    for key in bundles:
        check(digest(load(directory / 'packets' / (key + '.json'))) == key, 'Delivered blind packet changed')
    check(isinstance(ballots, list), 'Ballots must be a list')
    seen = set()
    sessions = {r['run_id'] for r in submissions['runs']}
    grouped = defaultdict(list)
    for key, (_, m) in bundles.items():
        grouped[m['case_id'], m['repeat'], m['comparator']]
    for ballot in ballots:
        key = ballot['packet_sha256']
        check(key in bundles and key not in seen, 'Unknown or duplicate ballot binding')
        packet, assignment = bundles[key]
        judgment = judge_ballot(ballot, packet, assignment)
        check(judgment['session_id'] not in sessions, 'Judging requires a fresh independent session per ballot')
        sessions.add(judgment['session_id'])
        seen.add(key)
        grouped[assignment['case_id'], assignment['repeat'], assignment['comparator']].append(judgment)
    design = manifest['design'] or {}
    blockers = set()
    if not design:
        blockers.add('design_not_preregistered')
    holdout = design.get('holdout', {})
    if not (holdout.get('untouched') is True and string(holdout.get('authorization_ref')) and string(holdout.get('custodian'))):
        blockers.add('unused_holdout_authorization_unverified')
    conditions = design.get('conditions', {})
    if not all(string(conditions.get(k)) for k in ('evidence_access', 'resource_budget', 'generation_protocol')):
        blockers.add('input_or_budget_controls_unregistered')
    systems, candidate, judges = submissions['systems'], submissions['candidate'], submissions['judges']
    comparators = sorted(set(systems) - {candidate})
    if {systems[s]['kind'] for s in comparators} != set(POLICY['required_comparators']):
        blockers.add('missing_required_comparator')
    locked = sorted(k for k, v in manifest['cases'].items() if v['split'] == 'locked')
    if not locked:
        blockers.add('no_locked_cases')
    units = [manifest['cases'][k].get('independence_unit') for k in locked]
    if not all(string(unit) for unit in units) or len(set(units)) != len(units):
        blockers.add('independent_case_units_unverified')
    tuning_units = {c.get('independence_unit') for c in manifest['cases'].values() if c['split'] == 'tuning'}
    if any(unit and unit in tuning_units for unit in units):
        blockers.add('tuning_episode_reused_in_holdout')
    if not all(manifest['cases'][k].get('gold_provenance_recorded') is True for k in locked):
        blockers.add('gold_provenance_unverified')
    if not all(re.fullmatch(r'[0-9a-f]{64}', s.get('artifact_sha256', '')) for s in systems.values()):
        blockers.add('variant_provenance_unverified')
    locked_regimes = {regime for k in locked for regime in manifest['cases'][k]['regimes']}
    if len(locked_regimes) < POLICY['min_regimes']:
        blockers.add('insufficient_regime_coverage')
    repeats = design.get('repeats', POLICY['min_repeats'])
    check(type(repeats) is int and 0 < repeats <= 1000, 'Invalid prespecified repeat count')
    if design.get('repeats') is None or repeats < POLICY['min_repeats']:
        blockers.add('insufficient_registered_repeats')
    gold_freezes = {case_id: instant(checked(root, manifest, case_id, 'gold').get('frozen_at'))
                    for case_id in locked}
    cost_records = []
    report_digests = defaultdict(list)
    for row in submissions['runs']:
        report_digests[digest(row['text'])].append(row['run_id'])
        if row['case_id'] in locked:
            started = instant(row.get('started_at'))
            frozen = gold_freezes[row['case_id']]
            if started is None or frozen is None or started < frozen:
                blockers.add('gold_before_generation_unverified')
            if (row.get('conditions_sha256') != digest(conditions) or row.get('closed_book') is not True
                    or row.get('input_mode') != 'frozen_replay'):
                blockers.add('run_exposure_or_conditions_unverified')
            if row['author'] == holdout.get('custodian') or holdout.get('custodian') in judges:
                blockers.add('holdout_custody_conflict')
        cost_records.append({'run_id': row['run_id'], 'measurements': row.get('costs')})
    comparisons = []
    for (case_id, repeat, comparator), judgments in sorted(grouped.items()):
        judgments.sort(key=lambda j: j['judge'])
        prefs = {j['preference'] for j in judgments}
        complete = len(judgments) == len(judges)
        agreed = complete and len(prefs) == 1 and None not in prefs and all(j['valid_blind_review'] for j in judgments)
        disputes = [axis for axis in AXES if len({j['axis_votes'][axis] for j in judgments}) > 1]
        row = {'case_id': case_id, 'split': manifest['cases'][case_id]['split'], 'repeat': repeat,
               'comparator': comparator, 'received': len(judgments), 'expected': len(judges),
               'judgments': judgments, 'axis_disagreements': disputes,
               'preference_disagreement': len(prefs) > 1, 'paired_preference': next(iter(prefs)) if agreed else None}
        comparisons.append(row)
        if case_id in locked:
            if not all(j['valid_blind_review'] for j in judgments):
                blockers.add('independence_or_blinding_unverified')
            if any(not j['all_gates_known'] or set(j['candidate_gates']) != {'pass'} for j in judgments):
                blockers.add('unknown_gate_or_candidate_failure')
            if disputes:
                blockers.add('ruling_disagreement')
            if any(j['axis_votes']['decision'] == -1 for j in judgments):
                blockers.add('locked_decision_axis_loss')
            for judgment in judgments:
                reports = bundles[judgment['packet_sha256']][0]['reports']
                if reports['A'] == reports['B'] and judgment['preference'] in (-1, 1):
                    blockers.add('preference_for_identical_reports')
    uncertainty = summarize(locked, comparators, comparisons, repeats, len(judges), blockers)
    return {'schema_version': 'mara.decision-gold-comparison/1', 'candidate': candidate, 'systems': systems,
            'manifest_sha256': digest(manifest), 'submissions_sha256': digest(submissions), 'ballots_sha256': digest(ballots),
            'comparisons': comparisons, 'uncertainty': uncertainty,
            'missing_ballots': len(bundles) - len(seen), 'locked_cases': locked, 'locked_regimes': sorted(locked_regimes),
            'execution_measurements': cost_records,
            'identical_output_runs': [v for v in report_digests.values() if len(v) > 1],
            'gate': {'status': 'hold' if blockers else 'eligible_on_locked_cases', 'reasons': sorted(blockers)},
            'scope': '한 사례의 반복과 평가자를 독립 사례 수에 더하지 않아요. 부호 검정은 독립적인 사례 표집을 가정하며 같은 시장 구간·유사 사례 간 의존성은 별도 판단이 필요해요. 사후 수익은 이 판정에 들어가지 않아요.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('freeze')
    p.add_argument('cases', type=Path)
    p.add_argument('--design', type=Path, help='Design registered before reports or holdout access')
    for name in ('replay', 'outcome', 'prepare', 'compare'):
        p = subs.add_parser(name)
        p.add_argument('cases', type=Path)
        p.add_argument('manifest', type=Path)
        if name in ('replay', 'outcome'):
            p.add_argument('case_id')
        if name == 'prepare':
            p.add_argument('submissions', type=Path)
        if name in ('prepare', 'compare'):
            p.add_argument('directory', type=Path)
        if name == 'compare':
            p.add_argument('ballots', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'freeze':
            result = freeze(args.cases, load(args.design) if args.design else None)
        else:
            manifest = load(args.manifest)
            if args.command in ('replay', 'outcome'):
                case = checked(args.cases, manifest, args.case_id, 'input')
                if args.command == 'replay':
                    result = replay(case)
                elif manifest['cases'][args.case_id]['outcome_sha256'] is None:
                    result = {'case_id': args.case_id, 'scope': 'ex_post_only', 'status': 'unknown',
                              'reason': 'No outcome series in the frozen manifest', 'causal_attribution': 'unidentified'}
                else:
                    result = outcome(case, checked(args.cases, manifest, args.case_id, 'outcome'))
            elif args.command == 'prepare':
                result = prepare(args.cases, manifest, load(args.submissions), args.directory)
            else:
                result = compare(args.cases, manifest, args.directory, load(args.ballots))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, 'decision-gold: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
