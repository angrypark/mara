import sys,types,unittest
from mara.quality_campaign import code_manifest

class CodeManifestTests(unittest.TestCase):
    def test_loaded_code_hash_stays_stable_when_functions_execute(self):
        first=code_manifest();second=code_manifest()
        self.assertEqual(first['loaded_python_code_format'],'python-marshal-v2')
        self.assertEqual(first['loaded_python_code'],second['loaded_python_code'])

    def test_real_loaded_code_change_is_detected_without_file_change(self):
        name='mara._manifest_fixture';module=types.ModuleType(name)
        exec('def sample(): return 1',module.__dict__);sys.modules[name]=module
        try:
            first=code_manifest()
            exec('def sample(): return 2',module.__dict__)
            second=code_manifest()
            self.assertEqual(first['filesystem'],second['filesystem'])
            self.assertNotEqual(first['loaded_python_code'][name+'.sample'],second['loaded_python_code'][name+'.sample'])
        finally:sys.modules.pop(name,None)
