import unittest
from mara.model_wire import packed,unpacked,serialized,MARKER,VALUE_MARKER,VERSION

class ModelWireTests(unittest.TestCase):
    def test_canonical_json_source_text_is_exact_and_v2_remains_readable(self):
        import json
        from mara.model_wire import JSON_MARKER
        rows=[{'period':'2026-01-01','text':'source narrative '*100,'value':i,'other':None} for i in range(20)]
        canonical=serialized({'observations':rows})
        original={'facts':[{'text':canonical},{'text':canonical}],
            'spaced':json.dumps({'observations':rows},ensure_ascii=False,sort_keys=True),
            'noncanonical':json.dumps({'observations':rows},indent=2),
            'reserved_json':serialized({VALUE_MARKER:'untrusted source '+'x'*300})}
        wire=packed(original)
        self.assertEqual(unpacked(wire),original)
        self.assertIn(JSON_MARKER,serialized(wire))
        self.assertLess(len(serialized(wire)),len(serialized(original))/2)
        self.assertEqual(unpacked({'version':'mara.model-wire/2.0','root':{VALUE_MARKER:0},'values':['old text']}),'old text')
        with self.assertRaises(ValueError):packed({JSON_MARKER:'untrusted'})
        self.assertEqual(unpacked({'version':'mara.model-wire/2.0','root':{JSON_MARKER:[]},'values':[]}),{JSON_MARKER:[]})

    def test_role_wire_preserves_source_and_output_repair_inputs(self):
        import tempfile
        from pathlib import Path
        from mara.agents import Agents,DemoModel
        from mara.store import Store
        class ReachedModel(Exception):pass
        class Model(DemoModel):
            input_wire_version=VERSION
            count=0
            def complete(self,role,guide,payload,contract):
                self.count+=1
                original={'role_guide':guide,'contract':contract,'input':payload}
                assert unpacked(packed(original))==original
                if self.count==1:return {}  # output correction must keep the same source
                assert payload['output_feedback']['previous_output']=={}
                raise ReachedModel()
        text='unchanged original source '*18000
        payload={'analysis':{'source':text,'again':text,'third':text},'market':{'facts':[]},'valuation':{'weights':{'CASH':1}}}
        for role in ('evidence','buffett','leader','validation'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as tmp:
                db=Store(Path(tmp)/'db');s=db.session(db.create_user('fixture'));model=Model()
                with self.assertRaises(ReachedModel):Agents(s,model,'2026-11-18','run').call(role,payload)
                inputs=s.events('agent_input');self.assertEqual(len(inputs),2)
                self.assertEqual(inputs[-1]['body']['payload']['analysis'],payload['analysis'])
                model.input_wire_version=None
                with self.assertRaisesRegex(ValueError,'context budget'):Agents(s,model,'2026-11-18','other').call(role,payload)
                db.close()

    def test_lossless_nested_values_escaped_paths_and_distinct_types(self):
        row={'a/b~c':['한국어 원문  \n'*100,3.5,False,None]}
        original={'array':[row,row], 'another':row,'numeric':1,'string':'1','empty':[]}
        wire=packed(original)
        self.assertEqual(unpacked(wire),original)
        self.assertNotEqual(wire,original)
        self.assertEqual(original['array'][0],row)
        with self.assertRaises(ValueError):packed({MARKER:'untrusted source'})
        with self.assertRaises(ValueError):unpacked({'loop':{MARKER:'/loop'}})

    def test_pool_saves_medium_values_and_keeps_order_and_types(self):
        rows=[{'fact_id':str(i),'text':'원본 '+str(i)+'의 같은 문장 '*12} for i in range(80)]
        original={'first':rows,'second':list(reversed(rows)), 'values':[0,False,None,1,'1',-2.3]}
        wire=packed(original)
        self.assertEqual(unpacked(wire),original)
        self.assertLess(len(serialized(wire)),len(serialized(original)))
        self.assertEqual(packed(original),wire)
        self.assertEqual(unpacked({'first':'original','again':{MARKER:'/first'}}),{'first':'original','again':'original'})

    def test_bad_references_and_reserved_keys_are_rejected(self):
        for index in (-1,True,'0',1):
            with self.subTest(index=index),self.assertRaises(ValueError):
                unpacked({'version':VERSION,'root':{VALUE_MARKER:index},'values':['zero']})
        with self.assertRaises(ValueError):
            unpacked({'version':VERSION,'root':{VALUE_MARKER:0},'values':[{VALUE_MARKER:0}]})
        with self.assertRaises(ValueError):
            unpacked({'version':VERSION,'root':{VALUE_MARKER:0,'extra':'ambiguous'},'values':['zero']})
        with self.assertRaises(ValueError):packed({'nested':[{VALUE_MARKER:0}]})
        with self.assertRaises(ValueError):packed({'value':float('nan')})
        invalid=[{'items':['zero'],'x':{MARKER:'/items/-1'}},
                 {'safe':'value','x':{MARKER:'invalid/safe'}},
                 {'safe':'value','x':{MARKER:'/safe','extra':True}},
                 {'items':['zero'],'x':{MARKER:'/items/00'}},
                 {'a~b':1,'x':{MARKER:'/a~b'}},
                 {'version':VERSION,'root':None,'values':[{VALUE_MARKER:3}]},
                 {'version':VERSION,'root':{MARKER:'/value'},'values':[]}]
        for wire in invalid:
            with self.subTest(wire=wire),self.assertRaises(ValueError):unpacked(wire)

    def test_wire_budget_does_not_discard_the_persisted_evaluator_input(self):
        import tempfile
        from pathlib import Path
        from mara.agents import Agents
        from mara.store import Store
        class ReachedModel(Exception):pass
        class Model:
            mode='live';identity={'model':'synthetic'};evaluator_wire_version=VERSION
            def complete(self,role,guide,payload,contract):raise ReachedModel()
        text='original evidence '*55000
        payload={'report':{'analysis':{},'original':text,'same_original':text},'market':{'facts':[]}}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.sqlite3');session=store.session(store.create_user('synthetic'))
            with self.assertRaises(ReachedModel):Agents(session,Model(),'2026-11-18',None).call('evaluator',payload)
            saved=session.events('agent_input')[-1]['body']['payload']
            self.assertEqual(saved['report'],payload['report'])
            self.assertEqual(saved['input_budget']['serialization'],VERSION)
            model=Model();model.evaluator_wire_version=None
            with self.assertRaisesRegex(ValueError,'context budget'):
                Agents(session,model,'2026-11-18',None).call('evaluator',payload)
            self.assertEqual(len(session.events('agent_input')),1)
            too_large={'report':{'analysis':{},'rows':[text]*6},'market':{'facts':[]}}
            with self.assertRaisesRegex(ValueError,'context budget'):
                Agents(session,Model(),'2026-11-18',None).call('evaluator',too_large)
            self.assertEqual(len(session.events('agent_input')),1)
            store.close()

if __name__=='__main__':unittest.main()
