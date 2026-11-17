"""An immutable analytical epoch; facts and audit records remain intact."""
import copy


def scope(session, as_of='9999-12-31', run_id=None):
    if run_id:
        starts=[e for e in session.events('run_started') if e['run_id']==run_id]
        if starts:return copy.deepcopy(starts[-1]['body'].get('history_scope',{'after_seq':0,'reset_id':None}))
    event=session.latest('history_reset',as_of)
    return {'after_seq':event['seq'] if event else 0,'reset_id':event['id'] if event else None}


def events(session,kind,as_of='9999-12-31',boundary=None):
    boundary=scope(session,as_of) if boundary is None else boundary
    return [e for e in session.events(kind,as_of) if belongs(session,e,boundary)]


def latest(session,kind,as_of='9999-12-31',boundary=None):
    rows=events(session,kind,as_of,boundary)
    return rows[-1] if rows else None


def profile_input(profile,boundary):
    result=copy.deepcopy(profile)
    if boundary['after_seq']:
        result.pop('context_note_history',None)
        facts={f['question_id']:f for f in result.get('confirmed_answer_facts',[]) if f.get('question_id')}
        for a in result.get('clarification_answers',[]):
            answer=a.get('answer') or a.get('text') or a.get('option_label')
            if not answer:continue
            q=a.get('question',{});key=a.get('question_id') or a.get('answer_id') or q.get('topic','other_context')
            facts[key]={'question_id':key,'topic':q.get('topic','other_context'),
                'answer':answer,'answer_context':q.get('prompt',''),
                'source_answer_id':a.get('answer_id'),
                'scope':'사용자가 답한 질문과 답변의 사실 기록. 이전 agent 이유·선택지 설명·분석은 제외.'}
        result['confirmed_answer_facts']=list(facts.values())
        result['clarification_answers']=[a for a in result.get('clarification_answers',[]) if a.get('history_reset_id')==boundary['reset_id']]
    return result


def belongs(session,event,boundary):
    if event['seq']<=boundary['after_seq']:return False
    if event.get('run_id'):
        # Shared facts learned by a run started before reset remain in the old epoch.
        row=session.store.db.execute("SELECT seq FROM events WHERE kind='run_started' AND run_id=? ORDER BY seq LIMIT 1",(event['run_id'],)).fetchone()
        if row and row['seq']<=boundary['after_seq']:return False
    return True


def market_input(market,boundary):
    result=copy.deepcopy(market)
    if boundary.get('after_seq',0):
        result['facts']=[f for f in result.get('facts',[]) if f.get('research_tool')!='company_valuation']
        if result.get('research'):
            result['research']['calls']=[c for c in result['research'].get('calls',[]) if c.get('tool')!='company_valuation']
    return result
