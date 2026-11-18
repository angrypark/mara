import copy
import json
import tempfile
import unittest
from pathlib import Path
from mara.agents import DemoModel
from narrative_fixture import ReportingDemoModel
from mara.engine import Engine
from mara.final_report import assemble,verified
from mara.reporting import present
from mara.store import Store

ROOT=Path(__file__).resolve().parent.parent
DAY='2026-11-14'


class FinalReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Store(Path(self.tmp.name)/'db')
        self.s=self.db.session(self.db.create_user('synthetic-reader'));self.engine=Engine(self.s,ReportingDemoModel())
        self.profile=json.loads((ROOT/'examples/profile.json').read_text());self.holdings=json.loads((ROOT/'examples/holdings.json').read_text());self.market=json.loads((ROOT/'examples/market.json').read_text())
        self.engine.set_profile(self.profile,DAY);self.engine.set_holdings(self.holdings)
        self.result=self.engine.run(DAY,self.db.publish_market(self.market));self.row=self.s.get(self.result['event_id'])
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def full_document(self):
        r=copy.deepcopy(self.row['body']);p=r['proposal'];weights=p['weights'];r['analysis']['reader_comparison']={'weights':weights}
        p['investment_case']={'key_points':['Conditional synthetic judgment'],
            'claims':[{'id':'source-claim','statement':'Conditional test claim','status':'supported','assumptions':['Only if the premise holds'],
                       'counterevidence':'Important opposing observation','decision_impact':'Keep the plan deferred','fact_ids':['demo-1'],
                       'calculation_paths':['/analysis/reader_comparison']}],
            'alternatives':[{'name':'synthetic alternative','weights':weights,'decision':'diagnostic_only','reason':'Same denominator comparison',
                             'change_condition':'Only after the premise changes','comparison_path':'/analysis/reader_comparison'}],
            'monitoring':[{'variable':'Premise','condition':'Changed observed fact','check_at':'Next review','owner':'leader','action':'Reconsider','counterexample_test':'Search adverse evidence'}],
            'scope_limits':['Synthetic fixture only'],'implementation':['No order authority']}
        return r,assemble(r,self.market['facts'])

    def test_engine_stores_document_after_final_state_and_early_market_is_not_final_change(self):
        r=self.row['body'];self.assertEqual(r['proposal']['market_changes'],[])
        self.assertEqual(r['market_observations']['stage'],'evidence')
        doc=r['final_report'];self.assertTrue(verified(doc,r,self.market['facts']))
        self.assertEqual(doc['decision']['action'],r['proposal']['action'])
        self.assertEqual(doc['decision']['decision_status'],r['proposal']['decision_status'])
        shown=present(self.s,self.row);self.assertEqual(shown['view']['final_report_status'],'stored_verified')
        self.assertEqual(shown['body'],r);self.assertEqual(self.s.get(self.row['id']),self.row)

    def test_deterministic_hash_and_blocked_final_state_do_not_approve_leader_claim(self):
        r,doc=self.full_document();r['proposal']['action']='defer';r['proposal']['decision_status']['status']='blocked';r['validation']['final_critique']['qualitative_pass']=False
        doc=assemble(r,self.market['facts']);self.assertEqual(doc,assemble(r,list(reversed(self.market['facts']))))
        self.assertEqual(doc['decision']['action'],'defer');self.assertFalse(doc['reasons']['claims'][0]['final_review_pass'])
        self.assertEqual(doc['reasons']['claims'][0]['status_scope'],'leader_judgment')
        self.assertEqual(doc['reasons']['claims'][0]['claim']['status'],'supported')
        self.assertEqual(len(doc['open_issues']['questions']),len(r['decision_scope']['questions']))
        self.assertTrue(verified(doc,r,self.market['facts']))
        changed=copy.deepcopy(doc);changed['decision']['action']='adjust';self.assertFalse(verified(changed,r,self.market['facts']))
        r['proposal']['weights']['CASH']+=.01;self.assertFalse(verified(doc,r,self.market['facts']))

    def test_missing_sources_calculations_and_amount_mismatch_remain_visible(self):
        r,_=self.full_document();r['proposal']['investment_case']['claims'][0]['fact_ids']=['missing']
        r['proposal']['investment_case']['claims'][0]['calculation_paths']=['/analysis/does-not-exist']
        r['proposal']['monthly_allocation']['amounts']['CASH']+=1
        doc=assemble(r,self.market['facts']);codes={i['code'] for i in doc['assembly_issues']}
        self.assertTrue({'missing_cited_fact','missing_calculation','monthly_amount_mismatch'}<=codes)
        self.assertEqual(doc['assembly_status'],'incomplete');self.assertEqual(doc['references']['facts'][0]['fact_id'],'missing')

    def test_r4_only_counterevidence_is_printable_and_self_consistent_bad_shape_rejected(self):
        from mara.final_report import digest
        r,_=self.full_document();opposing=dict(self.market['facts'][0],id='r4-only',topic='Independent opposing observation')
        r['validation']['final_critique']['judgment_report']={'evidence_ids':['r4-only']}
        doc=assemble(r,self.market['facts']+[opposing]);self.assertIn('r4-only',{f['fact_id'] for f in doc['references']['facts']})
        bad=copy.deepcopy(doc);bad.pop('allocation');bad['provenance'].pop('document_sha256');bad['provenance']['document_sha256']=digest(bad)
        self.assertFalse(verified(bad,r,self.market['facts']+[opposing]))
        bad=copy.deepcopy(doc);bad['decision']['action']='adjust' if r['proposal']['action']!='adjust' else 'defer'
        bad['provenance'].pop('document_sha256');bad['provenance']['document_sha256']=digest(bad)
        self.assertFalse(verified(bad,r,self.market['facts']+[opposing]))

    def test_old_unsupported_or_tampered_documents_use_explicit_projection_without_mutation(self):
        for how in ('old','unknown','tampered','null_provenance','list_provenance','string_provenance'):
            body=copy.deepcopy(self.row['body'])
            if how=='old':body.pop('final_report')
            elif how=='unknown':body['final_report']['schema_version']='mara.final-report/999'
            elif how.endswith('_provenance'):body['final_report']['provenance']={'null_provenance':None,'list_provenance':[],'string_provenance':'broken'}[how]
            else:body['final_report']['decision']['action']='adjust' if body['proposal']['action']!='adjust' else 'defer'
            eid=self.s.append('completed',body,DAY,body['run_id']);original=self.s.get(eid);shown=present(self.s,original)
            self.assertEqual(shown['body'],body);self.assertEqual(self.s.get(eid),original)
            self.assertEqual(shown['view']['final_report_status'],'display_projection' if how=='old' else 'invalid_saved_document_projection')
            if how!='old':self.assertIn('saved_document_unverified',{i['code'] for i in shown['view']['final_report']['assembly_issues']})

    def test_role_rewrite_history_preserves_both_accepted_outputs_and_feedback(self):
        before=present(self.s,self.row);old=next(e for e in self.s.events('agent_output') if e['body']['role']=='leader')
        first=copy.deepcopy(old['body']);first['output']['judgment_report']={'title':'Synthetic first opinion','as_of':DAY,
            'portfolio_context':'Synthetic portfolio','market_context':'Synthetic market','decision_method':'Synthetic method',
            'conclusion':'Synthetic opinion','evidence_ids':['demo-1']}
        first_id=self.s.append('agent_output',first,DAY,self.row['run_id'])
        self.s.append('agent_validation',{'role':'leader','input_id':first['input_id'],'output_id':first_id,'status':'accepted'},DAY,self.row['run_id'])
        source=copy.deepcopy(self.s.get(old['body']['input_id'])['body']);source['payload']['output_feedback']={'reason':'Synthetic correction'}
        iid=self.s.append('agent_input',source,DAY,self.row['run_id'])
        new=copy.deepcopy(first);new['input_id']=iid;new['output']['judgment_report']['title']='Synthetic revised opinion'
        oid=self.s.append('agent_output',new,DAY,self.row['run_id'])
        self.s.append('agent_validation',{'role':'leader','input_id':iid,'output_id':oid,'status':'accepted'},DAY,self.row['run_id'])
        eid=self.s.append('completed',copy.deepcopy(self.row['body']),DAY,self.row['run_id'])
        history=present(self.s,self.s.get(eid))['view']['judgment_report_history'];items=[x for x in history if x['role']=='leader']
        old_count=len([x for x in before['view']['judgment_report_history'] if x['role']=='leader'])
        self.assertEqual(len(items),old_count+2);self.assertFalse(items[-2]['latest_accepted_for_stage']);self.assertTrue(items[-1]['latest_accepted_for_stage'])
        self.assertEqual(items[-1]['feedback'],{'reason':'Synthetic correction'})
        self.assertEqual(present(self.s,self.row),before)


if __name__=='__main__':unittest.main()
