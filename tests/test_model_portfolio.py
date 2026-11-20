import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mara.agents import DemoModel
from mara.domain import dumps
from mara.model_exposures import acquire, calculate
from unittest.mock import patch
from mara.model_portfolio import read, request, run
from mara.onboarding import InputError
from mara.registry import personas
from mara.store import Store


class Provider:
    mode = 'live'
    identity = {'provider':'fixture'}

    def __init__(self, reject_final=False):
        self.calls = []
        self.reject_final = reject_final

    def complete(self, role, guide, payload, contract):
        self.calls.append((role, copy.deepcopy(payload)))
        stage = payload['analysis_stage']
        if stage=='leader_mandate':
            return DemoModel().complete(role,guide,payload,contract)
        if role=='context':
            return dict(summary='conditional',conditional_inputs=['horizon'])
        if role=='evidence':
            return dict(summary='issuer observations',evidence_ids=['ITOT'],gaps=['swap risk'])
        if role in personas():
            return dict(weights={'ITOT':1},evidence_ids=['ITOT'],thesis='index',risk='loss',
                        benchmark_comparison='neutral',weight_reason='broad',falsifier='concentration')
        if role=='validation':
            return dict(qualitative_pass=not (stage=='final_validation' and self.reject_final),
                        reason='independent check',issues=[],revision_requests=[])
        if role=='evaluator':
            return dict(summary='quality',limitations=['no performance record'])
        redo = not any(r=='wood' and 'revision_instructions' in p for r,p in self.calls)
        return dict(weights={'ITOT':1},evidence_ids=['ITOT'],rationale='simple',
                    weight_reasons='broad',benchmark_comparison='equal',dissent='tilt',risks='drawdown',
                    rebalance='quarterly',scenarios='short or long horizon',questions=[],
                    revision_requests=[dict(target_role='wood',requested_change='compare costs')] if redo else [])


class ModelPortfolioTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Store(Path(temp.name)/'store.sqlite3')
        self.addCleanup(self.db.close)
        self.s = self.db.session(self.db.create_user('test'))
        self.date = '2026-11-20'
        self.jid = '1'*32
        self.s.append('model_request',{},self.date,self.jid)
        self.funds = {t:dict(annual_fee=.001,sources=[{'source':'https://example.org/fund'}],
                             named_swaps=0.,futures_gross=.01) for t in ['ITOT','IWF']}
        self.positions = {
            'ITOT':{('A','EXAMPLE CLASS A','EX'): (.3,'IT'),('B','EXAMPLE CLASS B','EX'):(.2,'IT')},
            'IWF':{('A','EXAMPLE CLASS A','EX'): (.4,'IT')}}
        self.inputs = dict(preference='risk seeking',objective='foreign diversification')

    def test_regular_handoffs_and_private_history_isolation(self):
        secret = 'prior user record must not be delivered'
        for kind in ('profile','actual','completed','guide','clarification_answer','knowledge'):
            self.s.append(kind,{'marker':secret},self.date)
        model = Provider()
        run(self.s, model, self.jid, self.date, self.inputs,self.funds,self.positions,{})
        report = read(self.s,self.jid)['result']
        self.assertEqual(report['metrics']['weights'], {'ITOT':1})
        self.assertLess([p['analysis_stage'] for _,p in model.calls].index('leader_mandate'),
                        [r for r,_ in model.calls].index('evidence'))
        self.assertTrue(report['final_validation']['qualitative_pass'])
        for _, packet in model.calls:
            if packet['analysis_stage'] in ('final_validation','frozen_quality_review'):
                upstream=self.s.get(packet['validation_output_id'])
                self.assertEqual(upstream['body']['output'],packet['perspective_validation'])
                self.assertEqual(packet['leader_mandate']['output_id'],report['mandate']['output_id'])
        self.assertNotIn(secret,dumps(model.calls))
        self.assertTrue(all('perspectives' not in p for r,p in model.calls if r in personas()))
        self.assertEqual(len(self.s.events('model_revision')),1)
        self.assertEqual(len(self.s.events('actual')),1)
        other = self.db.session(self.db.create_user('other'))
        with self.assertRaises(PermissionError):
            read(other,self.jid)

    def test_confirmed_horizon_and_tolerance_reach_planning_and_final_review(self):
        inputs = dict(self.inputs, minimum_holding_years=7, tolerable_drawdown_fraction=.18)
        model = Provider()
        run(self.s, model, self.jid, self.date, inputs, self.funds, self.positions, {})
        plan = next(packet for _,packet in model.calls if packet['analysis_stage']=='leader_mandate')
        self.assertEqual(plan['user_persona']['body']['confirmed'],inputs)
        budget = plan['decision_context']['risk_budget']
        self.assertEqual(budget['confirmed_tolerance_fraction'],.18)
        self.assertIn('잠정',budget['interpretation'])
        self.assertIn('최소 7년',str(plan['constraint_basis']['constraints']))
        for _,packet in model.calls:
            if packet['analysis_stage']=='leader_mandate':
                continue
            self.assertEqual(packet['confirmed'], inputs)
            self.assertEqual(packet['risk_interpretation'],budget)
            self.assertNotIn('감내 가능한 손실',packet['unknowns'])
        report = read(self.s,self.jid)['result']
        self.assertEqual(report['risk_interpretation'],budget)
        self.assertEqual(report['confirmed'],inputs)

    def test_request_rejects_invalid_optional_inputs(self):
        for key, value in [('minimum_holding_years',False),('minimum_holding_years',0),
                           ('tolerable_drawdown_fraction',float('nan')),('tolerable_drawdown_fraction',1.1),
                           ('tolerable_drawdown_fraction',True)]:
            with self.subTest(key=key,value=value), self.assertRaises(InputError):
                request(None,dict(self.inputs,request_id=self.jid,**{key:value}))

    def test_failed_final_review_cannot_publish(self):
        run(self.s, Provider(reject_final=True), self.jid, self.date, self.inputs,self.funds,self.positions,{})
        self.assertEqual(read(self.s,self.jid)['status'],'blocked')
        self.assertFalse(self.s.events('model_completed'))

    def test_restart_preserves_saved_result_and_request_date(self):
        self.s.lock(self.jid)
        self.s.append('model_completed',{'verified':True},self.date,self.jid)
        self.s.recover('service restart','2026-11-21')
        result = read(self.s,self.jid)
        self.assertEqual((result['status'],result['as_of']),('completed',self.date))

    def test_truncated_issuer_table_cannot_be_normalized_to_full_fund(self):
        header = 'Ticker,Asset Class,Market Value,Notional Value,Currency,Market Currency'
        rows = [f'{i},Equity,1,1,USD,USD' for i in range(10)]
        csv_data = '\n'.join(['Fund Holdings as of,"Nov 18, 2026"',header,*rows,'','BlackRock'])
        class Archive:
            def get(self,url):
                return csv_data.encode(),{}
        profile = dict(holdings_url='https://example.org/data',
                       issuer_metrics={'numHoldings':{'observed_at':'2026-11-18','value':20}})
        with patch('mara.model_exposures.fund_profile',return_value=profile):
            with self.assertRaisesRegex(ValueError,'count'):
                acquire(Archive(),self.date)

    def test_lookthrough_and_no_cash_or_normalization(self):
        self.assertAlmostEqual(calculate({'ITOT':.5,'IWF':.5},self.funds,self.positions)['top_issuers']['EXAMPLE'],.45)
        for invalid in ({'CASH':1},{'ITOT':.99},{'IWF':-1,'ITOT':2}):
            with self.assertRaises(ValueError):
                calculate(invalid,self.funds,self.positions)
