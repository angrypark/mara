"""Bounded conversational intake with grounded updates and immutable version pairs."""
import copy,re,threading,uuid
from datetime import date
from . import domain as d
from .contracts import validate,schema
from .persona import ensure,snapshot,build,value_at
from .registry import role_guide, resource

class PersonaError(ValueError):pass

MONEY={
 'monthly_income':r'월.{0,12}(소득|월급|수입|실수령)|월급',
 'monthly_expenses':r'월.{0,12}(지출|생활비|소비)',
 'contribution_amount':r'(매월|월|매달).{0,20}(납입|적립|투자)|(?:납입|적립|투자).{0,12}(매월|매달|월)',
 'household.reported_liquid_cash':r'(전체|총|보유).{0,12}현금|현금.{0,12}(보유|전체|총|있)',
 'household.property_value':r'(부동산|집|주택).{0,15}(시가|가격)|시가',
 'household.mortgage_balance':r'(담보대출|주택대출|대출).{0,12}(잔액|잔고|남|원|억|만)',
 'household.monthly_debt_payment':r'(월|매달|매월).{0,20}(상환|원리금)',
 'cash_need':r'(필요|남길|인출).{0,12}현금|현금.{0,12}(필요|남길|인출)'}
FRACTIONS={'max_loss_fraction','usd_buffer_reference_fraction','household.mortgage_rate','max_position_fraction','criteria.max_sector_fraction'}
COUNTS={'horizon_months','rebalance_every_days','contribution_every_days'}
TEXT={'goal','context_notes','horizon_purpose','funding_source','contribution_schedule','investment_style','household.debt_payment_in_expenses','cash_need_date'}
SOFT={'interests','sector_interests','investment_preferences','risk_preference'}
FIELDS=set(MONEY)|FRACTIONS|COUNTS|TEXT|{'persona_preferences.'+x for x in SOFT}


def money_values(text):
    text=text.replace(',','').replace(' ','');values=[]
    for match in re.finditer(r'(?<![\d.])(?:\d+(?:\.\d+)?(?:억|천만|백만|십만|만|천)?)+원?',text):
        if not re.search(r'억|만|천|원',match.group()):continue
        value=0.
        for n,unit in re.findall(r'(\d+(?:\.\d+)?)(억|천만|백만|십만|만|천)?',match.group()):
            value+=float(n)*{'억':1e8,'천만':1e7,'백만':1e6,'십만':1e5,'만':1e4,'천':1e3,'':1}[unit]
        values.append(value)
    return values


