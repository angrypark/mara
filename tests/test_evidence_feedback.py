import copy,tempfile,unittest
from pathlib import Path
from mara.agents import DemoModel,validate_output
from mara.engine import Engine
from mara.store import Store
from mara.company_research import CompanyLibrary
from mara.evidence_feedback import collect
from test_decision import profile,market


def request(need='Read the existing issuer exposure'):
    return dict(question_id='candidate-FUND',need=need,gap_type='extraction',
        acceptance='Read the issuer source for the dated FUND exposure and missing dimensions',
        decision_impact='Reassess the inclusion premise; no target allocation is requested')


class FeedbackModel(DemoModel):
    def __init__(self,late=False,endless=False):self.late=late;self.endless=endless;self.round=0;self.inputs=[]
    def complete(self,role,guide,p,contract):
        self.inputs.append((role,copy.deepcopy(p)))
        out=super().complete(role,guide,p,contract)
        if role=='evidence' and p.get('evidence_assignments'):
            self.round+=1
            out['evidence_responses']=[dict(request_id=r['request_id'],status='evidence_supplied',
                fact_ids=[p['market']['facts'][0]['id']],reason='Existing source located, not a new independent source',
                remaining_gap='Economic argument still needs review') for r in p['evidence_assignments']]
        if role in ('buffett','marks','bogle','wood','validation','leader'):
            own={x['request_id']:x for x in p.get('evidence_feedback',[]) if x['requester']==role and x.get('response')}
            if own:out['evidence_assessments']=[dict(request_id=key,status='still_missing',reason='Read source but the economic premise remains unresolved',fact_ids=row['response']['fact_ids']) for key,row in own.items()]
        if (not self.late and role=='buffett') or (self.late and role=='validation' and p.get('final_proposal')):
            out['evidence_requests']=[request('Additional premise '+str(self.round) if self.endless else 'Read the existing issuer exposure')]
        return out


