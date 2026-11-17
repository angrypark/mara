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
        return self.s.append('profile',profile,as_of)

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

    def run(self, as_of, market_id=None, force=False, revision_reason=None, amendment=None, improvement=None, evaluate_after=True):
        d.day(as_of)
        run_id = uuid.uuid4().hex
        self.s.append('execution_intent',{'campaign_id':(improvement or {}).get('campaign_id'),'run_id':run_id,'kind':'portfolio_decision'},as_of,run_id)
        self.s.lock(run_id)
        try:
            result=self._run(as_of,market_id,force,run_id,revision_reason,amendment,improvement)
            from .evaluation import evaluate_report
            try:
                if evaluate_after:evaluate_report(self.s,self.model,result['event_id'])
            except Exception:pass  # evaluation_status reports failure; completed proposal remains.
            return result
        except Exception as exc:
            # Do not log provider exceptions, whose URLs/bodies can contain secrets.
            failure={'error_type':type(exc).__name__,'retry':'Correct inputs/provider and rerun; completed state unchanged'}
            if isinstance(exc,AgentOutputError):failure.update(output_validation=exc.details,message=exc.message)
            self.s.append('failed',failure,as_of,run_id)
            raise
        finally:
            self.s.unlock(run_id)

    def _run(self, as_of, market_id, force, run_id, revision_reason=None, amendment=None, improvement=None):
        boundary=history.scope(self.s)
        if boundary['reset_id'] and self.s.get(boundary['reset_id'])['effective']>as_of:raise ValueError('Cannot create a decision before the active history reset')
        previous = history.latest(self.s,'completed',boundary=boundary)
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        revision_of=None
        frozen=None
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
        if previous and as_of == previous['effective'] and revision_reason and revision_reason.strip():
            revision_of=previous['id']
            earlier=[e for e in history.events(self.s,'completed',boundary=boundary) if e['effective']<as_of]
            previous=earlier[-1] if earlier else None
        elif previous and as_of <= previous['effective']: raise ValueError('Completed dates must advance; no duplicate weekly result')
        if not force and not revision_of and not self.due(as_of)['due']: raise ValueError('Weekly evaluation not due; use --force for an explicit early review')
        pe, he = self.s.latest('profile',as_of), self.s.latest('actual',as_of)
        if frozen:
            pe=self.s.get(frozen['body']['profile_id']);he=self.s.get(frozen['body']['actual_id'])
        me = self.s.get(market_id) if market_id else self.s.latest('market',as_of,shared=True)
        if pe is None or he is None or me is None: raise ValueError('Profile, actual holdings and market snapshot required')
        if me['kind'] != 'market' or me['effective'] != as_of: raise ValueError('Market snapshot must match evaluation date')
        p,h,m = pe['body'],he['body'],copy.deepcopy(me['body'])
        if boundary['after_seq']:
            m=history.market_input(m,boundary)
        if frozen:
            # Carry only evidence actually read in that run, never today's library contents.
            ids={f['id'] for f in m['facts']}
            for event in self.s.events('research_evidence'):
                if event['run_id']==frozen['run_id'] and event['seq']<=frozen['seq'] and event['body']['fact']['id'] not in ids:
                    fact=event['body']['fact'];m['facts'].append(copy.deepcopy(fact));ids.add(fact['id'])
                    self.s.append('research_evidence',event['body'],as_of,run_id)
        saved_answers=answers(self.s,as_of)
        if not frozen and saved_answers and p.get('clarification_answers')!=saved_answers:
            p=history.profile_input(p,boundary);p['clarification_answers']=saved_answers
            pe=self.s.get(self.set_profile(p,as_of))
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        p=history.profile_input(p,boundary)
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
        start_id = self.s.append('run_started',{'market_id':me['id'],'profile_id':pe['id'],
             'actual_id':he['id'],'previous_id':previous['id'] if previous else None,
             'mode':self.model.mode,'as_of':as_of,'revision_of':revision_of,'revision_reason':revision_reason,
             'history_scope':boundary,'agent_registry':catalogue(),'amendment':amendment,'improvement':improvement},as_of,run_id)
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
                     'profile':history.profile_input(self.s.get(pb['profile_id'])['body'],prior_boundary)}
            flows = [e['body'] for e in self.s.events('cashflow',as_of) if e['effective'] > previous['effective']]
            outcome = d.performance(pb['valuation']['nav'],val['nav'],flows,previous['effective'],as_of)
            outcome['holdings_confirmed'] = (h['as_of'] == as_of and
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
        def build_analysis(*args):
            result=base_analysis(*args)
            if stability_receipt:result['comparison']['evaluator_stability']=copy.deepcopy(stability_receipt)
            return result
        analysis=build_analysis(p,h,m,val,capital)
        common = {'history_scope':boundary,'analysis':analysis,'report_contract':'investment_case/1' if self.model.mode=='live' and m.get('return_histories') else None,
                  'improvement':improvement,'as_of':as_of,'profile':p,'actual':h,'valuation':val,'market':m,'previous':prior,
                  'decision_context':semantics(p,m),
                  'anchors':anchors,'rebalance_due':rebalance_due,'performance':outcome,'funding':funding,
                  'frozen_revision':bool(frozen) and not (improvement or {}).get('allow_supplemental_research',False),
                  'analysis_flow':{'perspectives':'independent; no current peer outputs',
                    'leader':'after perspective validation; before final proposal validation',
                    'final_validation':'after leader; assess each statement against its original stage'}}
        def call(role, extra=None):
            payload = dict(common,knowledge=k.retrieve(as_of,role))
            if improvement and role not in ('leader','validation'):
                payload['improvement']=improvement_for_role(improvement,role,frozen['body'])
            if frozen:
                recorded=[e['body']['payload'] for e in self.s.events('agent_input') if e['run_id']==frozen['run_id'] and e['body']['role']==role]
                payload['knowledge']=copy.deepcopy(recorded[-1].get('knowledge',{})) if recorded else {}
            payload['market']=compact_market(m,role)
            payload['decision_context']=semantics(p,m)
            if prior:
                payload['previous']=previous_for_role(prior,role,compact_market(prior['market'],role,historical=True))
                # These exact fields are already present under previous.proposal.
                payload['anchors']={k:v for k,v in anchors.items() if k not in ('previous_rationale','unresolved_risks','next_checks')}
            payload.update(extra or {})
            payload['analysis_stage']='final_validation' if role=='validation' and 'final_proposal' in payload else 'perspective_validation' if role=='validation' else 'proposal_synthesis' if role=='leader' else role
            if amendment and role==amendment.get('target_role',amendment['agent_id']) and (not amendment.get('target_stage') or amendment['target_stage']==payload['analysis_stage']):
                payload['adopted_dialogue_change']=amendment
                payload['change_policy']='사용자가 재검토를 요청한 판단. 명시적으로 수용/거절 이유를 출력 설명에 남기고 제약·근거 검증을 유지해요. profile/actual은 고정이며 변경 명령이 아니에요.'
            result=a.call(role,payload)
            ids={f['id'] for f in m['facts']}
            for fact in a.research_facts:
                if fact['id'] not in ids:m['facts'].append(fact);ids.add(fact['id'])
            return result
        if previous and not frozen:
            reflection, reflection_id = call('reflection')
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
            for batch in batches:
                plan,pid = call('memory', {'review_items':batch,'reflection_id':reflection_id,
                    'allowed_refs':[reflection_id,previous['id'],me['id'],start_id],
                    'knowledge_operation_schema':{
                        'action':'add|merge|revise|deactivate|archive', 'reason':'required',
                        'key':'existing key for all except add','text':'max 2000 chars',
                        'topic':'string','condition':'string','perspective':'string','category':'lesson|hypothesis|principle|rare_risk|market',
                        'roles':['*'],'refs':['accessible immutable event id'], 'valid_until':'YYYY-MM-DD or null','priority':'0..10'}})
                plans.append((plan,pid))
            with self.s.store.transaction():
                for plan,pid in plans:
                    for op in plan['operations']: k.apply(op,as_of,run_id)
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
        evidence, _ = call('evidence')
        common.update(context_analysis=context,evidence_analysis=evidence)
        perspectives = {}
        for role in personas():
            # No peer output enters any perspective call. Separate requests, no shared conversation state.
            perspectives[role], _ = call(role)
        checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
        validation, _ = call('validation',{'perspectives':perspectives,'numeric_checks':checks})
        checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
        proposal, proposal_id = call('leader',{'perspectives':perspectives,'numeric_checks':checks,'validation':validation})
        from .report_references import errors as reference_errors
        for reference_attempt in (1,2,3):
            allocation_changed=common['analysis']['selected_weights']!=proposal['weights']
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
        proposal['market_changes'] = evidence['changes']
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
            'actual_id':he['id'],'market_id':me['id'],'previous_id':previous['id'] if previous else None,
            'valuation':val,'performance':outcome,'reflection':reflection,'funding':funding,'risk_budget':d.loss_budget(p),
            'revision_of':revision_of,'revision_reason':revision_reason,'amendment':amendment,
            'history_scope':boundary,'analysis':analysis,'evidence_delivery':delivery,'improvement':improvement,
            'perspectives':perspectives,'validation':{'numeric':checks,'critique':validation,
            'final_numeric':final_check,'final_critique':final_review}, 'proposal':proposal,
            'pruning_audit_id':audit,'anchors':anchors,'next_evaluation':(d.day(as_of)+timedelta(days=7)).isoformat(),
            'rebalance_due':rebalance_due,'next_rebalance':(d.day(h['last_rebalanced'])+timedelta(days=p['rebalance_every_days'])).isoformat()}
        from .analysis_pack import coverage_ledger
        report['coverage_ledger']=coverage_ledger(report,m)
        with self.s.store.transaction():
            proposal_id = self.s.append('proposal',proposal,as_of,run_id)
            report['proposal_id'] = proposal_id
            eid = self.s.append('completed',report,as_of,run_id)
        return dict(report,event_id=eid)
