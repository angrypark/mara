import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mara.earnings_bridge import normalize,bind_valuation,observations
from mara.company_research import CompanyLibrary,ResearchTools,owner_value,research_loop
from mara.store import Store
from mara.contracts import schema,validate
from mara.thesis_workspace import build
from test_valuation_cases import inputs,expanded,DAY


def fixture():
    a,m=inputs();v=json.loads(m['facts'][1]['text'])
    row=copy.deepcopy(v['metrics']['operating_cashflow'][0]['observations'][0]);row['value']=10
    v['metrics']['diluted_shares']=[dict(unit='shares',tag='WeightedAverageNumberOfDilutedSharesOutstanding',observations=[row])]
    m['facts'][1]['text']=json.dumps(v)
    def ref(metric):return {'fact_id':'fin','path':'/metrics/'+metric+'/0/observations/0'}
    cases={name:dict(shares=ref('diluted_shares'),components=[dict(label='cashflow',observation=ref('operating_cashflow'),multiplier=mult,reason='Synthetic recurring portion assumption'),dict(label='capex',observation=ref('capital_expenditure'),multiplier=-1,reason='Synthetic all capex deduction')],explanation='Synthetic arithmetic, not a company estimate',reinvestment='Explicit capex subtraction',dilution='Average diluted shares; economic adequacy unverified',falsifier='Change the retained cashflow share when filings contradict it') for name,mult in [('bear',.5),('base',1),('bull',1.2)]}
    args=dict(symbol='TEST',quote_fact_id='quote',period_start='2025-01-01',period_end='2025-12-31',share_basis='Synthetic annual diluted unchanged split basis',cases=cases)
    return args,a,m


