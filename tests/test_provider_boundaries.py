import copy,json,unittest
from types import SimpleNamespace
from mara.codex_model import ProviderSubmissionError
from mara.company_research import research_loop
from mara.editorial import create
import test_system as fixtures
import test_editorial as editorial_fixtures

class RemainingProviderBoundaryTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 def test_planner_preserves_unattested_output_and_uses_existing_single_repair(self):
  report=self.e.run('2026-11-14',self.mid)
  source=next(x for x in self.s.events('agent_input') if x['body']['role']=='evidence')
  class Model:
   mode='live';identity={'test':'planner'};n=0
   def complete(inner,role,guide,p,c):
    inner.n+=1;out={'calls':[],'reason':'Synthetic source complete','stop_reason':'evidence_sufficient'}
    if inner.n==1:raise ProviderSubmissionError('completion_unverified',json.dumps({'result_json':json.dumps(out)}))
    assert p.get('planning_feedback')
    return out
  model=Model();result=research_loop(self.s,model,'evidence','guide',copy.deepcopy(source['body']['payload']),'planner-test','2026-11-14',SimpleNamespace(today='2026-11-14'))
  self.assertEqual(model.n,2);self.assertEqual(result['research_access']['planning_repairs'],1)
  self.assertTrue(self.s.events('research_plan_output')[-2]['body']['raw_provider_response'])
  self.assertEqual(len([x for x in self.s.events('research_plan_accepted') if x['run_id']=='planner-test']),1)
 def test_reader_preserves_unattested_output_and_frozen_proposal(self):
  f=SimpleNamespace();editorial_fixtures.EditorialTests.setUp(f);before=copy.deepcopy(f.report);f.report['run_id']='editor-test'
  class Model:
   mode='live';identity={'test':'editor'};n=0
   def complete(inner,role,guide,p,c):
    inner.n+=1
    if inner.n==1:raise ProviderSubmissionError('trace_json',json.dumps({'result_json':json.dumps(f.brief)}))
    assert p.get('repair');return copy.deepcopy(f.brief)
  model=Model();result=create(self.s,model,f.report,f.facts)
  self.assertEqual(model.n,2);self.assertEqual(result['brief'],f.brief)
  self.assertEqual(f.report['proposal'],before['proposal'])
  self.assertEqual([e['body']['status'] for e in self.s.events('report_editor_validation')],['rejected','accepted'])
  self.assertTrue(self.s.events('report_editor_output')[0]['body']['raw_provider_response'])
