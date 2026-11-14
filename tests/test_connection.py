import json
import tempfile
import unittest
from pathlib import Path
from mara.connection import verify,status,save_private


class ConnectionTests(unittest.TestCase):
    def setup_files(self,folder):
        root=Path(folder)
        save_private(root/'credentials.json',{'client_id':'test-client','client_secret':'test-secret','account_seq':None})
        save_private(root/'policy.json',{'live_enabled':False,'account_seq':None,'max_capital_krw':30000000})
        (root/'STOP').touch()
        return root

    class Broker:
        def __init__(self,*args):self.account=None
        def accounts(self):return [{'accountSeq':7,'accountType':'BROKERAGE'}]
        def holdings(self):return {'items':[]}
        def buying_power(self):return {'cashBuyingPower':'100'}
        def open_orders(self):return {'orders':[]}
        def submit(self,*args):raise AssertionError('Connection check must never trade')

    def test_read_only_success_keeps_safety_controls_and_redacts_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_files(folder);result=verify(root,self.Broker)
            self.assertTrue(result['verified']);self.assertTrue(status(root)['verified'])
            config=json.loads((root/'credentials.json').read_text())
            policy=json.loads((root/'policy.json').read_text())
            self.assertEqual(config['account_seq'],7);self.assertEqual(policy['account_seq'],7)
            self.assertFalse(policy['live_enabled']);self.assertTrue((root/'STOP').exists())
            self.assertNotIn('test-secret',(root/'connection-status.json').read_text())
            self.assertEqual((root/'credentials.json').stat().st_mode&0o777,0o600)
            config['account_seq']=8;save_private(root/'credentials.json',config)
            self.assertFalse(status(root)['verified'])

    def test_failed_probe_clears_prior_success_and_does_not_select_account(self):
        class Broken(self.Broker):
            def holdings(self):raise RuntimeError('private provider detail')
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_files(folder)
            with self.assertRaises(RuntimeError):verify(root,Broken)
            self.assertFalse(status(root)['verified'])
            self.assertIsNone(json.loads((root/'credentials.json').read_text())['account_seq'])
            self.assertNotIn('private provider detail',(root/'connection-status.json').read_text())

    def test_multiple_accounts_require_explicit_selection(self):
        class Multiple(self.Broker):
            def accounts(self):return [{'accountSeq':n,'accountType':'BROKERAGE'} for n in [1,2]]
        with tempfile.TemporaryDirectory() as folder:
            root=self.setup_files(folder)
            with self.assertRaises(ValueError):verify(root,Multiple)
            self.assertIsNone(json.loads((root/'credentials.json').read_text())['account_seq'])

if __name__=='__main__':unittest.main()
