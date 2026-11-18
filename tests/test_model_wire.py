import unittest
from mara.model_wire import packed,unpacked,MARKER

class ModelWireTests(unittest.TestCase):
    def test_lossless_nested_values_escaped_paths_and_distinct_types(self):
        row={'a/b~c':['한국어 원문  \n'*100,3.5,False,None]}
        original={'array':[row,row], 'another':row,'numeric':1,'string':'1','empty':[]}
        wire=packed(original)
        self.assertEqual(unpacked(wire),original)
        self.assertNotEqual(wire,original)
        self.assertEqual(original['array'][0],row)
        with self.assertRaises(ValueError):packed({MARKER:'untrusted source'})
        with self.assertRaises(ValueError):unpacked({'loop':{MARKER:'/loop'}})

if __name__=='__main__':unittest.main()
