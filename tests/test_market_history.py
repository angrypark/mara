import unittest
import time
from datetime import date,timedelta
from mara.market_history import parse,url
class HistoryTests(unittest.TestCase):
 def raw(self,series='SP500'):
  rows=['observation_date,'+series]
  for i in range(91):
   stamp=(date(2026,8,18)+timedelta(days=i)).isoformat();value=(4+i*.01) if series=='DGS10' else (100-i*.1+(2 if i==40 else 0))
   rows.append(stamp+','+str(value))
  return ('\n'.join(rows)+'\n').encode()
 def test_endpoints_units_and_rebound(self):
  r=parse(self.raw(),'SP500','2026-11-18');self.assertAlmostEqual(r['change_value'],-9)
  self.assertFalse(r['each_observed_step_down']);self.assertFalse(r['continuous_decline_verified'])
  r=parse(self.raw('DGS10'),'DGS10','2026-11-18');self.assertAlmostEqual(r['change_value'],90);self.assertEqual(r['change_unit'],'basis_points')
  self.assertIn('cosd=2026-08-18',url('SP500','2026-11-18'))
 def test_observation_date_is_not_publication_date(self):
  from mara.research import Research
  r=parse(self.raw(),'SP500','2026-11-18')
  self.assertEqual(r['observed_at'],'2026-11-16')
  self.assertIsNone(r['date_provenance']['original_published_at'])
  collector=Research.__new__(Research)
  collector.archive=type('Archive',(),{'started':time.monotonic()})()
  collector.as_of='2026-11-18';collector.records=[];collector.facts=[];collector.calls=[];collector.used_chars=0
  collector.record('market_history','SP500',lambda:r,r['source'])
  self.assertEqual(collector.facts[0]['published_at'],'2026-11-18')
  self.assertEqual(collector.calls[0]['status'],'collected')
 def test_missing_days_no_interpolation(self):
  raw=self.raw().replace(b'2026-08-20,99.8',b'2026-08-20,.');r=parse(raw,'SP500','2026-11-18')
  self.assertIn('2026-08-20',r['missing_dates']);self.assertEqual(len(r['observations']),90)
 def test_invalid_identity_period_gap_and_number_rejected(self):
  for raw in [self.raw('DGS10'),self.raw()+b'2026-11-19,90\n',self.raw()+b'2026-11-16,90\n',self.raw().replace(b'2026-08-18,100.0',b'2026-08-18,nan'),b'\n'.join(self.raw().splitlines()[:35])]:
   with self.assertRaises(ValueError):parse(raw,'SP500','2026-11-18')
if __name__=='__main__':unittest.main()
