import copy,json,tempfile,unittest
from pathlib import Path
from mara.engine import Engine
from mara.agents import DemoModel,Agents
from mara.store import Store,Session,SHARED
from mara.knowledge import Knowledge
from mara.history import scope,latest
from mara.analysis_pack import build
from mara.contracts import validate,schema
from test_analysis_pack import fixture

ROOT=Path(__file__).resolve().parent.parent
class FreshHistoryTests(unittest.TestCase):
    def test_reset_is_non_destructive_and_scopes_all_inputs_then_weekly_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));other=db.session(db.create_user('other'));e=Engine(s,DemoModel())
            p=json.loads((ROOT/'examples/profile.json').read_text());h=json.loads((ROOT/'examples/holdings.json').read_text());m=json.loads((ROOT/'examples/market.json').read_text());date=m['as_of']
            p['context_note_history']=[{'text':'OLD_AGENT_SENTINEL'}];p['clarification_answers']=[{'question':{'reason':'OLD_AGENT_SENTINEL'}}]
            e.set_profile(p,date);e.set_holdings(h);mid=db.publish_market(m);first=e.run(date,mid)
            s.append('guide',{'role':'buffett','text':'OLD_AGENT_SENTINEL'},date)
            op={'action':'add','reason':'synthetic','text':'OLD_AGENT_SENTINEL','topic':'x','condition':'x','perspective':'all','category':'lesson','roles':['*'],'refs':[mid],'valid_until':None,'priority':5}
            Knowledge(s).apply(op,date);shared=Session(db,SHARED);Knowledge(shared).apply(op,date)
            originals=s.export()['events'];actual=s.latest('actual')['id'];reset=e.reset_history(date,'User requests fresh analysis')
            # Delayed result from an old run cannot re-enter through shared memory.
            Knowledge(shared).apply(op,date,first['run_id'])
            current=e.run(date,mid,force=True)
            self.assertIsNone(current['previous_id']);self.assertIsNone(current['reflection']);self.assertEqual(current['history_scope']['reset_id'],reset)
            self.assertEqual(actual,s.latest('actual')['id']);self.assertEqual(originals,s.export()['events'][:len(originals)])
            for row in s.events('agent_input'):
                if row['run_id']==current['run_id']:
                    self.assertNotIn('OLD_AGENT_SENTINEL',json.dumps(row['body']))
                    if 'profile' in row['body']['payload']:self.assertEqual(row['body']['payload']['profile']['goal'],p['goal'])
            self.assertIsNone(scope(other)['reset_id']);self.assertEqual(len(s.events('completed')),2)
            with self.assertRaises(ValueError):e.run(date,mid,force=True,amendment={'completed_id':first['event_id']})
            m=copy.deepcopy(m);m['as_of']='2026-11-21'
            for q in m['prices'].values():q.update(observed_at=m['as_of'],known_at=m['as_of'])
            next_run=e.run(m['as_of'],db.publish_market(m),force=True)
            self.assertEqual(next_run['previous_id'],current['event_id']);self.assertEqual(next_run['history_scope'],current['history_scope'])
            db.close()

    def test_reset_rejects_running_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));s.lock('running')
            with self.assertRaises(RuntimeError):Engine(s,DemoModel()).reset_history('2026-11-17','fresh')
            self.assertFalse(s.events('history_reset'));s.unlock('running');db.close()

