import unittest
from mara.planning_scenarios import joint_household,cash_hurdle


class PlanningScenariosTests(unittest.TestCase):
    def test_joint_shock_keeps_cash_and_nonliquid_losses_separate(self):
        p={'monthly_income':10000};h={'stress':[{'expenses':6000}],'reported_account_cash':10000,'property_value':1390000,'mortgage_balance':520000}
        r=joint_household(p,h,3000,.4,.4,.4,3000)
        partial,stopped,rate=r['scenarios']
        self.assertEqual(partial['monthly_affordable_contribution_before_reserve_replenishment'],1000)
        self.assertEqual(stopped['cash_needed_if_contributions_paused'],36000)
        self.assertEqual(stopped['gap_against_reported_account_cash_only'],26000)
        self.assertEqual(stopped['property_equity_loss'],278000)
        self.assertAlmostEqual(stopped['proposal_loss_if_funded'],720)
        self.assertEqual(stopped['income_needed_to_resume_planned_contribution'],9000)
        self.assertAlmostEqual(rate['monthly_expenses'],6000+520000*.02/12)

    def test_krw_break_even_solves_equal_initial_cash_comparison(self):
        p={'base_currency':'KRW'}
        rates={'fact_id':'synthetic','us_stock_standard_commission_fraction':.001,'fx_regular_effective_spread_fraction':.0005}
        cost={'published_conditions_and_examples':{'available':True,'published_rates':rates}}
        result=cash_hurdle(p,cost);self.assertEqual(len(result['scenarios']),9)
        for row in result['scenarios']:
            terminal=(1+row['required_usd_nav_total_return_to_match_cash'])*(1+row['usd_krw_one_year_change_assumption'])/((1+.001)*(1+.0005))
            self.assertAlmostEqual(terminal,1+row['krw_cash_one_year_return_assumption'])
        self.assertFalse(cash_hurdle({'base_currency':'USD'},cost)['available'])
        self.assertFalse(cash_hurdle(p,{})['available'])

    def test_cpi_published_precision_is_not_a_false_conflict(self):
        import json
        from mara.planning_scenarios import macro_consistency
        index={'series':'CUSR0000SA0','unit':'index 1982-84=100, seasonally adjusted','observations':[{'month':'2026-10','value':337.476},{'month':'2026-09','value':336.298}]}
        release={'id':'bls-cpi-fixture','observations':{'period':'2026-10','all_items_monthly_change_percent_sa':.4}}
        def pack():return {'as_of':'2026-11-16','facts':[{'id':'index','research_tool':'bls','text':json.dumps(index)},{'id':'release','research_tool':'release_notes','text':json.dumps(release)}]}
        r=macro_consistency(pack());self.assertTrue(r['agrees_at_published_precision']);self.assertEqual(r['rounded_one_decimal_percent'],.4)
        release['observations']['all_items_monthly_change_percent_sa']=.5
        self.assertFalse(macro_consistency(pack())['agrees_at_published_precision'])
        release['observations']['period']='2027-01';self.assertFalse(macro_consistency(pack())['available'])
        release['observations']=[];self.assertFalse(macro_consistency(pack())['available'])
