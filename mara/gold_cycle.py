"""Register a falsifiable change and decide it against an independently scored replay."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from .decision_gold import AXES, digest as value_digest
from .registry import resource


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_new(path, data):
    with Path(path).open('x', encoding='utf-8') as out:
        json.dump(data, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write('\n')


def register(proposal, manifest, dest):
    fields = ('id', 'observation', 'source_ref', 'hypothesis', 'change_ref',
              'candidate', 'expected_change', 'falsifier')
    if any(not isinstance(proposal.get(key), str) or not proposal[key].strip() for key in fields):
        raise ValueError('Provide an observed problem, evidence, prediction, change and falsifier')
    if proposal.get('target_axis') not in AXES:
        raise ValueError('Register a specific scored target_axis')
    if 'decision' in proposal or 'report' in proposal:
        raise ValueError('Register the hypothesis before comparing the candidate')
    registration = {'schema': 'mara.gold-hypothesis/1', 'proposal': proposal,
                    'manifest_sha256': digest(manifest)}
    save_new(dest, registration)
    return registration


def holdout_units(manifest):
    records = [value for value in manifest['cases'].values() if value['split'] == 'locked']
    units = [r['independence_unit'] for r in records]
    if not units or any(not isinstance(u, str) or not u for u in units) or len(set(units)) != len(units):
        raise ValueError('Unique unused decision episodes required')
    return units


def reserve(registration, manifest, ledger):
    """A custodian claims all decision episodes before distributing any locked packet."""
    data = read(manifest)
    if read(registration)['manifest_sha256'] != digest(manifest):
        raise ValueError('Registration must bind the manifest')
    units = holdout_units(data)
    public = read(resource('resources/decision-gold/manifest-v1.json'))
    public_units = {row.get('independence_unit') for row in public['cases'].values()}
    if public_units.intersection(units):
        raise ValueError('Published regression episodes cannot serve as unseen holdout')
    with sqlite3.connect(ledger) as db:
        db.execute('CREATE TABLE IF NOT EXISTS claims (unit TEXT PRIMARY KEY, registration TEXT NOT NULL)')
        try:
            db.executemany('INSERT INTO claims VALUES (?, ?)', [(u, digest(registration)) for u in units])
        except sqlite3.IntegrityError as exc:
            raise ValueError('Previously reserved decision episode; use a fresh locked set') from exc
    return units


def has_reservation(registration, manifest, ledger):
    if ledger is None or not Path(ledger).is_file():
        return False
    try:
        units = set(holdout_units(manifest))
        with sqlite3.connect(Path(ledger).resolve().as_uri() + '?mode=ro', uri=True) as db:
            found = {r[0] for r in db.execute('SELECT unit FROM claims WHERE registration=?', (digest(registration),))}
        return units == found
    except (ValueError, sqlite3.DatabaseError):
        return False


def seal_value(ledger, registration, stage, content):
    """Repeated verification of identical inputs is allowed, substitution is not."""
    with sqlite3.connect(ledger) as db:
        db.execute('CREATE TABLE IF NOT EXISTS seals (registration TEXT, stage TEXT, digest TEXT NOT NULL, PRIMARY KEY(registration, stage))')
        db.execute('INSERT OR IGNORE INTO seals VALUES (?, ?, ?)', (registration, stage, content))
        bound = db.execute('SELECT digest FROM seals WHERE registration=? AND stage=?',
                           (registration, stage)).fetchone()[0]
        if bound != content:
            raise ValueError('Custodian seal conflicts with a prior ' + stage)


def seal_batch(registration, manifest, batch, ledger):
    if not has_reservation(registration, read(manifest), ledger):
        raise ValueError('Reserve fresh episodes before sealing submissions')
    if read(registration)['manifest_sha256'] != digest(manifest):
        raise ValueError('Registration must bind the manifest')
    index = read(Path(batch) / 'private.json')
    if index['manifest_sha256'] != value_digest(read(manifest)):
        raise ValueError('Batch differs from frozen manifest')
    seal_value(ledger, digest(registration), 'batch', value_digest(index))


def batch_is_sealed(registration, batch, ledger):
    try:
        with sqlite3.connect(Path(ledger).resolve().as_uri() + '?mode=ro', uri=True) as db:
            row = db.execute('SELECT digest FROM seals WHERE registration=? AND stage=?',
                             (digest(registration), 'batch')).fetchone()
        return row is not None and row[0] == value_digest(read(Path(batch) / 'private.json'))
    except (sqlite3.DatabaseError, OSError):
        return False


def decision_reasons(registration, manifest, report):
    """Adoption requires the predicted axis to gain against every registered comparator."""
    proposal = registration['proposal']
    candidate = report['candidate']
    reasons = list(report['gate']['reasons'])
    if report['gate']['status'] != 'eligible_on_locked_cases':
        reasons.append('comparison_not_eligible')
    if (manifest.get('design') or {}).get('hypothesis_sha256') != value_digest(proposal):
        reasons.append('hypothesis_not_bound_to_frozen_design')
    if report['systems'][candidate]['version'] != proposal['change_ref']:
        reasons.append('registered_change_version_mismatch')
    axis = proposal['target_axis']
    rows = [row for row in report['comparisons'] if row['split'] == 'locked']
    for rival in sorted(set(report['systems']) - {candidate}):
        votes = [j['axis_votes'][axis] for row in rows if row['comparator'] == rival for j in row['judgments']]
        if not votes or any(v not in (0, 1) for v in votes) or 1 not in votes:
            reasons.append('target_axis_gain_not_verified:' + rival)
    return sorted(set(reasons))


def decide(registration, cases, manifest, batch, ballots, dest, ledger=None):
    reg = read(registration)
    if reg['schema'] != 'mara.gold-hypothesis/1' or reg['manifest_sha256'] != digest(manifest):
        raise ValueError('Frozen evaluation manifest differs from registration')
    # Recompute from the submitted texts and ballots, never consume a pasted score.
    command = [sys.executable, '-m', 'mara.decision_gold', 'compare',
               str(cases), str(manifest), str(batch), str(ballots)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError('Comparison did not validate: ' + result.stderr.strip()[-700:])
    report = json.loads(result.stdout)
    if reg['proposal']['candidate'] != report['candidate']:
        raise ValueError('Candidate differs from registered hypothesis')
    data = read(manifest)
    reasons = decision_reasons(reg, data, report)
    if not has_reservation(registration, data, ledger):
        reasons.append('no_custodian_episode_reservation')
    elif not batch_is_sealed(registration, batch, ledger):
        reasons.append('submissions_not_sealed_before_judging')
    else:
        seal_value(ledger, digest(registration), 'ballots', report['ballots_sha256'])
    decision = {'schema': 'mara.gold-hypothesis-decision/1',
                'registration_sha256': digest(registration), 'hypothesis_id': reg['proposal']['id'],
                'change_ref': reg['proposal']['change_ref'], 'decision': 'do_not_adopt' if reasons else 'accept_for_scope',
                'decision_reasons': reasons,
                'report': report}
    save_new(dest, decision)
    return decision


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest='action', required=True)
    for command, args in [('register', ['proposal', 'manifest', 'output']),
                          ('reserve', ['registration', 'manifest', 'ledger']),
                          ('seal', ['registration', 'manifest', 'batch', 'ledger']),
                          ('decide', ['registration', 'cases', 'manifest', 'batch', 'ballots', 'output'])]:
        parser = commands.add_parser(command)
        for arg in args:
            parser.add_argument(arg, type=Path)
        if command == 'decide':
            parser.add_argument('--ledger', type=Path, help='Custodian ledger reserved before distributing locked cases')
    args = cli.parse_args()
    try:
        if args.action == 'register':
            register(read(args.proposal), args.manifest, args.output)
        elif args.action == 'reserve':
            reserve(args.registration, args.manifest, args.ledger)
        elif args.action == 'seal':
            seal_batch(args.registration, args.manifest, args.batch, args.ledger)
        else:
            result = decide(args.registration, args.cases, args.manifest, args.batch, args.ballots, args.output, args.ledger)
            print(result['decision'])
    except (OSError, ValueError, KeyError) as exc:
        cli.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
