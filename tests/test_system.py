import itertools
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from engine import ExpertSystem
from app import Handler, ThreadingHTTPServer
from rule_editor import RuleStore
SCENARIOS=json.loads((Path(__file__).parent/'scenarios.json').read_text(encoding='utf-8'))

class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.system=ExpertSystem()

    def test_twenty_reference_cases_through_dialogue(self):
        output=[]
        for case in SCENARIOS:
            with self.subTest(case=case['id']):
                answers={}; asked=[]
                state=self.system.consult(case['category'],answers)
                while state['question']:
                    question=state['question']['id']
                    self.assertNotIn(question,asked)
                    self.assertIn(question,case['answers'],f'Неожиданный вопрос {question}')
                    asked.append(question); answers[question]=case['answers'][question]
                    state=self.system.consult(case['category'],answers)
                    self.assertLessEqual(len(asked),len(self.system.questions))
                actual=[r['rule_id'] for r in state['results']]
                self.assertEqual(actual,case['expected'])
                self.assertEqual(state['status'],case['status'])
                output.append({**case,'actual':actual,'actual_status':state['status'],
                               'asked':asked,'fired':state['fired_rules'],'results':state['results'],'passed':True})
        (Path(__file__).parent/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def test_no_unknown_equals_no(self):
        condition={'field':'fan_heard','eq':False}
        self.assertIsNone(self.system.evaluate(condition,{'fan_heard':None}))
        self.assertIs(self.system.evaluate(condition,{'fan_heard':False}),True)

    def test_validation(self):
        for category,answers in [('missing',{}),('start',{'starter':'bad'}),('start',{'starter':True}),('brakes',{'grinding':1}),('brakes',{'manual':True}),('start',{'start_branch':True})]:
            with self.subTest(category=category,answers=answers):
                with self.assertRaises(ValueError): self.system.consult(category,answers)

    def test_contradiction(self):
        with self.assertRaises(ValueError):
            self.system.consult('exhaust',{'smoke_color':'white','white_persists':True,'cold_disappears':True})
        with self.assertRaisesRegex(ValueError,'приборная панель'):
            self.system.consult('start',{'starter':'none','dashboard_off':True,'click':True,'brightness_same':True})

    def test_back_recalculates_facts(self):
        before=self.system.consult('start',{'starter':'slow'})
        after=self.system.consult('start',{'starter':'normal','after_empty_refuel':False})
        self.assertEqual([r['rule_id'] for r in before['results']],[5])
        self.assertEqual(after['results'],[])
        self.assertNotIn(5,after['fired_rules'])

    def test_chain_and_evidence(self):
        state=self.system.consult('start',{'starter':'none','dashboard_off':True,'click':False})
        self.assertTrue({1,2,3}.issubset(state['fired_rules']))
        self.assertEqual([e['id'] for e in state['results'][0]['evidence']],['starter','dashboard_off'])
        trace=state['results'][0]['trace']
        self.assertEqual([step['rule_id'] for step in trace if step['type']=='rule'],[1,2,3])
        self.assertEqual([step['type'] for step in trace],['complaint','rule','answer','rule','answer','rule'])

    def test_all_terminal_rules_reachable(self):
        # Перебор полных допустимых комбинаций независимо от условий правил.
        # Проверяет отсутствие недостижимых конечных выводов в базе знаний.
        reached=set()
        for category in self.system.categories:
            questions=[q for q in self.system.kb['questions'] if q['category']==category]
            for values in itertools.product(*[[o['value'] for o in q['options']] for q in questions]):
                data=dict(zip([q['id'] for q in questions],values))
                try: state=self.system.consult(category,data)
                except ValueError: continue
                reached.update(r['rule_id'] for r in state['results'])
        expected={r['id'] for r in self.system.rules if r['type']=='terminal'}
        self.assertEqual(reached,expected)

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir=tempfile.TemporaryDirectory()
        source=Path(__file__).resolve().parents[1]/'data'/'knowledge.json'
        target=Path(cls.temp_dir.name)/'knowledge.json'
        shutil.copyfile(source,target)
        cls.original_store=app.STORE
        app.STORE=RuleStore(target)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start();cls.base=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        app.STORE=cls.original_store
        cls.temp_dir.cleanup()
    def test_assets(self):
        for path,mime in [('/','text/html'),('/style.css','text/css'),('/app.js','text/javascript')]:
            with urlopen(self.base+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn(mime,response.headers['Content-Type'])
                self.assertTrue(response.read())
    def test_api(self):
        with urlopen(self.base+'/api/knowledge') as response:
            knowledge=json.load(response)
            self.assertEqual(knowledge['rule_count'],len(knowledge['rules']))
            self.assertEqual(len(knowledge['questions']),61)
        request=Request(self.base+'/api/consult',json.dumps({'category':'start','answers':{'starter':'slow'}}).encode(),{'Content-Type':'application/json'})
        with urlopen(request) as response:
            self.assertEqual(json.load(response)['results'][0]['rule_id'],5)
    def test_bad_request_and_path(self):
        for path,body,code in [('/api/consult',b'[]',400),('/api/consult',b'{',400),('/api/consult',b'{"category":"start","answers":{"starter":42}}',400),('/api/missing',b'{}',404)]:
            with self.subTest(path=path,body=body):
                with self.assertRaises(HTTPError) as e: urlopen(Request(self.base+path,body,{'Content-Type':'application/json'}))
                self.assertEqual(e.exception.code,code)
        with self.assertRaises(HTTPError) as e: urlopen(self.base+'/../engine.py')
        self.assertEqual(e.exception.code,404)

    def test_rule_editor_lifecycle(self):
        def send(method,path,body):
            request=Request(self.base+path,json.dumps(body).encode(),{'Content-Type':'application/json'},method=method)
            with urlopen(request) as response: return json.load(response)
        with urlopen(self.base+'/api/knowledge') as response: before=json.load(response)
        rule_id=max(item['id'] for item in before['rules'])+1
        rule={'id':rule_id,'category':'start','type':'terminal',
              'if':{'all':[{'field':'complaint','eq':'start'},{'field':'starter','eq':'slow'}]},
              'then':{'conclusion':'Контрольный вывод','component':'Тестовый узел'},
              'text':'ЕСЛИ стартер крутит медленно, ТО контрольный вывод.'}
        created=send('POST','/api/rules',{'rule':rule,'revision':before['revision']})
        self.assertEqual(created['rule_count'],before['rule_count']+1)
        self.assertNotEqual(created['revision'],before['revision'])
        result=send('POST','/api/consult',{'category':'start','answers':{'starter':'slow'}})
        self.assertIn(rule_id,[r['rule_id'] for r in result['results']])
        rule['then']['conclusion']='Изменённый вывод'
        updated=send('PUT',f'/api/rules/{rule_id}',{'rule':rule,'revision':created['revision']})
        result=send('POST','/api/consult',{'category':'start','answers':{'starter':'slow'}})
        self.assertIn('Изменённый вывод',[r['text'] for r in result['results']])
        invalid=json.loads(json.dumps(rule))
        invalid['if']['all'][1]['eq']='impossible'
        with self.assertRaises(HTTPError) as error:
            send('PUT',f'/api/rules/{rule_id}',{'rule':invalid,'revision':updated['revision']})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(HTTPError) as error:
            send('DELETE','/api/rules/1',{'revision':updated['revision']})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(HTTPError) as error:
            send('DELETE',f'/api/rules/{rule_id}',{'revision':before['revision']})
        self.assertEqual(error.exception.code,409)
        deleted=send('DELETE',f'/api/rules/{rule_id}',{'revision':updated['revision']})
        self.assertEqual(deleted['rule_count'],before['rule_count'])
        self.assertFalse(any(r['id']==rule_id for r in deleted['rules']))

if __name__=='__main__': unittest.main(verbosity=2)
