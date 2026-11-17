"""Versioned personal context, distinct from investor philosophies and learned advice."""
import copy,hashlib
from .domain import dumps

VERSION='mara.user-persona/1.0.0'
LABELS={
 'goal':('목표','text'),'monthly_income':('월 소득','KRW/month'),'monthly_expenses':('월 지출','KRW/month'),
 'contribution_amount':('정기 납입 계획','KRW'),'contribution_schedule':('납입 주기','text'),
 'funding_source':('투자 재원','text'),'proposal_capital':('이번 제안 기준액','KRW'),
 'horizon_months':('계획 기간','months'),'horizon_purpose':('기간의 의미','text'),
 'rebalance_every_days':('리밸런싱 간격','days'),'investment_style':('투자 부분의 성향','text'),
 'usd_buffer_reference_fraction':('달러 완충 비교 비중','fraction'),
 'household.reported_liquid_cash':('전체 보유 현금 진술','KRW'),
 'household.property_value':('부동산 시가 진술','KRW'),'household.mortgage_balance':('담보대출 잔액','KRW'),
 'household.debt_payment_in_expenses':('지출에 대출 상환 포함','text'),
 'household.mortgage_rate':('대출 금리','fraction'),
 'cash_need':('계획 안의 필요 현금','KRW'),'cash_need_date':('현금 필요 시점','date'),
 'max_position_fraction':('상품별 비중 상한','fraction'),
 'criteria.max_sector_fraction':('섹터 비중 상한','fraction'),
 'criteria.preferred_sectors':('저장된 선호 섹터','list'),'criteria.excluded_sectors':('제외 섹터','list')}


def value_at(profile,path):
    value=profile
    for part in path.split('.'):
        if not isinstance(value,dict):return None
        value=value.get(part)
    return value


def build(profile,profile_id,version,as_of):
    sources=profile.get('persona_fact_sources',{});facts=[]
    for key,(label,unit) in LABELS.items():
        value=value_at(profile,key);source=sources.get(key)
        facts.append({'id':key,'label':label,'value':copy.deepcopy(value),'unit':unit.replace('KRW',profile.get('base_currency','KRW')),
            'status':'disputed' if key in profile.get('contested_fields',{}) else 'unknown' if value is None or value in ('unknown','undecided') else 'user_stated' if source else 'recorded',
            'source':copy.deepcopy(source) if source else {'kind':'saved_profile','profile_id':profile_id},
            'scope':'달러 완충은 확정 비중이 아닌 비교 예시' if key=='usd_buffer_reference_fraction' else
                '가계 전체 진술 현금. 실제 계좌와 합산하거나 전액 투자 가능액으로 해석하지 않음' if key=='household.reported_liquid_cash' else
                '월 소득의 세전/세후·지속성은 명시된 근거가 없으면 미확인' if key=='monthly_income' else '저장된 개인 맥락; 실제 계좌 확인이나 시장 근거가 아님'})
    preferences=copy.deepcopy(profile.get('persona_preferences',{}))
    risk={'investment_preference':profile.get('investment_style','general'),
        'contribution_preference':profile.get('contribution_risk_preference','inherit'),
        'reference_loss_fraction':profile.get('max_loss_fraction'),
        'confirmed_loss_capacity_fraction':profile.get('max_loss_fraction') if profile.get('persona_loss_capacity_confirmed') and 'max_loss_fraction' not in profile.get('contested_fields',{}) else None,
        'analysis_loss_budget':profile.get('analysis_loss_budget'),'budget_scope':profile.get('loss_budget_scope','confirmed'),
        'rule':'투자 의지·비교 기준·분석용 예산은 서로 달라요. 확인된 감내손실이나 최대손실 보장으로 바꾸지 않아요.'}
    unknowns=[{'id':key,'label':LABELS.get(key,(key,''))[0]+' · 이전 값을 철회하거나 정정 중','blocks_research':True} for key in profile.get('contested_fields',{})]
    if risk['confirmed_loss_capacity_fraction'] is None:unknowns.append({'id':'loss_capacity','label':'실제로 감당 가능한 손실','blocks_research':False})
    if value_at(profile,'household.mortgage_rate') is None:unknowns.append({'id':'mortgage_rate','label':'대출 금리와 금리 변동 조건','blocks_research':False})
    unknowns.append({'id':'account_reconciliation','label':'실제 계좌·입출금 대조는 개인 페르소나와 별도로 확인','blocks_research':False})
    return {'schema_version':VERSION,'version':version,'as_of':as_of,'profile_id':profile_id,'status':'current' if profile_id else 'draft',
        'title':'공격적 성장 적립형 · 현금 완충 분리' if profile.get('investment_style')=='aggressive_innovation' else '나의 투자 맥락',
        'summary':profile.get('goal','목표를 대화로 정리해요.'),'facts':facts,'preferences':preferences,'risk':risk,
        'current_context':profile.get('context_notes',''),'answer_memory':answer_memory(profile),'answer_memory_scope':answer_memory_scope(profile),'unknowns':unknowns,
        'source_policy':'recorded는 기존 저장값이며 새로 확인한 사용자 발언이 아니에요. 사용자 원문과 모델 해석은 출처·상태로 구분해요. 개인 정보는 시장 근거로 인용하지 않아요.',
        'handoff_policy':'이 버전을 실행 시작에 고정해 모든 역할에 전달해요. 새 대화는 다음 실행에 반영하며 과거 보고서는 변경하지 않아요.'}


def answer_memory(profile):
    # Keep user answers plus the minimum question context, never old agent reasoning.
    from .history import profile_input
    facts=profile_input(profile,{'after_seq':1,'reset_id':None}).get('confirmed_answer_facts',[])
    selected=[];used=0
    for item in reversed(facts):
        entry={k:copy.deepcopy(item[k]) for k in ('question_id','topic','answer','answer_context','source_answer_id','scope') if k in item}
        size=len(dumps(entry))
        if used+size>12000:continue
        selected.append(entry);used+=size
    return list(reversed(selected))


def answer_memory_scope(profile):
    from .history import profile_input
    all_facts=profile_input(profile,{'after_seq':1,'reset_id':None}).get('confirmed_answer_facts',[])
    included=answer_memory(profile);ids={x.get('question_id') for x in included}
    omitted=[{'question_id':x.get('question_id'),'source_answer_id':x.get('source_answer_id'),'topic':x.get('topic')} for x in all_facts if x.get('question_id') not in ids]
    return {'complete':not omitted,'total':len(all_facts),'included':len(included),'omitted':omitted,
        'rule':'원본은 보존돼요. 생략된 사실이 있으면 맥락이 완전하다고 간주하지 말고 해당 주제의 현재 조건을 확인해요.'}


def ensure(session,profile_row):
    if not session.store.in_transaction:
        with session.store.transaction():return _ensure(session,profile_row)
    return _ensure(session,profile_row)


def _ensure(session,profile_row):
    from .contracts import validate,schema
    for row in reversed(session.events('user_persona')):
        if row['body']['profile_id']==profile_row['id']:
            try:validate(row['body'],schema('persona'));return row
            except ValueError:pass
    body=build(profile_row['body'],profile_row['id'],len(session.events('user_persona'))+1,profile_row['effective'])
    validate(body,schema('persona'))
    eid=session.append('user_persona',body,profile_row['effective'])
    return session.get(eid)


def snapshot(row):
    return {'id':row['id'],'hash':hashlib.sha256(dumps(row['body']).encode()).hexdigest(),'body':copy.deepcopy(row['body'])}
