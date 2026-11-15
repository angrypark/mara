import copy
import tempfile
import unittest
from pathlib import Path
from mara import domain as d
from mara.agents import DemoModel
from mara.engine import Engine
from mara.store import Store
from test_decision import profile,market


class ContextBudgetTests(unittest.TestCase):
    def test_three_weeks_with_full_supplemental_evidence_preserve_reasoning(self):
        sizes=[]
        class Model(DemoModel):
            def complete(self,role,guide,p,contract):
                sizes.append((role,len(d.dumps(p))))
                if p.get('previous'):
                    self_check=p['previous']['projection']
                    assert self_check['source_event_id']
                    if role in ('validation','leader','reflection'):
                        assert set(p['previous']['perspectives'])=={'buffett','marks','bogle'}
                        assert all('critical countercase' in x['falsifiers'] for x in p['previous']['perspectives'].values())
                out=super().complete(role,guide,p,contract)
                if role in ('buffett','marks','bogle','leader'):out['weights']={'FUND':.4,'CASH':.6}
                if role in ('buffett','marks','bogle'):out['falsifiers']=['critical countercase']
                if role=='leader':out['action']='adjust'
                fields={'context':('summary','constraints'),'evidence':('summary','drivers'),
                    'buffett':('thesis','decision_basis'),'marks':('thesis','decision_basis'),'bogle':('thesis','decision_basis'),
                    'validation':('reason','issues'),'leader':('rationale','dissent'),
                    'reflection':('investment_outcome','lessons'),'memory':('summary','conflicts')}
                first,second=fields[role];out[first]='SYNTHETIC '+('x'*14900)
                out[second]=['Synthetic boundary '+('y'*max(0,23800-len(d.dumps(out))-100))]
                assert 23000<len(d.dumps(out))<24000
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));engine=Engine(s,Model())
            # Initial 64k plus the full 80k supplemental tool allowance. This
            # tests delivery, not acquisition: every synthetic fact is retained.
            p=profile();m=market();remaining=144000-sum(len(f['text']) for f in m['facts'])
            for i in range(10):
                size=remaining//(10-i);remaining-=size
                m['facts'].append(dict(m['facts'][0],id='research-fixture-'+str(i),text='x'*size,research_tool='candles'))
            m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{'max_fact_characters':64000},'collected_at':'2026-11-15T12:00:00+00:00','calls':[]}
            engine.set_profile(p,m['as_of'])
            for date in ('2026-11-15','2026-11-22','2026-11-29'):
                current=copy.deepcopy(m);current['as_of']=date
                for q in current['prices'].values():q.update(observed_at=date,known_at=date)
                engine.set_holdings({'as_of':date,'base_currency':'USD','cash':0,'positions':{},'rationale':'Synthetic','last_rebalanced':'2026-11-15'})
                result=engine.run(date,db.publish_market(current));self.assertEqual(result['proposal']['eligibility'],'review_now' if date=='2026-11-15' else 'review_at_rebalance')
            self.assertEqual(len(s.events('completed')),3)
            self.assertTrue(all(len(d.dumps(x['body']['payload']))<=x['body']['payload']['input_budget']['max_characters'] for x in s.events('agent_input')))
            self.assertTrue(all(len(x['body']['perspectives']['buffett']['thesis'])>14000 for x in s.events('completed')))
            db.close()

    def test_improvement_parent_is_not_confused_with_previous_week(self):
        from mara.context_budget import improvement_for_role
        parent={'proposal':{'rationale':'current parent','risks':['countercase'],'investment_case':{'large':'detail'}},'perspectives':{'buffett':{'thesis':'own original'},'bogle':{'thesis':'peer'}}}
        improvement={'parent_completed_id':'parent','previous_proposal':parent['proposal'],'feedback':{'missing':'evidence'}}
        for role in ('context','evidence','buffett','marks'):
            out=improvement_for_role(improvement,role,parent)
            self.assertEqual(out['parent_judgment']['proposal']['rationale'],'current parent')
            self.assertEqual(out['parent_judgment']['source_event_id'],'parent')
            self.assertEqual(out['parent_judgment']['perspectives'],{'buffett':{'thesis':'own original'}} if role=='buffett' else {})
            self.assertEqual(out['feedback'],improvement['feedback'])
        self.assertIn('investment_case',improvement['previous_proposal'])