def grounded(update,message):
    field=update['field'];quote=update['basis_quote'];value=update['value']
    if field not in FIELDS or not quote.strip() or quote not in message:raise PersonaError('변경 내용의 사용자 발언 출처를 확인하지 못했어요.')
    if field in set(MONEY)|FRACTIONS|COUNTS:
        if update['certainty']!='explicit' or type(value) not in (int,float):raise PersonaError('숫자는 명시된 값만 반영해요.')
        d.number(value,0)
        # A correction is accepted only when its complete statement is quoted,
        # with one rejected and one current value. Cropped old values cannot pass.
        correction=re.search(r'(?:이|가)?\s*아니라\s*',quote)
        context=message
        if correction and field in MONEY and len(money_values(quote))==2 and money_values(quote)[-1]==value:
            before,after=quote[:correction.start()],quote[correction.end():]
            label=re.split(r'\d',before,1)[0]
            if re.search(MONEY[field],label):
                quote=label+after
                context=message.replace(update['basis_quote'],quote,1)
        if re.search(r'아니|않|못|말고|취소|철회|예를|가정|만약|이라면|였다면|예전|과거|작년|지난|이전에는|세전|연봉|하면|다면|으면|라면|생기면|예상|예정',context):
            raise PersonaError('정정·부정·가정 또는 과거 금액의 범위를 확인하지 못해 숫자는 보류했어요. 원문은 보존돼요.')
        if re.search(r'예를|가정|만약|이라면|였다면|아니|않|말고|취소|철회|예전|과거|작년|지난|이전에는',quote):raise PersonaError('가정·예시·부정 또는 철회 문장의 숫자는 현재 사실로 반영하지 않아요.')
    if field in MONEY:
        if re.search(r'달러|USD|\$|세전|연봉|연간|매년|주간|매주',quote,re.I):raise PersonaError('통화와 소득·지출 주기를 먼저 구분해야 해요.')
        amounts=money_values(quote)
        if len(amounts)!=1 or not re.search(MONEY[field],quote) or abs(value-amounts[0])>=.01:
            raise PersonaError('금액·주기·범위를 발언과 일치시키지 못했어요.')
        if field=='household.reported_liquid_cash' and re.search(r'계좌|주식|증권',quote) and not re.search(r'전체|총|모든',quote):raise PersonaError('계좌 현금과 전체 현금을 구분해야 해요.')
        if field!='contribution_amount' and re.search(r'으면|다면|생기면|예상|목표|계획|예정',quote):raise PersonaError('향후 계획을 현재 자금으로 반영하지 않아요.')
    elif field in FRACTIONS:
        numbers=[float(x)/100 for x in re.findall(r'(\d+(?:\.\d+)?)\s*%',quote)]
        if not 0<=value<=1 or len(numbers)!=1 or abs(value-numbers[0])>=1e-9:raise PersonaError('비율은 명시한 퍼센트와 같아야 해요.')
        if field=='max_loss_fraction' and re.search(r'\?|까요|될까|가능할|가정',message):raise PersonaError('감내손실에 대한 질문을 확정된 허용 손실로 바꾸지 않아요.')
        if field=='max_loss_fraction' and (not re.search(r'손실|하락|낙폭',quote) or not re.search(r'감당|감수|허용',quote)):
            raise PersonaError('공격적 성향만으로 감내손실을 높이지 않아요.')
        patterns={'household.mortgage_rate':r'(대출|담보).{0,12}금리|금리.{0,12}(대출|담보)','max_position_fraction':r'(종목|상품|개별).{0,12}(상한|한도|최대)','criteria.max_sector_fraction':r'섹터.{0,12}(상한|한도|최대)'}
        if field in patterns and not re.search(patterns[field],quote):raise PersonaError('어떤 비율인지 발언과 일치시키지 못했어요.')
        if field=='usd_buffer_reference_fraction' and not re.search(r'달러|USD',quote,re.I):raise PersonaError('달러 완충 비율의 범위를 확인해야 해요.')
    elif field in COUNTS:
        unit='개월' if field=='horizon_months' else '일'
        values=[int(x) for x in re.findall(r'(\d+)\s*'+unit,quote)]
        if field=='horizon_months':values += [int(x)*12 for x in re.findall(r'(\d+)\s*년',quote)]
        scope={'horizon_months':r'투자|기간|계획','rebalance_every_days':r'리밸런싱|재조정','contribution_every_days':r'납입|적립|투자'}
        if not re.search(scope[field],quote) or len(values)!=1 or type(value)!=int or value<1 or value not in values:raise PersonaError('기간과 단위가 발언과 같아야 해요.')
    else:
        if not isinstance(value,str) or not value.strip() or len(value)>2000:raise PersonaError('설명 길이를 확인해주세요.')
    enum_rules={
        'funding_source':{'future_income':r'(소득|월급|급여).{0,30}(투자|납입|적립)|(?:투자|납입|적립).{0,30}(소득|월급|급여)',
            'current_assets':r'(기존|현재|보유).{0,20}(현금|자산).{0,20}(투자|납입)|(?:투자|납입).{0,20}(기존|현재|보유).{0,20}(현금|자산)','undecided':r'(재원|자금|투자).{0,20}(미정|모르|미확인)'},
        'horizon_purpose':{'review':r'(기간|개월|년).{0,25}(점검|재평가|검토)|(?:점검|재평가).{0,25}(기간|개월|년)','withdrawal':r'(기간|개월|년).{0,25}(인출|사용|매도)|(?:인출|사용|매도).{0,25}(기간|개월|년)','unknown':r'(기간|목적).{0,20}(미정|모르|미확인)'},
        'household.debt_payment_in_expenses':{'yes':r'(상환|원리금).{0,30}(지출|생활비).{0,20}포함|(?:지출|생활비).{0,30}(상환|원리금).{0,20}포함',
            'no':r'(상환|원리금).{0,30}(지출|생활비).{0,20}별도|(?:지출|생활비).{0,30}(상환|원리금).{0,20}별도','unknown':r'(상환|원리금).{0,20}(미정|모르|미확인)'},
        'contribution_schedule':{'monthly':r'매월|매달|월마다','days':r'\d+일마다|매\s*\d+일'},
        'investment_style':{'aggressive_innovation':r'공격적|혁신.{0,15}성장','general':r'일반.{0,15}(배분|투자)|폭넓.{0,15}분산'}}
    if field in enum_rules:
        if value not in enum_rules[field] or not re.search(enum_rules[field][value],quote):raise PersonaError('설정의 의미를 명시한 발언이 없어 설명으로만 남겨요.')
        if re.search(r'아니|않|못|예를|가정|만약|하면|다면|으면|라면|예전|과거',message):raise PersonaError('부정·가정·과거 설정을 현재 조건으로 확정하지 않아요.')
    if field in {'goal','context_notes'} and value!=update['basis_quote']:raise PersonaError('목표와 개인 설명은 사용자 원문 그대로만 채택해요.')
    if field=='cash_need_date' and (value not in quote or not re.search(r'현금|인출|필요',quote)):raise PersonaError('현금 필요 날짜의 출처를 확인하지 못했어요.')
    return update


