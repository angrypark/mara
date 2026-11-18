import copy
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from mara.company_research import owner_value,ResearchTools,CompanyLibrary
from mara.valuation_evidence import validate_sources
from mara.research import compact_market
from mara.research_sources import sec_financials
from mara.store import Store
from test_research import financial

DAY='2026-11-18'
FIN='https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json'
SUB='https://data.sec.gov/submissions/CIK0000000001.json'


def inputs():
    a={'owner_earnings_per_share':4,'currency':'USD','earnings_period':'FY2025',
       'share_basis':'Same diluted split-adjusted share basis in all cases',
       'normalization':'Observed earnings adjusted for reinvestment; explicit synthetic example',
       'price':50,'price_as_of':DAY,'source_ids':['quote','fin'],'margin_of_safety':.2,
       'scenarios':[{'name':name,'growth':g,'discount':.1,'terminal_growth':.02,'years':5,'reason':'Synthetic assumptions'}
                    for name,g in [('bull',.1),('bear',0),('base',.05)]]}
    company={'symbol':'TEST','cik':1,'known_at':DAY,'raw_refs':[{'source':SUB}],
             'quote':{'currency':'USD','price':50,'observed_at':DAY}}
    def fact(fid,kind,value,source):
        return {'id':fid,'text':json.dumps(value),'topic':'synthetic','source':source,
                'research_tool':kind,'published_at':DAY,'known_at':DAY,'valid_until':DAY,'uncertainty':'synthetic'}
    f=fact('fin','sec_financials',sec_financials(financial(),DAY),FIN)
    f['company_identity']={'symbol':'TEST','cik':1}
    m={'as_of':DAY,'facts':[fact('quote','company_company',{'companies':[company]},SUB),f]}
    return a,m


def expanded(a):
    a=copy.deepcopy(a)
    a['earnings_cases']={name:{'owner_earnings_per_share':e,'normalization':'Synthetic observed-to-assumed bridge',
        'reinvestment':'Maintenance and growth spending reflected in E and per-share growth',
        'dilution':'SBC remains in earnings; no additional duplicate share haircut',
        'source_ids':['fin'],'falsifier':'Review when reported reinvestment exceeds the assumed range'}
        for name,e in [('base',4),('bull',6),('bear',2)]}
    return a


def independently_discount(e,s):
    e=D(str(e));g=D(str(s['growth']));r=D(str(s['discount']));t=D(str(s['terminal_growth']));n=s['years']
    total=D(0)
    for year in range(1,n+1):total+=e*(1+g)**year/(1+r)**year
    return float(total+e*(1+g)**n*(1+t)/(r-t)/(1+r)**n)


