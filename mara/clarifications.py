"""Explicit user answers, separate from read-only agent dialogue and immutable analysis."""
import copy
import hashlib
import re
from datetime import date
from .domain import dumps


class ClarificationError(ValueError):pass

# Stable slots identify the personal fact, not the wording of a question.
TOPICS=['funding_source','funding_timing','funding_scope','cash_need_amount','cash_need_timing',
        'cash_need_purpose','horizon_plan','goal_definition','income_stability','debt',
        'holdings_rationale','constraint_conflict','other_context']


def questions(output):
    if output.get('questions') is not None:return copy.deepcopy(output['questions'])
    # Historical prose has no reliable semantic IDs or specific choice candidates.
    return [{'id':'legacy_'+hashlib.sha256(re.sub(r'\s+','',text).encode()).hexdigest()[:20],
             'topic':'other_context','prompt':text,'reason':'개인 맥락 에이전트가 판단에 필요한 내용으로 남긴 질문이에요.',
             'options':[{'id':'undecided','label':'아직 정하지 않았어요','description':'미정인 상태를 그대로 전달해요.','requires_text':False}],
             'revisit_reason':''} for text in output.get('missing',[])]


def answers(session,as_of=None):
    latest={}
    from .history import events,scope
    boundary=scope(session,as_of or '9999-12-31')
    for event in events(session,'clarification_answer',as_of or '9999-12-31',boundary):
        latest[event['body']['question_id']]=dict(event['body'],answer_id=event['id'],recorded_at=event['recorded'],history_reset_id=boundary['reset_id'])
    return list(latest.values())


def notes_history(session,current):
    versions=[]
    for event in session.events('onboarding_draft'):
        note=event['body'].get('context_notes','').strip()
        if note and (not versions or versions[-1]['text']!=note):
            versions.append({'source_id':event['id'],'recorded_at':event['recorded'],'text':note})
    if current.strip() and (not versions or versions[-1]['text']!=current.strip()):
        versions.append({'source_id':'current_input','recorded_at':date.today().isoformat(),'text':current.strip()})
    selected=[];size=0
    for item in reversed(versions[-12:]):
        n=len(dumps(item))
        if size+n>12000:break
        selected.append(item);size+=n
    return list(reversed(selected))


def save_answers(session,body):
    # Read the expected version and append atomically, including independent sessions.
    with session.store.transaction():return _save_answers(session,body)


def _save_answers(session,body):
    if not isinstance(body,dict) or set(body)!={'context_output_id','request_id','answers'}:
        raise ClarificationError('답변 요청 형식을 확인해주세요.')
    source_id,rid,submitted=(body[k] for k in ('context_output_id','request_id','answers'))
    if not isinstance(source_id,str) or not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9-]{32,36}',rid):
        raise ClarificationError('질문과 요청 ID를 확인해주세요.')
    for event in session.events('clarification_submission'):
        if event['body']['request_id']==rid:
            if event['body']['request']!=body:raise ClarificationError('같은 요청 ID의 답변이 달라요.')
            return {'saved':True,'duplicate':True,'answers':answers(session)}
    source=session.get(source_id)
    if source['kind']!='agent_output' or source['body'].get('role')!='context':raise PermissionError('Context output required')
    known={q['id']:q for q in questions(source['body']['output'])}
    if not isinstance(submitted,list) or not 1<=len(submitted)<=3:raise ClarificationError('한 번에 1~3개 질문에 답해주세요.')
    latest={x['question_id']:x for x in answers(session)};pending=[];ids=set()
    for value in submitted:
        if not isinstance(value,dict) or set(value)!={'question_id','option_id','text','expected_answer_id'}:raise ClarificationError('답변 형식을 확인해주세요.')
        qid,option_id,text=(value[k] for k in ('question_id','option_id','text'))
        if not isinstance(qid,str) or qid not in known or qid in ids:raise ClarificationError('질문을 다시 확인해주세요.')
        ids.add(qid);q=known[qid]
        if value['expected_answer_id']!=latest.get(qid,{}).get('answer_id'):
            raise ClarificationError('다른 화면에서 답변이 변경됐어요. 새로고침하여 저장된 답변을 확인해주세요. 입력 중인 답변은 복사해 보관할 수 있어요.')
        if not isinstance(text,str) or len(text)>1200:raise ClarificationError('직접 답변은 1,200자 이내로 적어주세요.')
        option=next((x for x in q['options'] if x['id']==option_id),None)
        if option_id is not None and not option:raise ClarificationError('질문에 없는 선택지예요.')
        if (option is None or option['requires_text']) and not text.strip():raise ClarificationError('선택한 답변에 필요한 내용을 적어주세요.')
        answer=(option['label']+' — ' if option and text.strip() else option['label'] if option else '')+text.strip()
        row={'question_id':qid,'question':q,'source_output_id':source_id,'option_id':option_id,
             'option_label':option['label'] if option else None,'text':text.strip(),'answer':answer,
             'supersedes':latest.get(qid,{}).get('answer_id')}
        latest[qid]=row;pending.append(row)
    if len(latest)>32 or len(dumps(list(latest.values())))>28000:
        raise ClarificationError('개인 맥락 답변의 활성 한도를 넘었어요. 기존 답변을 간결하게 수정해주세요.')
    for row in pending:session.append('clarification_answer',row,date.today().isoformat(),source['run_id'])
    session.append('clarification_submission',{'request_id':rid,'request':body},date.today().isoformat(),source['run_id'])
    return {'saved':True,'duplicate':False,'answers':answers(session)}


def repeated_questions(output,profile):
    # Semantic equivalence cannot be proven with a string ID. Once context exists,
    # every follow-up must compare known answers with the remaining gap, even if
    # the model renamed its fact ID/topic or rephrased a historical prose question.
    prior=profile.get('clarification_answers') or profile.get('context_note_history')
    return [q for q in questions(output) if prior and not q['revisit_reason'].strip()]
