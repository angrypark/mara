import copy,json,unittest
from pathlib import Path
from mara.judgment_reports import validate_report,body_length,VERSION
from mara.agents import validate_output
from mara.onboarding import proposal_amount,inputs
from mara.decision import household,semantics
from mara.analysis_pack import build
from mara.domain import profile,valuation
from mara.reporting import present
from mara.workbench import project
from narrative_fixture import narrative
import test_onboarding_risk as setup_fixture

class NarrativeTests(unittest.TestCase):
 def setUp(self):
  self.payload={'as_of':'2026-11-16','market':{'facts':[{'id':'f1'}]},'narrative_contract':VERSION}
  self.report=narrative(self.payload)
 def test_length_structure_date_references_and_legacy_boundary(self):
  validate_report({'judgment_report':self.report},self.payload)
  for edit in [lambda r:r.update(conclusion='짧음'),lambda r:r.update(conclusion=' '*300),lambda r:r.update(as_of='2026-11-15'),lambda r:r.update(evidence_ids=['invented']),lambda r:r.update(conclusion=r['decision_method'])]:
   changed=copy.deepcopy(self.report);edit(changed)
   with self.assertRaisesRegex(ValueError,'Judgment report:'):validate_report({'judgment_report':changed},self.payload)
  with self.assertRaises(ValueError):validate_report({},self.payload)
  validate_output('context',{'summary':'old','constraints':[],'missing':[]},{'as_of':'2026-11-15'})
 def test_spaces_and_titles_do_not_satisfy_half_page_floor(self):
  r=copy.deepcopy(self.report)
  for i,k in enumerate(('portfolio_context','market_context','decision_method','conclusion')):r[k]=str(i)*260+' '*500
  self.assertLess(body_length(r),1400)
  with self.assertRaisesRegex(ValueError,'1400'):validate_report({'judgment_report':r},self.payload)
 def test_salary_sleeve_not_enlarged_by_existing_assets(self):
  self.assertEqual(proposal_amount(100,1000,'additional','future_income'),100)
  self.assertEqual(proposal_amount(100,100000,'total','future_income'),100)
  self.assertEqual(proposal_amount(100,1000,'additional','current_assets'),1100)
  self.assertEqual(proposal_amount(100,1000,'total','current_assets'),100)

class DetailedFlowTests(unittest.TestCase):
 setUp=setup_fixture.SetupTests.setUp
 tearDown=setup_fixture.SetupTests.tearDown
 def test_narratives_reach_review_and_print_with_funding_separation(self):
  self.value.update(funding_source='future_income',capital_mode='additional',reported_liquid_cash=9000000,contribution_risk_preference='growth',contribution_amount=100000,monthly_income=900000,monthly_expenses=500000)
  r=self.app.generate(self.value,self.snapshot)
  self.assertEqual(r['funding']['proposal_capital'],self.value['capital_amount'])
  with self.app.session() as s:
   p=s.get(r['profile_id'])['body'];a=s.get(r['actual_id'])['body']
   self.assertEqual(a['cash'],self.value['cash_krw']);self.assertEqual(household(p)['reported_liquid_cash'],9000000)
   self.assertEqual(p['max_loss_fraction'],self.value['max_loss_fraction']);self.assertEqual(p['max_position_fraction'],self.value['max_position_fraction'])
   calls=[e['body'] for e in s.events('agent_input') if e['run_id']==r['run_id']]
   for role in ('validation','leader'):
    for call in [c for c in calls if c['role']==role]:
     self.assertEqual(call['payload']['decision_context']['contribution_mandate']['preference'],'growth')
     self.assertTrue(all(v.get('judgment_report') for v in call['payload']['perspectives'].values()))
   row=s.get(r['event_id']);before=copy.deepcopy(row)
   shown=present(s,row)['view'];self.assertGreaterEqual(len(shown['judgment_reports']),8)
   stages=[x['stage'] for x in shown['judgment_reports'] if x['role']=='validation']
   self.assertEqual(stages,['perspective_validation','final_validation'])
   self.assertTrue(all(body_length(x['report'])>=1400 for x in shown['judgment_reports']))
   workbench=project(s,r['run_id'])
   for component in workbench['components']:
    if component['output'] and component['output'].get('judgment_report'):
     self.assertTrue(set(component['output']['judgment_report']['evidence_ids'])<=set(component['source_ids']))
   for step in workbench['extensions']['flow']:
    snap=step.get('snapshot')
    if snap and snap.get('output',{}):self.assertTrue(set(snap['output'].get('judgment_report',{}).get('evidence_ids',[]))<=set(snap['source_ids']))
   self.assertEqual(row,before)
   self.assertFalse(s.events('broker_order'))
