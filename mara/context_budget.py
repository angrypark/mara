"""Bounded role projections of one preceding run; immutable originals untouched."""
import copy

LIMITS={'context':256000,'evidence':256000,'buffett':256000,'marks':256000,'bogle':256000,
        'reflection':384000,'memory':384000,'validation':512000,'leader':512000}
PROPOSAL=('action','weights','rationale','dissent','risks','next_checks','premise_changes','validation_response','eligibility')


def previous_for_role(prior,role,market):
    out=copy.deepcopy(prior)
    out['market']=market
    out['proposal']={k:v for k,v in prior['proposal'].items() if k in PROPOSAL}
    # Each investor sees its own original reasoning. Cross-perspective synthesis
    # and process review retain ALL original positions, assumptions and dissent.
    perspectives=prior['perspectives']
    if role in perspectives:out['perspectives']={role:copy.deepcopy(perspectives[role])}
    elif role in ('context','evidence','memory'):out['perspectives']={}
    review=prior['validation']
    out['validation']={'final_critique':review.get('final_critique',review.get('critique')),
        'final_numeric':{k:v for k,v in review.get('final_numeric',{}).items() if k in ('passed','status','errors','missing','warnings')}}
    out['projection']={'version':'previous-role/1.0','source_event_id':prior['event_id'],
        'perspective_roles':list(out['perspectives']),
        'omitted':'중복된 종목별 수치 계산, UI 부가값, 중간 검증. 개인·자료·기억 역할에는 리더의 이유·반론·위험·다음 점검을 전달하고 투자자 역할에는 자기 원문도 전달. 검증·리더·회고는 모든 관점 원문을 유지.',
        'rule':'생략된 세부 주장을 확인했다고 하지 않아요. 원문은 source_event_id에 보존하며 한 실행만 재사용해요.'}
    return out
