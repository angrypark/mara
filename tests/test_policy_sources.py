import unittest
from mara.policy_sources import latest_statement,statement,discover_statement

URL='https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm'
BODY=('The Committee decided to maintain the target range for the federal funds rate. '
      'Future policy depends on incoming information, employment and inflation. ')*4

class PolicySourcesTests(unittest.TestCase):
    def test_exact_official_latest_not_future_or_other_host(self):
        raw=''.join('<a href="'+u+'">FOMC statement</a>' for u in [URL,URL.replace('20261028','20261210'),URL.replace('www.federalreserve.gov','example.com')])
        self.assertEqual(latest_statement(raw,'2026-11-16'),URL)
        self.assertRaises(ValueError,latest_statement,raw,'2026-10-01')
    def test_duplicate_title_in_head_does_not_hide_dated_body(self):
        raw='<title>Federal Reserve issues FOMC statement</title><p>October 28, 2026</p><h1>Federal Reserve issues FOMC statement</h1><div class="col-xs-12 col-sm-8 col-md-8"><p>Available indicators suggest uncertainty.</p><p>'+BODY+'</p><p>For media inquiries</p></div>'
        self.assertEqual(statement(raw,URL,'2026-11-16')['statement_text'],'Available indicators suggest uncertainty.\n'+BODY.strip())
        for broken in [raw.replace('October 28','October 27'),raw.replace('For media inquiries','End'),raw.replace(BODY,'Short federal funds rate.')]:
            self.assertRaises(ValueError,statement,broken,URL,'2026-11-16')
        self.assertRaises(ValueError,statement,raw,URL,'2026-10-27')
    def test_year_boundary_uses_prior_official_list_without_future_leak(self):
        calls=[];december=URL.replace('20261028','20261210')
        def fetch(url):
            calls.append(url)
            return '<p>Current year list</p>' if '2027-' in url else '<a href="'+december+'">FOMC statement</a>'
        self.assertEqual(discover_statement(fetch,'2027-01-10'),december);self.assertEqual(len(calls),2)