class EvidenceFeedbackTests(unittest.TestCase):
    def run_fixture(self,model,frozen=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        db=Store(Path(tmp.name)/'db');self.addCleanup(db.close);s=db.session(db.create_user('fixture'))
        m=market();library=CompanyLibrary(Path(tmp.name)/'library',today='2026-11-18' if frozen else m['as_of'])
        e=Engine(s,model,library);e.set_profile(profile(),m['as_of']);e.set_holdings(dict(as_of=m['as_of'],base_currency='USD',cash=100,positions={},rationale='Synthetic only',last_rebalanced=m['as_of']))
        before=[(x['id'],x['digest']) for kind in ('profile','actual') for x in s.events(kind)]
        result=e.run(m['as_of'],db.publish_market(m),evaluate_after=False)
        self.assertEqual(before,[(x['id'],x['digest']) for kind in ('profile','actual') for x in s.events(kind)])
        return result,s

    def test_existing_fact_response_is_reassessed_and_peer_allocations_never_leak(self):
        model=FeedbackModel();result,s=self.run_fixture(model)
        self.assertEqual(result['evidence_feedback']['rounds'],1)
        self.assertEqual(len(s.events('evidence_feedback_return')),1)
        self.assertTrue(s.events('evidence_feedback_assessment'))
        rows=result['evidence_feedback']['exchanges']
        self.assertEqual(rows[0]['status'],'reassessed');self.assertEqual(rows[0]['assessment']['status'],'still_missing')
        self.assertEqual(rows[-1]['status'],'duplicate')
        for role,p in model.inputs:
            if role in ('buffett','marks','bogle','wood') and p.get('evidence_feedback_reassessment'):
                self.assertNotIn('perspectives',p)
                self.assertNotIn('perspective_comparisons',p['analysis']);self.assertNotIn('alternative_comparisons',p['analysis'])
                self.assertTrue(all(r['requester']==role for r in p['evidence_feedback']))
                self.assertNotIn('evidence_responses',p['evidence_analysis'])
        self.assertEqual(result['market_observations']['stage'],'evidence_followup')
        self.assertEqual(len(s.events('research_evidence')),0)

    def test_final_validator_request_roundtrip_and_hard_limit(self):
        result,s=self.run_fixture(FeedbackModel(late=True,endless=True))
        self.assertEqual(result['evidence_feedback']['rounds'],2)
        self.assertEqual(len(s.events('evidence_feedback_return')),2)
        self.assertTrue(any(x['status']=='round_budget' for x in result['evidence_feedback']['exchanges']))
        self.assertTrue(any(x['requester']=='validation' and x['assessment']['status']=='still_missing' for x in result['evidence_feedback']['exchanges'] if x.get('assessment')))

    def test_historical_run_records_request_without_fetching_new_evidence(self):
        result,s=self.run_fixture(FeedbackModel(),frozen=True)
        self.assertEqual(result['evidence_feedback']['rounds'],0)
        self.assertEqual(result['evidence_feedback']['exchanges'][0]['status'],'frozen_snapshot')
        self.assertFalse(s.events('evidence_feedback_dispatch'))

    def test_overflow_is_served_next_round_and_unavailable_response_is_assessed(self):
        class Many(FeedbackModel):
            def complete(self,role,guide,p,contract):
                out=super().complete(role,guide,p,contract)
                if role in ('buffett','marks'):
                    out['evidence_requests']=[request('Distinct source '+str(i)) for i in range(4)]
                if role=='evidence' and p.get('evidence_assignments'):
                    for row in out['evidence_responses']:
                        row.update(status='unavailable',fact_ids=[],remaining_gap='Public source not available')
                return out
        result,s=self.run_fixture(Many())
        self.assertEqual([len(e['body']['requests']) for e in s.events('evidence_feedback_dispatch')],[6,2])
        rows=[r for r in result['evidence_feedback']['exchanges'] if r.get('response')]
        self.assertEqual(len(rows),8)
        self.assertTrue(all(r['status']=='reassessed' and r['assessment']['status']=='still_missing' for r in rows))
        self.assertFalse(any(r['status'] in ('pending','deferred_capacity') for r in result['evidence_feedback']['exchanges']))

    def test_contract_rejects_wrong_question_response_or_unacknowledged_reply(self):
        m=market();payload={'market':m,'decision_scope':{'questions':[{'id':'candidate-FUND'}]}}
        out=DemoModel().complete('evidence','',payload,{})
        payload['evidence_assignments']=[{'request_id':'request-one'}]
        with self.assertRaises(ValueError):validate_output('evidence',out,payload)
        out['evidence_responses']=[dict(request_id='request-one',status='evidence_supplied',fact_ids=['invented'],reason='bad',remaining_gap='')]
        with self.assertRaises(ValueError):validate_output('evidence',out,payload)
        out['evidence_responses'][0]['fact_ids']=[m['facts'][0]['id']]
        validate_output('evidence',out,payload)
        p=dict(payload,valuation={'weights':{'CASH':1}})
        out=DemoModel().complete('buffett','',p,{})
        out['evidence_requests']=[dict(request(),question_id='unknown')]
        with self.assertRaises(ValueError):validate_output('buffett',out,p)
        out.pop('evidence_requests');p['evidence_feedback']=[{'request_id':'request-one','requester':'buffett','response':{'status':'unavailable'}}]
        with self.assertRaises(ValueError):validate_output('buffett',out,p)

    def test_dedup_normalizes_whitespace_and_keeps_receipts(self):
        seen=set();a=collect([('buffett','buffett','output-1',{'evidence_requests':[request()]})],seen,1)
        b=collect([('buffett','buffett','output-2',{'evidence_requests':[request('  READ the existing  issuer exposure  ')]})],seen,2)
        self.assertEqual(a[0]['request_id'],b[0]['request_id']);self.assertEqual(b[0]['status'],'duplicate')

    def test_reopened_supplier_uses_released_pool_without_restoring_capacity(self):
        from test_research_budget import fact,DAY
        from mara.research_budget import allocate,TOTAL
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('fixture'))
            iid=s.append('agent_input',{'role':'evidence','payload':{}},DAY,'run')
            s.append('agent_validation',{'role':'evidence','status':'accepted','input_id':iid},DAY,'run')
            parts,receipt=allocate(s,'run',DAY,[],'evidence',fact('one',1000),True)
            self.assertIsNone(parts)
            s.append('evidence_feedback_dispatch',{'round':1},DAY,'run')
            parts,receipt=allocate(s,'run',DAY,[],'evidence',fact('one',100000),True)
            self.assertEqual(parts,{'general':80000,'role_reserved':0,'borrowed':20000})
            rows=[{'role':'evidence','fact':fact('one',100000),'budget_allocation':parts}]
            parts,receipt=allocate(s,'run',DAY,rows,'evidence',fact('two',30000),True)
            self.assertIsNone(parts);self.assertEqual(receipt['available_borrow'],28000)
            s.append('evidence_feedback_return',{},DAY,'run')
            parts,receipt=allocate(s,'run',DAY,rows,'evidence',fact('two',1000),True)
            self.assertIsNone(parts);self.assertEqual(receipt['blocked_reason'],'research_role_already_closed')
            self.assertEqual(receipt['run_limit'],TOTAL);db.close()