def assign(profile,path,value):
    target=profile;parts=path.split('.')
    for key in parts[:-1]:target=target.setdefault(key,{})
    target[parts[-1]]=value


def apply_updates(profile,updates,message,request_event):
    result=copy.deepcopy(profile);accepted=[];issues=[]
    if re.search(r'취소|철회|확정.{0,5}아니|잘못.{0,5}(입력|말)',message):
        labels={'monthly_income':r'소득|월급|실수령','monthly_expenses':r'지출|생활비','contribution_amount':r'납입|적립',
            'household.reported_liquid_cash':r'보유 현금|전체 현금','max_loss_fraction':r'감내|손실|감당','horizon_months':r'기간|개월'}
        for field,pattern in labels.items():
            if re.search(pattern,message):
                result.setdefault('contested_fields',{})[field]={'source_id':request_event['id'],'quote':message,'status':'withdrawn_or_disputed'}
                accepted.append('contested_fields.'+field)
    for change in updates:
        try:
            grounded(change,message);field=change['field'];value=change['value']
            if field in MONEY and profile.get('base_currency','KRW')!='KRW':raise PersonaError('원화 발언을 다른 기준 통화의 금액으로 변환하지 않아요.')
            if field.startswith('persona_preferences.'):
                key=field.split('.',1)[1];old_pref=result.get('persona_preferences',{}).get(key,{})
                replacing=bool(re.search(r'대신|(?:관심|선호|투자 방식).{0,20}(바꿔|철회|취소|제외|없)',change['basis_quote']))
                items=copy.deepcopy(old_pref.get('items',[]))
                if not items and old_pref.get('text'):items=[{k:old_pref[k] for k in ('text','status','source_id','quote') if k in old_pref}]
                if replacing:items=[]
                if not any(item['text']==value and item['status']==change['certainty'] for item in items):
                    items.append({'text':value,'status':change['certainty'],'source_id':request_event['id'],'quote':change['basis_quote']})
                combined='\n'.join(item['text'] for item in items)
                if len(combined)>6000:raise PersonaError('선호 요약의 활성 한도에 도달했어요. 기존 선호를 무엇으로 바꿀지 명시하면 갱신해요. 원문은 보존돼요.')
                statuses={item['status'] for item in items}
                result.setdefault('persona_preferences',{})[key]={'text':combined,'status':next(iter(statuses)) if len(statuses)==1 else 'mixed',
                    'items':items,'source_id':request_event['id'],'quote':change['basis_quote']}

            else:
                if field in TEXT and change['certainty']!='explicit':raise PersonaError('해석은 관심사에 기록하고 사실 설정은 명시 내용만 바꿔요.')
                result.get('contested_fields',{}).pop(field,None)
                old=value_at(result,field)
                if field=='context_notes' and old and value not in old:value=old+'\n'+value
                if field=='context_notes' and len(value)>12000:raise PersonaError('설명 한도에 도달해 자동 갱신을 보류했어요. 원문은 보존돼요.')
                assign(result,field,value)
                if field=='contribution_amount' and result.get('funding_source')=='future_income' and result.get('proposal_capital')==old:result['proposal_capital']=value
                if field=='household.reported_liquid_cash' and result.get('financial_assets_basis','').startswith('declared_cash_only'):result['total_assets']=value
                if field=='max_loss_fraction':result.update(persona_loss_capacity_confirmed=True,loss_budget_scope='confirmed',analysis_loss_budget=None)
                result.setdefault('persona_fact_sources',{})[field]={'kind':'user_message','event_id':request_event['id'],'quote':change['basis_quote'],'recorded_on':request_event['effective']}
            accepted.append(field)
        except (ValueError,TypeError,KeyError) as exc:issues.append({'field':change.get('field'),'reason':str(exc)})
    if accepted:
        result['context_answer_cutoff_seq']=request_event['seq']
        result.pop('clarification_source_run_id',None)
    return result,accepted,issues