class ValuationCasesTests(unittest.TestCase):
    def test_legacy_math_and_named_case_math_with_permuted_order(self):
        a,_=inputs();old=owner_value(a,{'quote','fin'},DAY)
        self.assertEqual(old['normalization_sensitivity']['mode'],'fixed_earnings')
        self.assertEqual(old['normalization_sensitivity']['rows'],[])
        for row in old['scenarios']:self.assertAlmostEqual(row['value_per_share'],independently_discount(4,row))
        a=expanded(a);new=owner_value(a,{'quote','fin'},DAY)
        for row in new['scenarios']:
            e=a['earnings_cases'][row['name']]['owner_earnings_per_share']
            self.assertEqual(row['owner_earnings_per_share'],e)
            self.assertAlmostEqual(row['value_per_share'],independently_discount(e,row))
        a['scenarios'].reverse();a['earnings_cases']=dict(reversed(list(a['earnings_cases'].items())))
        again=owner_value(a,{'quote','fin'},DAY)
        self.assertEqual({x['name']:x for x in new['scenarios']},{x['name']:x for x in again['scenarios']})
        self.assertEqual(new['normalization_sensitivity'],again['normalization_sensitivity'])

    def test_earnings_only_sensitivity_holds_other_inputs_fixed(self):
        a,_=inputs();a=expanded(a);result=owner_value(a,{'quote','fin'},DAY)
        base=next(s for s in a['scenarios'] if s['name']=='base')
        for row in result['normalization_sensitivity']['rows']:
            self.assertAlmostEqual(row['value_per_share'],independently_discount(row['owner_earnings_per_share'],base))
            self.assertAlmostEqual(row['buy_ceiling'],row['value_per_share']*.8)
        combined=next(s for s in result['scenarios'] if s['name']=='bear')
        isolated=next(s for s in result['normalization_sensitivity']['rows'] if s['name']=='bear')
        self.assertNotEqual(combined['value_per_share'],isolated['value_per_share'])
        for case in a['earnings_cases'].values():case['owner_earnings_per_share']=4
        same=owner_value(a,{'quote','fin'},DAY)
        self.assertEqual(len({r['value_per_share'] for r in same['normalization_sensitivity']['rows']}),1)

    def test_invalid_cases_never_fall_back_to_shared_earnings(self):
        a,_=inputs();a=expanded(a)
        mutations=[lambda x:x.update(earnings_cases=None),lambda x:x['earnings_cases'].pop('bear'),
            lambda x:x['earnings_cases'].update(extra=x['earnings_cases']['base']),
            lambda x:x['earnings_cases']['base'].update(owner_earnings_per_share=5),
            lambda x:x['earnings_cases']['bear'].update(normalization=''),
            lambda x:x['earnings_cases']['bear'].update(currency='KRW'),
            lambda x:x['earnings_cases']['bear'].update(source_ids=['missing'])]
        mutations += [(lambda x,v=v:x['earnings_cases']['bear'].update(owner_earnings_per_share=v)) for v in [0,-1,True,float('nan'),float('inf')]]
        for mutate in mutations:
            bad=copy.deepcopy(a);mutate(bad)
            with self.subTest(bad=bad),self.assertRaises(ValueError):owner_value(bad,{'quote','fin'},DAY)

    def test_source_validation_for_both_legacy_and_cases(self):
        a,m=inputs()
        for args in (a,expanded(a)):
            receipt=validate_sources(args,m,'TEST',DAY)
            self.assertEqual(receipt['cik'],'1')
            self.assertEqual([x['fact_id'] for x in receipt['sources'] if x['substantive_observation']],['fin'])
            mutations=[lambda x:x['facts'][1].update(known_at='2026-11-19'),
                lambda x:x['facts'][1].update(published_at='2026-11-19'),
                lambda x:x['facts'][1].update(valid_until='2026-11-17'),
                lambda x:x['facts'][1]['company_identity'].update(symbol='OTHER'),
                lambda x:x['facts'][1].update(source=FIN.replace('0000000001','0000000002')),
                lambda x:x['facts'][1].update(research_tool='company_valuation'),
                lambda x:x['facts'].pop(),lambda x:x['facts'].append(copy.deepcopy(x['facts'][1]))]
            for mutate in mutations:
                bad=copy.deepcopy(m);mutate(bad)
                with self.subTest(mutate=mutate),self.assertRaises(ValueError):validate_sources(args,bad,'TEST',DAY)

    def test_quote_only_empty_observation_and_case_unlisted_sources_rejected(self):
        a,m=inputs();only=copy.deepcopy(a);only['source_ids']=['quote']
        with self.assertRaises(ValueError):validate_sources(only,m,'TEST',DAY)
        bad=copy.deepcopy(m);v=json.loads(bad['facts'][1]['text']);v['metrics']={};bad['facts'][1]['text']=json.dumps(v)
        with self.assertRaises(ValueError):validate_sources(a,bad,'TEST',DAY)
        for ids in (['quote'],['missing'],['fin','fin']):
            bad=expanded(a);bad['earnings_cases']['bear']['source_ids']=ids
            with self.assertRaises(ValueError):validate_sources(bad,m,'TEST',DAY)

    def test_internal_observation_dates_and_typed_nonpositive_model_limit(self):
        from mara.research import safe_code
        a,m=inputs()
        for field in ('filed','end'):
            bad=copy.deepcopy(m);v=json.loads(bad['facts'][1]['text'])
            v['metrics']['revenue'][0]['observations'][0][field]='2026-11-19'
            bad['facts'][1]['text']=json.dumps(v)
            with self.assertRaises(ValueError):validate_sources(a,bad,'TEST',DAY)
        for e in (0,-1):
            bad=expanded(a);bad['earnings_cases']['bear']['owner_earnings_per_share']=e
            try:owner_value(bad,{'quote','fin'},DAY)
            except ValueError as error:self.assertEqual(safe_code(error),'valuation_model_nonpositive_earnings')
            else:self.fail('Nonpositive earnings must not be clamped')
        numeric=owner_value(expanded(a),{'quote','fin'},DAY)
        strings=expanded(a)
        for c in strings['earnings_cases'].values():c['owner_earnings_per_share']=str(c['owner_earnings_per_share'])
        for s in strings['scenarios']:
            for key in ('growth','discount','terminal_growth'):s[key]=str(s[key])
        actual=owner_value(strings,{'quote','fin'},DAY)
        self.assertEqual(actual['normalization_sensitivity'],numeric['normalization_sensitivity'])
        self.assertEqual([s['value_per_share'] for s in actual['scenarios']],[s['value_per_share'] for s in numeric['scenarios']])

    def test_filing_and_xbrl_sources_bind_issuer_and_nonempty_read_ranges(self):
        a,m=inputs();a=expanded(a)
        acc='0000000001-26-000001'
        examples=[('company_filing_read',{'symbol':'TEST','source_scope':'same_filing','text':'Actual extracted text',
            'filing':{'filed':DAY,'accession':acc,'url':'https://www.sec.gov/Archives/edgar/data/1/'+acc.replace('-','')+'/test.htm'}},'https://issuer.example/test.pdf'),
            ('company_filing_search',{'symbol':'TEST','source_scope':'same_filing','hits':[{'excerpt':'Actual excerpt','start':0,'end':14}],
            'filing':{'filed':DAY,'accession':acc,'url':'https://www.sec.gov/Archives/edgar/data/1/'+acc.replace('-','')+'/test.htm'}},'https://issuer.example/test.pdf'),
            ('company_xbrl_read',{'symbol':'TEST','cik':1,'unit':'USD','observations':[{'end':'2025-12-31','filed':DAY,'val':5,'form':'10-K','accn':acc}]},FIN)]
        for kind,body,url in examples:
            row=copy.deepcopy(m);row['facts'][1].update(research_tool=kind,text=json.dumps(body),source=url)
            validate_sources(a,row,'TEST',DAY)
            other=copy.deepcopy(body);other['symbol']='OTHER';row['facts'][1]['text']=json.dumps(other)
            with self.assertRaises(ValueError):validate_sources(a,row,'TEST',DAY)

    def test_substantive_sources_require_numbers_units_and_valid_periods(self):
        a,m=inputs();a=expanded(a)
        bad_rows=[{'end':'2025-12-31','filed':DAY},
                  {'val':3,'end':'2025-12-31','filed':DAY,'form':'10-K','accn':'0000000001-26-000001','start':'2026-01-01'}]
        for obs in bad_rows:
            bad=copy.deepcopy(m);bad['facts'][1].update(research_tool='company_xbrl_read',text=json.dumps({'symbol':'TEST','cik':1,'unit':'USD','observations':[obs]}))
            with self.assertRaises(ValueError):validate_sources(a,bad,'TEST',DAY)
        for unit in ('',None):
            bad=copy.deepcopy(m);v=json.loads(bad['facts'][1]['text']);v['metrics']['revenue'][0]['unit']=unit;bad['facts'][1]['text']=json.dumps(v)
            with self.assertRaises(ValueError):validate_sources(a,bad,'TEST',DAY)
        for value in (None,True,'12',float('nan'),float('inf')):
            bad=copy.deepcopy(m);v=json.loads(bad['facts'][1]['text']);v['metrics']['revenue'][0]['observations'][0]['value']=value;bad['facts'][1]['text']=json.dumps(v)
            with self.assertRaises(ValueError):validate_sources(a,bad,'TEST',DAY)

    def test_real_tool_delivery_and_budget_rejection_preserve_source_chain(self):
        a,m=inputs();a=expanded(a)
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('fixture'))
            runner=ResearchTools(CompanyLibrary(Path(tmp)/'library',today=DAY),s,'valuation-case-test',DAY)
            out=runner.execute('buffett',{'tool':'valuation','arguments':{'symbol':'TEST','assumptions':a}},m)
            fid=out['fact_id'];self.assertTrue(fid)
            for role in ('leader','validation'):
                delivered=next(f for f in compact_market(m,role)['facts'] if f['id']==fid)
                body=json.loads(delivered['text'])
                self.assertEqual(body['assumptions']['earnings_cases'],a['earnings_cases'])
                self.assertEqual({x['fact_id'] for x in body['source_validation']['sources']},{'quote','fin'})
            m['facts'].pop();a['margin_of_safety']=.3
            with patch.object(runner,'activate',return_value=False):
                runner.activation_budget={'blocked_reason':'synthetic_budget_rejection'}
                blocked=runner.execute('buffett',{'tool':'valuation','arguments':{'symbol':'TEST','assumptions':a}},m)
            self.assertIsNone(blocked['fact_id']);self.assertEqual(blocked['status'],'stored_not_activated')
            self.assertEqual(len(s.events('research_evidence')),1)
            db.close()


if __name__=='__main__':unittest.main()
