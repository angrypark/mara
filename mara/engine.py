"""R1–R6/F1/F2 orchestration. A successful proposal never mutates actual holdings."""
import copy
import uuid
from datetime import timedelta
from . import domain as d
from .agents import Agents, PERSONAS
from .registry import catalogue, personas
from .knowledge import Knowledge
from .risk import evaluate
from .clarifications import questions, repeated_questions, answers
from .output_validation import AgentOutputError
from .research import compact_market
from .decision import semantics,decision_findings
from .contracts import validate,schema
from .context_budget import previous_for_role, improvement_for_role
from . import history


class ContextNeedsInput(ValueError):
    """A validated analyst request, not a provider/connection failure."""
    message='개인 투자 맥락에 추가 확인이 필요해요. 아래 항목을 확인하고 추가 설명을 입력해주세요.'

    def __init__(self,questions,output_id,structured_questions=None):
        super().__init__(self.message)
        self.questions=list(questions)
        self.output_id=output_id
        self.structured_questions=structured_questions


class ContextRepeatError(ValueError):
    message='이미 저장한 답변을 에이전트가 다시 질문했어요. 한 번 재검토했지만 해소되지 않아 분석을 멈췄어요. 답변은 보존돼요. 반복 답변 대신 저장된 맥락을 확인하고 다시 시도해주세요.'


