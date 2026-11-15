"""Versioned analytical procedures, not external tools or trading permission."""
import hashlib
import json
from .registry import resource


def for_role(role):
    entries=json.loads(resource('resources/analysis-skills.json').read_text())
    selected=[];guides=[]
    for item in entries:
        if '*' not in item['roles'] and role not in item['roles']:continue
        path=item['guide']
        if not path.startswith('guides/skills/') or '..' in path:raise ValueError('Invalid skill path')
        text=resource(path).read_text();guides.append(text)
        selected.append(dict(item,sha256=hashlib.sha256(text.encode()).hexdigest()))
    return selected,'\n\n'.join(guides)