class ThesisEnvironmentTests(unittest.TestCase):
    def test_observation_arithmetic_and_negative_cases_are_preserved(self):
        args,a,m=fixture();before=copy.deepcopy(m);out=normalize(args,m,DAY)
        self.assertAlmostEqual(out['cases']['base']['owner_earnings_per_share'],2.7)
        self.assertAlmostEqual(out['cases']['bear']['owner_earnings_per_share'],.95)
        self.assertEqual(m,before)
        args['cases']['bear']['components'][0]['multiplier']=0
        out=normalize(args,m,DAY);self.assertEqual(out['cases']['bear']['owner_earnings_per_share'],-.8)
        self.assertFalse(out['cases']['bear']['positive_earnings_model_applicable'])

    def test_mixed_units_periods_unknown_paths_duplicates_and_future_data_rejected(self):
        args,a,m=fixture()
        mutations=[lambda b:b['cases']['base']['shares'].update(path='/metrics/assets/0/observations/0'),
            lambda b:b['cases']['base']['components'][0]['observation'].update(path='/unknown'),
            lambda b:b['cases']['base']['components'].append(copy.deepcopy(b['cases']['base']['components'][0])),
            lambda b:b.update(period_end='2025-09-30'),lambda b:b['cases']['base']['components'][0].update(multiplier=True),
            lambda b:b['cases']['base'].update(falsifier='')]
        for mutate in mutations:
            b=copy.deepcopy(args);mutate(b)
            with self.assertRaises(ValueError):normalize(b,m,DAY)
        for field,value in [('known_at','2027-01-01'),('valid_until','2020-01-01')]:
            b=copy.deepcopy(m);b['facts'][1][field]=value
            with self.assertRaises(ValueError):normalize(args,b,DAY)
        b=copy.deepcopy(m);b['facts'][1]['company_identity']['symbol']='OTHER'
        with self.assertRaises(ValueError):normalize(args,b,DAY)

    def test_bridge_to_valuation_recomputes_source_versions_and_reverse_price(self):
        args,a,m=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('fixture'));tool=ResearchTools(CompanyLibrary(Path(tmp)/'library',today=DAY),s,'run',DAY)
            out=tool.execute('buffett',{'tool':'normalize_earnings','arguments':args},m)
            a=expanded(a);a['share_basis']=args['share_basis'];a['owner_earnings_per_share']=2.7
            for name,row in a['earnings_cases'].items():row['owner_earnings_per_share']=out['result']['cases'][name]['owner_earnings_per_share']
            call={'tool':'valuation','arguments':dict(symbol='TEST',assumptions=a,normalization_fact_id=out['fact_id'])}
            result=tool.execute('buffett',call,m)['result']
            self.assertEqual(result['normalization_binding']['status'],'arithmetic_bound_economic_judgment_unverified')
            from mara.fact_catalog import snapshots
            nodes,issues=snapshots(m['facts'],DAY)
            self.assertEqual(issues,[])
            derived=[n for n in nodes if n['fact_id'] in (out['fact_id'],m['facts'][-1]['id'])]
            self.assertTrue(all(n['derivation_status']=='bound_parent_snapshots' and n['epistemic_scope']=='analyst_assumptions_and_calculation' for n in derived))
            self.assertIn(out['fact_id'],[p['fact_id'] for p in derived[-1]['parents']])
            from mara.research import project_fact
            projected=copy.deepcopy(m);projected['facts']=[project_fact(f,'validation') for f in m['facts']]
            self.assertEqual(bind_valuation(out['fact_id'],a,projected,'TEST',DAY)['status'],'arithmetic_bound_economic_judgment_unverified')
            for row in result['scenarios']:
                changed=copy.deepcopy(a);changed.pop('earnings_cases');changed['owner_earnings_per_share']=row['price_implied_annual_earnings_per_share']
                rerun=owner_value(changed,{'fin','quote'},DAY)
                self.assertAlmostEqual(next(x for x in rerun['scenarios'] if x['name']==row['name'])['value_per_share'],a['price'])
            a['earnings_cases']['bear']['owner_earnings_per_share']+=1
            with self.assertRaises(ValueError):bind_valuation(out['fact_id'],a,m,'TEST',DAY)
            a['earnings_cases']['bear']['owner_earnings_per_share']-=1
            v=json.loads(m['facts'][1]['text']);v['metrics']['operating_cashflow'][0]['observations'][0]['value']=36;m['facts'][1]['text']=json.dumps(v)
            with self.assertRaises(ValueError):bind_valuation(out['fact_id'],a,m,'TEST',DAY)
            db.close()

    def test_plan_contract_and_actual_research_loop_deliver_workspace_and_bridge(self):
        args,a,m=fixture();m['assets']={'TEST':{'kind':'STOCK'},'ETF':{'kind':'ETF'}}
        payload={'as_of':DAY,'market':m,'profile':{'goal':'fixture'},'decision_scope':{'questions':[dict(id='candidate-TEST',target='TEST',owner='buffett'),dict(id='candidate-ETF',target='ETF',owner='bogle')]},'previous':{'question_followups':[{'id':'candidate-TEST','review':{'status':'unresolved','next_action':'Read the note'}}]}}
        workspace=build(payload,'buffett')
        self.assertEqual(workspace['candidates'][0]['state'],'requires_analysis_review')
        self.assertTrue(workspace['candidates'][0]['observation_locators'])
        self.assertEqual(len(workspace['candidates'][1]['tasks']),2)
        self.assertEqual(workspace['candidates'][0]['prior_review']['status'],'unresolved')
        stale=copy.deepcopy(payload);stale['market']['facts'][1]['valid_until']='2020-01-01'
        self.assertEqual(build(stale,'buffett')['candidates'][0]['observation_locators'],[])
        class Model:
            mode='live';identity={'provider':'synthetic'};count=0
            def complete(self,role,guide,p,contract):
                assert p['thesis_workspace']['candidates'][0]['question_id']=='candidate-TEST'
                self.count+=1
                if self.count==1:return dict(reason='Normalize explicitly',calls=[dict(tool='normalize_earnings',arguments=args,question_ids=['candidate-TEST'])])
                return dict(reason='Arithmetic is not sufficiency',calls=[],stop_reason='low_information_value')
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('fixture'))
            out=research_loop(s,Model(),'buffett','fixture',payload,'run',DAY,CompanyLibrary(Path(tmp)/'library',today=DAY))
            self.assertTrue(any(f.get('research_tool')=='company_normalize_earnings' for f in out['market']['facts']))
            self.assertEqual(len(s.events('research_plan_input')),2)
            self.assertEqual(s.events('research_activity')[0]['body']['question_ids'],['candidate-TEST'])
            db.close()

    def test_new_alternative_is_calculated_and_read_before_final_validation(self):
        from mara.agents import DemoModel
        from mara.engine import Engine
        from test_decision import profile,market
        seen=[]
        class Model(DemoModel):
            def complete(self,role,guide,p,contract):
                out=super().complete(role,guide,p,contract)
                if role in ('buffett','leader','validation'):
                    assert p['thesis_workspace']['completion_rule']
                if role=='leader':
                    if p['analysis'].get('alternative_comparisons'):
                        seen.append('leader_read');assert p['analysis']['alternative_comparisons']['0']['weights']=={'FUND':.1,'CASH':.9}
                    out['investment_case']={'key_points':['synthetic']*3, 'claims':[dict(id='c'+str(i),requirement_id=contract['properties']['investment_case']['properties']['claims']['items']['properties']['requirement_id']['enum'][i],importance='Synthetic necessary condition',statement='Synthetic unresolved premise',status='unresolved',assumptions=['Synthetic only'],counterevidence='Unresolved evidence',decision_impact='Do not infer superiority',fact_ids=[],calculation_paths=[]) for i in range(12)],
                        'alternatives':[dict(name='Small alternative',weights={'FUND':.1,'CASH':.9},decision='diagnostic_only',reason='Test a real author-supplied alternative',change_condition='Unresolved value premise',comparison_path='/analysis/alternative_comparisons/'+str(i)) for i in range(3)],
                        'monitoring':[dict(variable='Premise',condition='Changed fact',check_at='Next review',owner='leader',action='Reconsider',counterexample_test='Adverse evidence')]*3, 'scope_limits':['synthetic'], 'implementation':['No orders']*3}
                if role=='validation' and p.get('final_proposal'):
                    assert 'leader_read' in seen
                    seen.append('final_read')
                    assert p['analysis']['alternative_comparisons']['0']['capital']==p['funding']['proposal_capital']
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));e=Engine(s,Model())
            p,m=profile(),market();e.set_profile(p,m['as_of']);e.set_holdings({'as_of':m['as_of'],'base_currency':'USD','cash':100,'positions':{},'rationale':'Synthetic','last_rebalanced':m['as_of']})
            result=e.run(m['as_of'],db.publish_market(m));validate(result['analysis'],schema('analysis'))
            self.assertEqual(seen,['leader_read','final_read'])
            self.assertFalse(result['analysis']['alternative_comparisons']['0']['historical_performance']['available'])
            db.close()

    def test_productive_asset_purchases_remain_a_distinct_observation(self):
        from test_research import financial,observation
        from mara.research_sources import sec_financials
        from mara.company_research import quality
        raw=financial();raw['facts']['us-gaap'].pop('PaymentsToAcquirePropertyPlantAndEquipment')
        raw['facts']['us-gaap']['PaymentsToAcquireProductiveAssets']={'units':{'USD':[observation(12)]}}
        parsed=sec_financials(raw,DAY)
        self.assertIn('productive_asset_purchases',parsed['metrics'])
        self.assertNotIn('capital_expenditure',parsed['metrics'])
        self.assertIsNone(quality(parsed)['annual_comparison'][0]['fcf_proxy_usd'])

    def test_valuation_plan_requires_array_before_dispatch(self):
        a,m=inputs();a['scenarios']={r['name']:{k:v for k,v in r.items() if k!='name'} for r in a['scenarios']}
        with self.assertRaises(ValueError):owner_value(a,{'quote','fin'},DAY)
        with self.assertRaises(ValueError):validate({'reason':'shape check','calls':[{'tool':'valuation','arguments':{'symbol':'TEST','assumptions':a},'question_ids':['candidate-TEST']}]},schema('research-plan'))
