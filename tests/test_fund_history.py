import calendar
import unittest
from mara.fund_history import monthly_returns,NAMES


def workbook(symbol='ITOT',bad=None):
    rows=[[NAMES[symbol]],['Month End Date','Monthly Total (NAV) Return']]
    for i in range(48):
        y=2023+i//12;m=i%12+1
        import datetime
        rows.append([datetime.date(y,m,calendar.monthrange(y,m)[1]).strftime('%b %d, %Y'),'1.25'])
    if bad:bad(rows)
    return '<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><ss:Worksheet ss:Name="Performance"><ss:Table>'+''.join('<ss:Row>'+''.join('<ss:Cell><ss:Data>'+v+'</ss:Data></ss:Cell>' for v in row)+'</ss:Row>' for row in rows)+'</ss:Table></ss:Worksheet></ss:Workbook>'


class FundHistoryTests(unittest.TestCase):
    def test_dated_nav_does_not_replace_monthly_returns(self):
        rows=[['As Of','NAV per Share','Ex-Dividends','Shares Outstanding'],['Nov 13, 2026','150.25','0','1000000'],['Nov 17, 2026','999','0','1000000']]
        sheet='<ss:Worksheet ss:Name="Historical"><ss:Table>'+''.join('<ss:Row>'+''.join('<ss:Cell><ss:Data>'+v+'</ss:Data></ss:Cell>' for v in row)+'</ss:Row>' for row in rows)+'</ss:Table></ss:Worksheet>'
        raw=workbook().replace('</ss:Workbook>',sheet+'</ss:Workbook>')
        result=monthly_returns(raw,'ITOT','2026-11-16')
        self.assertEqual(result['latest_nav']['date'],'2026-11-13')
        self.assertEqual(result['latest_nav']['nav_per_share_usd'],150.25)
        self.assertEqual(len(result['observations']),46)
        self.assertEqual(result['observations'][0]['return'],.0125)
        for bad in [raw.replace('Nov 13, 2026','Oct 01, 2026'),raw.replace('Nov 13, 2026','bad date'),raw.replace('150.25','NaN')]:
            result=monthly_returns(bad,'ITOT','2026-11-16')
            self.assertEqual(len(result['observations']),46)
            self.assertIsNone(result['latest_nav']);self.assertTrue(result['latest_nav_unavailable_reason'])

    def test_monthly_percent_and_future_cutoff(self):
        x=monthly_returns(workbook(),'ITOT','2026-11-16')
        self.assertEqual(len(x['observations']),46)
        self.assertEqual(x['observed_at'],'2026-10-31')
        self.assertEqual(x['observations'][0]['return'],.0125)
        self.assertNotIn('risk_history',x)

    def test_identity_gaps_duplicates_units_and_stale_are_rejected(self):
        self.assertRaises(ValueError,monthly_returns,workbook('IVV'),'ITOT','2026-11-16')
        mutations=[lambda r:r.pop(20),lambda r:r.append(r[20]),lambda r:r[20].__setitem__(1,'NaN'),
            lambda r:r[20].__setitem__(1,'--'),lambda r:r[1].__setitem__(1,'Monthly Price Return')]
        for change in mutations:
            with self.assertRaises(ValueError):monthly_returns(workbook(bad=change),'ITOT','2026-11-16')
        self.assertRaises(ValueError,monthly_returns,workbook(),'ITOT','2027-05-01')

    def test_bare_url_ampersand_is_escaped_but_entities_not_executed(self):
        s=workbook().replace('<ss:Cell>','<ss:Cell ss:HRef="https://example.com/?a=1&b=2">',1)
        self.assertEqual(len(monthly_returns(s,'ITOT','2026-11-16')['observations']),46)
        self.assertRaises(ValueError,monthly_returns,'<!DOCTYPE x>'+s,'ITOT','2026-11-16')