class Engine:
    def __init__(self, session, model, research_library=None):
        self.s, self.model = session, model
        self.research_library=research_library

    def reset_history(self, as_of, reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Reset reason required')
        lock='history-reset-'+uuid.uuid4().hex
        self.s.lock(lock)
        try:
            current=self.s.latest('profile',as_of)
            if current:
                projected=history.profile_input(current['body'],{'after_seq':1,'reset_id':None})
                self.set_profile(projected,as_of)
            return self.s.append('history_reset',{'reason':reason,'policy':'Archive originals; exclude previous judgments, learned knowledge and guide overrides; retain current facts and public evidence'},as_of)
        finally:self.s.unlock(lock)

    def set_profile(self, profile, as_of):
        d.profile(profile)
        from .persona import ensure
        from contextlib import nullcontext
        with (nullcontext() if self.s.store.in_transaction else self.s.store.transaction()):
            eid=self.s.append('profile',profile,as_of)
            ensure(self.s,self.s.get(eid))
        return eid

    def set_holdings(self, holdings):
        d.holdings(holdings)
        p = self.s.latest('profile',holdings['as_of'])
        if p is None or p['body']['base_currency'] != holdings['base_currency']: raise ValueError('Profile currency mismatch')
        return self.s.append('actual',holdings,holdings['as_of'])

    def cashflow(self, flow):
        d.required(flow,['date','amount','reference'])
        d.day(flow['date']); d.number(flow['amount'],float('-inf'))
        if not isinstance(flow['reference'],str) or not flow['reference'].strip(): raise ValueError('Unique flow reference required')
        if any(e['body']['reference']==flow['reference'] for e in self.s.events('cashflow')): raise ValueError('Duplicate cashflow')
        last = history.latest(self.s,'completed')
        if last and flow['date'] <= last['effective']: raise ValueError('Historical correction needs a separate reconciliation; completed returns are immutable')
        return self.s.append('cashflow',flow,flow['date'])

    def due(self, as_of):
        last = history.latest(self.s,'completed')
        due = last is None or d.day(as_of) >= d.day(last['body']['next_evaluation'])
        return {'due':due,'next_evaluation':last['body']['next_evaluation'] if last else as_of}

    def run(self, as_of, market_id=None, force=False, revision_reason=None, amendment=None, improvement=None, evaluate_after=True, profile_id=None, actual_id=None, external_review_id=None, learning_review_id=None):
        d.day(as_of)
        run_id = uuid.uuid4().hex
        self.s.append('execution_intent',{'campaign_id':(improvement or {}).get('campaign_id'),'run_id':run_id,'kind':'portfolio_decision'},as_of,run_id)
        self.s.lock(run_id)
        try:
            result=self._run(as_of,market_id,force,run_id,revision_reason,amendment,improvement,profile_id,actual_id,external_review_id,learning_review_id)
            from .evaluation import evaluate_report
            try:
                if evaluate_after:evaluate_report(self.s,self.model,result['event_id'])
            except Exception:pass  # evaluation_status reports failure; completed proposal remains.
            return result
        except Exception as exc:
            # Do not log provider exceptions, whose URLs/bodies can contain secrets.
            failure={'error_type':type(exc).__name__,'retry':'Correct inputs/provider and rerun; completed state unchanged'}
            from .codex_model import CodexError
            if isinstance(exc,CodexError):failure['message']=str(exc)
            if isinstance(exc,AgentOutputError):failure.update(output_validation=exc.details,message=exc.message)
            self.s.append('failed',failure,as_of,run_id)
            raise
        finally:
            self.s.unlock(run_id)

    def _run(self, as_of, market_id, force, run_id, revision_reason=None, amendment=None, improvement=None, profile_id=None, actual_id=None, external_review_id=None, learning_review_id=None):
        boundary=history.scope(self.s)
        if boundary['reset_id'] and self.s.get(boundary['reset_id'])['effective']>as_of:raise ValueError('Cannot create a decision before the active history reset')
        previous = history.latest(self.s,'completed',boundary=boundary)
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        revision_of=None
        frozen=None
        if learning_review_id:
            if not force or not revision_reason or not revision_reason.strip():raise ValueError('Learning review requires force and a reason')
            if amendment or improvement or external_review_id:raise ValueError('Learning review cannot mix revision modes')
            if not previous or previous['id']!=learning_review_id or previous['effective']!=as_of:raise ValueError('Learning review requires the latest active same-date completed report')
            for key,value in (('profile_id',profile_id),('actual_id',actual_id)):
                if value and value!=previous['body'][key]:raise ValueError('Learning review pins original personal context')
            profile_id=previous['body']['profile_id'];actual_id=previous['body']['actual_id']
            revision_of=previous['id']
        if improvement:
            frozen=self.s.get(improvement['parent_completed_id'])
            if not previous or previous['id']!=frozen['id']:raise ValueError('A newer report exists; improvement branch must not replace it')
            if frozen['kind']!='completed' or frozen['effective']!=as_of:raise ValueError('Invalid improvement basis')
            market_id=improvement.get('market_id',frozen['body']['market_id'])
        if amendment:
            frozen=self.s.get(amendment['completed_id'])
            if not previous or previous['id']!=frozen['id']:raise ValueError('A newer report exists; apply to latest report')
            if frozen['kind']!='completed' or frozen['effective']!=as_of:raise ValueError('Invalid amendment basis')
            market_id=frozen['body']['market_id']
        if learning_review_id:
            pass  # Keep the immediate predecessor for actual process learning.
        elif previous and as_of == previous['effective'] and revision_reason and revision_reason.strip():
            revision_of=previous['id']
            earlier=[e for e in history.events(self.s,'completed',boundary=boundary) if e['effective']<as_of]
            previous=earlier[-1] if earlier else None
        elif previous and as_of <= previous['effective']: raise ValueError('Completed dates must advance; no duplicate weekly result')
        if not force and not revision_of and not self.due(as_of)['due']: raise ValueError('Weekly evaluation not due; use --force for an explicit early review')
        pe, he = self.s.latest('profile',as_of), self.s.latest('actual',as_of)
        if profile_id:pe=self.s.get(profile_id)
        if actual_id:he=self.s.get(actual_id)
        if frozen:
            if profile_id or actual_id:raise ValueError('Frozen amendment already pins its original context')
            pe=self.s.get(frozen['body']['profile_id']);he=self.s.get(frozen['body']['actual_id'])
        me = self.s.get(market_id) if market_id else self.s.latest('market',as_of,shared=True)
        if pe is None or he is None or me is None: raise ValueError('Profile, actual holdings and market snapshot required')
        if pe['kind']!='profile' or he['kind']!='actual' or pe['effective']>as_of or he['effective']>as_of:raise ValueError('Invalid pinned personal context')
        if me['kind'] != 'market' or me['effective'] != as_of: raise ValueError('Market snapshot must match evaluation date')
        external_review=None
        if external_review_id:
            if amendment or improvement:raise ValueError('Failure review cannot be combined with a completed-report revision')
            review=self.s.get(external_review_id)
            if review['owner']!=self.s.owner or review['kind']!='external_improvement_feedback' or review['effective']!=as_of:
                raise ValueError('Invalid external review')
            body=review['body'];failure=self.s.get(body['source_failed_id'])
            import re
            if any(not isinstance(body.get(key),str) or not re.fullmatch('[a-f0-9]{64}',body[key])
                for key in ('rubric_hash','source_packet_sha256')):raise ValueError('External review hashes required')
            if failure['owner']!=self.s.owner or failure['kind']!='failed' or failure['effective']!=as_of:
                raise ValueError('External review requires same-date failed execution')
            starts=[e for e in self.s.events('run_started') if e['run_id']==failure['run_id'] and e['seq']<failure['seq']]
            if len(starts)!=1 or any(starts[0]['body'][key]!=value for key,value in
                (('profile_id',pe['id']),('actual_id',he['id']),('market_id',me['id']))):
                raise ValueError('Failure review must retain its original personal and market inputs')
            if not isinstance(body.get('feedback'),dict):raise ValueError('External feedback must be an object')
            external_review={'source_event_id':review['id'],'source_failed_id':failure['id'],
                'rubric_hash':body['rubric_hash'],'source_packet_sha256':body['source_packet_sha256'],
                'feedback':copy.deepcopy(body['feedback']),
                'scope':'Failed execution feedback, not an adopted portfolio or permission to change personal constraints.'}
        p,h,m = pe['body'],he['body'],copy.deepcopy(me['body'])
        if boundary['after_seq']:
            m=history.market_input(m,boundary)
        if frozen:
            # Carry only evidence actually read in that run, never today's library contents.
            ids={f['id']:f for f in m['facts']}
            for event in self.s.events('research_evidence'):
                if event['run_id']==frozen['run_id'] and event['seq']<=frozen['seq']:
                    fact=event['body']['fact']
                    if fact['id'] in ids:
                        if ids[fact['id']]!=fact:raise ValueError('Inherited evidence ID collision')
                        continue
                    m['facts'].append(copy.deepcopy(fact));ids[fact['id']]=fact
                    carried=copy.deepcopy(event['body'])
                    carried['carried_from']={'event_id':event['id'],'run_id':event['run_id'],'completed_id':frozen['id']}
                    self.s.append('research_evidence',carried,as_of,run_id)
        saved_answers=answers(self.s,as_of)
        if not frozen and not external_review and not profile_id and saved_answers and p.get('clarification_answers')!=saved_answers:
            p=history.profile_input(p,boundary);p['clarification_answers']=saved_answers
            pe=self.s.get(self.set_profile(p,as_of))
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        p=history.profile_input(p,boundary)
        if p.get('contested_fields'):raise ValueError('Withdrawn or disputed personal facts require resolution before calculation: '+', '.join(p['contested_fields']))
        d.profile(p); d.holdings(h); d.market(m)
        if self.model.mode == 'live' and (m.get('synthetic') or not m['facts']):
            raise ValueError('Live analysis requires real, nonempty market evidence')
        if m['base_currency'] != p['base_currency']: raise ValueError('Market currency mismatch')
        val = d.valuation(h,m,allow_empty=p.get('proposal_capital',0)>0)
        capital=p.get('proposal_capital',val['nav'])
        future_funded=p.get('funding_source')=='future_income'
        funding={'proposal_capital':capital,'actual_nav':val['nav'],
                 'additional_funding_needed':capital if future_funded else max(0,capital-val['nav']),
                 'amount_outside_proposal':val['nav'] if future_funded else max(0,val['nav']-capital),
                 'source':p.get('funding_source','undecided'),
                 'availability':'conditional_on_deposit' if capital>val['nav'] or p.get('funding_source')=='future_income' else 'reported_holdings',
                 'monthly_contribution_is_future_flow':True}
        # Retain expired facts in immutable evidence but exclude them from current inference.
        m['facts'] = [f for f in m['facts'] if f['valid_until'] >= as_of]
        if self.model.mode=='live' and not m['facts']:
            raise ValueError('Live analysis requires currently valid evidence')
        from .persona import ensure as ensure_persona,snapshot as persona_snapshot
        user_persona=persona_snapshot(ensure_persona(self.s,pe))
        start_id = self.s.append('run_started',{'market_id':me['id'],'profile_id':pe['id'],
             'persona_id':user_persona['id'],'persona_hash':user_persona['hash'],
             'actual_id':he['id'],'previous_id':previous['id'] if previous else None,
             'mode':self.model.mode,'as_of':as_of,'revision_of':revision_of,'revision_reason':revision_reason,'learning_review_id':learning_review_id,
             'history_scope':boundary,'agent_registry':catalogue(),'amendment':amendment,'improvement':improvement,'external_review':external_review},as_of,run_id)
        from .research_questions import freeze,ledger
        decision_scope=copy.deepcopy(frozen['body']['decision_scope']) if frozen and frozen['body'].get('decision_scope') else freeze(p,m)
        self.s.append('decision_scope',decision_scope,as_of,run_id)
        k = Knowledge(self.s,after_seq=boundary['after_seq'])
        a = Agents(self.s,self.model,as_of,run_id,self.research_library)
        rebalance_due = d.day(as_of) >= d.day(h['last_rebalanced']) + timedelta(days=p['rebalance_every_days'])
        anchors = {'goal':p['goal'],'constraints':p['constraints'],'actual_rationale':h['rationale'],
            'previous_rationale':previous['body']['proposal']['rationale'] if previous else None,
            'unresolved_risks':previous['body']['proposal']['risks'] if previous else [],
            'next_checks':previous['body']['proposal']['next_checks'] if previous else []}
        if frozen:
            anchors.update(previous_rationale=frozen['body']['proposal']['rationale'],
                unresolved_risks=frozen['body']['proposal']['risks'],next_checks=frozen['body']['proposal']['next_checks'])
        prior = None
        outcome = None
        reflection = None
        reflection_id = None
        if previous:
            pb = previous['body']
            prior_boundary=pb.get('history_scope',{'after_seq':0,'reset_id':None})
            prior_market = history.market_input(self.s.get(pb['market_id'])['body'],prior_boundary)
            prior_market=copy.deepcopy(prior_market);known={f['id'] for f in prior_market['facts']}
            for e in self.s.events('research_evidence'):
                if e['run_id']==previous['run_id'] and e['seq']<=previous['seq'] and e['body']['fact']['id'] not in known:
                    prior_market['facts'].append(e['body']['fact']);known.add(e['body']['fact']['id'])
            prior = {'event_id':previous['id'],'as_of':previous['effective'],'proposal':pb['proposal'],
                     'perspectives':pb['perspectives'],'validation':pb['validation'],
                     'reflection':pb['reflection'],'market':prior_market,
                     'question_followups':[{'id':q['id'],'state':q['state'],'review':q['review']} for q in pb.get('research_questions',{}).get('questions',[])],
                     'profile':history.profile_input(self.s.get(pb['profile_id'])['body'],prior_boundary)}
            flows = [e['body'] for e in self.s.events('cashflow',as_of) if e['effective'] > previous['effective']]
            if learning_review_id:
                outcome={'start_nav':pb['valuation']['nav'],'end_nav':val['nav'],'external_net_flows':0,
                    'pnl':None,'modified_dietz':None,'holdings_confirmed':False,
                    'method':'Same-day learning review: valuation only, no return interval',
                    'limitation':'Pinned holdings are not a fresh confirmation; valuation changes are not investment performance'}
            else:
                outcome = d.performance(pb['valuation']['nav'],val['nav'],flows,previous['effective'],as_of)
            outcome['holdings_confirmed'] = (not learning_review_id and h['as_of'] == as_of and
                self.s.get(pb['actual_id'])['body']['as_of'] == previous['effective'])
            if not outcome['holdings_confirmed']:
                outcome['modified_dietz'] = None
                outcome['pnl'] = None
                outcome['limitation'] = 'Actual holdings not reconfirmed: valuation only; no realized performance claim'
            if h.get('cashflows_reconciled') is False:
                outcome['modified_dietz']=None
                outcome['pnl']=None
                outcome['cashflows_reconciled']=False
                outcome['limitation']='외부 입출금 대조가 끝나지 않아 평가액만 표시해요. 자금 납입을 투자 수익으로 해석하지 않아요.'
        from .analysis_pack import build as base_analysis
        stability=history.latest(self.s,'quality_stability_result',as_of,boundary)
        stability_receipt=None
        if stability:
            from .evaluation import evaluator_fingerprint
            if stability['body'].get('evaluator_spec_hash')==evaluator_fingerprint(self.s,self.model,as_of):
                stability_receipt=dict(stability['body'],source_event_id=stability['id'])
        comparison_perspectives={}
        comparison_alternatives={}
        def build_analysis(*args):
            result=base_analysis(*args)
            if comparison_perspectives:
                result['perspective_comparisons']={role:base_analysis(p,h,m,val,capital,view['weights'])['selected_comparison']
                    for role,view in comparison_perspectives.items()}
            if comparison_alternatives:
                result['alternative_comparisons']={key:base_analysis(p,h,m,val,capital,weights)['selected_comparison'] for key,weights in comparison_alternatives.items()}
            if stability_receipt:result['comparison']['evaluator_stability']=copy.deepcopy(stability_receipt)
            return result
        analysis=build_analysis(p,h,m,val,capital)
        common = {'decision_scope':decision_scope,'user_persona':user_persona,'history_scope':boundary,'analysis':analysis,'report_contract':'investment_case/1' if self.model.mode=='live' and m.get('return_histories') else None,
                  'improvement':improvement,'external_review':external_review,'as_of':as_of,'profile':p,'actual':h,'valuation':val,'market':m,'previous':prior,
                  'decision_context':semantics(p,m),
                  'anchors':anchors,'rebalance_due':rebalance_due,'performance':outcome,'funding':funding,
                  'frozen_revision':bool(frozen) and not (improvement or {}).get('allow_supplemental_research',False),
                  'analysis_flow':{'perspectives':'independent; no current peer outputs',
                    'leader':'after perspective validation; before final proposal validation',
                    'final_validation':'after leader; assess each statement against its original stage'}}
        from . import evidence_feedback as feedback
        from . import research_learning as learning
        research_history=learning.history(self.s,previous,as_of,self.s.get(start_id)['seq']) if previous else None
        history_id=self.s.append('research_feedback_history',research_history,as_of,run_id) if research_history else None
        learning_cycle={'status':'skipped_frozen_revision' if frozen else 'no_predecessor' if not previous else 'pending',
            'history_event_id':history_id,'source_completed_id':previous['id'] if previous else None,
            'reflection_output_id':None,'memory_outputs':[],'applications':[]}
        frozen_learning=frozen['body'].get('research_learning',{}) if frozen else {}
        memory_sources=frozen_learning.get('memory_outputs',[]) or [
            {'output_id':oid} for oid in dict.fromkeys(r['memory_output_id'] for r in frozen_learning.get('memory_feedback',{}).get('conflicts',[]))]
        memory_feedback=learning.memory_feedback(self.s,memory_sources)
        exchanges=[];feedback_seen=set();output_receipts=[];feedback_round=0
        def call(role, extra=None):
            payload = dict(common,knowledge=k.retrieve(as_of,role))
            if improvement and role not in ('leader','validation'):
                payload['improvement']=improvement_for_role(improvement,role,frozen['body'])
            if frozen:
                recorded=[e['body']['payload'] for e in self.s.events('agent_input') if e['run_id']==frozen['run_id'] and e['body']['role']==role]
                payload['knowledge']=copy.deepcopy(recorded[-1].get('knowledge',{})) if recorded else {}
            payload['market']=compact_market(m,role)
            if research_history:payload['research_feedback_history']=learning.for_role(research_history,role)
            if role in ('leader','validation') and memory_feedback['conflicts']:payload['memory_feedback']=copy.deepcopy(memory_feedback)
            if payload.get('current_reflection'):payload['current_reflection']=learning.reflection_for_role(payload['current_reflection'],role)
            payload['decision_context']=semantics(p,m)
            if prior:
                payload['previous']=previous_for_role(prior,role,compact_market(prior['market'],role,historical=True))
                payload['previous']['reflection']=learning.reflection_for_role(payload['previous'].get('reflection'),role)
                # These exact fields are already present under previous.proposal.
                payload['anchors']={k:v for k,v in anchors.items() if k not in ('previous_rationale','unresolved_risks','next_checks')}
            if role in ('validation','leader'):payload['research_question_progress']=ledger(self.s,run_id,decision_scope)
            if exchanges:
                payload['evidence_feedback']=feedback.for_role(exchanges,role)
                payload['evidence_feedback_reassessment']=True
                # Explicitly requested source content must not disappear in a
                # role's usual projection (e.g. Bogle's financial metrics).
                requested={fid for x in payload['evidence_feedback'] if x.get('response')
                    for fid in x['response']['fact_ids']}
                from .research import project_fact
                originals={f['id']:f for f in m['facts']}
                payload['market']['facts']=[project_fact(originals[f['id']],'validation') if f['id'] in requested else f
                    for f in payload['market']['facts']]
            payload['evidence_feedback_rounds_remaining']=feedback.MAX_ROUNDS-feedback_round
            payload.update(extra or {})
            payload['analysis_stage']='final_validation' if role=='validation' and 'final_proposal' in payload else 'perspective_validation' if role=='validation' else 'proposal_synthesis' if role=='leader' else role
            if role=='evidence' and payload.get('evidence_assignments'):payload['analysis_stage']='evidence_followup'
            if amendment and role==amendment.get('target_role',amendment['agent_id']) and (not amendment.get('target_stage') or amendment['target_stage']==payload['analysis_stage']):
                payload['adopted_dialogue_change']=amendment
                payload['change_policy']='사용자가 재검토를 요청한 판단. 명시적으로 수용/거절 이유를 출력 설명에 남기고 제약·근거 검증을 유지해요. profile/actual은 고정이며 변경 명령이 아니에요.'
            result=a.call(role,payload)
            output_receipts.append((role,payload['analysis_stage'],result[1],result[0]))
            for assessment in result[0].get('evidence_assessments',[]):
                for exchange in exchanges:
                    if exchange['request_id']==assessment['request_id'] and exchange['requester']==role and exchange.get('response'):
                        receipt={'request_id':exchange['request_id'],'request_event_id':exchange['request_event_id'],
                            'response_event_id':exchange['response_event_id'],'requester_output_id':result[1],
                            'requester_input_id':self.s.get(result[1])['body']['input_id'],'assessment':assessment}
                        exchange['assessment_event_id']=self.s.append('evidence_feedback_assessment',receipt,as_of,run_id)
                        exchange['assessment']=copy.deepcopy(assessment)
                        exchange['assessed_at']=self.s.get(exchange['assessment_event_id'])['recorded']
                        exchange['status']='reassessed'
            ids={f['id'] for f in m['facts']}
            for fact in a.research_facts:
                if fact['id'] not in ids:m['facts'].append(fact);ids.add(fact['id'])
            return result
        if previous and not frozen:
            reflection, reflection_id = call('reflection')
            learning_cycle.update(status='reviewed',reflection_output_id=reflection_id,
                reflection_input_id=self.s.get(reflection_id)['body']['input_id'])
            common['current_reflection'] = reflection
            # Every active record is inspected in bounded batches, including unrelated topics.
            active = k.active(as_of)
            batches, batch, size = [], [], 0
            for item in active:
                n = len(d.dumps(item))
                if size+n > 6000 and batch: batches.append(batch); batch=[]; size=0
                batch.append(item); size += n
            batches.append(batch)
            plans=[]
            for batch_no,batch in enumerate(batches):
                plan,pid = call('memory', {'review_items':batch,'reflection_id':reflection_id,
                    'learning_proposals':reflection.get('research_learning',[]) if batch_no==0 else [],
                    'allowed_refs':[reflection_id,previous['id'],me['id'],start_id]+([history_id] if history_id else []),
                    'knowledge_operation_schema':{
                        'action':'add|merge|revise|deactivate|archive', 'reason':'required',
                        'key':'existing key for all except add','text':'max 2000 chars',
                        'topic':'string','condition':'string','perspective':'string','category':'lesson|hypothesis|principle|rare_risk|market',
                        'roles':['*'],'refs':['accessible immutable event id'], 'valid_until':'YYYY-MM-DD or null','priority':'0..10'}})
                plans.append((plan,pid))
                learning_cycle['memory_outputs'].append({'output_id':pid,'input_id':self.s.get(pid)['body']['input_id'],
                    'learning_applications':plan.get('learning_applications',[]),'conflicts':plan.get('conflicts',[])})
            memory_feedback=learning.memory_feedback(self.s,learning_cycle['memory_outputs'])
            with self.s.store.transaction():
                for plan,pid in plans:
                    for i,op in enumerate(plan['operations']):
                        kid=k.apply(op,as_of,run_id)
                        receipt={'memory_output_id':pid,'reflection_output_id':reflection_id,'operation_index':i,
                            'knowledge_event_id':kid,'review_ids':[r['review_id'] for r in plan.get('learning_applications',[]) if i in r['operation_indices']]}
                        receipt['event_id']=self.s.append('research_learning_application',receipt,as_of,run_id)
                        learning_cycle['applications'].append(receipt)
                audit = k.prune(as_of,run_id)
                self.s.append('anchor_check',{'anchors':anchors,'preserved':True,'audit_id':audit},as_of,run_id)
        elif not frozen:
            audit = k.prune(as_of,run_id)
        else:audit=frozen['body']['pruning_audit_id']
        context, context_id = call('context')
        repeated=repeated_questions(context,p)
        if repeated:
            context,context_id=call('context',{'clarification_feedback':{'repeated_questions':repeated,
                'instruction':'이미 저장된 답변은 profile.clarification_answers에 있어요. 같은 의미는 기존 ID를 유지하세요. 정말 충돌/변경되어 다시 확인해야 하면 revisit_reason에 구체적인 이유를 적고, 그렇지 않으면 해당 질문을 missing/questions에서 제외하세요.'}})
            if repeated_questions(context,p):raise ContextRepeatError(ContextRepeatError.message)
        if context['missing']: raise ContextNeedsInput(context['missing'],context_id,questions(context))
        common['context_analysis']=context
        evidence, initial_evidence_id = call('evidence')
        initial_evidence=copy.deepcopy(evidence)
        common.update(context_analysis=context,evidence_analysis=evidence)
        initial_perspectives=None
        while True:
            output_receipts.clear()
            comparison_perspectives.clear();comparison_alternatives.clear()
            common['analysis']=build_analysis(p,h,m,val,capital)
            perspectives = {}
            for role in personas():
                # No peer output enters any perspective call. Separate requests, no shared conversation state.
                perspectives[role], _ = call(role)
            # Peer allocations are attached only AFTER every independent perspective.
            comparison_perspectives.update(perspectives)
            common['analysis']=build_analysis(p,h,m,val,capital)
            checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
            validation, _ = call('validation',{'perspectives':perspectives,'numeric_checks':checks})
            checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
            common['analysis']=build_analysis(p,h,m,val,capital)
            proposal, proposal_id = call('leader',{'perspectives':perspectives,'numeric_checks':checks,'validation':validation})
            from .report_references import errors as reference_errors
            for reference_attempt in (1,2,3):
                alternatives={str(i):item['weights'] for i,item in enumerate(proposal.get('investment_case',{}).get('alternatives',[]))}
                allocation_changed=common['analysis']['selected_weights']!=proposal['weights'] or comparison_alternatives!=alternatives
                comparison_alternatives.clear();comparison_alternatives.update(alternatives)
                common['analysis']=build_analysis(p,h,m,val,capital,proposal['weights'])
                errors=reference_errors(proposal,common['analysis'],funding,val)
                self.s.append('proposal_reference_validation',{'output_id':proposal_id,'attempt':reference_attempt,
                    'status':'failed' if errors or allocation_changed else 'passed','errors':errors,
                    'reference_status':'failed' if errors else 'passed',
                    'allocation_reconciliation_required':allocation_changed,
                    'code':'allocation_reconciliation' if allocation_changed else 'proposal_reference' if errors else None},as_of,run_id)
                if not errors and not allocation_changed:break
                if reference_attempt==3:raise AgentOutputError('leader','allocation_reconciliation' if allocation_changed else 'proposal_reference',proposal_id,attempts=3)
                proposal,proposal_id=call('leader',{'perspectives':perspectives,'numeric_checks':checks,'validation':validation,
                    'reference_feedback':{'errors':errors,'previous_output':proposal,
                        'selected_weights_recomputed':common['analysis']['selected_weights'],
                        'allocation_instruction':'선택한 비중의 계산을 새로 완료했어요. 같은 비중을 유지하고 보고서·주장·반대 근거의 모든 수치를 지금 analysis와 대조해 다시 작성해요. 잠정 비교안의 수치를 최종 제안의 성과로 서술하지 않아요. 수익률이 미확인인 선택 자산은 대체 지수 이력으로 채우지 않아요.',
                        'instruction':'계산 연결을 실제 report body 기준으로 교정해 전체 JSON을 다시 작성해요. evaluator가 평가 입력에서 쓰는 /report 접두사는 저자 calculation_paths에 붙이지 않아요. /input도 존재하지 않아요. 다른 값에 억지로 연결하거나 자료 공백을 숨기지 말고 주장의 범위와 반대 근거를 유지해요.'}})
            final_check = evaluate(proposal['weights'],p,m,capital,val)
            final_review, _ = call('validation',{'perspectives':perspectives,'numeric_checks':checks,
                                             'final_proposal':proposal,'final_numeric_check':final_check})

            if initial_perspectives is None:initial_perspectives=copy.deepcopy(perspectives)
            pending=feedback.collect(output_receipts,feedback_seen,feedback_round+1)
            for row in pending:
                row.update(recipient='evidence',requested_at=self.s.get(row['source_output_id'])['recorded'])
            exchanges.extend(pending)
            waiting=[r for r in exchanges if r['status'] in ('pending','deferred_capacity')]
            for row in waiting:
                row['status']='pending'
                if feedback_round>=feedback.MAX_ROUNDS:row['status']='round_budget'
                elif not self.research_library:row['status']='research_unavailable'
                elif common['frozen_revision'] or as_of!=self.research_library.today:row['status']='frozen_snapshot'
            active=feedback.schedule([r for r in waiting if r['status']=='pending'],exchanges)
            for row in pending:
                row['request_event_id']=self.s.append('evidence_feedback_request',row,as_of,run_id)
                row['queued_at']=self.s.get(row['request_event_id'])['recorded']
            self.s.append('evidence_feedback_schedule',{'round':feedback_round+1,
                'selected':[r['request_id'] for r in active],
                'dispositions':[{'request_id':r['request_id'],'request_event_id':r.get('request_event_id'),
                    'status':r['status'],'reason':r.get('scheduling_reason',r['status']),
                    'priority_score':r.get('priority_score'),'research_group':r.get('research_group')} for r in waiting]},as_of,run_id)
            if not active:break
            feedback_round+=1
            assignments=[{k:v for k,v in r.items() if k not in ('dedup_key','status')} for r in active]
            dispatch_id=self.s.append('evidence_feedback_dispatch',{'round':feedback_round,'requests':assignments},as_of,run_id)
            supplied,supplier_id=call('evidence',{'evidence_assignments':assignments,
                'evidence_feedback_reassessment':False,'evidence_feedback':[]})
            responses={r['request_id']:r for r in supplied['evidence_responses']}
            supplier_input_id=self.s.get(supplier_id)['body']['input_id']
            supplied_facts=self.s.get(supplier_input_id)['body']['payload']['market']['facts']
            tool_events=[e['id'] for kind in ('research_tool_result','research_tool_failure','research_stop')
                for e in self.s.events(kind) if e['run_id']==run_id and e['seq']>self.s.get(dispatch_id)['seq']]
            return_id=self.s.append('evidence_feedback_return',{'dispatch_id':dispatch_id,
                'supplier_output_id':supplier_id,'supplier_input_id':supplier_input_id,
                'tool_event_ids':tool_events,'responses':supplied['evidence_responses'],
                'delivered_facts':{f['id']:__import__('hashlib').sha256(d.dumps(f).encode()).hexdigest()
                    for f in supplied_facts if any(f['id'] in r['fact_ids'] for r in supplied['evidence_responses'])}},as_of,run_id)
            for row in active:
                row.update(status='returned_for_reassessment',response=responses[row['request_id']],
                    supplier_output_id=supplier_id,response_event_id=return_id,
                    responded_at=self.s.get(return_id)['recorded'])
            # Re-reading existing evidence and an unavailable response both
            # require a new analyst judgment; new fact IDs are not the trigger.
            evidence=supplied
            common['evidence_analysis']={k:v for k,v in evidence.items() if k!='evidence_responses'}
        final_check = evaluate(proposal['weights'],p,m,capital,val)
        checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
        differences = {s:proposal['weights'].get(s,0)-val['weights'].get(s,0)
                       for s in set(proposal['weights'])|set(val['weights'])}
        if proposal['action'] == 'hold' and any(abs(x)>1e-6 for x in differences.values()):
            raise ValueError('Hold proposal changes actual weights')
        blocked = proposal['action']=='defer' or not final_check['passed'] or not final_review['qualitative_pass']
        if blocked:
            proposal['action'] = 'defer'
            proposal['risks'] += final_check['errors'] + final_check['missing'] + final_review['issues']
        if proposal['action']=='hold' and abs(capital-val['nav'])>1e-6:
            proposal['action']='defer'
            blocked=True
            proposal['risks'].append('실제 운용액과 제안 기준액이 달라 단순 유지로 처리할 수 없어요.')
        proposal['eligibility'] = 'blocked' if blocked else ('review_now' if rebalance_due or not previous else 'review_at_rebalance')
        proposal['weight_changes'] = differences
        proposal['execution'] = 'Proposal only; user records actual changes separately'
        proposal['decision_status']={'scope':'portfolio_proposal_only','status':'blocked' if blocked else 'ready_for_user_review',
            'numeric_blockers':final_check['errors']+final_check['missing'],
            'analyst_blockers':final_review['issues'] if not final_review['qualitative_pass'] else [],
            'findings':decision_findings(final_check,final_review),
            'execution_status':'not_authorized','funding_availability':funding['availability'],
            'execution_checks':(final_check.get('evidence_assessment') or {}).get('execution_checks',[])}
        proposal['monthly_allocation']={'schedule':p.get('contribution_schedule','days'),
            'amount':p['contribution_amount'],'currency':p['base_currency'],
            'amounts':{s:p['contribution_amount']*w for s,w in proposal['weights'].items()},
            'status':'blocked' if blocked else 'conditional_plan',
            'rule':'첫 납입은 같은 달의 정기 납입과 중복하지 않아요. 실제 입금 후 기존 편차와 비용을 재검토할 목표 배분이며 주문 지시가 아니에요.'}
        validate(proposal['decision_status'],schema('decision'))
        # Evidence was written before the final portfolio existed. Keep that
        # observation in its original stage, never as final portfolio changes.
        proposal['market_changes']=[]
        # Record facts actually present in each accepted input, not just collected.
        delivery=[]
        for event in self.s.events('agent_validation'):
            if event['run_id']==run_id and event['body']['status']=='accepted':
                inp=self.s.get(event['body']['input_id'])
                body=inp['body'];facts=body['payload'].get('market',{}).get('facts',[])
                delivery.append({'role':body['role'],'input_id':inp['id'],'output_id':event['body']['output_id'],
                    'stage':body['payload'].get('analysis_stage'), 'fact_ids':[f['id'] for f in facts],
                    'guide_hash':body['guide_hash'],'input_hash':__import__('hashlib').sha256(d.dumps(body['payload']).encode()).hexdigest(),
                    'provider':body['provider']})
        analysis=build_analysis(p,h,m,val,capital,proposal['weights'])
        analysis['source_ids']={'profile_id':pe['id'],'actual_id':he['id'],'market_id':me['id']}
        # Original dissent is retained regardless of how the leader summarizes it.
        report = {'run_id':run_id,'mode':self.model.mode,'as_of':as_of,'profile_id':pe['id'],
            'persona_id':user_persona['id'],'persona_hash':user_persona['hash'],
            'actual_id':he['id'],'market_id':me['id'],'previous_id':previous['id'] if previous else None,
            'valuation':val,'performance':outcome,'reflection':reflection,'funding':funding,'risk_budget':d.loss_budget(p),
            'revision_of':revision_of,'revision_reason':revision_reason,'learning_review_id':learning_review_id,'amendment':amendment,
            'history_scope':boundary,'analysis':analysis,'evidence_delivery':delivery,'improvement':improvement,'external_review':external_review,
            'perspectives':perspectives,'validation':{'numeric':checks,'critique':validation,
            'final_numeric':final_check,'final_critique':final_review}, 'proposal':proposal,
            'pruning_audit_id':audit,'anchors':anchors,'next_evaluation':(d.day(as_of)+timedelta(days=7)).isoformat(),
            'rebalance_due':rebalance_due,'next_rebalance':(d.day(h['last_rebalanced'])+timedelta(days=p['rebalance_every_days'])).isoformat()}
        from .analysis_pack import coverage_ledger
        report['coverage_ledger']=coverage_ledger(report,m)
        report['evidence_feedback']={'schema_version':feedback.VERSION,'rounds':feedback_round,
            'exchanges':exchanges,'initial_perspectives':initial_perspectives,
            'initial_evidence':{'output_id':initial_evidence_id,'analysis':initial_evidence},
            'scope':'Supplier receipts are not analytical resolution; final validation and readiness remain separate.'}
        for row in exchanges:
            row['final_decision']={'action':proposal['action'],'question_id':row['question_id'],
                'proposal_output_id':proposal_id,'final_validation_output_id':next(x[2] for x in reversed(output_receipts) if x[1]=='final_validation'),
                'linked_gaps':[g for g in proposal.get('decision_gaps',[]) if g['question_id']==row['question_id']]}
        learning_cycle['knowledge_usage']=learning.usage_receipts(self.s,run_id)
        learning_cycle['memory_feedback']=copy.deepcopy(memory_feedback)
        learning_cycle['memory_reviews']={'leader':copy.deepcopy(proposal.get('memory_reviews',[])),
            'final_validation':copy.deepcopy(final_review.get('memory_reviews',[]))}
        learning_cycle['scope']='Stored/delivered/model-reported use are separately traceable; decision quality and investment outcomes are not inferred from receipts.'
        report['research_learning']=learning_cycle
        report['decision_scope']=decision_scope
        report['research_questions']=ledger(self.s,run_id,decision_scope,delivery,final_review)
        report['market_observations']={'stage':'evidence_followup' if feedback_round else 'evidence','output_id':next((x['output_id'] for x in reversed(delivery) if x['role']=='evidence'),None),
            'analysis':copy.deepcopy(evidence),'scope':'최종 제안 전에 작성한 시황 기록이에요. 당시 비중 설명을 최종 상태로 해석하지 않아요.'}
        from .decision import contributions
        report['contribution_basis']=dict(contributions(p),every_days=p.get('contribution_every_days') if p.get('contribution_schedule')!='monthly' else None)
        # Write the reader's summary only after late research and final review.
        # An editorial failure cannot turn a blocked decision into an approval.
        from .editorial import create as create_brief
        try:report['reader_brief']=create_brief(self.s,self.model,report,m['facts'])
        except Exception as exc:
            self.s.append('report_editor_failed',{'error_type':type(exc).__name__,
                'scope':'Final decision preserved; reader brief unavailable'},as_of,run_id)
            report['reader_brief']=None
        from .final_report import safe_assemble
        report['final_report']=safe_assemble(report,m['facts'])
        with self.s.store.transaction():
            proposal_id = self.s.append('proposal',proposal,as_of,run_id)
            report['proposal_id'] = proposal_id
            eid = self.s.append('completed',report,as_of,run_id)
            from .fact_catalog import persist
            persist(self.s,eid,m['facts'])
        return dict(report,event_id=eid)
