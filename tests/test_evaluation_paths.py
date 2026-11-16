import unittest
from mara.evaluation import pointer,raw_reference_paths

class EvaluationPathsTest(unittest.TestCase):
 def test_catalog_preserves_sparse_raw_reference_indices(self):
  packet={'market':{'facts':[{'raw_refs':[{'url':'https://example.org'},{'sha256':'a'}]}, {'raw_refs':[]}],
                    'research':{'calls':[{'raw_refs':[{'sha256':'b'}]}]}}}
  paths=raw_reference_paths(packet)
  self.assertEqual(paths,['/market/facts/0/raw_refs/1/sha256','/market/research/calls/0/raw_refs/0/sha256'])
  self.assertEqual([pointer(packet,p) for p in paths],['a','b'])
  self.assertEqual(raw_reference_paths({}),[])
  with self.assertRaises(ValueError):pointer(packet,'/market/research/calls/0/raw_refs/1/sha256')
