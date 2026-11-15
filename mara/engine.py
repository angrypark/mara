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
    def __init__(self, session, model):
        self.s, self.model = session, model

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
        last = self.s.latest('completed')
        if last and flow['date'] <= last['effective']: raise ValueError('Historical correction needs a separate reconciliation; completed returns are immutable')
        return self.s.append('cashflow',flow,flow['date'])

    def due(self, as_of):
        last = self.s.latest('completed')
        due = last is None or d.day(as_of) >= d.day(last['body']['next_evaluation'])
        return {'due':due,'next_evaluation':last['body']['next_evaluation'] if last else as_of}

    def run(self, as_of, market_id=None, force=False, revision_reason=None):
        d.day(as_of)
        run_id = uuid.uuid4().hex
        self.s.lock(run_id)
        try:
            return self._run(as_of,market_id,force,run_id,revision_reason)
        except Exception as exc:
            # Do not log provider exceptions, whose URLs/bodies can contain secrets.
            failure={'error_type':type(exc).__name__,'retry':'Correct inputs/provider and rerun; completed state unchanged'}
            if isinstance(exc,AgentOutputError):failure.update(output_validation=exc.details,message=exc.message)
            self.s.append('failed',failure,as_of,run_id)
            raise
        finally:
            self.s.unlock(run_id)

    def _run(self, as_of, market_id, force, run_id, revision_reason=None):
        previous = self.s.latest('completed')
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        revision_of=None
        if previous and as_of == previous['effective'] and revision_reason and revision_reason.strip():
            revision_of=previous['id']
            earlier=[e for e in self.s.events('completed') if e['effective']<as_of]
            previous=earlier[-1] if earlier else None
        elif previous and as_of <= previous['effective']: raise ValueError('Completed dates must advance; no duplicate weekly result')
        if not force and not revision_of and not self.due(as_of)['due']: raise ValueError('Weekly evaluation not due; use --force for an explicit early review')
        pe, he = self.s.latest('profile',as_of), self.s.latest('actual',as_of)
        me = self.s.get(market_id) if market_id else self.s.latest('market',as_of,shared=True)
        if pe is None or he is None or me is None: raise ValueError('Profile, actual holdings and market snapshot required')
        if me['kind'] != 'market' or me['effective'] != as_of: raise ValueError('Market snapshot must match evaluation date')
        p,h,m = pe['body'],he['body'],copy.deepcopy(me['body'])
        saved_answers=answers(self.s,as_of)
        if saved_answers and p.get('clarification_answers')!=saved_answers:
            p=copy.deepcopy(p);p['clarification_answers']=saved_answers
            pe=self.s.get(self.set_profile(p,as_of))
        if previous and previous['body']['mode'] != self.model.mode: raise ValueError('Demo and live histories must use separate users')
        d.profile(p); d.holdings(h); d.market(m)
        if self.model.mode == 'live' and (m.get('synthetic') or not m['facts']):
            raise ValueError('Live analysis requires real, nonempty market evidence')
        if m['base_currency'] != p['base_currency']: raise ValueError('Market currency mismatch')
        val = d.valuation(h,m,allow_empty=p.get('proposal_capital',0)>0)
        capital=p.get('proposal_capital',val['nav'])
        funding={'proposal_capital':capital,'actual_nav':val['nav'],
                 'additional_funding_needed':max(0,capital-val['nav']),
                 'amount_outside_proposal':max(0,val['nav']-capital)}
        # Retain expired facts in immutable evidence but exclude them from current inference.
        m['facts'] = [f for f in m['facts'] if f['valid_until'] >= as_of]
        if self.model.mode=='live' and not m['facts']:
            raise ValueError('Live analysis requires currently valid evidence')
        start_id = self.s.append('run_started',{'market_id':me['id'],'profile_id':pe['id'],
             'actual_id':he['id'],'previous_id':previous['id'] if previous else None,
             'mode':self.model.mode,'as_of':as_of,'revision_of':revision_of,'revision_reason':revision_reason,
             'agent_registry':catalogue()},as_of,run_id)
        k = Knowledge(self.s)
        a = Agents(self.s,self.model,as_of,run_id)
        rebalance_due = d.day(as_of) >= d.day(h['last_rebalanced']) + timedelta(days=p['rebalance_every_days'])
        anchors = {'goal':p['goal'],'constraints':p['constraints'],'actual_rationale':h['rationale'],
            'previous_rationale':previous['body']['proposal']['rationale'] if previous else None,
            'unresolved_risks':previous['body']['proposal']['risks'] if previous else [],
            'next_checks':previous['body']['proposal']['next_checks'] if previous else []}
        prior = None
        outcome = None
        reflection = None
        reflection_id = None
        if previous:
            pb = previous['body']
            prior_market = self.s.get(pb['market_id'])['body']
            prior = {'as_of':previous['effective'],'proposal':pb['proposal'],
                     'perspectives':pb['perspectives'],'validation':pb['validation'],
                     'reflection':pb['reflection'],'market':prior_market,
                     'profile':self.s.get(pb['profile_id'])['body']}
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
        common = {'as_of':as_of,'profile':p,'actual':h,'valuation':val,'market':m,'previous':prior,
                  'anchors':anchors,'rebalance_due':rebalance_due,'performance':outcome,'funding':funding,
                  'analysis_flow':{'perspectives':'independent; no current peer outputs',
                    'leader':'after perspective validation; before final proposal validation',
                    'final_validation':'after leader; assess each statement against its original stage'}}
        def call(role, extra=None):
            payload = dict(common,knowledge=k.retrieve(as_of,role))
            payload['market']=compact_market(m,role)
            if prior:
                payload['previous']=copy.deepcopy(prior)
                payload['previous']['market']=compact_market(prior['market'],role,historical=True)
            payload.update(extra or {})
            payload['analysis_stage']='final_validation' if role=='validation' and 'final_proposal' in payload else 'perspective_validation' if role=='validation' else 'proposal_synthesis' if role=='leader' else role
            return a.call(role,payload)
        if previous:
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
        else:
            audit = k.prune(as_of,run_id)
        context, context_id = call('context')
        repeated=repeated_questions(context,p)
        if repeated:
            context,context_id=call('context',{'clarification_feedback':{'repeated_questions':repeated,
                'instruction':'이미 저장된 답변은 profile.clarification_answers에 있어요. 같은 의미는 기존 ID를 유지하세요. 정말 충돌/변경되어 다시 확인해야 하면 revisit_reason에 구체적인 이유를 적고, 그렇지 않으면 해당 질문을 missing/questions에서 제외하세요.'}})
            if repeated_questions(context,p):raise ContextRepeatError(ContextRepeatError.message)
        if context['missing']: raise ContextNeedsInput(context['missing'],context_id,questions(context))
        evidence, _ = call('evidence')
        common.update(context_analysis=context,evidence_analysis=evidence)
        perspectives = {}
        for role in personas():
            # No peer output enters any perspective call. Separate requests, no shared conversation state.
            perspectives[role], _ = call(role)
        checks = {r:evaluate(x['weights'],p,m,capital,val) for r,x in perspectives.items()}
        validation, _ = call('validation',{'perspectives':perspectives,'numeric_checks':checks})
        proposal, _ = call('leader',{'perspectives':perspectives,'numeric_checks':checks,'validation':validation})
        final_check = evaluate(proposal['weights'],p,m,capital,val)
        final_review, _ = call('validation',{'perspectives':perspectives,'numeric_checks':checks,
                                         'final_proposal':proposal,'final_numeric_check':final_check})
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
        proposal['market_changes'] = evidence['changes']
        # Original dissent is retained regardless of how the leader summarizes it.
        report = {'run_id':run_id,'mode':self.model.mode,'as_of':as_of,'profile_id':pe['id'],
            'actual_id':he['id'],'market_id':me['id'],'previous_id':previous['id'] if previous else None,
            'valuation':val,'performance':outcome,'reflection':reflection,'funding':funding,
            'revision_of':revision_of,'revision_reason':revision_reason,
            'perspectives':perspectives,'validation':{'numeric':checks,'critique':validation,
            'final_numeric':final_check,'final_critique':final_review}, 'proposal':proposal,
            'pruning_audit_id':audit,'anchors':anchors,'next_evaluation':(d.day(as_of)+timedelta(days=7)).isoformat(),
            'rebalance_due':rebalance_due,'next_rebalance':(d.day(h['last_rebalanced'])+timedelta(days=p['rebalance_every_days'])).isoformat()}
        with self.s.store.transaction():
            proposal_id = self.s.append('proposal',proposal,as_of,run_id)
            report['proposal_id'] = proposal_id
            eid = self.s.append('completed',report,as_of,run_id)
        return dict(report,event_id=eid)
