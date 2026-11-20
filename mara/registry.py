"""One catalogue for orchestration, contracts, guides and presentation."""
from pathlib import Path
import json
import re
import sys


def resource(relative):
    path=Path(__file__).resolve().parent.parent/relative
    return path if path.exists() else Path(sys.prefix)/'share/mara'/relative


REGISTRY=json.loads(resource('contracts/agents.json').read_text())


def catalogue():
    ids=[a['id'] for a in REGISTRY]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate agent id')
    for a in REGISTRY:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',a['id']):raise ValueError('Invalid agent id')
        if '..' in a['guide'] or a['guide'].startswith('/'):raise ValueError('Invalid guide path')
    return [dict(a) for a in REGISTRY]


def agent(role):
    for a in catalogue():
        if a['id']==role:return a
    raise ValueError('Unknown agent')


def personas():
    return tuple(a['id'] for a in catalogue() if a['kind']=='perspective')


def role_guide(role, instructions=None):
    """Compose a fresh call. Persist the returned text for exact replay."""
    path = 'guides/roles/editor.md' if role == 'editor' else agent(role)['guide']
    canonical = resource(path).read_text()
    text = canonical if instructions is None else instructions
    # A local guide override replaces the strategy, while the role retains
    # its handoff responsibilities. Extension roles may supply their own guide.
    heading = '\n## 역할 책임과 인계\n'
    _, marker, responsibilities = canonical.rpartition(heading)
    if marker and responsibilities.strip() not in text:
        text += marker + responsibilities
    team = resource('guides/roles/team.md').read_text()
    return text if team in text else text + '\n' + team


def submission_guide(role, guide, payload):
    """Standalone synthesis has no Agents envelope to resolve the role guide."""
    if role == 'leader' and payload.get('analysis_stage') == 'proposal_synthesis' and 'input_budget' not in payload:
        return role_guide(role, guide)
    return guide
