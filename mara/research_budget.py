"""One fixed supplemental-evidence budget per execution, including inherited facts."""
import hashlib
from .domain import dumps
from .research_sources import EvidenceError

ROLES=('evidence','buffett','marks','bogle','wood','validation')
TOTAL=368000


def size(fact):return len(dumps(fact))


def plan(session,run_id,as_of,rows):
    inherited={}
    for row in rows:
        lineage=row.get('carried_from')
        if not lineage:continue
        source=session.get(lineage['event_id']);parent=session.get(lineage['completed_id'])
        if source['kind']!='research_evidence' or parent['kind']!='completed' or source['run_id']!=lineage['run_id'] or parent['run_id']!=source['run_id'] or source['seq']>parent['seq']:
            raise EvidenceError('invalid_inherited_evidence_lineage')
        if any(source['body'].get(k)!=row.get(k) for k in ('fact','role','budget_bucket','budget_allocation')):
            raise EvidenceError('inherited_evidence_changed')
        fact=row['fact'];digest=hashlib.sha256(dumps(fact).encode()).hexdigest()
        if fact['id'] in inherited and inherited[fact['id']]['sha256']!=digest:raise EvidenceError('evidence_id_collision')
        inherited[fact['id']]={'sha256':digest,'characters':size(fact)}
    existing=[e for e in session.events('research_budget_plan') if e['run_id']==run_id]
    if existing:
        value=existing[0]['body']
        if value['inherited']!=inherited:raise EvidenceError('inherited_evidence_changed_after_budget_freeze')
        return value
    used=sum(x['characters'] for x in inherited.values());remaining=max(0,TOTAL-used)
    general=remaining*80000//TOTAL;reserve=(remaining-general)//len(ROLES)
    # Put rounding characters in general so the quotas sum to the exact balance.
    general=remaining-reserve*len(ROLES)
    value={'policy':'inherited-plus-remaining-shares/2','inherited':inherited,'inherited_characters':used,
        'supplemental_limit':TOTAL,'remaining_at_start':remaining,'general_limit':general,'role_limit':reserve,
        'scope':'Supplemental research_evidence characters only. Base market facts, planner transcript and role input envelopes have separate unchanged limits.'}
    session.append('research_budget_plan',value,as_of,run_id)
    return value


def closed_roles(session,run_id):
    closed=set()
    for event in session.events('agent_validation'):
        row=event['body']
        if event['run_id']!=run_id or row['status']!='accepted' or row['role'] not in ROLES:continue
        if row['role']=='validation':
            payload=session.get(row['input_id'])['body']['payload']
            if payload.get('analysis_stage')!='final_validation':continue
        closed.add(row['role'])
    return closed


def allocate(session,run_id,as_of,rows,role,fact,eligible):
    frozen=plan(session,run_id,as_of,rows);general=0;own={r:0 for r in ROLES};borrowed=0;seen={};total=0
    for row in rows:
        f=row['fact'];digest=hashlib.sha256(dumps(f).encode()).hexdigest()
        if f['id'] in seen:
            if seen[f['id']]!=digest:raise EvidenceError('evidence_id_collision')
            continue
        seen[f['id']]=digest;cost=size(f);total+=cost
        if row.get('carried_from'):continue
        allocation=row.get('budget_allocation')
        if allocation:
            if set(allocation)!={'general','role_reserved','borrowed'} or any(type(v)!=int or v<0 for v in allocation.values()) or sum(allocation.values())!=cost:
                raise EvidenceError('invalid_evidence_budget_allocation')
            general+=allocation['general']
            if allocation['role_reserved'] and row['role'] not in own:raise EvidenceError('invalid_reserved_role')
            if row['role'] in own:own[row['role']]+=allocation['role_reserved']
            borrowed+=allocation['borrowed']
        elif row.get('budget_bucket','general')=='general':general+=cost
        else:own[row['role']]+=cost
    closed=closed_roles(session,run_id);requested=size(fact);limit=frozen['role_limit']
    released=sum(max(0,limit-own[r]) for r in closed)
    available_borrow=max(0,released-borrowed)
    protected=sum(max(0,limit-own[r]) for r in ROLES if r not in closed and r!=role)
    receipt={'policy':frozen['policy'],'inherited_characters':frozen['inherited_characters'],
        'general_used':general,'general_limit':frozen['general_limit'],'role':role,
        'role_reserved_used':own.get(role,0),'role_reserved_limit':limit,'run_used':total,'run_limit':TOTAL,
        'requested_characters':requested,'closed_roles':sorted(closed),'protected_other_roles':protected,
        'released_characters':released,'borrowed_characters':borrowed,'available_borrow':available_borrow,
        'rule':'이전 근거도 보충 자료 전체 한도에서 차감해요. 남은 몫은 실행 시작에 고정하며 재시도와 마지막 검토가 함께 사용해요. 실제 역할 입력 상한은 별도로 유지해요.'}
    if total+requested>TOTAL:return None,dict(receipt,blocked_reason='supplemental_global_limit')
    dispatches=[e for e in session.events('evidence_feedback_dispatch') if e['run_id']==run_id]
    returns=[e for e in session.events('evidence_feedback_return') if e['run_id']==run_id]
    feedback_active=role=='evidence' and bool(dispatches) and (not returns or dispatches[-1]['seq']>returns[-1]['seq'])
    receipt['feedback_supplier']=feedback_active
    if role in closed and not feedback_active:return None,dict(receipt,blocked_reason='research_role_already_closed')
    parts={'general':min(requested,max(0,frozen['general_limit']-general)),'role_reserved':0,'borrowed':0}
    remainder=requested-parts['general']
    if eligible and role in ROLES:
        # A closed supplier's old reserve has already been released (and may
        # have been borrowed). Use the shared released balance, never reclaim it.
        parts['role_reserved']=0 if role in closed else min(remainder,max(0,limit-own[role]));remainder-=parts['role_reserved']
        parts['borrowed']=min(remainder,available_borrow);remainder-=parts['borrowed']
    if remainder:return None,dict(receipt,blocked_reason='protected_role_or_general_limit')
    return parts,receipt