def draft_projection(profile,draft,profile_id):
    result=copy.deepcopy(draft);result['profile_base_id']=profile_id;result['confirmed']=False
    for key in ('goal','context_notes','total_assets','monthly_income','monthly_expenses','cash_need','cash_need_date','horizon_months','horizon_purpose','contribution_amount','contribution_schedule','contribution_every_days','rebalance_every_days','max_loss_fraction','max_position_fraction','funding_source','investment_style','usd_buffer_reference_fraction','loss_budget_scope','analysis_loss_budget'):
        if key in profile:result[key]=profile[key]
    result.update(profile.get('household',{}));result.update(profile.get('criteria',{}))
    if profile.get('funding_source')=='future_income' and profile.get('proposal_capital'):result['capital_amount']=profile['proposal_capital']
    return result


class PersonaConversations:
    def __init__(self,setup):self.setup=setup;self.guard=threading.RLock();self.thread=None

    def current(self,s):
        profile=s.latest('profile')
        if profile:return snapshot(ensure(s,profile))
        pending=s.latest('persona_draft')
        return snapshot(pending) if pending else None

    def read(self):
        with self.setup.session() as s:
            requests=s.events('persona_message');results={x['body']['request_id']:x['body'] for x in s.events('persona_reply')}
            turns=[{'id':x['body']['request_id'],'message':x['body']['message'],'result':results.get(x['body']['request_id'])} for x in requests[-30:]]
            return {'schema_version':'mara.persona-conversation/1.0.0','persona':self.current(s),'turns':turns,'total_turns':len(requests),
                'running':bool(turns and turns[-1]['result'] is None)}

    def recover(self):
        with self.setup.session() as s:
            done={e['body']['request_id'] for e in s.events('persona_reply')}
            for row in s.events('persona_message'):
                if row['body']['request_id'] not in done:s.append('persona_reply',{'request_id':row['body']['request_id'],'status':'interrupted','reply':'서비스가 재시작됐어요. 메시지는 보존됐고 같은 내용을 다시 이어갈 수 있어요.','updates':[],'issues':[],'question':None},date.today().isoformat())

    def start(self,body):
        if not isinstance(body,dict) or set(body)!={'request_id','message','persona_id'}:raise PersonaError('대화 요청 형식을 확인해주세요.')
        if not isinstance(body['message'],str) or not 1<=len(body['message'].strip())<=4000 or (not isinstance(body['request_id'],str) or not re.fullmatch('[a-f0-9-]{32,36}',body['request_id'])):raise PersonaError('메시지는 4,000자 이내로 적어주세요.')
        with self.guard,self.setup.session() as s:
            with s.store.transaction():
                old=next((x for x in s.events('persona_message') if x['body']['request_id']==body['request_id']),None)
                if old:
                    if old['body']['message']!=body['message'] or old['body']['persona_id']!=body['persona_id']:raise PersonaError('같은 요청 ID의 내용이 달라요.')
                    return {'accepted':True,'duplicate':True,'request_id':body['request_id']}
                if self.thread and self.thread.is_alive():raise PersonaError('이전 대화 답변을 정리하고 있어요.')
                current=self.current(s)
                if body['persona_id']!=(current['id'] if current else None):raise PersonaError('개인 페르소나가 바뀌었어요. 최신 내용을 불러온 뒤 이어가 주세요.')
                profile=s.latest('profile');pending=s.latest('persona_intake')
                basis=profile or pending
                row_id=s.append('persona_message',dict(body,profile_id=profile['id'] if profile else None,basis_id=basis['id'] if basis else None),date.today().isoformat())
            self.thread=threading.Thread(target=self._work,args=(row_id,),daemon=True);self.thread.start()
            return {'accepted':True,'duplicate':False,'request_id':body['request_id']}

    def _work(self,event_id):
        with self.setup.session() as s:
            event=s.get(event_id);request=event['body'];reply={'request_id':request['request_id'],'status':'failed','reply':'대화를 끝내지 못했어요. 메시지는 저장되어 있어요.','updates':[],'issues':[],'question':None}
            try:
                profile=s.get(request['basis_id'])['body'] if request['basis_id'] else {'base_currency':'KRW','markets':['US'],'constraints':[]}
                current=s.get(request['persona_id'])['body'] if request['persona_id'] else None
                turns=[];used=0
                results={e['body']['request_id']:e['body'] for e in s.events('persona_reply')}
                for row in reversed(s.events('persona_message')):
                    if row['seq']>=event['seq']:continue
                    item={'user':row['body']['message'],'assistant':results.get(row['body']['request_id'],{}).get('reply','')}
                    size=len(d.dumps(item))
                    if used+size>12000 or len(turns)>=10:break
                    turns.append(item);used+=size
                active_profile={k:copy.deepcopy(v) for k,v in profile.items() if k not in ('context_note_history','clarification_answers','confirmed_answer_facts','persona_preferences','persona_fact_sources','context_notes')}
                payload={'persona':current,'profile':active_profile,'recent_conversation':list(reversed(turns)),'user_message':request['message'],
                    'allowed_update_fields':sorted(FIELDS),'scope':'개인 맥락 대화. 원본은 보존하고 현재 사실과 해석을 갱신. 투자 제안/실제 보유/주문 변경이 아님.'}
                while len(d.dumps(payload))>60000 and payload['recent_conversation']:payload['recent_conversation'].pop(0)
                if len(d.dumps(payload))>60000:raise PersonaError('현재 맥락이 대화 입력 한도를 넘었어요. 긴 설명은 핵심 사실 중심으로 정리해주세요. 원본은 보존돼요.')
                model=self.setup.analysis_model();contract=schema('persona-reply');guide=role_guide('context',resource('guides/roles/persona-conversation.md').read_text())
                s.append('persona_model_input',{'request_id':request['request_id'],'payload':payload,'contract':contract,'guide':guide,'provider':model.identity},event['effective'])
                output=model.complete('context',guide,payload,contract)
                s.append('persona_model_output',{'request_id':request['request_id'],'output':output},event['effective'])
                validate(output,contract)
                changed,applied,issues=apply_updates(profile,output['updates'],request['message'],event)
                prospective_profile={k:copy.deepcopy(v) for k,v in changed.items() if k not in ('context_note_history','clarification_answers','confirmed_answer_facts','persona_preferences','persona_fact_sources','context_notes')}
                prospective=dict(payload,persona=build(changed,request['profile_id'],1,event['effective']),profile=prospective_profile,recent_conversation=[],user_message='x'*4000)
                if applied and len(d.dumps(prospective))>58000:
                    changed=copy.deepcopy(profile);applied=[]
                    issues.append({'field':'context_budget','reason':'현재 페르소나가 대화 입력 한도를 넘게 되어 이번 갱신은 보류했어요. 관심사를 짧게 대체하면 이어갈 수 있고 원문은 보존돼요.'})
                with s.store.transaction():
                    latest=s.latest('profile') or s.latest('persona_intake')
                    if (latest['id'] if latest else None)!=request['basis_id']:raise PersonaError('대화 중 개인 정보가 다른 화면에서 바뀌었어요. 최신 페르소나를 기준으로 다시 이어가 주세요.')
                    if applied:
                        try:d.profile(changed)
                        except (ValueError,KeyError,TypeError):
                            if request['profile_id']:raise PersonaError('변경 후 개인 설정이 서로 맞지 않아 반영하지 않았어요.')
                            iid=s.append('persona_intake',changed,event['effective']);draft=build(changed,None,len(s.events('persona_draft'))+1,event['effective']);draft['basis_id']=iid
                            s.append('persona_draft',draft,event['effective'])
                        else:
                            from .engine import Engine
                            pid=Engine(s,None).set_profile(changed,event['effective'])
                            old=s.latest('onboarding_draft');draft=draft_projection(changed,old['body'] if old else {},pid)
                            s.append('onboarding_draft',draft,event['effective'])
                    question=output['question']
                    if question and current and not question['revisit_reason'].strip():
                        question=None;issues.append({'field':'question','reason':'기존 맥락과 남은 공백을 비교하지 않은 반복 질문을 제외했어요.'})
                    reply_text=output['reply'] if not any(i['field']!='question' for i in issues) else '말씀하신 내용은 저장했어요. 검증을 통과한 항목만 현재 페르소나에 반영했어요. 반영 항목과 보류 사유를 아래에서 확인해주세요.'
                    reply.update(status='completed',reply=reply_text,updates=applied,issues=issues,question=question,
                        persona_id=(self.current(s) or {}).get('id'))
                    s.append('persona_reply',reply,event['effective'])
                return
            except Exception as exc:
                reply.update(error_type=type(exc).__name__)
                from .codex_model import CodexError
                if isinstance(exc,(PersonaError,CodexError)):reply['reply']=str(exc)
            s.append('persona_reply',reply,event['effective'])