class SleeveTests(unittest.TestCase):
    def test_two_denominators_and_usd_cash_fx(self):
        p,m,a,v=fixture();p['base_currency']='KRW';p['contribution_schedule']='monthly';p['contribution_amount']=300;p['usd_buffer_reference_fraction']=1/3
        m['assets']['USD_CASH']={'asset_class':'cash','currency':'USD','market':'US','stress_loss':.2};m['prices']['USD_CASH']=dict(m['prices']['ITOT'])
        r=build(p,a,m,v,300,{'ITOT':2/3,'USD_CASH':1/3});x=r['allocation_sleeves'];validate(r,schema('analysis'))
        self.assertEqual(x['invested_weights'],{'ITOT':1});self.assertAlmostEqual(sum(t['monthly_amount'] for t in x['rows']),300)
        self.assertAlmostEqual(r['fx_stress']['scenarios'][5]['portfolio_change_fraction'],-7/15)
        self.assertAlmostEqual(r['costs']['monthly_non_cash_allocation'],200)
        cash=build(p,a,m,v,300,{'USD_CASH':1})['allocation_sleeves'];self.assertEqual(cash['invested_weights'],{});self.assertEqual(cash['invested_fraction'],0)

    def test_no_initial_allocation_or_false_proposal_backtest(self):
        p,m,a,v=fixture();r=build(p,a,m,v,1000)
        self.assertEqual(r['selected_weights'],{});self.assertEqual(r['allocation_sleeves']['status'],'decision_pending')
        self.assertNotIn('proposal',r['comparison']['results']);validate(r,schema('analysis'))

class ResearchReserveTests(unittest.TestCase):
    def test_later_role_can_read_prerequisites_filing_and_value_after_shared_pool_full(self):
        from mara.company_research import ResearchTools
        from mara.domain import dumps
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));runner=ResearchTools(None,s,'run','2026-11-17');m={'facts':[]}
            def fact(id,tool,size):return {'id':id,'research_tool':tool,'text':'x'*size}
            for i in range(6):self.assertTrue(runner.activate('evidence',fact(str(i),'company_compare',12500),m))
            self.assertFalse(runner.activate('wood',fact('general-over','company_compare',8000),m))
            for i,tool in enumerate(['sec_financials','sec_filings','company_company','company_filing_search','company_valuation']):
                self.assertTrue(runner.activate('wood',fact('wood-'+str(i),tool,8000),m))
            before=len(s.events('research_evidence'))
            self.assertTrue(runner.activate('wood',fact('wood-4','company_valuation',8000),m));self.assertEqual(len(s.events('research_evidence')),before)
            self.assertFalse(runner.activate('wood',fact('over','company_filing_search',16000),m))
            self.assertTrue(runner.activate('validation',fact('validation','company_filing_search',24000),m))
            again=ResearchTools(None,s,'run','2026-11-17')
            self.assertFalse(again.activate('validation',fact('second-stage','company_filing_search',25000),m))
            self.assertEqual(again.activation_budget['role_reserved_limit'],48000)
            self.assertLessEqual(sum(len(dumps(e['body']['fact'])) for e in s.events('research_evidence')),368000)
            baseline={'id':'already-market','text':'y'*90000};m['facts'].append(baseline)
            self.assertTrue(again.activate('wood',baseline,m));db.close()

    def test_maximum_research_and_four_large_views_fit_leader_repair_envelope(self):
        from mara.agents import Agents
        from mara.context_budget import LIMITS
        from mara.domain import dumps
        from test_decision import profile,market
        class Repair(DemoModel):
            def __init__(self):self.calls=0
            def complete(self,role,guide,p,contract):
                self.calls+=1
                self.assert_size=len(dumps(p))
                return {'bad':'x'*37000} if self.calls==1 else super().complete(role,guide,p,contract)
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));m=market();p=profile()
            m['facts'].append(dict(m['facts'][0],id='max-reserve',text='x'*432000))
            m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{},'collected_at':m['as_of'],'calls':[]}
            views={role:{'weights':{'CASH':1},'thesis':'x'*38000} for role in ('buffett','marks','bogle','wood')}
            model=Repair();payload={'market':m,'profile':p,'valuation':{'nav':1000,'weights':{'CASH':1},'values':{'CASH':1000}},'actual':{'cash':1000},
                'funding':{'proposal_capital':1000},'perspectives':views,'previous':{'perspectives':views,'proposal':{'rationale':'x'*38000},'reflection':{'process':'x'*38000},'market':{'text':'x'*8000}}}
            Agents(s,model,m['as_of'],'synthetic').call('leader',payload)
            self.assertEqual(model.calls,2);self.assertLessEqual(model.assert_size,LIMITS['leader']);db.close()
