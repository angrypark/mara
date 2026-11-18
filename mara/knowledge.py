"""Versioned working knowledge; original evidence is never pruned."""
import uuid
from .domain import day, dumps, required, texts

PROTECTED = {'principle', 'rare_risk'}


class Knowledge:
    def __init__(self, session, after_seq=None):
        self.s = session
        from .history import scope
        self.after_seq=scope(session)['after_seq'] if after_seq is None else after_seq

    def current(self, as_of):
        result = {}
        for e in self.s.events('knowledge', as_of):
            from .history import belongs
            if not belongs(self.s,e,{'after_seq':self.after_seq}):continue
            result[e['body']['key']] = dict(e['body'], event_id=e['id'])
        return result

    def active(self, as_of):
        return [dict(k,needs_revalidation=bool(k['valid_until'] and k['valid_until']<as_of))
                for k in self.current(as_of).values() if k['status'] == 'active'
                and (k['category'] in PROTECTED or not k['valid_until'] or k['valid_until'] >= as_of)]

    def retrieve(self, as_of, role, limit=6000):
        from .store import Session, SHARED
        available = self.active(as_of)
        if self.s.owner != SHARED:
            available += Knowledge(Session(self.s.store, SHARED),self.after_seq).active(as_of)
        items = sorted(available, key=lambda k: (k['category'] in PROTECTED, k['priority']), reverse=True)
        selected, size = [], 0
        for k in items:
            if role not in k['roles'] and '*' not in k['roles']: continue
            n = len(dumps(k))
            if size+n <= limit:
                selected.append(k); size += n
        return {'items': selected, 'budget_chars': limit, 'used_chars': size,
                'omitted': len(items)-len(selected)}

    def apply(self, op, as_of, run_id=None):
        from .contracts import validate,schema
        validate(op,schema('knowledge-operation'))
        required(op, ['action', 'reason'])
        if not isinstance(op['reason'],str) or not op['reason'].strip(): raise ValueError('Change reason required')
        action = op['action']
        current = self.current(as_of)
        key = op.get('key')
        old = current.get(key)
        if action == 'add':
            required(op, ['text','topic','condition','perspective','category','roles','refs','valid_until','priority'])
            key = uuid.uuid4().hex
            body = {k: op[k] for k in ['text','topic','condition','perspective','category','roles','refs','valid_until','priority']}
            body.update(key=key, version=1, status='active', occurrences=1, conflicts=[])
        elif action in {'revise','merge','deactivate','archive','restore'}:
            if old is None: raise ValueError('Unknown knowledge key')
            body = {k:v for k,v in old.items() if k != 'event_id'}
            body['version'] += 1
            if action in {'deactivate','archive'}:
                if old['category'] in PROTECTED and not op.get('invalidating_refs'):
                    raise ValueError('Principles and rare risks need invalidating evidence, never recency alone')
                for ref in op.get('invalidating_refs',[]):
                    if self.s.get(ref)['effective'] > as_of: raise ValueError('Future invalidating evidence')
                body['refs'] = sorted(set(body['refs'] + op.get('invalidating_refs',[])))
                body['status'] = 'inactive' if action == 'deactivate' else 'archived'
            elif action == 'restore':
                e = self.s.get(op['version_event'])
                if e['kind'] != 'knowledge' or e['body']['key'] != key: raise ValueError('Invalid restore version')
                body = dict(e['body'], version=body['version'], status='active')
            elif action == 'revise':
                required(op,['text','refs'])
                body['text'] = op['text']; body['refs'] = sorted(set(body['refs']+op['refs']))
                if old['category'] in PROTECTED and op.get('category',old['category']) not in PROTECTED and not op.get('invalidating_refs'):
                    raise ValueError('Protected knowledge downgrade needs invalidating evidence')
                for field in ('topic','condition','perspective','category','roles','priority','valid_until'):
                    if field in op:body[field]=op[field]
                body['refs']=sorted(set(body['refs']+op.get('invalidating_refs',[])))
            else:
                required(op, ['refs'])
                body['refs'] = sorted(set(body['refs']+op['refs']))
                body['occurrences'] += 1
                # An occurrence is NOT an independent source or a confidence increment.
        else: raise ValueError('Unsupported knowledge action')
        texts(body['refs'],True); texts(body['roles'],True)
        for ref in body['refs']:
            if self.s.get(ref)['effective'] > as_of: raise ValueError('Future knowledge evidence')
        if body['category'] not in {'lesson','hypothesis','principle','rare_risk','market'}: raise ValueError('Unknown category')
        if not isinstance(body['priority'], int) or not 0 <= body['priority'] <= 10: raise ValueError('Invalid priority')
        if not isinstance(body['text'],str) or not body['text'].strip() or len(body['text'])>2000: raise ValueError('Knowledge text too large/empty')
        if body['valid_until']: day(body['valid_until'])
        body.update(action=action, reason=op['reason'], previous_event=old['event_id'] if old else None)
        return self.s.append('knowledge', body, as_of, run_id)

    def prune(self, as_of, run_id=None):
        """Full active-set sweep every run; no arbitrary semantic contradiction resolution."""
        changes, groups = [], {}
        for k in self.current(as_of).values():
            if k['status'] != 'active': continue
            if k['valid_until'] and k['valid_until'] < as_of and k['category'] not in PROTECTED:
                changes.append(self.apply({'action':'deactivate','key':k['key'],'reason':'Validity expired'},as_of,run_id)); continue
            fingerprint = (k['topic'], k['condition'], k['perspective'], ' '.join(k['text'].lower().split()),
                k['category'],tuple(sorted(k['roles'])),k['priority'],k['valid_until'])
            if fingerprint in groups and k['category'] not in PROTECTED:
                primary = groups[fingerprint]
                changes.append(self.apply({'action':'merge','key':primary,'refs':k['refs'],'reason':'Exact duplicate; no confidence increase'},as_of,run_id))
                changes.append(self.apply({'action':'archive','key':k['key'],'reason':'Duplicate retained through merged provenance'},as_of,run_id))
            else: groups[fingerprint] = k['key']
        # Persist unresolved groups for semantic review; differences of perspective remain distinct.
        topics = {}
        for k in self.active(as_of): topics.setdefault((k['topic'],k['condition']), []).append(k['key'])
        unresolved = [{'topic':t[0],'condition':t[1],'keys':keys} for t,keys in topics.items() if len(keys)>1]
        return self.s.append('pruning_audit', {'changes':changes,'unresolved_groups':unresolved,
            'policy':'Full scan; preserve source records, principles, rare risks and perspective differences'},as_of,run_id)
