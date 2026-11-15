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
