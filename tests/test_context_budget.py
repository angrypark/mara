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
    def test_three_weeks_of_near_maximum_role_outputs_preserve_reasoning(self):
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
            p=profile();m=market();remaining=44000-sum(len(f['text']) for f in m['facts'])
            for i in range(10):
                size=remaining//(10-i);remaining-=size
                m['facts'].append(dict(m['facts'][0],id='research-fixture-'+str(i),text='x'*size,research_tool='candles'))
            m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{'max_fact_characters':44000},'collected_at':'2026-11-15T12:00:00+00:00','calls':[]}
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
